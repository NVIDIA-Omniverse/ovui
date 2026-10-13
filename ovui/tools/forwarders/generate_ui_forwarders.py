# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Preserve named Windows omni.ui.dll imports after moving its UI core to ovui.dll.

The export names come from the completed core DLL, including exact MSVC decoration.
Only symbols whose qualified name belongs to omni::ui are forwarded. Carbonite
module entry points and globals remain owned by the adapter DLL.
"""

import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import sys


@dataclass(frozen=True)
class Export:
    name: str
    ordinal: int
    data: bool
    forwarder: str | None = None


def read_exports(path: Path) -> tuple[str, list[Export]]:
    """Read named AMD64 PE exports without executing the DLL or requiring dumpbin."""
    image = path.read_bytes()

    def unpack(fmt, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(image):
            raise ValueError("Truncated PE structure")
        return struct.unpack_from(fmt, image, offset)

    if image[:2] != b"MZ":
        raise ValueError("Expected a PE DLL")
    pe, = unpack("<I", 0x3C)
    if image[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Invalid PE signature")
    machine, section_count, _, _, _, optional_size, characteristics = unpack("<HHIIIHH", pe + 4)
    if machine != 0x8664 or not characteristics & 0x2000:
        raise ValueError("Expected an AMD64 DLL")
    optional = pe + 24
    magic, = unpack("<H", optional)
    if magic != 0x20B or optional_size < 120:
        raise ValueError("Expected a PE32+ optional header")
    directory_count, = unpack("<I", optional + 108)
    if not directory_count:
        raise ValueError("DLL has no export directory")
    export_rva, export_size = unpack("<II", optional + 112)
    if not export_rva or export_size < 40:
        raise ValueError("DLL has no export directory")
    sections = []
    for index in range(section_count):
        section = optional + optional_size + 40 * index
        _, virtual_size, rva, raw_size, raw_offset, _, _, _, _, flags = unpack("<8sIIIIIIHHI", section)
        sections.append((rva, max(virtual_size, raw_size), raw_offset, raw_size, flags))

    def location(rva, size=1):
        for start, span, offset, raw_size, flags in sections:
            if start <= rva < start + span:
                delta = rva - start
                if size < 0 or delta + size > raw_size or offset + delta + size > len(image):
                    raise ValueError("PE RVA extends beyond file-backed section")
                return offset + delta, flags, raw_size - delta
        raise ValueError("Unmapped PE RVA")

    def string(rva):
        offset, _, available = location(rva)
        end = image.find(b"\0", offset, offset + available)
        if end < 0:
            raise ValueError("Unterminated PE export string")
        return image[offset:end].decode("ascii")

    directory, _, _ = location(export_rva, 40)
    _, _, _, _, module_rva, base, function_count, name_count, functions_rva, names_rva, ordinals_rva = unpack("<IIHHIIIIIII", directory)
    functions, _, _ = location(functions_rva, function_count * 4)
    names, _, _ = location(names_rva, name_count * 4)
    ordinals, _, _ = location(ordinals_rva, name_count * 2)
    result = []
    seen = set()
    for index in range(name_count):
        name_rva, = unpack("<I", names + index * 4)
        name = string(name_rva)
        ordinal_index, = unpack("<H", ordinals + index * 2)
        if ordinal_index >= function_count or name in seen:
            raise ValueError("Invalid or duplicate PE named export")
        seen.add(name)
        target_rva, = unpack("<I", functions + ordinal_index * 4)
        if not target_rva:
            raise ValueError("Named export has no address")
        if export_rva <= target_rva < export_rva + export_size:
            result.append(Export(name, base + ordinal_index, False, string(target_rva)))
        else:
            # Exported zero-initialized data may live in the virtual-only tail
            # of a section. Classification needs section flags, not data bytes.
            flags = next((flags for start, span, _, _, flags in sections if start <= target_rva < start + span), None)
            if flags is None:
                raise ValueError("Unmapped PE RVA")
            result.append(Export(name, base + ordinal_index, not bool(flags & 0x20000000)))
    return string(module_rva), result


def windows_qualified_name():
    """Use Windows' name-only undecoration to distinguish scope from argument types."""
    if sys.platform != "win32":
        raise RuntimeError("UI forwarding generation requires Windows DbgHelp name undecoration")
    undecorate = ctypes.WinDLL("dbghelp.dll", winmode=0x800).UnDecorateSymbolName
    undecorate.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32]
    undecorate.restype = ctypes.c_uint32

    def qualified_name(name):
        # UNDNAME_NAME_ONLY returns the qualified symbol name without parameter
        # and return types; a foreign function taking a UI object must stay local.
        buffer = ctypes.create_string_buffer(max(4096, len(name) * 16))
        if not undecorate(name.encode("ascii"), buffer, len(buffer), 0x1000):
            raise ValueError(f"Cannot undecorate export: {name}")
        return buffer.value.decode("ascii")

    return qualified_name


def make_definition(exports, qualified_name):
    forwarded, local = [], []
    lines = ['LIBRARY "omni.ui.dll"', "EXPORTS"]
    for export in sorted(exports, key=lambda item: item.name):
        name = export.name
        if not name.startswith("?") or not qualified_name(name).startswith("omni::ui::"):
            local.append(name)
            continue
        if export.forwarder:
            raise ValueError(f"Core UI export already forwards to another DLL: {name}")
        if any(character.isspace() or character in '\"\0=;' for character in name):
            raise ValueError("Export name cannot be represented in a module definition")
        # A data export needs DATA in the adapter import library as well. The PE
        # loader itself follows the same exact-name forwarder for code and data.
        # MSVC preserves quotes around decorated names in forwarder definitions
        # as literal export/import-library characters. Emit validated tokens so
        # rebuilt consumers and existing DLL imports resolve the exact name.
        lines.append(f'    {name}=ovui.{name}' + (" DATA" if export.data else ""))
        forwarded.append(name)
    if not forwarded:
        raise ValueError("Core DLL contains no named omni::ui exports")
    return "\n".join(lines) + "\n", forwarded, local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Completed matching-configuration ovui.dll")
    parser.add_argument("--output", required=True, type=Path, help="Generated adapter module definition")
    parser.add_argument("--manifest", required=True, type=Path, help="Exact export and producer hash record")
    args = parser.parse_args()
    module, exports = read_exports(args.input)
    if module.lower() != "ovui.dll":
        raise ValueError(f"Expected ovui.dll export identity, found {module}")
    definition, forwarded, local = make_definition(exports, windows_qualified_name())
    manifest = {
        "source_module": module,
        "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "adapter_module": "omni.ui.dll",
        "forwarded": forwarded,
        "not_forwarded": local,
        "definition_sha256": hashlib.sha256(definition.encode("ascii")).hexdigest(),
    }
    for path, content in ((args.output, definition), (args.manifest, json.dumps(manifest, indent=2) + "\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="ascii")
        temporary.replace(path)


if __name__ == "__main__":
    main()
