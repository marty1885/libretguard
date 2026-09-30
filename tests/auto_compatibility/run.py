#!/usr/bin/env python3
"""Inspect automatic hooks and run each behavior in an isolated process."""

import resource
import re
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

symbols = subprocess.run(
    ["nm", "-n", binary], check=True, capture_output=True, text=True,
).stdout
table_addresses = {}
for line in symbols.splitlines():
    fields = line.split()
    if len(fields) == 3 and fields[2] in ("retguard_auto_masks", "retguard_auto_cookies"):
        table_addresses[fields[2]] = int(fields[0], 16)
if len(table_addresses) != 2:
    raise SystemExit(f"{binary}: automatic secret tables are missing")
dynamic_relocations = subprocess.run(
    ["readelf", "-rW", binary], check=True, capture_output=True, text=True,
).stdout
got_addresses = {}
for line in dynamic_relocations.splitlines():
    fields = line.split()
    if len(fields) == 4 and fields[2] == "R_X86_64_RELATIVE":
        for name, address in table_addresses.items():
            if int(fields[3], 16) == address:
                got_addresses[name] = int(fields[0], 16)
if len(got_addresses) != 2:
    raise SystemExit(f"{binary}: GOT entries for automatic tables are missing")
frames = subprocess.run(
    ["readelf", "--debug-dump=frames", binary],
    check=True, capture_output=True, text=True,
).stdout
frame_addresses = [int(value, 16) for value in re.findall(
    r"DW_OP_GNU_encoded_addr: fmt:9b addr:([0-9a-f]+)", frames,
)]
expected_pair = [got_addresses["retguard_auto_masks"],
                 got_addresses["retguard_auto_cookies"]]
if not frame_addresses or len(frame_addresses) % 2 or any(
    frame_addresses[i:i + 2] != expected_pair
    for i in range(0, len(frame_addresses), 2)
):
    raise SystemExit(f"{binary}: unwind expressions do not address the secret tables")

def instructions(name):
    code = subprocess.run(
        ["objdump", "-d", "-Mintel", f"--disassemble={name}", binary],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line.split("\t")[-1].split()[0]
            for line in code.splitlines()
            if re.match(r"\s*[0-9a-f]+:\s", line)]


entry_instructions = instructions("__retguard_fentry")
if entry_instructions[-18:] != ["jmp", *(["int3"] * 16), "ret"]:
    raise SystemExit(f"{binary}: entry hook does not jump over an int3 slide")
thunk_instructions = instructions("__retguard_auto_return_thunk")
if thunk_instructions[-19:] != ["jmp", "ud2", *(["int3"] * 16), "ret"]:
    raise SystemExit(f"{binary}: checked return does not jump over an int3 slide")

for object_file in object_files:
    relocations = subprocess.run(
        ["readelf", "-rW", object_file],
        check=True, capture_output=True, text=True,
    ).stdout
    cookie_relocations = [line for line in relocations.splitlines()
                          if "retguard_auto_cookies" in line]
    if not cookie_relocations or any("R_X86_64_GOTPCREL" not in line
                                     for line in cookie_relocations):
        raise SystemExit(
            f"{object_file}: cookie references are not all GOT-relative"
        )
    mask_relocations = [line for line in relocations.splitlines()
                        if "retguard_auto_masks" in line]
    if not mask_relocations or any("R_X86_64_GOTPCREL" not in line
                                   for line in mask_relocations):
        raise SystemExit(
            f"{object_file}: mask references are not all GOT-relative"
        )
    code = subprocess.run(
        ["objdump", "-dr", "-Mintel", object_file],
        check=True, capture_output=True, text=True,
    ).stdout
    if "__retguard_fentry" not in code or "__retguard_auto_return_thunk" not in code:
        raise SystemExit(f"{object_file}: automatic entry or return hook missing")
    if re.search(r"\tret(?:q)?\b", code):
        raise SystemExit(f"{object_file}: unthunked return in automatic object")

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
