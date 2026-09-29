#!/usr/bin/env python3
"""Check that compiler stack canaries and CET survive RETGUARD macros."""

import argparse
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent


def command(arguments, **kwargs):
    result = subprocess.run(arguments, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(map(str, arguments))}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result


def disassemble(object_file, function):
    return command(
        ["objdump", "-dr", "-Mintel", f"--disassemble={function}", object_file]
    ).stdout


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def build(compiler, ssp, cet, directory):
    compiler_name = Path(compiler).name
    name = f"{compiler_name}_{'ssp' if ssp else 'plain'}_{'cet' if cet else 'nocet'}"
    fixture = directory / f"{name}_fixture.o"
    runtime = directory / f"{name}_runtime.o"
    executable = directory / name
    flags = [
        "-O2", "-g", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
        "-fno-omit-frame-pointer", "-fno-optimize-sibling-calls",
        "-fstack-protector-all" if ssp else "-fno-stack-protector",
        "-fcf-protection=full" if cet else "-fcf-protection=none",
        f"-DTEST_CET={int(cet)}", f"-I{ROOT / 'src'}",
    ]
    command([compiler, *flags, "-c", FIXTURES / "c_fixture.c", "-o", fixture])
    command([compiler, "-O2", "-fno-stack-protector", "-fcf-protection=branch",
             "-c", ROOT / "src/retguard.c", "-o", runtime])
    objects = [fixture, runtime]
    link_flags = ["-Wl,--wrap=__stack_chk_fail"]
    if cet:
        link_flags.append("-Wl,-z,shstk")
    command([compiler, *objects, *link_flags, "-o", executable])
    return fixture, runtime, executable


def build_cpp(compiler, ssp, cet, directory):
    cxx = "clang++" if "clang" in Path(compiler).name else "g++"
    expect(shutil.which(cxx), f"{cxx} is required for the C++ workload")
    name = f"{Path(compiler).name}_{'ssp' if ssp else 'plain'}_{'cet' if cet else 'nocet'}_cpp"
    fixture = directory / f"{name}.o"
    runtime = directory / f"{name}_runtime.o"
    executable = directory / name
    flags = [
        "-O2", "-g", "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fno-omit-frame-pointer", "-fno-optimize-sibling-calls",
        "-fstack-protector-all" if ssp else "-fno-stack-protector",
        "-fcf-protection=full" if cet else "-fcf-protection=none",
        f"-DTEST_CET={int(cet)}", f"-I{ROOT / 'src'}",
    ]
    command([cxx, *flags, "-c", FIXTURES / "cpp_fixture.cc", "-o", fixture])
    command([compiler, "-O2", "-fno-stack-protector", "-fcf-protection=branch",
             "-c", ROOT / "src/retguard.c",
             "-o", runtime])
    objects = [fixture, runtime]
    link_flags = ["-Wl,--wrap=__stack_chk_fail"]
    if cet:
        link_flags.append("-Wl,-z,shstk")
    command([cxx, *objects, *link_flags, "-o", executable])
    return fixture, executable


def inspect_codegen(fixture, ssp, cet):
    normal = disassemble(fixture, "normal_unguarded")
    expect(re.search(r"\bret\b", normal), "direct return was not emitted")

    if ssp:
        for function in ("ssp_unguarded", "ssp_guarded", "ssp_before_cet"):
            code = disassemble(fixture, function)
            expect("fs:0x28" in code, f"{function}: no compiler canary load/check")
            expect(re.search(r"\[rbp-0x8\]", code),
                   f"{function}: test's canary slot assumption changed")
            expect("__stack_chk_fail" in code,
                   f"{function}: no compiler canary failure edge")
    if cet:
        code = disassemble(fixture, "cet_unguarded")
        expect("endbr64" in code, "CET branch protection was not emitted")


def execute(executable, mode, cet):
    environment = os.environ.copy()
    if cet:
        environment["GLIBC_TUNABLES"] = (
            "glibc.cpu.hwcaps=SHSTK:glibc.cpu.x86_shstk=on"
        )
    return subprocess.run([executable, mode], text=True, capture_output=True,
                          env=environment)


