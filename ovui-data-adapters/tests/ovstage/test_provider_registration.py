# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage provider registration through the common adapter registry."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import importlib
import importlib.util
import pathlib
import sys
from types import SimpleNamespace
import tomllib
from unittest.mock import MagicMock

import pytest

from ovui_data_adapters.common import (
    ADAPTER_ENTRY_POINT_GROUP,
    LayerStackAdapter,
    PropertyAdapter,
    RendererAdapter,
    SelectionAdapter,
    StageAdapter,
    TransformAdapter,
    discover_adapter_modules,
    select_adapter,
)
OVSTAGE_SOURCE_ROOT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "ovui_data_adapters"
    / "ovstage"
)
OVSTAGE_DIST_PYPROJECT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "dist"
    / "ovstage"
    / "pyproject.toml"
)
OPENUSD_DIST_PYPROJECT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "dist"
    / "openusd"
    / "pyproject.toml"
)
COMPONENT_ENTRY_POINT_GROUP = "ovui_widgets.components"


@dataclass(frozen=True)
class _FakeEntryPoint:
    name: str
    value: str
    group: str

    def load(self):
        module_name, attr_name = self.value.split(":", 1)
        module = __import__(module_name, fromlist=[attr_name])
        return getattr(module, attr_name)


def _source_files() -> list[pathlib.Path]:
    return sorted(
        path
        for path in OVSTAGE_SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _patch_provider_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    import ovui_data_adapters.common._adapter_registry as registry_module
    import ovui_data_adapters.ovstage.provider as provider_module
    register_module = importlib.import_module("ovui_data_adapters.ovstage.register")
    renderer_module = importlib.import_module(
        "ovui_data_adapters.ovstage.renderer_adapter"
    )

    class _TestOvstageRendererAdapter(renderer_module.OvstageRendererAdapter):
        def __init__(self, scene=None, undo_manager=None):
            self.scene = scene
            self.undo_manager = undo_manager

    monkeypatch.setattr(
        provider_module,
        "load_required_runtimes",
        lambda **_: object(),
    )
    monkeypatch.setattr(
        provider_module,
        "OvstageRendererAdapter",
        _TestOvstageRendererAdapter,
    )
    monkeypatch.setattr(
        register_module,
        "build_factories",
        lambda: provider_module.build_factories(runtime=object()),
    )
    entries = (
        _FakeEntryPoint(
            name="openusd",
            value="ovui_data_adapters.openusd.register:register",
            group=ADAPTER_ENTRY_POINT_GROUP,
        ),
        _FakeEntryPoint(
            name="ovstage",
            value="ovui_data_adapters.ovstage.register:register",
            group=ADAPTER_ENTRY_POINT_GROUP,
        ),
    )
    monkeypatch.setattr(
        registry_module,
        "entry_points",
        lambda *, group: entries if group == ADAPTER_ENTRY_POINT_GROUP else (),
    )


def test_ovstage_entry_point_metadata_uses_common_adapter_group() -> None:
    pyproject = tomllib.loads(OVSTAGE_DIST_PYPROJECT.read_text(encoding="utf-8"))
    entry_points = pyproject["project"]["entry-points"][ADAPTER_ENTRY_POINT_GROUP]

    assert entry_points["ovstage"] == "ovui_data_adapters.ovstage.register:register"


def test_openusd_and_ovstage_dist_metadata_declare_provider_entry_points() -> None:
    openusd = tomllib.loads(OPENUSD_DIST_PYPROJECT.read_text(encoding="utf-8"))
    ovstage = tomllib.loads(OVSTAGE_DIST_PYPROJECT.read_text(encoding="utf-8"))

    assert (
        openusd["project"]["entry-points"][ADAPTER_ENTRY_POINT_GROUP]["openusd"]
        == "ovui_data_adapters.openusd.register:register"
    )
    assert (
        ovstage["project"]["entry-points"][ADAPTER_ENTRY_POINT_GROUP]["ovstage"]
        == "ovui_data_adapters.ovstage.register:register"
    )


def test_ovstage_dist_metadata_declares_component_entry_point() -> None:
    pyproject = tomllib.loads(OVSTAGE_DIST_PYPROJECT.read_text(encoding="utf-8"))
    entry_points = pyproject["project"]["entry-points"][COMPONENT_ENTRY_POINT_GROUP]

    assert (
        entry_points["ovstage_physics_controls"]
        == "ovui_widgets_physx_controls:register"
    )


def test_openusd_and_ovstage_providers_are_discoverable_through_common(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_discovery(monkeypatch)
    registry = discover_adapter_modules()
    providers = {provider.name: provider for provider in registry.available_adapters()}

    # The separate OpenUSD provider registers only when its own runtime
    # prerequisite (pxr) is importable. In the exact native-only OVStage
    # environment discovery truthfully exposes OVStage alone and records the
    # missing prerequisite as that provider's load failure instead of failing
    # registration or faking the OpenUSD provider.
    openusd_runtime_present = importlib.util.find_spec("pxr") is not None
    if openusd_runtime_present:
        assert "openusd" in providers
    else:
        assert "openusd" not in providers
    assert "ovstage" in providers

    provider = providers["ovstage"]
    selected = select_adapter(registry, requested_name="ovstage")

    assert selected is provider
    assert registry.active_provider is provider
    assert provider.name == "ovstage"
    assert provider.requirements == (
        "ovstage",
        "ovrtx",
    )
    assert callable(provider.factories.stage)
    assert callable(provider.factories.properties)
    assert callable(provider.factories.transforms)
    assert callable(provider.factories.renderer)
    assert callable(provider.factories.selection)
    assert callable(provider.factories.layers)
    assert callable(provider.factories.session)
    if openusd_runtime_present:
        assert registry.load_failures == ()
    else:
        # Exactly the OpenUSD provider fails to load, exactly because its
        # runtime prerequisite is absent; any other failure stays an error.
        assert [
            (failure.name, failure.exception_type)
            for failure in registry.load_failures
        ] == [("openusd", "ModuleNotFoundError")]
        (openusd_failure,) = registry.load_failures
        assert "pxr" in openusd_failure.exception_text


def test_ovstage_factories_construct_common_abc_scaffolds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_discovery(monkeypatch)
    registry = discover_adapter_modules()
    provider = select_adapter(registry, requested_name="ovstage")
    factories = provider.factories

    stage = factories.stage()
    properties = factories.properties(None, ["/World"], None, stage)
    transforms = factories.transforms()
    renderer = factories.renderer()
    selection = factories.selection(None, stage)
    layers = factories.layers()
    session = factories.session()

    assert isinstance(stage, StageAdapter)
    assert isinstance(properties, PropertyAdapter)
    assert isinstance(transforms, TransformAdapter)
    assert isinstance(renderer, RendererAdapter)
    assert isinstance(selection, SelectionAdapter)
    assert isinstance(layers, LayerStackAdapter)
    assert type(stage).__name__ == "OvstageStageAdapter"
    assert type(properties).__name__ == "OvstagePropertyAdapter"
    assert type(transforms).__name__ == "OvstageTransformAdapter"
    assert type(renderer).__name__ == "_TestOvstageRendererAdapter"
    assert type(selection).__name__ == "OvstageSelectionAdapter"
    assert type(layers).__name__ == "OvstageLayerStackAdapter"

    assert properties.get_paths() == ["/World"]
    assert properties.get_scheme() == "ovstage"
    assert properties.is_valid() is False
    assert properties.get_attribute_names() == []
    assert transforms.can_transform("/World") is False
    assert selection.to_adapter_items([]) == []
    assert selection.to_selection_items([]) == []
    assert layers.get_layer_stack_identifiers() == []
    assert layers.save_layer("missing") is False
    assert session.renderer_available() is True
    assert session.renderer_unavailable_reason() == ""


def test_provider_session_passes_application_undo_manager_to_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_discovery(monkeypatch)
    import ovui_data_adapters.ovstage.provider as provider_module

    undo_manager = object()
    app = SimpleNamespace(undo_manager=undo_manager)
    session = provider_module.OvstageProviderSession(app=app, runtime=object())

    renderer = session.create_renderer()

    assert renderer.undo_manager is undo_manager


def test_ovstage_session_creates_real_common_livestream_tap_without_ovrtx_data_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ovui_data_adapters.ovstage.provider as provider_module
    from ovui_data_adapters.common import _livestream_tap as tap_module

    ovstream = MagicMock()
    ovstream.ServerType.WEBRTC = "WEBRTC"
    ovstream.ServerType.NATIVE = "NATIVE"
    ovstream.ServerType.RTSP = "RTSP"
    monkeypatch.setitem(sys.modules, "ovstream", ovstream)
    monkeypatch.setenv(tap_module._ENABLED_ENV_VAR, "1")
    monkeypatch.setattr(tap_module, "_Cudart", lambda: SimpleNamespace())

    # Creating the transport must not discover OVRTX or touch any renderer
    # scene-data surface. It consumes only a frame pointer when driven later.
    runtime_probe = MagicMock(
        side_effect=AssertionError("livestream creation must not access OVRTX")
    )
    monkeypatch.setattr(provider_module, "load_required_runtimes", runtime_probe)

    session = provider_module.OvstageProviderSession(runtime=object())
    tap = session.create_livestream_tap()

    assert type(tap) is tap_module.LivestreamTap
    assert tap._ovstream is ovstream
    runtime_probe.assert_not_called()

    tap.close()
    ovstream.shutdown.assert_called_once_with()


@pytest.mark.parametrize(
    ("factory_name", "factory_args", "method_name", "method_args"),
    [
        ("stage", (), "get_root", ()),
        ("properties", (None, ["/World"], None, None), "get_value", ("size",)),
        ("transforms", (), "get_local_transform", ("/World",)),
        ("layers", (), "get_root_layer", ()),
    ],
)
def test_ovstage_scaffold_methods_signal_not_implemented_yet(
    monkeypatch: pytest.MonkeyPatch,
    factory_name: str,
    factory_args: tuple[object, ...],
    method_name: str,
    method_args: tuple[object, ...],
) -> None:
    _patch_provider_discovery(monkeypatch)
    registry = discover_adapter_modules()
    provider = select_adapter(registry, requested_name="ovstage")
    factory = getattr(provider.factories, factory_name)
    instance = factory(*factory_args)
    method = getattr(instance, method_name)

    with pytest.raises(NotImplementedError, match="not implemented yet"):
        method(*method_args)


def test_ovstage_adapter_package_does_not_import_ovui_widgets() -> None:
    violations: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ovui_widgets" or alias.name.startswith("ovui_widgets."):
                        violations.append(f"{path.relative_to(OVSTAGE_SOURCE_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "ovui_widgets" or module.startswith("ovui_widgets."):
                    violations.append(f"{path.relative_to(OVSTAGE_SOURCE_ROOT)}:{node.lineno}")

    assert violations == []
