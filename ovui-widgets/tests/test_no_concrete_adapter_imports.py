# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Normal release widget modules must not import concrete scene backends."""

from __future__ import annotations

import ast
import fnmatch
import pathlib
import shutil

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 test support
    import tomli as tomllib

MONOREPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OVUI_WIDGETS_PROJECT_ROOT = MONOREPO_ROOT / "ovui-widgets"
OVUI_WIDGETS_DIST_ROOT = OVUI_WIDGETS_PROJECT_ROOT / "dist"

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


def _distribution_package_includes(
    project_root: pathlib.Path = OVUI_WIDGETS_PROJECT_ROOT,
) -> list[tuple[pathlib.Path, str]]:
    includes: list[tuple[pathlib.Path, str]] = []
    for pyproject_path in sorted((project_root / "dist").glob("*/pyproject.toml")):
        config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        if config.get("tool", {}).get("ovui", {}).get("internal", False):
            continue
        package_find = config["tool"]["setuptools"]["packages"]["find"]
        for source_root in package_find.get("where", ["."]):
            resolved_root = (pyproject_path.parent / source_root).resolve()
            includes.extend(
                (resolved_root, pattern)
                for pattern in package_find.get("include", ["*"])
            )
    return includes


def _module_name(path: pathlib.Path, source_root: pathlib.Path) -> str:
    parts = path.relative_to(source_root).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _release_python_files(
    project_root: pathlib.Path = OVUI_WIDGETS_PROJECT_ROOT,
) -> list[pathlib.Path]:
    includes_by_root: dict[pathlib.Path, list[str]] = {}
    for source_root, pattern in _distribution_package_includes(project_root):
        includes_by_root.setdefault(source_root, []).append(pattern)

    files: set[pathlib.Path] = set()
    for source_root, patterns in includes_by_root.items():
        for path in source_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            module_name = _module_name(path, source_root)
            if any(fnmatch.fnmatchcase(module_name, pattern) for pattern in patterns):
                files.add(path)
    return sorted(files)


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


def _concrete_backend_import_violations(
    files: list[pathlib.Path],
    *,
    report_root: pathlib.Path,
) -> list[str]:
    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(report_root)
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
    return violations


def test_no_release_widget_module_imports_concrete_scene_backends(tmp_path) -> None:
    files = _release_python_files()
    assert files, f"no release Python files under {OVUI_WIDGETS_PROJECT_ROOT}"

    violations = _concrete_backend_import_violations(
        files,
        report_root=MONOREPO_ROOT,
    )
    assert not violations, "concrete backend imports found:\n" + "\n".join(violations)

    probe_root = tmp_path / "ovui-widgets"
    shutil.copytree(OVUI_WIDGETS_DIST_ROOT, probe_root / "dist")
    expected_probe_paths: set[pathlib.Path] = set()
    for _, pattern in _distribution_package_includes():
        package_prefix = pattern.partition("*")[0].rstrip(".")
        if not package_prefix:
            continue
        probe_path = probe_root.joinpath(*package_prefix.split("."), "__init__.py")
        probe_path.parent.mkdir(parents=True, exist_ok=True)
        probe_path.write_text(
            "from ovui_data_adapters.ovstage import provider as _probe\n",
            encoding="utf-8",
        )
        expected_probe_paths.add(probe_path.relative_to(probe_root))

    probe_files = _release_python_files(probe_root)
    assert {path.relative_to(probe_root) for path in probe_files} == expected_probe_paths
    probe_violations = _concrete_backend_import_violations(
        probe_files,
        report_root=probe_root,
    )
    assert {
        pathlib.Path(violation.partition(":")[0])
        for violation in probe_violations
    } == expected_probe_paths
