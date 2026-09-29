# libretguard

Best effort approximation of OpenBSD's RETGUARD for Linux, without custom compiler passes.

The design is based on the [OpenBSD RETGUARD paper](https://www.openbsd.org/papers/asiabsdcon2019-rop-paper.pdf).

## Usage

`libretguard.a` supports manual and automatic protection in the same application. Manual source files use `RETGUARD_SCOPE()`, or `RETGUARD_GADGET_FUNCTION` with `RETGUARD_GADGET_SCOPE()`, to select protected functions. Automatic source files use GCC instrumentation and the object patcher described below.

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

The automatic mode protects every instrumentable function that GCC emits for a translation unit, without source annotations or a compiler pass. The `RETGUARD_SCOPE()`, `RETGUARD_GADGET_FUNCTION` and `RETGUARD_GADGET_SCOPE()` macros are no-op in this mode as the compiler now instruments each function automatically. We recommetn this mode for most users.

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

At startup, the library creates secret cookies. A protected function combines its return address, the address of its stack slot, and a cookie into a seal. On return, it calculates the seal again and stops the program if it changed.

In manual mode, `RETGUARD_SCOPE()` checks every ordinary return and also runs during C++ exception unwinding. The explicit `RETGUARD_BEGIN()` and `RETGUARD_CHECK()` macros let callers choose check sites, but they must cover every exit. Protected code needs frame pointers and must not turn returns into tail calls.

The two gadget macros also remove the function's own `ret`: the function passes its seal in `r11` to a shared return thunk, which checks it again and returns. We try to reserve `r11` for this; if the compiler cannot, register zeroing must be disabled for these functions so the seal survives until the thunk. The two macros must be used together.

Automatic mode uses GCC's entry and return hooks, then patches each compiled object so exception unwinding checks returns too. On entry, it puts an 8-bit tag in the top byte of the stack return address; on return, a shared thunk checks the tag and restores the address. The patcher rejects objects it cannot cover. Only source files passed to `retguard_target()` are protected automatically.

The checks run at return or unwind, after any stack corruption has already happened. A plain manual scope checks before the machine `ret`, leaving a gap; the gadget thunk checks again just before returning. `longjmp()` skips checks for frames it discards. Unprotected code and paths that bypass a checked return are outside this protection. Stack protectors and CET shadow stacks can be used alongside it.

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
retguard_target(app STACK_FLAG -fno-stack-protector SOURCES guarded.c)
```

## Security properties

Manual scopes and the gadget thunk each compare a 64-bit seal. If the stored seal is untouched, any change to the return address in the same stack slot is detected. If an attacker can change both, the check depends on the cookie staying secret; 64 compared bits do not mean a guaranteed 64-bit resistance to forgery.

Automatic returns and unwinding compare an 8-bit tag. An ideal unknown tag gives a blind guess a 1-in-256 chance, though this tag does not guarantee that probability for every address. This mode assumes a user-space return address has an unused top byte (aka high address) and depends on the cookie staying secret.
