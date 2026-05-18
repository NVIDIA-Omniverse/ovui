# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: ``ovui_data_adapters.openusd`` must NOT import any
``ovwidgets.*`` module.

Step 26 (Rev 4 §6.4 + §10.5): the data-adapters package is a leaf in
the dependency graph — concrete OpenUSD adapters live there and may
import ``ovui_data_adapters.common``, ``pxr``, ``numpy``, and
``ovrtx``, but they must not depend on any widget-side module. A
back-edge (e.g. an openusd file accidentally importing
``ovwidgets.common.error_reporter``) would re-introduce the cyclic
boundary the refactor was built to dissolve.

This test enforces the invariant statically — it does NOT execute the
openusd modules, just parses them. Two scans:

  1. Static ``Import`` / ``ImportFrom`` AST scan (Rev 4 §6.4).
  2. Dynamic-import AST scan (Rev 3 — replaces Rev 2's broad string
     substring scan): only flags string literals passed as the first
     positional argument to ``__import__()`` or
     ``importlib.import_module()``. Documentation prose mentioning
     widget-side symbols (``ovwidgets.viewport.camera_controller`` in
     a docstring) does NOT trip this scan.

The Rev 2 broad substring scan is rejected because the moved files
contain legitimate documentation strings that describe widget-side
symbols the openusd file does NOT import. The Rev 3 AST-targeted scan
flags real attack vectors only. The allow-list stays empty.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MONOREPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
# Source layout: after the monorepo merge, the dash-form repository
# folder ``ovui-data-adapters/`` hosts a unified Python import-package
# root. The OpenUSD-flavored concrete adapters live under
# ``ovui_data_adapters/openusd/``. Imports are unaffected by the
# dash-form parent — Python only ever sees ``ovui_data_adapters.openusd``.
OPENUSD_ROOT = (
    MONOREPO_ROOT
    / "ovui-data-adapters"
    / "ovui_data_adapters"
    / "openusd"
)

FORBIDDEN_PREFIXES = (
    "ovwidgets.viewport",
    "ovwidgets.stage",
    "ovwidgets.layers",
    "ovwidgets.property",
    "ovwidgets.content",
    "ovwidgets.app",
    "ovwidgets.common",
)

# Allow-list intentionally empty (Rev 3 §10.5 / §6.4): no openusd file is
# permitted to import a widget module, even temporarily. Future shims, if
# ever needed, must be argued for in a follow-up plan revision and added
# here explicitly.
ALLOWED_FROM_VIEWPORT_TEMPORARY_SHIMS: tuple[str, ...] = ()


def _openusd_python_files() -> list[pathlib.Path]:
    return sorted(OPENUSD_ROOT.rglob("*.py"))


def _is_dynamic_import_call(node: ast.Call) -> bool:
    """True if this Call invokes ``__import__()`` or ``importlib.import_module()``."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "__import__":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        if isinstance(func.value, ast.Name) and func.value.id == "importlib":
            return True
    return False


def test_openusd_root_exists():
    """Sanity: the openusd package directory must exist with at least
    one Python file. Catches a tree-layout regression that would
    silently skip every other assertion below.
    """
    assert OPENUSD_ROOT.is_dir(), f"missing openusd root: {OPENUSD_ROOT}"
    files = _openusd_python_files()
    assert files, f"no .py files under {OPENUSD_ROOT}"


@pytest.mark.parametrize("py", _openusd_python_files(), ids=lambda p: p.name)
def test_openusd_static_imports_do_not_target_widgets(py: pathlib.Path):
    """Scan every static ``Import`` / ``ImportFrom`` for forbidden widget targets."""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    offences: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(mod == p or mod.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                if mod in ALLOWED_FROM_VIEWPORT_TEMPORARY_SHIMS:
                    continue
                offences.append(f"line {node.lineno}: from {mod} import …")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name or ""
                if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                    offences.append(f"line {node.lineno}: import {name}")
    assert not offences, (
        f"{py.relative_to(MONOREPO_ROOT)}: forbidden widget imports:\n  "
        + "\n  ".join(offences)
    )


@pytest.mark.parametrize("py", _openusd_python_files(), ids=lambda p: p.name)
def test_openusd_dynamic_imports_do_not_target_widgets(py: pathlib.Path):
    """Reject ``__import__("ovwidgets.…")`` / ``importlib.import_module("ovwidgets.…")``.

    Rev 3 narrowed scan: only inspects the first positional argument
    of an import-call when that argument is a string literal. Docstring
    prose and runtime-computed module paths are deliberately out of
    scope.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"))
    offences: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_dynamic_import_call(node)):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        target = first.value
        if any(target == p or target.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
            offences.append(f"line {node.lineno}: dynamic import target {target!r}")
    assert not offences, (
        f"{py.relative_to(MONOREPO_ROOT)}: dynamic widget imports:\n  "
        + "\n  ".join(offences)
    )


def test_dynamic_helper_correctly_identifies_import_calls():
    """Self-test for ``_is_dynamic_import_call`` so a future regression
    in the helper itself doesn't silently disable the dynamic-import
    scan above.
    """
    src = (
        "import importlib\n"
        "__import__('foo')\n"           # match
        "importlib.import_module('foo')\n"  # match
        "other.import_module('foo')\n"  # NOT match — wrong namespace
        "importlib.import_module\n"     # NOT match — not a Call
        "print('foo')\n"                # NOT match — wrong call
    )
    tree = ast.parse(src)
    matches = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _is_dynamic_import_call(n)
    ]
    assert len(matches) == 2, f"expected 2 matches, got {len(matches)}"
