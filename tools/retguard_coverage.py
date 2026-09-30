"""Read-only validation of automatic object coverage."""

from __future__ import annotations

import struct

from elftools.elf.elffile import ELFFile


def safe_entry_prefix(prefix: bytes) -> bool:
    """Recognize ENDBR64 and canonical compiler alignment/patch-entry NOPs."""
    while prefix:
        if prefix.startswith(b"\xf3\x0f\x1e\xfa"):
            prefix = prefix[4:]
            continue
        # GAS/compiler NOPs may use operand-size and CS prefixes. Their
        # effective-address displacement need not be zero (Clang uses 8).
        offset = 0
        while offset < len(prefix) and prefix[offset] in (0x66, 0x2E):
            offset += 1
        if prefix[offset:offset + 1] == b"\x90":
            size = offset + 1
        elif prefix[offset:offset + 2] == b"\x0f\x1f" and offset + 3 <= len(prefix):
            modrm = prefix[offset + 2]
            if modrm & 0x38:  # NOP's /0 opcode extension
                return False
            mode, base = modrm >> 6, modrm & 7
            size = offset + 3
            if mode != 3 and base == 4:
                if size >= len(prefix):
                    return False
                base = prefix[size] & 7
                size += 1  # SIB
            size += 1 if mode == 1 else 4 if mode == 2 or (mode == 0 and base == 5) else 0
        else:
            return False
        if size > len(prefix):
            return False
        prefix = prefix[size:]
    return True


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
        if sym.name in ("__retguard_fentry", "__fentry__")
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
            call = next(iter(hits))[1]
            prefix = elf.get_section(section_index).data()[start:call]
            # The hook encodes the word immediately below its own return
            # address. GCC nested functions can push their static-chain
            # register before fentry, changing that slot. Fail closed rather
            # than encoding a saved register and later returning to raw data.
            if not safe_entry_prefix(prefix):
                raise ValueError(
                    f"FDE at {offset:#x} has unsupported instructions before "
                    "fentry; automatic entry requires an unchanged return slot "
                    "(check nested functions and patchable function entries)"
                )
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
        helpers = [sym for sym in functions
                   if sym["st_shndx"] == section_index
                   and sym["st_value"] == start
                   and sym["st_size"] == size
                   and sym.name == "__clang_call_terminate"]
        if len(helpers) == 1 and size > 0:
            # Clang emits this noreturn EH helper after the fentry pass.
            # Verify its last instruction calls std::terminate.
            section = elf.get_section(section_index)
            body = section.data()[start:start + size]
            if body[-5] != 0xE8:
                raise ValueError("Clang terminate helper has a return path")
            terminal_call = start + size - 4
            terminate_relocations = [
                reloc for reloc_section in elf.iter_sections()
                if reloc_section["sh_type"] == "SHT_RELA"
                and reloc_section["sh_info"] == section_index
                for reloc in reloc_section.iter_relocations()
                if reloc["r_offset"] == terminal_call
                and symbols[reloc["r_info_sym"]].name == "_ZSt9terminatev"
            ]
            if len(terminate_relocations) != 1:
                raise ValueError("Clang terminate helper does not call std::terminate")
            continue
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
