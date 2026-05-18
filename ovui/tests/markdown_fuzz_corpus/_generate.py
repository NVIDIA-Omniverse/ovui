#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Regenerates the large hand-unfriendly files in this corpus directory.

Invoke manually when the shape of the generated fixtures needs to change:

    python tests/markdown_fuzz_corpus/_generate.py

The files this script writes are also committed so tests work without a
generation step.
"""
from __future__ import annotations

from pathlib import Path


HERE = Path(__file__).resolve().parent


def write_deeply_nested_lists(path: Path, depth: int = 30) -> None:
    lines = ["# Deeply nested unordered list", ""]
    for level in range(depth):
        indent = "  " * level
        lines.append(f"{indent}- level {level + 1}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_giant_table(path: Path, rows: int = 50, cols: int = 30) -> None:
    header = "| " + " | ".join(f"C{c + 1}" for c in range(cols)) + " |"
    sep = "|" + "|".join("---" for _ in range(cols)) + "|"
    body = []
    for r in range(rows):
        cells = [f"r{r + 1}c{c + 1}" for c in range(cols)]
        body.append("| " + " | ".join(cells) + " |")
    content = "# Giant pipe table\n\n" + header + "\n" + sep + "\n" + "\n".join(body) + "\n"
    path.write_text(content, encoding="utf-8")


def main() -> None:
    write_deeply_nested_lists(HERE / "deeply_nested_lists.md")
    write_giant_table(HERE / "giant_table.md")


if __name__ == "__main__":
    main()