def check_variant(fixture, executable, ssp, cet):
    inspect_codegen(fixture, ssp, cet)

    result = execute(executable, "normal", cet)
    expect(result.returncode == 0, f"normal returns failed: {result.stderr}")

    if ssp:
        for mode in ("ssp_unguarded", "ssp_guarded"):
            result = execute(executable, mode, cet)
            expect(result.returncode == -signal.SIGABRT,
                   f"{mode}: real stack canary handler did not abort: {result}")
            expect(result.stderr.count("STACK_CHK_FAIL_HOOK") == 1,
                   f"{mode}: compiler did not call __stack_chk_fail: {result.stderr}")

    if cet:
        status = execute(executable, "cet_status", cet)
        expect(status.returncode == 0 and "CET_ACTIVE" in status.stdout,
               "CET shadow stack is not active")
        result = execute(executable, "cet_unguarded", cet)
        expect(result.returncode == 86 and "CET_CPERR" in result.stderr,
               f"corrupt return did not produce SEGV_CPERR: {result}")
        if ssp:
            result = execute(executable, "ssp_before_cet", cet)
            expect(result.returncode == -signal.SIGABRT and
                   result.stderr.count("STACK_CHK_FAIL_HOOK") == 1,
                   f"stack protector did not run before return/CET: {result}")


def check_cpp_variant(fixture, executable, ssp, cet):
    code = command(["objdump", "-dr", "-Mintel", fixture]).stdout
    expect("retguard_auto_cookies" in code,
           "C++ workload did not emit RETGUARD checks")
    if ssp:
        probe = disassemble(fixture, "cpp_ssp_guarded")
        expect("fs:0x28" in probe and "__stack_chk_fail" in probe and
               "[rbp-0x8]" in probe,
               "C++ workload lost compiler stack canaries")
    if cet:
        expect("endbr64" in code, "C++ workload lost CET branch protection")
    normal = execute(executable, "normal", cet)
    expect(normal.returncode == 0,
           f"C++ workload failed: {normal.returncode}: {normal.stderr}")
    bad_seal = execute(executable, "bad_seal", cet)
    expect(bad_seal.returncode == -signal.SIGABRT,
           f"C++ exception did not run RETGUARD cleanup: {bad_seal}")
    if ssp:
        bad_canary = execute(executable, "bad_canary", cet)
        expect(bad_canary.returncode == -signal.SIGABRT and
               bad_canary.stderr.count("CPP_STACK_CHK_FAIL_HOOK") == 1,
               f"C++ compiler canary handler did not run: {bad_canary}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", action="append", help="compiler to test; repeatable")
    parser.add_argument("--build-dir", type=Path,
                        help="keep generated test executables in this directory")
    parser.add_argument("--require-cet", action="store_true",
                        help="fail instead of skipping CET when unavailable")
    options = parser.parse_args()
    compilers = options.cc or [name for name in ("gcc", "clang") if shutil.which(name)]
    if not compilers:
        parser.error("neither GCC nor Clang is installed")
    if not shutil.which("objdump"):
        parser.error("objdump is required for code generation checks")

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    count = 0
    if options.build_dir:
        options.build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retguard-tests-",
                                     dir=options.build_dir) as temporary:
        directory = Path(temporary)
        for compiler in compilers:
            cet_probe_fixture, cet_probe_runtime, cet_probe = build(
                compiler, False, True, directory)
            del cet_probe_fixture, cet_probe_runtime
            cet_status = execute(cet_probe, "cet_status", True)
            cet_available = (cet_status.returncode == 0 and
                             "CET_ACTIVE" in cet_status.stdout)
            if options.require_cet:
                expect(cet_available, f"{compiler}: CET shadow stack unavailable")
            for ssp in (False, True):
                for cet in (False, True):
                    if cet and not cet_available:
                        continue
                    fixture, runtime, executable = build(
                        compiler, ssp, cet, directory)
                    check_variant(fixture, executable, ssp, cet)
                    cpp_fixture, cpp_executable = build_cpp(
                        compiler, ssp, cet, directory)
                    check_cpp_variant(cpp_fixture, cpp_executable, ssp, cet)
                    count += 1
                    print(f"PASS {compiler}: "
                          f"{'SSP' if ssp else 'no SSP'}, "
                          f"{'CET' if cet else 'no CET'}")
            if not cet_available:
                print(f"SKIP {compiler}: CET shadow stack unavailable")
    print(f"{count} protection combinations passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
