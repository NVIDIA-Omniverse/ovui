# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Structural and runtime isolation contract for the OVStage adapter."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Iterable

from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    OvstageProviderSession,
    create_layer_stack_adapter,
    create_property_adapter,
    create_selection_adapter,
    create_stage_adapter,
    create_transform_adapter,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.runtime_import import resolve_ovstage_runtime_module
from ovui_data_adapters.ovstage.selection_adapter import OvstageSelectionAdapter
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MODULE_ROOTS = ("pxr", "ovui_data_adapters.openusd")
PROHIBITED_LOCAL_MODULES = (
    "ovui_data_adapters.ovstage._usd_sync",
    "ovui_data_adapters.ovstage.backing_usd",
)
PROHIBITED_LOCAL_LEAVES = frozenset({"_usd_sync", "backing_usd"})
PROHIBITED_FILES = ("_usd_sync.py", "backing_usd.py")
PROHIBITED_OBJECT_FLOW_NAMES = frozenset(
    {
        "_backing_usd_transform_adapter",
        "_make_usd_adapter",
        "_usd",
        "_usd_adapter",
        "_usd_delegate",
        "_usd_layer",
        "_usd_prim",
        "_usd_snapshot",
        "_usd_stage",
        "backing_usd_source_layer",
        "backing_usd_stage",
        "inspector_bridge_identity",
        "inspector_usd_edit_target_identifier",
        "inspector_usd_layer_identifiers",
        "inspector_usd_prim",
        "inspector_usd_stage",
        "synchronize_backing_usd_changes",
        "validate_backing_usd_edit_target",
    }
)
PROHIBITED_ANNOTATION_ROOTS = frozenset(
    {
        "Ar",
        "Gf",
        "Kind",
        "Pcp",
        "Plug",
        "Sdf",
        "Tf",
        "Usd",
        "UsdGeom",
        "UsdLux",
        "UsdPhysics",
        "UsdRender",
        "UsdShade",
        "Vt",
    }
)
PROHIBITED_ANNOTATION_PREFIXES = (
    "Gf",
    "Sdf",
    "Tf",
    "Usd",
    "Vt",
)
_DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})


