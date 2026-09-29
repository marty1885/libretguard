#!/usr/bin/env python3
"""Exercise GCC and Clang per-function checked returns."""

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


def command(arguments):
    result = subprocess.run(arguments, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(map(str, arguments))}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def disassemble(obj, name):
    return command(["objdump", "-dr", "-Mintel", f"--disassemble={name}", obj])


def clang_fixed_r11():
    return subprocess.run(["clang", "-ffixed-r11", "-x", "c",
                           "-fsyntax-only", "/dev/null"],
                          capture_output=True).returncode == 0


def build(directory, compiler, opt, ssp, cet, zero=None, gap=False,
          fixed_clang=False):
    tag = f"{compiler}_{opt}_{'ssp' if ssp else 'plain'}_{'cet' if cet else 'nocet'}"
    if zero:
        tag += f"_{zero}"
    if gap:
        tag += "_signal_gap"
    c_obj = directory / f"{tag}_c.o"
    cpp_obj = directory / f"{tag}_cpp.o"
    driver_obj = directory / f"{tag}_driver.o"
    runtime_obj = directory / f"{tag}_runtime.o"
    thunk_obj = directory / f"{tag}_thunk.o"
    executable = directory / tag
    common = [
        f"-{opt}", "-g", "-Wall", "-Wextra", "-Werror",
        "-fno-omit-frame-pointer", "-fno-optimize-sibling-calls",
        *(["-ffixed-r11"] if compiler == "gcc" else []),
        *(["-ffixed-r11", "-DRETGUARD_CLANG_FIXED_R11"] if fixed_clang else []),
        *([f"-fzero-call-used-regs={zero}"] if zero else []),
        "-fstack-protector-all" if ssp else "-fno-stack-protector",
        "-fcf-protection=full" if cet else "-fcf-protection=none",
        f"-I{ROOT / 'src'}",
    ]
    cc = "gcc" if compiler == "gcc" else "clang"
    cxx = "g++" if compiler == "gcc" else "clang++"
    command([cc, *common, "-std=gnu11", "-c",
             FIXTURES / "c_targets.c", "-o", c_obj])
    command([cxx, *common, "-std=c++17", "-c",
             FIXTURES / "cpp_targets.cc", "-o", cpp_obj])
    command([cxx, *common, "-std=c++17", "-c",
             FIXTURES / "driver.cc", "-o", driver_obj])
    command([cc, f"-{opt}", "-std=gnu11", "-c", ROOT / "src/retguard.c",
             "-o", runtime_obj])
    gap_flag = ["-DRETGUARD_TEST_SIGNAL_GAP"] if gap else []
    command([cc, *gap_flag, "-c", ROOT / "src/retguard_thunks.S",
             "-o", thunk_obj])
    link = ["-Wl,--wrap=__stack_chk_fail"]
    if cet:
        link.append("-Wl,-z,shstk")
    command([cxx, c_obj, cpp_obj, driver_obj, runtime_obj, thunk_obj,
             *link, "-o", executable])
    return c_obj, cpp_obj, thunk_obj, executable


def run(executable, mode, cet):
    env = os.environ.copy()
    if cet:
        env["GLIBC_TUNABLES"] = "glibc.cpu.hwcaps=SHSTK:glibc.cpu.x86_shstk=on"
    return subprocess.run([executable, mode], capture_output=True, text=True,
                          env=env)


def check_code(c_obj, cpp_obj, thunk_obj, compiler, opt, ssp, cet, zero,
               fixed_clang):
    plain = disassemble(c_obj, "plain_function")
    expect(re.search(r"\bret\b", plain), "unselected function lost direct ret")
    scope_only = disassemble(c_obj, "scope_only")
    expect(re.search(r"\bret\b", scope_only) and
           "__x86_return_thunk" not in scope_only,
           "check-only function did not keep its direct return")
    expect(not re.search(r"\bmov\s+r11,", scope_only),
           "check-only scope exposed its seal in r11")
    for name in ("gadget_normal", "gadget_recursive", "gadget_void",
                 "gadget_pair_value",
                 "gadget_double_value", "gadget_bad_address", "gadget_bad_seal",
                 "gadget_bad_canary"):
        code = disassemble(c_obj, name)
        expect("__x86_return_thunk" in code, f"{name}: no checked return jump")
        expect(not re.search(r"\bret\b", code), f"{name}: direct ret remains")
        expect(re.search(r"\bmov\s+r11,", code), f"{name}: no seal handoff")
        # No instruction may overwrite the handoff before the thunk jump.
        handoff = list(re.finditer(r"\bmov\s+r11,", code))[-1]
        tail = code[handoff.end():code.rfind("__x86_return_thunk")]
        expect(not re.search(r"\b(?:mov|xor|sub|add|pop|lea)\s+r11(?:d|w|b)?,", tail),
               f"{name}: r11 clobbered after handoff")
        if cet:
            expect("endbr64" in code, f"{name}: no CET branch protection")
    no_scope = disassemble(c_obj, "gadget_no_scope")
    expect("__x86_return_thunk" in no_scope and
           not re.search(r"\bret\b", no_scope),
           "gadget_no_scope did not use the checked return path")
    for name in ("gadget_cpp_workload",):
        code = disassemble(cpp_obj, name)
        expect("__x86_return_thunk" in code, f"{name}: no checked return jump")
        expect(not re.search(r"\bret\b", code), f"{name}: direct ret remains")
    for name in ("gadget_cpp_exception", "gadget_cpp_bad_exception"):
        code = disassemble(cpp_obj, name)
        expect(not re.search(r"\bret\b", code), f"{name}: direct ret remains")
    thunk = disassemble(thunk_obj, "__x86_return_thunk")
    expect("retguard_auto_cookies" in thunk and "ud2" in thunk and
           "xor    r11d,r11d" in thunk and re.search(r"\bret\b", thunk),
           "thunk lost its cookie check or cookie-register clear")
    if ssp:
        code = disassemble(c_obj, "gadget_bad_canary")
        canary_slot = "[rbp-0x18]" if compiler == "gcc" and opt == "O0" else "[rbp-0x8]"
        expect("fs:0x28" in code and "__stack_chk_fail" in code and
               canary_slot in code,
               "compiler stack canary or known test slot disappeared")
    if zero:
        plain = disassemble(c_obj, "plain_function")
        expect(re.search(r"\bxor\s+r\w+d,r\w+d", plain),
               "register clearing disappeared from unselected functions")
        gadget = disassemble(c_obj, "gadget_normal")
        if compiler == "clang" and not fixed_clang:
            expect(not re.search(r"\bxor\s+r(?:8|9|10|11)d,r(?:8|9|10|11)d", gadget),
                   "Clang did not suppress register clearing in the selected function")
        else:
            expect(re.search(r"\bxor\s+r10d,r10d", gadget) and
                   not re.search(r"\bxor\s+r11d,r11d", gadget),
                   "failed to clear call-used GPRs while preserving the seal")


