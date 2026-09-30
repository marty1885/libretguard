#!/usr/bin/env python3
"""Reject return-thunk overrides before an encoded address can be returned."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
from elftools.elf.elffile import ELFFile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from retguard_asm_compiler import patch_assembly, patch_assembly_bytes  # noqa: E402
from retguard_coverage import safe_entry_prefix  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--nested-functions", action="store_true",
                        help="also check GCC's captured nested-function entry")
    args = parser.parse_args()

    for instruction in ("ret", "retq", "ret $16", "rep ret", "bnd retq", "lretq"):
        try:
            patch_assembly("probe:\n\t.cfi_startproc\n\t" + instruction + "\n")
        except ValueError as error:
            assert "unthunked return" in str(error), error
        else:
            raise AssertionError(f"accepted {instruction}")

    # Mnemonics in data are harmless; preserve strings and replace symbols
    # only in instructions/metadata.
    text = 'probe:\n\t.cfi_startproc\n\t.string "ret __fentry__"\n\tjmp __x86_return_thunk\n'
    patched = patch_assembly(text)
    assert '\t.string "ret __fentry__"' in patched
    assert "jmp __retguard_auto_return_thunk" in patched
    # Literal non-UTF8 data and non-LF control characters stay inside GAS
    # strings. Do not replace hook names embedded in those literals.
    data_line = b'\t.asciz "\x8f\xff\x85\xc2\x85\x0b__fentry__\x0cret __x86_return_thunk"\n'
    raw = b'probe:\n\t.cfi_startproc\n' + data_line + b'\tjmp __x86_return_thunk\n'
    patched_bytes = patch_assembly_bytes(raw)
    assert data_line in patched_bytes
    assert b'\tjmp __retguard_auto_return_thunk\n' in patched_bytes
    assert safe_entry_prefix(b"\xf3\x0f\x1e\xfa\x90\x66\x90")
    assert not safe_entry_prefix(b"\x41\x52")  # push %r10

    with tempfile.TemporaryDirectory(prefix="retguard-return-regression-") as temp:
        source = Path(temp) / "override.c"
        source.write_text(
            '__attribute__((noinline, function_return("keep"))) '
            'int probe(int value) { return value + 1; }\n'
        )
        command = [
            sys.executable, str(ROOT / "tools/retguard_asm_compiler.py"),
            args.cc, "-O2", "-g", "-fPIE", "-fno-omit-frame-pointer",
            "-fno-optimize-sibling-calls", "-pg", "-mfentry",
            "-mfunction-return=thunk-extern", "-fasynchronous-unwind-tables",
            "-c", str(source), "-o", str(Path(temp) / "override.o"),
        ]
        if "clang" in Path(args.cc).name:
            command.append("-fno-addrsig")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 or "unthunked return" not in result.stderr:
            raise AssertionError(f"return override was not rejected:\n{result.stderr}")
        if args.nested_functions:
            source.write_text(
                'int outer(int x) { '
                '__attribute__((noinline)) int nested(int y) { return x + y; } '
                'return nested(3); }\n'
            )
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0 or "unchanged return slot" not in result.stderr:
                raise AssertionError(f"nested entry was not rejected:\n{result.stderr}")
        source.write_text('int probe(int value) { return value + 1; }\n')
        result = subprocess.run(command + ["-fcf-protection=branch", "-fpatchable-function-entry=4"],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(f"safe entry prefix was rejected:\n{result.stderr}")
        object_file = Path(temp) / "override.o"
        verified_bytes = object_file.read_bytes()
        result = subprocess.run(command + ["-fno-asynchronous-unwind-tables", "-fno-unwind-tables"],
                                capture_output=True, text=True)
        if result.returncode == 0 or not any(message in result.stderr for message in
                ("no unwind-covered functions", "missing .eh_frame")):
            raise AssertionError(f"unwind-disabled object was not rejected:\n{result.stderr}")
        assert object_file.read_bytes() == verified_bytes, "failed compilation replaced verified output"
        # Exercise file I/O through the real launcher with synthetic compiler
        # output, then verify that GAS sees the original constant bytes.
        emitted = (
            b'.text\n.globl probe\n.type probe,@function\nprobe:\n'
            b'\t.cfi_startproc\n\tcall __fentry__\n\tjmp __x86_return_thunk\n'
            b'\t.cfi_endproc\n.size probe,.-probe\n.section .rodata\n'
            b'\t.asciz "\x8f\xff\x85 __fentry__"\n'
        )
        compiler = Path(temp) / "emit_assembly.py"
        compiler.write_text(
            'from pathlib import Path\nimport sys\n'
            f'Path(sys.argv[sys.argv.index("-o") + 1]).write_bytes(bytes.fromhex("{emitted.hex()}"))\n'
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/retguard_asm_compiler.py"),
             sys.executable, str(compiler), "-c", str(source), "-o", str(object_file)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(f"binary assembly output failed:\n{result.stderr}")
        with object_file.open("rb") as stream:
            assert ELFFile(stream).get_section_by_name(".rodata").data() == b'\x8f\xff\x85 __fentry__\0'
    print("automatic return-override regression passed")


if __name__ == "__main__":
    main()
