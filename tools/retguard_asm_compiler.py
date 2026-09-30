#!/usr/bin/env python3
"""Compile an automatic source file to GAS assembly with checked-return CFI."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile

from elftools.elf.elffile import ELFFile

from retguard_coverage import check_coverage, records


def return_address_rule() -> str:
    # GAS builds the FDE, its lengths, and the GOT relocations. The two table
    # references are indirect PC-relative addresses so linked PIEs need no
    # dynamic relocation in read-only .eh_frame.
    expression: list[tuple[str, int]] = []

    def bytes_(*values: int) -> None:
        expression.extend((f"0x{value:02x}", 1) for value in values)

    def table(name: str) -> None:
        bytes_(0xF1, 0x9B)  # DW_OP_GNU_encoded_addr, indirect pcrel sdata4
        expression.append((f"data4({name}@GOTPCREL)", 4))

    bytes_(0x12, 0x10, 0x08, 0x1C)  # CFA -> CFA, slot=CFA-8
    bytes_(0x12, 0x06)              # slot, stored word
    bytes_(0x12, 0x0E)              # duplicate stored word; const8u mask
    bytes_(0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00)
    bytes_(0x1A)                    # payload = stored & ((1<<56)-1)
    bytes_(0x12, 0x15, 0x03)        # duplicate payload; select slot
    bytes_(0x12, 0x34, 0x25, 0x16, 0x3C, 0x25)
    bytes_(0x27, 0x3F, 0x1A, 0x33, 0x24)  # ((slot>>4)^(slot>>12))&15, times 8
    table("retguard_auto_masks")
    bytes_(0x22, 0x06, 0x27)        # load mask; unmask payload
    # The mask's high byte is zero, so the raw address is already canonical.
    bytes_(0x15, 0x03, 0x34, 0x25, 0x3F, 0x1A, 0x33, 0x24)
    table("retguard_auto_cookies")
    bytes_(0x22, 0x06, 0x15, 0x02, 0x15, 0x05, 0x27, 0x1E)
    bytes_(0x08, 0x38, 0x25, 0x15, 0x03, 0x08, 0x38, 0x25)
    bytes_(0x29, 0x1F, 0x1A)        # return raw if tag matches, otherwise zero
    size = sum(width for _, width in expression)
    parts = ["0x16", "0x10", f"uleb128({size})"]
    parts.extend(value for value, _ in expression)
    return "\t.cfi_escape " + ", ".join(parts)


def patch_assembly(source: str) -> str:
    rule = return_address_rule()
    output = []
    fdes = 0
    clang_terminate = False
    for line in source.splitlines(keepends=True):
        if line.startswith("__clang_call_terminate:"):
            # Clang synthesizes this noreturn EH helper after instrumentation.
            # It has no fentry hook or return to decode.
            clang_terminate = True
        elif line and not line[0].isspace() and not line.startswith(".L") \
                and line.rstrip().endswith(":"):
            clang_terminate = False
        if not line.lstrip().startswith((".string", ".asciz", ".ascii")):
            line = re.sub(r"\b__x86_return_thunk\b",
                          "__retguard_auto_return_thunk", line)
            line = re.sub(r"\b__fentry__\b", "__retguard_fentry", line)
        output.append(line)
        if line.strip() == ".cfi_startproc" and not clang_terminate:
            output.append(rule + "\n")
            fdes += 1
    if not fdes:
        raise ValueError("automatic source emitted no unwind-covered functions")
    return "".join(output)


def main(args: list[str]) -> None:
    if len(args) < 4 or "-c" not in args or "-o" not in args:
        raise ValueError("expected a compiler command with -c and -o")
    output = Path(args[args.index("-o") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retguard-", dir=output.parent) as temp:
        assembly = Path(temp) / "raw.s"
        patched = Path(temp) / "guarded.s"
        compile_args = args.copy()
        compile_args[compile_args.index("-c")] = "-S"
        compile_args[compile_args.index("-o") + 1] = str(assembly)
        subprocess.run(compile_args, check=True)
        patched.write_text(patch_assembly(assembly.read_text()))
        subprocess.run(["as", "--64", "-o", str(output), str(patched)], check=True)
    with output.open("rb") as stream:
        elf = ELFFile(stream)
        check_coverage(elf, records(elf.get_section_by_name(".eh_frame").data()))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"retguard assembly compiler: {error}") from error