def check_runtime(executable, ssp, cet):
    for mode in ("normal", "exception"):
        result = run(executable, mode, cet)
        expect(result.returncode == 0, f"{mode}: {result}")
    for mode in ("bad_address", "bad_seal", "bad_exception"):
        result = run(executable, mode, cet)
        expect(result.returncode == -signal.SIGABRT,
               f"{mode}: return guard did not abort: {result}")
    bypass = run(executable, "bypass", cet)
    expect(bypass.returncode == -signal.SIGILL,
           f"direct jump to checked thunk was accepted: {bypass}")
    no_scope = run(executable, "no_scope", cet)
    expect(no_scope.returncode == -signal.SIGILL,
           f"return path without RETGUARD_SCOPE was accepted: {no_scope}")
    if ssp:
        result = run(executable, "bad_canary", cet)
        expect(result.returncode == -signal.SIGABRT and
               result.stderr.count("GADGET_STACK_CHK_FAIL") == 1,
               f"compiler stack canary handler did not run: {result}")
    if cet:
        status = run(executable, "cet_status", True)
        expect(status.returncode == 0 and "GADGET_CET_ACTIVE" in status.stdout,
               "CET shadow stack is not active")
        result = run(executable, "cet_plain_corrupt", True)
        expect(result.returncode == 86 and "GADGET_CET_CPERR" in result.stderr,
               f"CET did not reject an unguarded corrupt return: {result}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-cet", action="store_true")
    parser.add_argument("--opt", choices=("O0", "O2", "O3"), default="O2")
    parser.add_argument("--compiler", choices=("gcc", "clang"), default="gcc")
    parser.add_argument("--build-dir", type=Path,
                        help="keep generated test executables in this directory")
    options = parser.parse_args()
    for tool in (("gcc", "g++", "objdump") if options.compiler == "gcc"
                 else ("clang", "clang++", "objdump")):
        if not shutil.which(tool):
            parser.error(f"{tool} is required")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    fixed_clang = options.compiler == "clang" and clang_fixed_r11()
    count = 0
    if options.build_dir:
        options.build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retguard-gadget-",
                                     dir=options.build_dir) as temp:
        directory = Path(temp)
        _, _, _, probe = build(directory, options.compiler, options.opt,
                              False, True, fixed_clang=fixed_clang)
        status = run(probe, "cet_status", True)
        cet_available = status.returncode == 0 and "GADGET_CET_ACTIVE" in status.stdout
        if options.require_cet:
            expect(cet_available, "CET shadow stack unavailable")
        for zero in (None, "all-gpr", "all"):
            for ssp in (False, True):
                for cet in (False, True):
                    if cet and not cet_available:
                        continue
                    c_obj, cpp_obj, thunk_obj, executable = build(
                        directory, options.compiler, options.opt, ssp, cet, zero,
                        fixed_clang=fixed_clang)
                    check_code(c_obj, cpp_obj, thunk_obj, options.compiler,
                               options.opt, ssp, cet, zero, fixed_clang)
                    check_runtime(executable, ssp, cet)
                    count += 1
                    print(f"PASS {options.compiler} checked return {options.opt}: "
                          f"{'SSP' if ssp else 'no SSP'}, "
                          f"{'CET' if cet else 'no CET'}, "
                          f"{zero if zero else 'no register clearing'}, "
                          f"{'fixed r11' if options.compiler == 'gcc' or fixed_clang else 'unreserved r11'}")
        if not cet_available:
            print(f"SKIP {options.compiler} checked return: CET shadow stack unavailable")
        _, _, _, gap_executable = build(
            directory, options.compiler, options.opt, True, cet_available,
            gap=True, fixed_clang=fixed_clang)
        gap_result = run(gap_executable, "signal_gap", cet_available)
        expect(gap_result.returncode == 0,
               f"signal between checked thunk and ret corrupted handoff: {gap_result}")
        print(f"PASS {options.compiler} checked return {options.opt}: signal gap")
    print(f"{count} checked-return combinations passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
