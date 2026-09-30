# Tests

Configure and run from the repository root:

```sh
cmake -S . -B build/cmake -G Ninja
cmake --build build/cmake
ctest --test-dir build/cmake --output-on-failure
```

CTest starts one runner per feature group. The runners build their own compiler
variants and launch one process per fatal case, since a successful guard check
ends that process. There is no `fork()` in a test fixture. Use `ctest -V` to see
the individual case names and matrix variants.

Each Python runner sits beside its fixture files. The initialization and
constructor smoke tests are single executables, so they need no Python runner:

```text
tests/
  initialization/      fixture.c
  manual_api/          run.py, fixture.c
  manual_smoke/        constructor_smoke.cc
  manual_protections/  run.py, c_fixture.c, cpp_fixture.cc
  checked_return/      run.py, c_targets.c, cpp_targets.cc, driver.cc
  auto_compatibility/  run.py, workload.cc, extra.c, mixed_manual.c
```

| CTest name | Runner and fixture | What it checks |
| --- | --- | --- |
| `manual.initialization` | `initialization/fixture.c` | A linker-wrapped `getrandom()` supplies even cookies and one zero cookie; preinit makes every cookie odd without another draw. |
| `manual.api` | `manual_api/run.py` → `fixture.c` | `normal`: pre-main cookie initialization, recursion, early void return, explicit return. `bad_return`: guarded address corruption aborts. With required CET, `cet_bad_return`: an unguarded corrupt return faults. |
| `manual.smoke` | `manual_smoke/constructor_smoke.cc` | A protected C++ global constructor runs before `main()`. |
| `manual.protections` | `manual_protections/run.py` → `c_fixture.c`, `cpp_fixture.cc` | For each stack protector/CET variant, inspect compiler output; run ordinary C/C++ returns and exceptions; verify compiler canary failure and C++ unwind cleanup; verify a CET control protection fault when available. |
| `manual.checked_return` | `checked_return/run.py` → `c_targets.c`, `cpp_targets.cc`, `driver.cc` | At the selected optimization level, vary stack protector, CET, and register clearing; inspect checked-return code generation; run scalar, aggregate, floating point, recursive, and C++ returns; verify missing scopes, corrupt addresses and seals, canary failure, exceptions, and a signal at the return handoff. |
| `auto_plain.compatibility` | `auto_compatibility/run.py` → `workload.cc`, `extra.c`, `mixed_manual.c` | Require PIE without `DT_TEXTREL`, inspect PC-relative cookie references and C/C++ entry/return hooks, then check recursive and mixed returns, exceptions, cancellation, `pthread_exit`, and corrupt return and unwind traps. |
| `auto_ssp.compatibility` | Same fixtures with `-fstack-protector-all` | Repeats the automatic cases and verifies the compiler canary slot and `__stack_chk_fail` path. |

The automatic workload includes both C and C++ translation units. Each is
compiled and patched separately by `retguard_target()`; the runner checks that
both retain the automatic entry and return hooks.
The CMake build links one archive. The object patcher redirects automatic
returns to `__retguard_auto_return_thunk`; manually selected returns keep
`__x86_return_thunk`. The mixed fixture exercises both in one executable.

The manual runners inspect generated instructions as well as process results.
They verify that protected functions retain compiler canary checks and that a
corrupted canary reaches `__stack_chk_fail`. CET cases are skipped if the host
cannot activate a userspace shadow stack. Configure with
`-DRETGUARD_REQUIRE_CET=ON` to require it. Automatic mode runs with GCC and Clang.

To run the Clang tests, configure a separate build directory with
`-DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++`. Google Benchmark
executables are optional via `-DRETGUARD_BUILD_BENCHMARKS=ON`.
