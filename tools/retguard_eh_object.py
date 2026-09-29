#!/usr/bin/env python3
"""Replace GCC's return-address CFI in a protected ELF64 x86-64 object.

GCC and GNU as run normally.  This post-assembly step changes only .eh_frame,
its relocations, and the symbol/string tables needed to reference the cookie
array and the automatic return entry. It rejects objects whose FDEs cannot
all be matched to fentry calls.
"""

from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile


COOKIE_NAME = b"retguard_auto_cookies\0"
AUTO_THUNK_NAME = b"__retguard_auto_return_thunk\0"
MASK = 0x00FF_FFFF_FFFF_FFFF
DW_OP_GNU_ENCODED_ADDR = 0xF1
DW_EH_PE_PCREL_SDATA4 = 0x1B
R_X86_64_PC32 = 2


def uleb(value: int) -> bytes:
    out = bytearray()
    while True:
        part = value & 0x7F
        value >>= 7
        out.append(part | (0x80 if value else 0))
        if not value:
            return bytes(out)


def read_leb(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def return_address_expression() -> tuple[bytes, int]:
    # The CFA is already on the DW_CFA_val_expression stack.  Compute
    # slot=CFA-8, raw=tagged&((1<<56)-1),
    # index=(slot>>4)&15, and cookie=cookies[index].  The final value is
    # raw if the top-byte tag matches, or zero if it does not.
    expr = bytearray([
        0x12, 0x10, 0x08, 0x1C,  # dup CFA, constu 8, minus
        0x12, 0x06,              # dup, deref: slot, tagged
        0x12, 0x0E,              # dup, const8u MASK
    ])
    expr.extend(struct.pack("<Q", MASK))
    expr.extend([
        0x1A,                    # and: slot, tagged, raw
        0x15, 0x02, 0x34, 0x25, # pick slot, lit4, shr
        0x3F, 0x1A, 0x33, 0x24, # lit15, and, lit3, shl
        DW_OP_GNU_ENCODED_ADDR, DW_EH_PE_PCREL_SDATA4,
                                 # PC-relative addr cookies
    ])
    cookie_operand = len(expr)
    expr.extend(b"\0" * 4)
    expr.extend([
        0x22, 0x06,              # plus, deref: cookie
        0x14,                    # over: preserve raw, copy it above cookie
        0x15, 0x04, 0x27,        # pick slot, xor: raw ^ slot
        0x1E,                    # mul by cookie
        0x08, 0x38, 0x25,       # const1u 56, shr: expected tag
        0x15, 0x02, 0x08, 0x38, 0x25, # pick tagged, >> 56
        0x29, 0x1F, 0x1A,        # eq, neg, and raw
    ])
    return bytes(expr), cookie_operand


def cie_instruction_start(record: bytes) -> int:
    pos = 8
    if record[pos] != 1:
        raise ValueError("only DWARF CIE version 1 is supported")
    pos += 1
    end = record.index(0, pos)
    augmentation = record[pos:end]
    if not augmentation.startswith(b"z"):
        raise ValueError("only z-augmented CIEs are supported")
    pos = end + 1
    _, pos = read_leb(record, pos)  # code alignment
    _, pos = read_leb(record, pos)  # signed data alignment; end is enough
    _, pos = read_leb(record, pos)  # return-address column
    augmentation_size, pos = read_leb(record, pos)
    return pos + augmentation_size


def records(data: bytes) -> list[tuple[int, bytes, bool]]:
    output = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("truncated .eh_frame length")
        length = struct.unpack_from("<I", data, offset)[0]
        if length == 0:
            if offset + 4 != len(data):
                raise ValueError("unexpected .eh_frame terminator")
            output.append((offset, data[offset:], False))
            break
        if length == 0xFFFFFFFF or offset + length + 4 > len(data):
            raise ValueError("unsupported or truncated .eh_frame record")
        record = data[offset:offset + length + 4]
        output.append((offset, record, struct.unpack_from("<I", record, 4)[0] == 0))
        offset += len(record)
    return output


def check_coverage(elf: ELFFile, entries: list[tuple[int, bytes, bool]]) -> None:
    symtab = elf.get_section_by_name(".symtab")
    eh_reloc = elf.get_section_by_name(".rela.eh_frame")
    if symtab is None or eh_reloc is None:
        raise ValueError("missing symbol table or .eh_frame relocations")
    symbols = list(symtab.iter_symbols())
    fentry_indices = {
        i for i, sym in enumerate(symbols)
        if sym.name == "__retguard_fentry"
    }
    if not fentry_indices:
        raise ValueError("no __retguard_fentry symbol")

    calls: set[tuple[int, int]] = set()
    for section in elf.iter_sections():
        if section["sh_type"] != "SHT_RELA" or not section.name.startswith(".rela.text"):
            continue
        target = section["sh_info"]
        code = elf.get_section(target).data()
        for reloc in section.iter_relocations():
            if reloc["r_info_sym"] in fentry_indices:
                offset = reloc["r_offset"]
                if not offset or code[offset - 1] != 0xE8:
                    raise ValueError("fentry relocation is not on a direct call")
                calls.add((target, offset - 1))

    matched: set[tuple[int, int]] = set()
    protected_starts: set[tuple[int, int]] = set()
    cold_fdes: list[tuple[int, int, int, int]] = []
    first_locations = {reloc["r_offset"]: reloc for reloc in eh_reloc.iter_relocations()}
    for offset, record, is_cie in entries:
        if is_cie or len(record) == 4:
            continue
        reloc = first_locations.get(offset + 8)
        if reloc is None or reloc["r_info_type"] != 2:
            raise ValueError("FDE has no PC-relative function relocation")
        symbol = symbols[reloc["r_info_sym"]]
        section_index = symbol["st_shndx"]
        if not isinstance(section_index, int):
            raise ValueError("FDE function section is unresolved")
        start = symbol["st_value"] + reloc["r_addend"]
        candidates = {(section_index, call) for call in range(start, start + 16)}
        hits = calls & candidates
        if len(hits) == 1:
            matched.update(hits)
            protected_starts.add((section_index, start))
        elif not hits:
            cold_fdes.append((offset, section_index, start,
                              struct.unpack_from("<I", record, 12)[0]))
        else:
            raise ValueError(f"FDE at {offset:#x} has multiple fentry calls")

    # GCC can split a protected function into hot and .cold fragments.  The
    # cold FDE starts after the entry hook, so it has no fentry call of its
    # own.  Accept it only with an exact-sized .cold function symbol whose
    # unsuffixed function owns a directly verified FDE above.
    functions = [sym for sym in symbols
                 if sym["st_info"]["type"] == "STT_FUNC"]
    for offset, section_index, start, size in cold_fdes:
        fragments = [sym for sym in functions
                     if sym["st_shndx"] == section_index
                     and sym["st_value"] == start
                     and sym["st_size"] == size
                     and sym.name.endswith(".cold")]
        if len(fragments) != 1 or size == 0:
            raise ValueError(f"FDE at {offset:#x} lacks one matching fentry call")
        parent_name = fragments[0].name[:-5]
        parents = [sym for sym in functions if sym.name == parent_name
                   and isinstance(sym["st_shndx"], int)
                   and (sym["st_shndx"], sym["st_value"]) in protected_starts]
        if len(parents) != 1:
            raise ValueError(f"cold FDE at {offset:#x} lacks a protected parent")
    if calls != matched:
        raise ValueError("fentry call lacks an FDE")


def fde_instruction_start(record: bytes) -> int:
    # This prototype accepts the 4-byte PC-relative initial location and
    # range emitted by GCC for ELF64 x86-64.
    size, pos = read_leb(record, 16)
    return pos + size


def rewrite_eh_frame(data: bytes, cie_id: int) -> tuple[bytes, dict[int, int], list[int], dict[int, tuple[int, int]]]:
    parsed = records(data)
    expr, cookie_operand = return_address_expression()
    rule = bytes([0x16, 0x10]) + uleb(len(expr)) + expr
    rewritten = bytearray()
    offset_map: dict[int, int] = {}
    cie_positions: dict[int, int] = {}
    cookie_relocations = []
    insertions: dict[int, tuple[int, int]] = {}

    for old_offset, record, is_cie in parsed:
        new_offset = len(rewritten)
        if len(record) == 4:
            rewritten.extend(record)
            continue
        offset_map[old_offset] = new_offset
        if is_cie:
            start = cie_instruction_start(record)
            if record[start:start + 5] != bytes([0x0C, 0x07, 0x08, 0x90, 0x01]):
                raise ValueError("unexpected CIE frame or return-address rule")
            if any(record[start + 5:]):
                raise ValueError("unsupported additional CIE instructions")
            cie_positions[old_offset] = new_offset
            # GNU ld folds byte-identical CIEs and does not adjust arbitrary
            # PC-relative operands inside an FDE when it moves that FDE.  A
            # balanced state change gives each patched object a distinct CIE
            # while leaving its final unwind state unchanged.
            marker = bytes([0x0A, 0x0E]) + uleb(cie_id) + bytes([0x0B])
            updated = bytearray(record[:start + 5] + marker)
            insertions[old_offset] = (start + 5, len(marker))
        else:
            old_cie = old_offset + 4 - struct.unpack_from("<I", record, 4)[0]
            if old_cie not in cie_positions:
                raise ValueError("FDE references unknown CIE")
            start = fde_instruction_start(record)
            cookie_relocations.append(new_offset + start + 2 + len(uleb(len(expr))) + cookie_operand)
            updated = bytearray(record[:start] + rule + record[start:])
            insertions[old_offset] = (start, len(rule))
            struct.pack_into("<I", updated, 4, new_offset + 4 - cie_positions[old_cie])
        updated.extend(b"\0" * (-len(updated) % 4))
        struct.pack_into("<I", updated, 0, len(updated) - 4)
        rewritten.extend(updated)
    return bytes(rewritten), offset_map, cookie_relocations, insertions


def patch(input_file: Path, output_file: Path) -> None:
    original = input_file.read_bytes()
    with io.BytesIO(original) as stream:
        elf = ELFFile(stream)
        if elf["e_type"] != "ET_REL" or elf["e_machine"] != "EM_X86_64" or not elf.little_endian:
            raise ValueError("expected a little-endian x86-64 relocatable object")
        eh = elf.get_section_by_name(".eh_frame")
        rela = elf.get_section_by_name(".rela.eh_frame")
        symtab = elf.get_section_by_name(".symtab")
        if any(section is None for section in (eh, rela, symtab)):
            raise ValueError("required ELF section is missing")
        strtab = elf.get_section(symtab["sh_link"])
        if strtab is None:
            raise ValueError("symbol string table is missing")
        parsed = records(eh.data())
        check_coverage(elf, parsed)
        cie_id = int.from_bytes(hashlib.sha256(original).digest()[:8], "little") or 1
        new_eh, mapping, cookie_offsets, insertions = rewrite_eh_frame(
            eh.data(), cie_id
        )

        old_relocations = []
        for reloc in rela.iter_relocations():
            old_offset = reloc["r_offset"]
            record = next((entry for entry in parsed if entry[0] <= old_offset < entry[0] + len(entry[1])), None)
            if record is None:
                raise ValueError("relocation is outside an .eh_frame record")
            new_offset = mapping[record[0]] + old_offset - record[0]
            if record[0] in insertions and old_offset - record[0] >= insertions[record[0]][0]:
                new_offset += insertions[record[0]][1]
            old_relocations.append((new_offset, reloc["r_info"], reloc["r_addend"]))

        # GCC always emits __x86_return_thunk. Redirect this protected
        # object's undefined symbol to the automatic entry in the shared
        # archive; manual objects retain the original symbol and entry.
        return_symbols = [i for i, symbol in enumerate(symtab.iter_symbols())
                          if symbol.name == "__x86_return_thunk"
                          and symbol["st_shndx"] == "SHN_UNDEF"]
        if len(return_symbols) > 1:
            raise ValueError("multiple undefined __x86_return_thunk symbols")
        cookie_symbol = symtab.num_symbols()
        auto_name_offset = len(strtab.data()) + len(COOKIE_NAME)
        new_strings = strtab.data() + COOKIE_NAME + AUTO_THUNK_NAME
        new_symbol = struct.pack("<IBBHQQ", len(strtab.data()), 0x11, 0, 0, 0, 0)
        new_symbols = bytearray(symtab.data())
        if return_symbols:
            struct.pack_into("<I", new_symbols, return_symbols[0] * 24,
                             auto_name_offset)
        new_symbols.extend(new_symbol)
        new_relocations = old_relocations + [
            (offset, (cookie_symbol << 32) | R_X86_64_PC32, 0)
            for offset in cookie_offsets
        ]
        new_relocations.sort()
        new_rela = b"".join(struct.pack("<QQq", *item) for item in new_relocations)

        section_count = elf.num_sections()
        shoff = elf["e_shoff"]
        headers = [bytearray(original[shoff + 64 * i:shoff + 64 * (i + 1)])
                   for i in range(section_count)]
        output = bytearray(original)
        for section, content in ((eh, new_eh), (rela, new_rela),
                                 (symtab, new_symbols), (strtab, new_strings)):
            alignment = section["sh_addralign"] or 1
            output.extend(b"\0" * (-len(output) % alignment))
            section_index = elf.get_section_index(section.name)
            struct.pack_into("<Q", headers[section_index], 24, len(output))
            struct.pack_into("<Q", headers[section_index], 32, len(content))
            output.extend(content)
        output.extend(b"\0" * (-len(output) % 8))
        struct.pack_into("<Q", output, 40, len(output))
        for header in headers:
            output.extend(header)
    output_file.write_bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        patch(args.input, args.output)
    except (ValueError, IndexError, struct.error) as error:
        parser.exit(1, f"retguard_eh_object: {error}\n")


if __name__ == "__main__":
    main()