def _is_forbidden_module(module_name: str) -> bool:
    return any(
        module_name == root or module_name.startswith(f"{root}.")
        for root in FORBIDDEN_MODULE_ROOTS
    )


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _annotation_tokens(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return set(node.value.replace(".", " ").split())
    return {
        name.id
        for name in ast.walk(node)
        if isinstance(name, ast.Name)
    }


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def _is_dynamic_loader_expression(node: ast.AST, loader_names: set[str]) -> bool:
    dotted = _dotted_name(node)
    if dotted.rsplit(".", 1)[-1] in loader_names:
        return True
    if not isinstance(node, ast.Call) or _dotted_name(node.func) != "getattr":
        return False
    if len(node.args) < 2 or _dotted_name(node.args[0]) != "importlib":
        return False
    return _constant_string(node.args[1]) == "import_module"


def audit_source(path: Path, *, runtime_source: bool | None = None) -> list[str]:
    """Return executable isolation violations found by parsing one source file."""

    if runtime_source is None:
        runtime_source = "tests" not in path.parts
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    dynamic_loader_names = set(_DYNAMIC_IMPORT_CALLS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    dynamic_loader_names.add(alias.asname or alias.name)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _is_dynamic_loader_expression(
                value,
                dynamic_loader_names,
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in dynamic_loader_names:
                    dynamic_loader_names.add(target.id)
                    changed = True

    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    violations.append(f"static-import:{line}:{alias.name}")
                if alias.name in PROHIBITED_LOCAL_MODULES:
                    violations.append(f"bridge-import:{line}:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if _is_forbidden_module(module_name):
                violations.append(f"static-import:{line}:{module_name}")
            if module_name in PROHIBITED_LOCAL_MODULES:
                violations.append(f"bridge-import:{line}:{module_name}")
            if any(alias.name in PROHIBITED_LOCAL_LEAVES for alias in node.names):
                violations.append(
                    f"bridge-import:{line}:{module_name or '<relative>'}"
                )
        elif isinstance(node, ast.Call):
            call_name = _dotted_name(node.func)
            terminal_name = call_name.rsplit(".", 1)[-1]
            is_dynamic_loader = (
                terminal_name in dynamic_loader_names
                or _is_dynamic_loader_expression(node.func, dynamic_loader_names)
            )
            if is_dynamic_loader and node.args:
                target = node.args[0]
                target_value = _constant_string(target)
                if target_value is not None and _is_forbidden_module(target_value):
                    violations.append(f"dynamic-import:{line}:{target_value}")
                elif target_value is None and runtime_source:
                    violations.append(
                        f"dynamic-import-nonliteral:{line}:{call_name}"
                    )
            if call_name in {
                "sys.path.append",
                "sys.path.extend",
                "sys.path.insert",
            } and path.name != "runtime_import.py":
                violations.append(f"path-injection:{line}:{call_name}")
        elif isinstance(node, ast.Subscript):
            if _dotted_name(node.value) == "sys.modules":
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if _is_forbidden_module(key.value):
                        violations.append(
                            f"module-cache-lookup:{line}:{key.value}"
                        )
        elif isinstance(node, ast.Constant) and runtime_source:
            if isinstance(node.value, str) and _is_forbidden_module(node.value):
                violations.append(f"module-root-string:{line}:{node.value}")

        annotation = None
        if isinstance(node, ast.arg):
            annotation = node.annotation
        elif isinstance(node, (ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef)):
            annotation = node.annotation if isinstance(node, ast.AnnAssign) else node.returns
        if annotation is not None:
            tokens = _annotation_tokens(annotation)
            forbidden = {
                token
                for token in tokens
                if token in PROHIBITED_ANNOTATION_ROOTS
                or token.startswith(PROHIBITED_ANNOTATION_PREFIXES)
            }
            if forbidden:
                violations.append(
                    f"annotation:{line}:{','.join(sorted(forbidden))}"
                )

        if runtime_source and isinstance(node, (ast.Name, ast.Attribute)):
            identifier = node.id if isinstance(node, ast.Name) else node.attr
            if identifier in PROHIBITED_OBJECT_FLOW_NAMES:
                violations.append(f"object-flow:{line}:{identifier}")

    return sorted(set(violations))


def audit_tree(root: Path = PACKAGE_ROOT) -> dict[str, list[str]]:
    """Audit all scoped Python sources without matching prose-only mentions."""

    violations: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        rows = audit_source(path, runtime_source="tests" not in path.parts)
        if rows:
            violations[str(path.relative_to(root))] = rows
    for filename in PROHIBITED_FILES:
        if (root / filename).exists():
            violations.setdefault(filename, []).append("prohibited-bridge-file")
    return violations


def _all_reachable_values(values: Iterable[object]) -> Iterable[object]:
    for value in values:
        yield value
        if hasattr(value, "__dict__"):
            yield from vars(value).values()


def _forbidden_runtime_value(value: object) -> bool:
    value_type = type(value)
    module_name = str(getattr(value_type, "__module__", ""))
    return _is_forbidden_module(module_name)


def test_structural_isolation_gate() -> None:
    assert not (PACKAGE_ROOT / PROHIBITED_FILES[0]).exists()
    assert not (PACKAGE_ROOT / PROHIBITED_FILES[1]).exists()
    assert audit_tree() == {}

    runtime_import_tree = ast.parse(
        (PACKAGE_ROOT / "runtime_import.py").read_text(encoding="utf-8")
    )
    allowlist_values = None
    has_membership_gate = False
    for node in ast.walk(runtime_import_tree):
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id == "_RUNTIME_MODULE_NAMES"
                for target in node.targets
            ):
                allowlist_values = ast.literal_eval(node.value)
        if isinstance(node, ast.Compare) and any(
            isinstance(operator, ast.NotIn) for operator in node.ops
        ):
            if _dotted_name(node.left) == "module_name" and any(
                _dotted_name(comparator) == "_RUNTIME_MODULE_NAMES"
                for comparator in node.comparators
            ):
                has_membership_gate = True
    assert allowlist_values == ("ovstage", "ovhierarchy", "ovpopulation", "ovphysx")
    assert has_membership_gate


def test_structural_gate_detects_each_dependency_class(tmp_path: Path) -> None:
    sample = tmp_path / "legacy.py"
    sample.write_text(
        textwrap.dedent(
            """
            import pxr
            from ovui_data_adapters.openusd import UsdStageAdapter
            from ovui_data_adapters.ovstage.backing_usd import resolve_backing_usd
            import importlib
            loader = importlib.import_module
            deferred = loader("p" + "xr.Usd")
            cached = sys.modules["ovui_data_adapters.openusd"]
            sys.path.insert(0, dependency_root)
            backing_usd_stage: Usd.Stage | None = None
            """
        ),
        encoding="utf-8",
    )

    violations = audit_source(sample, runtime_source=True)
    categories = {row.split(":", 1)[0] for row in violations}
    assert {
        "annotation",
        "bridge-import",
        "dynamic-import",
        "module-cache-lookup",
        "module-root-string",
        "object-flow",
        "path-injection",
        "static-import",
    } <= categories


def test_runtime_import_allowlist_rejects_forbidden_roots_without_importing() -> None:
    attempts: list[str] = []

    def importer(name: str):
        attempts.append(name)
        raise AssertionError(f"unexpected import attempt: {name}")

    for module_name in FORBIDDEN_MODULE_ROOTS:
        result = resolve_ovstage_runtime_module(
            module_name,
            import_module_fn=importer,
        )
        assert result.module is None
        assert isinstance(result.error, ImportError)
    assert attempts == []


def test_every_module_and_provider_selection_are_forbidden_import_free() -> None:
    script = textwrap.dedent(
        f"""
        import importlib
        import json
        from pathlib import Path
        import sys

        forbidden = {FORBIDDEN_MODULE_ROOTS!r}

        def is_forbidden(name):
            return any(name == root or name.startswith(root + ".") for root in forbidden)

        before = sorted(name for name in sys.modules if is_forbidden(name))
        assert before == [], before
        attempts = []

        class Blocker:
            def find_spec(self, fullname, path=None, target=None):
                if is_forbidden(fullname):
                    attempts.append(fullname)
                    raise ImportError("blocked forbidden adapter dependency: " + fullname)
                return None

        sys.meta_path.insert(0, Blocker())
        root = Path({str(PACKAGE_ROOT)!r})
        modules = []
        for source in sorted(root.glob("*.py")):
            if source.name == "__init__.py":
                name = "ovui_data_adapters.ovstage"
            else:
                name = "ovui_data_adapters.ovstage." + source.stem
            importlib.import_module(name)
            modules.append(name)

        from ovui_data_adapters.common import AdapterRegistry, LayerHandle
        from ovui_data_adapters.ovstage import register
        from ovui_data_adapters.ovstage.provider import OvstageProviderSession

        registry = AdapterRegistry()
        register(registry)
        selected = registry.select_adapter("ovstage")
        assert selected.name == "ovstage"
        factories = selected.factories
        session = factories.session()
        capabilities = session.get_capabilities().stage
        assert capabilities.create_prims.is_supported
        assert capabilities.delete_prims.is_supported
        assert capabilities.create_stage.is_unsupported
        assert capabilities.export_stage.is_unsupported
        stage = factories.stage(scene=None)
        properties = factories.properties(scene=None, paths=[])
        transforms = factories.transforms(scene=None)
        selection = factories.selection(scene=None, stage_adapter=stage)
        layers = factories.layers(scene=None)
        assert layers.get_layer_stack_identifiers() == []
        assert layers.find_layer("missing") is None
        assert layers.get_sublayer_identifiers(LayerHandle("missing")) == []
        assert properties.get_capabilities().clear_values.is_unsupported
        try:
            properties.clear_value("size")
        except NotImplementedError:
            pass
        else:
            raise AssertionError("unsupported clear did not fail")
        assert transforms is not None and selection is not None
        try:
            session.create_stage("/tmp/forbidden-new.usda")
        except NotImplementedError:
            pass
        else:
            raise AssertionError("unsupported create did not fail")
        try:
            session.export_stage(object(), "/tmp/forbidden-export.usda")
        except NotImplementedError:
            pass
        else:
            raise AssertionError("unsupported export did not fail")
        legacy_authoring_calls = (
            lambda: session.make_delete_prim_command(object(), "/World"),
            lambda: session.get_geometry_standard_prim_attrs(object()),
            lambda: session.get_light_prim_attrs(object()),
            lambda: session.get_next_free_prim_path(object(), "Cube"),
            lambda: session.get_next_free_path(object(), "/World/Cube"),
        )
        for call in legacy_authoring_calls:
            try:
                call()
            except NotImplementedError:
                pass
            else:
                raise AssertionError("removed hybrid authoring path did not fail closed")

        after = sorted(name for name in sys.modules if is_forbidden(name))
        assert attempts == [], attempts
        assert after == [], after
        print(json.dumps({{
            "attempts": attempts,
            "forbidden_modules": after,
            "imported_scoped_modules": len(set(modules)),
            "selected_provider": selected.name,
        }}, sort_keys=True))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence == {
        "attempts": [],
        "forbidden_modules": [],
        "imported_scoped_modules": len(tuple(PACKAGE_ROOT.glob("*.py"))),
        "selected_provider": "ovstage",
    }


def test_public_objects_have_no_forbidden_runtime_origin_or_bridge_contract() -> None:
    class NativeStage:
        current_ordinal = 7

    scene = OvstageScene(
        stage=NativeStage(),
        source_path="scene.usda",
        initial_ordinal=7,
        root_paths=("/World",),
    )
    session = OvstageProviderSession(runtime=object())
    stage = create_stage_adapter(scene=scene)
    properties = create_property_adapter(scene=scene, paths=["/World"])
    transforms = create_transform_adapter(scene=scene)
    selection = create_selection_adapter(scene=scene, stage_adapter=stage)
    layers = create_layer_stack_adapter(scene=scene)
    renderer_shell = object.__new__(OvstageRendererAdapter)
    public_objects = (
        scene,
        session,
        stage,
        properties,
        transforms,
        selection,
        layers,
        renderer_shell,
    )

    for value in _all_reachable_values(public_objects):
        assert not _forbidden_runtime_value(value), (type(value), value)
    for instance in public_objects:
        for name in vars(instance):
            assert name not in PROHIBITED_OBJECT_FLOW_NAMES
            assert "backing_usd" not in name

    classes = (
        OvstageScene,
        OvstageProviderSession,
        OvstageStageAdapter,
        OvstagePropertyAdapter,
        OvstageTransformAdapter,
        OvstageSelectionAdapter,
        OvstageLayerStackAdapter,
        OvstageRendererAdapter,
    )
    for cls in classes:
        for name in PROHIBITED_OBJECT_FLOW_NAMES:
            assert not hasattr(cls, name), (cls.__name__, name)
        signature = str(inspect.signature(cls))
        assert "backing_usd" not in signature
        assert "pxr" not in signature
        assert "ovui_data_adapters.openusd" not in signature


def test_distribution_metadata_declares_no_openusd_or_pxr_dependency() -> None:
    """The ovstage distribution must not require or install an OpenUSD adapter.

    ``pip install ovui-data-adapters-ovstage`` must never pull in
    ``ovui-data-adapters-openusd``, ``pxr``, or ``usd-core`` — not as a hard
    dependency and not through an extra. Only present in a source checkout;
    installed-wheel runs have no dist config to audit.
    """
    import tomllib

    pyproject = PACKAGE_ROOT.parents[1] / "dist" / "ovstage" / "pyproject.toml"
    if not pyproject.is_file():
        import pytest

        pytest.skip("distribution config only exists in a source checkout")

    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    requirements = list(project.get("dependencies", ()))
    for extra_requirements in project.get("optional-dependencies", {}).values():
        requirements.extend(extra_requirements)

    forbidden = ("openusd", "pxr", "usd-core", "usd_core")
    for requirement in requirements:
        normalized = requirement.lower().replace("_", "-")
        for marker in forbidden:
            assert marker not in normalized, requirement
