# libretguard

Best effort approximation of OpenBSD's RETGUARD for Linux, without custom compiler passes.

The design is based on the [OpenBSD RETGUARD paper](https://www.openbsd.org/papers/asiabsdcon2019-rop-paper.pdf), adapted to Linux and uses high-address for tagging.

> [!CAUTION]
> libretguard is NOT a security catch-all. It is a cheap (to implement and to use) mitigation that makes ROP attacks require more steps or be probabilistic and crash most of the time. You should still audit and fix bugs.

> [!IMPORTANT]
> This is a research prototype. We tried reducing automatic-protection overhead without a compiler pass: some workloads improved, but frequent small calls remain expensive and tuning introduces regressions. That investigation is closed. Further work should require an explicitly approved GCC/Clang compiler pass; do not recreate a script-based optimizer. See [BENCHMARK.md](BENCHMARK.md) for the final results.

## Usage

`libretguard.a` supports manual and automatic protection in the same application. Manual source files use `RETGUARD_SCOPE()`, or `RETGUARD_GADGET_FUNCTION` with `RETGUARD_GADGET_SCOPE()`, to select protected functions. Automatic source files use compiler instrumentation and the GAS assembly step described below.

### Manual mode

The manual C/C++ macros check whether a function's stack return address changed upon function return (or C++ exceptions). This is useful to protect a single function.

```c
#include "retguard.h"

int example(int x)
{
    // Inserts return address check
    RETGUARD_SCOPE();
    if (x < 0)
        return -1;
    return x + 1;
}

int main(void)
{
    // Use as normal
    return example(1);
}
```

`RETGUARD_GADGET_FUNCTION` should be used together with `RETGUARD_GADGET_SCOPE()` that implements the OpenBSD style return address check + return gadget reduction. Though it is rather usless without instrumenting every function as attackers can simply find a stray return somewhere.

```c
#include "retguard.h"

// removes the final `ret` from the function call and use a centralized return implementation
RETGUARD_GADGET_FUNCTION
int example(int x)
{
    // Inserts return address check
    RETGUARD_GADGET_SCOPE();
    if (x < 0)
        return -1;
    return x + 1;
}

int main(void)
{
    // Use as normal
    return example(1);
}
```

### Automatic translation-unit mode

The automatic mode protects every instrumentable function that GCC or Clang emits for a translation unit, without source annotations or a compiler pass. The `RETGUARD_SCOPE()`, `RETGUARD_GADGET_FUNCTION` and `RETGUARD_GADGET_SCOPE()` macros are no-op in this mode as the compiler now instruments each function automatically. We recommetn this mode for most users.

However, understand that, automatic has a higher overhead per-function then manual mode.

```c
#include "retguard.h"

// The compiler instruments the function automatically
int example(int x)
{
    if (x < 0)
        return -1;
    return x + 1;
}

int main(void)
{
    // Including main()
    return example(1);
}
```

## Implementation details

At startup, the library creates secret cookies and a separate table of address masks. A protected function combines its return address, the address of its stack slot, and a cookie into a seal. On return, it calculates the seal again and stops the program if it changed.

In manual mode, `RETGUARD_SCOPE()` checks every ordinary return and also runs during C++ exception unwinding. The explicit `RETGUARD_BEGIN()` and `RETGUARD_CHECK()` macros let callers choose check sites, but they must cover every exit. Protected code needs frame pointers and must not turn returns into tail calls.

The two gadget macros also remove the function's own `ret`: the function passes its seal in `r11` to a shared return thunk, which checks it again and returns. We try to reserve `r11` for this; if the compiler cannot, register zeroing must be disabled for these functions so the seal survives until the thunk. The two macros must be used together.

Automatic mode uses compiler entry and return hooks. `retguard_target()` compiles protected sources to assembly, adds an unwind rule, and uses GAS to assemble them; it rejects objects it cannot cover. On entry, the hook XORs the return address with an independently random mask selected by `((slot >> 4) ^ (slot >> 12)) & 15`, keeps the low 56 masked bits, then computes an 8-bit tag over that masked payload and puts it in the high byte. On return or exception unwind, it checks the tag over the stored payload and unmasks the return address. Both hooks jump over 16 `int3` instructions to their `ret`; the return thunk takes this path only after a successful check, following the return layout in the OpenBSD RETGUARD paper. Only source files passed to `retguard_target()` are protected automatically. Clang's generated constructor wrappers need `-mllvm -force-attribute=fn_ret_thunk_extern`; `retguard_target()` supplies this flag and maps Clang's `__fentry__` hook to the runtime entry hook. Automatic targets require LLD or gold to link the unwind references correctly.

The checks run at return or unwind, after any stack corruption has already happened. A plain manual scope checks before the machine `ret`, leaving a gap; the gadget thunk checks again just before returning. The interrupt slides constrain instruction streams that run into the hooks' `ret` instructions; both `ret` bytes remain directly addressable, and the entry hook does not authenticate its own return address. `longjmp()` skips checks for frames it discards. Unprotected code and paths that bypass a checked return are outside this protection. Stack protectors and CET shadow stacks can be used alongside it.

For example, a manual scope checks the return from `guarded()`, not the return from a function it calls. Jumping out of `guarded()` skips its check:

```c
#include <setjmp.h>
#include "retguard.h"

static jmp_buf escape;

int unguarded(void) { return 1; } // This return is not checked.

int guarded(int jump)
{
    RETGUARD_SCOPE();
    if (jump)
        longjmp(escape, 1);       // Skips the check in guarded().
    return unguarded();           // Checks guarded() when it returns, but not unguarded().
}

int main(void)
{
    if (setjmp(escape) == 0)
        guarded(1);
    return guarded(0);
}
```

In automatic mode, coverage is selected by source file. In this example, returns in `guarded.c` are checked, while returns in `main.c` and `unguarded.c` are not:

```cmake
add_executable(app main.c unguarded.c)
retguard_target(app SOURCES guarded.c)
```

Automatic compilation rejects raw return instructions (including per-function return-thunk overrides), stack-changing instructions before the entry hook (such as captured GCC nested functions), and missing runtime unwind tables. Recognized ENDBR64 and compiler NOP entry prefixes are supported. See [tests/README.md](tests/README.md) for compatibility probes and [BENCHMARK.md](BENCHMARK.md) for the final overhead results.

`retguard_target()` accepts optional compiler inlining tuning. For example, with Clang in the source CMake build:

```cmake
retguard_target(app INLINE_LIMIT 200 SOURCES parser.cc)
```

This maps to Clang's LLVM inline threshold; GCC maps the same option to `-finline-limit`. The benchmark suite runs both compiler defaults and an explicit setting of 200 for GCC and Clang, applied equally to plain and protected implementation objects. The numeric setting is standardized, but the compiler heuristics are different. Every function that remains emitted still receives protection. Clang's option is internal, so configuration checks compiler support. `--inline-limit` and `RETGUARD_BENCH_INLINE_LIMIT` allow an explicit override. See [BENCHMARK.md](BENCHMARK.md) for the final measured tradeoffs.

`retguard_target()` preserves the configured compiler stack protection. Its optional `STACK_FLAG` argument lets tests select a specific protection mode; the benchmarks use `-fstack-protector-strong` for both plain and guarded builds.

## Security properties

On startup, before `main`, 16 seal cookies and 16 independent address masks at startup; each seal cookie is forced odd. The stack-slot address selects a seal cookie with `cookies[(slot >> 4) & 15]`; the seal is `(return_address ^ slot) * cookie` modulo 2^64. The cookie and mask values are not derived from the address. Page-aligned stack ASLR does not randomize the seal-cookie selection, which uses slot-address bits 4–7. An address disclosure reveals the table selections but not their secret values. A fresh program execution generates new secrets; a child created with `fork()` inherits the existing ones.

Manual scopes and the gadget thunk compare the full 64-bit seal. If the stored seal is untouched, any change to the return address in the same stack slot is detected. If an attacker can change both the return address and seal, resistance to forgery depends on the secret cookie; a 64-bit comparison does not by itself establish 64-bit security.

Automatic returns and unwinding compare the top 8 bits of the seal computed from the masked payload as a tag. The tag check and address unmask can execute independently. The separate mask obscures the stored return address, but a disclosure of a masked word paired with its known original address reveals the corresponding mask's 56 random bits. The mask's high byte is zero because the tag occupies that byte. The seal cookie supplies the independent secret input for the tag, and the 8-bit comparison limits what each check can distinguish. A blind tag guess would have a 1-in-256 chance only if the tag were uniform and unknown; this construction does not guarantee that bound for every address or repeated attempt. Automatic mode also assumes user-space return addresses have an unused top byte.
