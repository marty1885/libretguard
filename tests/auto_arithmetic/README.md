# Automatic arithmetic and SysV ABI regression

Run `python3 tests/auto_arithmetic/run.py --cc gcc --build-dir /tmp/retguard-arithmetic-gcc` (or `--cc clang`). Each invocation compiles O2 and O3 fixtures against the current runtime and actual hooks; no performance timings are collected.

The uninstrumented assembly bridge selects controlled stack slots and invokes `__retguard_fentry` and `__retguard_auto_return_thunk` directly. The independent C oracle checks:

- all 256 cookie/mask slot-index combinations, over eight deterministic random-key rounds (2,048 cases per compiler/optimization);
- odd 64-bit cookies, nontrivial low-56-bit masks, and nonzero tag bytes;
- exact `payload = raw ^ mask`, `tag = ((payload ^ slot) * cookie) >> 56`, and `stored = payload | (tag << 56)` arithmetic with unsigned 64-bit wraparound;
- complete restoration of the raw return address and return-stack position;
- preservation of all six incoming integer argument registers and RAX/AL;
- preservation of representative RAX/RDX and XMM0/XMM1 return values.

Instrumented C functions additionally verify weighted six-argument calls, int128 returns, a three-word aggregate using the hidden result pointer, double arguments and return, and variadic double arguments requiring the incoming AL vector count. A separate corrupted-tag subprocess must terminate with SIGILL. Existing tests cover unwinding, cancellation, and CET; this fixture does not duplicate them.

The ABI register roles are specified in the primary [x86-64 psABI source](https://gitlab.com/x86-psABIs/x86-64-ABI/-/blob/master/x86-64-ABI/low-level-sys-info.tex). R8/R9 are caller-saved and are not normal SysV return registers. R10 can carry a nested function's static chain. GCC saves R10 with a push before fentry in captured nested functions; the assembly compiler currently rejects those pre-hook stack changes. Bypassing that check would expose the hook's R10 clobber and an incorrect return-slot assumption. Nested-function support is deliberately unchanged.

The bridge uses an allocated synthetic stack and is intended for ordinary non-CET test execution; it does not simulate a hardware shadow-stack entry for its synthetic return target. These arithmetic checks do not establish resistance to exhaustive forgery of the existing eight-bit tag.
