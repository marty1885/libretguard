#!/usr/bin/env python3
"""Inspect automatic hooks and run each behavior in an isolated process."""

import resource
import signal
import subprocess
import sys


binary = sys.argv[1]
ssp = sys.argv[2] == "--ssp"
object_files = sys.argv[3:]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

elf_header = subprocess.run(
    ["readelf", "-hW", binary], check=True, capture_output=True, text=True,
).stdout
if "Type:                              DYN" not in elf_header:
    raise SystemExit(f"{binary}: automatic executable is not PIE")

dynamic = subprocess.run(
    ["readelf", "-dW", binary], check=True, capture_output=True, text=True,
).stdout
if "TEXTREL" in dynamic:
    raise SystemExit(f"{binary}: PIE contains text relocations")

for object_file in object_files:
    relocations = subprocess.run(
        ["readelf", "-rW", object_file],
        check=True, capture_output=True, text=True,
    ).stdout
    cookie_relocations = [line for line in relocations.splitlines()
                          if "retguard_auto_cookies" in line]
    if not cookie_relocations or any("R_X86_64_PC32" not in line
                                     for line in cookie_relocations):
        raise SystemExit(
            f"{object_file}: cookie references are not all PC-relative"
        )
    code = subprocess.run(
        ["objdump", "-dr", "-Mintel", object_file],
        check=True, capture_output=True, text=True,
    ).stdout
    if "__retguard_fentry" not in code or "__retguard_auto_return_thunk" not in code:
        raise SystemExit(f"{object_file}: automatic entry or return hook missing")

if ssp:
    code = subprocess.run(
        ["objdump", "-dr", "-Mintel", "--disassemble=auto_canary_probe", object_files[0]],
        check=True, capture_output=True, text=True,
    ).stdout
    if "fs:0x28" not in code or "__stack_chk_fail" not in code or "[rbp-0x8]" not in code:
        raise SystemExit("automatic function lost its compiler canary or test slot")

def check_case(mode, expected, marker=None):
    result = subprocess.run([binary, mode], capture_output=True, text=True)
    if result.returncode != expected or (marker and result.stderr.count(marker) != 1):
        raise SystemExit(
            f"FAIL {mode}: expected {expected}"
            f"{f' and one {marker}' if marker else ''}, got {result.returncode}\n"
            f"{result.stdout}{result.stderr}"
        )
    print(f"PASS {mode}")


for mode in ("returns", "exception", "deferred_cancel", "thread_exit",
             "async_cancel"):
    check_case(mode, 0)

check_case("bad_return", -signal.SIGILL)
check_case("bad_exception", -signal.SIGABRT)

if ssp:
    check_case("bad_canary", -signal.SIGABRT, "AUTO_STACK_CHK_FAIL")

print("automatic RETGUARD tests passed")
