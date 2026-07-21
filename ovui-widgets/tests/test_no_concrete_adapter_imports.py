# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Production ovui-widgets modules must not import concrete scene backends."""

from __future__ import annotations

import ast
import pathlib


MONOREPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OVUI_WIDGETS_ROOT = MONOREPO_ROOT / "ovui-widgets" / "ovui_widgets"

FORBIDDEN_IMPORT_PREFIXES = (
    "ovui_data_adapters.openusd",
    "ovui_data_adapters.ovstage",
    "pxr",
    "ovstage",
    "ovpopulation",
    "ovhierarchy",
    "ovphysx",
    "ovrtx",
)


def _production_python_files() -> list[pathlib.Path]:
    return sorted(
        path
        for path in OVUI_WIDGETS_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _forbidden_import_name(name: str) -> str | None:
    for prefix in FORBIDDEN_IMPORT_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            return prefix
    return None


def _static_import_targets(node: ast.AST) -> list[str]:
    targets: list[str] = []
    if isinstance(node, ast.Import):
        targets.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module:
            targets.append(module)
        if module == "ovui_data_adapters":
            targets.extend(f"{module}.{alias.name}" for alias in node.names)
    return targets


def _is_dynamic_import_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "__import__":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        return isinstance(func.value, ast.Name) and func.value.id == "importlib"
    return False


def _dynamic_import_target(node: ast.Call) -> str | None:
    if not _is_dynamic_import_call(node) or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def test_no_production_ovui_widgets_module_imports_concrete_scene_backends() -> None:
    assert OVUI_WIDGETS_ROOT.is_dir(), f"missing ovui-widgets package root: {OVUI_WIDGETS_ROOT}"
    files = _production_python_files()
    assert files, f"no production Python files under {OVUI_WIDGETS_ROOT}"

    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(MONOREPO_ROOT)
        for node in ast.walk(tree):
            for target in _static_import_targets(node):
                forbidden = _forbidden_import_name(target)
                if forbidden is not None:
                    violations.append(
                        f"{rel}:{node.lineno}: imports {target!r} "
                        f"(forbidden prefix {forbidden!r})"
                    )
            if isinstance(node, ast.Call):
                target = _dynamic_import_target(node)
                if target is None:
                    continue
                forbidden = _forbidden_import_name(target)
                if forbidden is not None:
                    violations.append(
                        f"{rel}:{node.lineno}: dynamically imports {target!r} "
                        f"(forbidden prefix {forbidden!r})"
                    )

    assert not violations, "concrete backend imports found:\n" + "\n".join(violations)
