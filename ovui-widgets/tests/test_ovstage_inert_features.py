# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OVStage provider capability gating and no-scene fallback behavior.

These tests exercise the application's capability-driven UI gating with
synthetic provider fakes. Some fakes model a provider that CAN author
documents and layers (a capability shape the retired hybrid provider had and
a future provider could have again); they are historical/synthetic test
doubles, not descriptions of the current native OVStage provider, which
reports those capabilities as unsupported.
"""

from __future__ import annotations

import ast
import pathlib
import types
from typing import Any, Callable

from ovui_data_adapters.common import AdapterCapability, LayerStackCapabilities
from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.provider import OvstageProviderSession
from ovui_data_adapters.services.testing import MockLayerStackAdapter

from ovui_widgets.layers.layer_model import LayerModel


class _FakeMenu:
    _active: list[str] = []

    def __init__(
        self,
        label: str,
        *_args: Any,
        on_build_fn: Callable[[], None] | None = None,
        eager_build: bool = True,
        **_kwargs: Any,
    ) -> None:
        self.label = label
        self.on_build_fn = on_build_fn
        self.eager_build = eager_build

    def __enter__(self) -> "_FakeMenu":
        _FakeMenu._active.append(self.label)
        if self.eager_build and self.on_build_fn is not None:
            self.on_build_fn()
        return self

    def __exit__(self, *_args: Any) -> None:
        _FakeMenu._active.pop()


class _FakeMenuItem:
    registry: dict[str, list[dict[str, Any]]] = {}

    def __init__(
        self,
        label: str,
        triggered_fn: Callable[[], Any] | None = None,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        hotkey_text: str = "",
        **_kwargs: Any,
    ) -> None:
        active = _FakeMenu._active[-1] if _FakeMenu._active else ""
        _FakeMenuItem.registry.setdefault(active, []).append(
            {
                "label": label,
                "triggered_fn": triggered_fn,
                "enabled": enabled,
                "checkable": checkable,
                "checked": checked,
                "hotkey_text": hotkey_text,
            }
        )


class _FakeSeparator:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class _FakeUndoManager:
    def __init__(self) -> None:
        self.pushed: list[Any] = []

    def push(self, command: Any) -> None:
        self.pushed.append(command)


class _NoCreateSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def can_create_prims(self) -> bool:
        return False

    def _called(self, name: str) -> None:
        self.calls.append(name)

    def create_mesh_prim(self, *_args: Any) -> None:
        self._called("create_mesh_prim")

    def create_shape_prim(self, *_args: Any) -> None:
        self._called("create_shape_prim")

    def create_light_prim(self, *_args: Any) -> None:
        self._called("create_light_prim")

    def create_camera(self, *_args: Any) -> None:
        self._called("create_camera")

    def create_scope(self, *_args: Any) -> None:
        self._called("create_scope")

    def create_xform(self, *_args: Any) -> None:
        self._called("create_xform")

    def create_usd_preview_surface_material(self, *_args: Any) -> None:
        self._called("create_usd_preview_surface_material")


class _BackingCreateSession(_NoCreateSession):
    """Synthetic (hybrid-era) session fake that reports create capability.

    The current native provider does not delegate to a backing USD stage;
    this fake only exercises the capability-gated UI path.
    """

    def can_create_prims(self) -> bool:
        return True


class _BackingLayerAdapter(MockLayerStackAdapter):
    """Synthetic (hybrid-era) layer fake that reports layer capabilities.

    The current native provider reports every layer capability unsupported;
    this fake only exercises the capability-gated UI path.
    """

    def get_capabilities(self) -> LayerStackCapabilities:
        supported = AdapterCapability.supported(
            "delegated to the backing UsdStage"
        )
        return LayerStackCapabilities(
            layer_stack=supported,
            edit_target_read=supported,
            edit_target_write=supported,
            save_layer=supported,
            save_layer_as=supported,
            create_sublayer=supported,
            insert_sublayer=supported,
            remove_sublayer=supported,
            reload_layer=supported,
        )


class _NoSaveSession:
    def __init__(self) -> None:
        self.export_calls: list[tuple[Any, str]] = []

    def get_capabilities(self) -> Any:
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            StageCapabilities,
        )

        return AdapterCapabilities(
            stage=StageCapabilities(
                export_stage=AdapterCapability.unsupported(
                    "test adapter cannot export"
                )
            )
        )

    def can_export_stage(self) -> bool:
        raise AssertionError("File menu must read explicit capabilities")

    def export_stage(self, stage: Any, path: str) -> None:
        self.export_calls.append((stage, path))


def _fake_ui(*, eager_build: bool = True) -> types.ModuleType:
    _FakeMenu._active = []
    _FakeMenuItem.registry = {}
    fake = types.ModuleType("omni.ui")

    class _Menu(_FakeMenu):
        def __init__(self, label: str, *args: Any, **kwargs: Any) -> None:
            super().__init__(label, *args, eager_build=eager_build, **kwargs)

    fake.Menu = _Menu
    fake.MenuItem = _FakeMenuItem
    fake.Separator = _FakeSeparator
    fake.Spacer = lambda *args, **kwargs: None
    return fake


def _item(menu: list[dict[str, Any]], label: str) -> dict[str, Any]:
    for entry in menu:
        if entry["label"] == label:
            return entry
    raise AssertionError(f"missing menu item {label!r}")


def test_ovstage_layers_model_attaches_as_empty_tree() -> None:
    adapter = OvstageLayerStackAdapter()
    model = LayerModel(adapter)
    try:
        assert model.root_item is None
        assert model.session_item is None
        assert model.get_item_children(None) == []
    finally:
        model.destroy()


def test_layer_menu_commands_disable_against_unsupported_ovstage_layer_stack(monkeypatch) -> None:
    import ovui_widgets.app.menu_bar as mb
    from ovui_widgets.common.error_reporter import ErrorReporter

    adapter = OvstageLayerStackAdapter()
    model = LayerModel(adapter)
    app = types.SimpleNamespace(
        _layer_adapter=adapter,
        _layer_window=types.SimpleNamespace(_model=model),
        undo_manager=_FakeUndoManager(),
        selection_bus=object(),
    )
    fake = _fake_ui()
    warnings: list[str] = []
    monkeypatch.setattr(mb, "ui", fake)
    monkeypatch.setattr(ErrorReporter, "show_warning", lambda message: warnings.append(message))
    try:
        _FakeMenu._active.append("Layer")
        mb._build_layer_menu(app)
        _FakeMenu._active.pop()

        layer_items = _FakeMenuItem.registry["Layer"]
        for label in (
            "Save Layer",
            "Save All",
            "Save As...",
            "Create Sublayer",
            "Insert Sublayer",
            "Remove Layer",
            "Reload Layer",
        ):
            entry = _item(layer_items, label)
            assert entry["enabled"] is False
            entry["triggered_fn"]()

        authoring_items = _FakeMenuItem.registry["Set Authoring Layer"]
        assert authoring_items == [
            {
                "label": "(layer stack unavailable)",
                "triggered_fn": None,
                "enabled": False,
                "checkable": False,
                "checked": False,
                "hotkey_text": "",
            }
        ]
        assert app.undo_manager.pushed == []
        assert warnings
        assert all(message == "Layer stack is unavailable" for message in warnings)
    finally:
        model.destroy()


def test_layer_menu_enables_actions_for_backing_usd_layer_adapter(monkeypatch) -> None:
    import ovui_widgets.app.menu_bar as mb

    adapter = _BackingLayerAdapter(include_session=False)
    root_id = adapter.get_root_layer().identifier
    adapter.add_sublayer(root_id, "child.usda", display_name="child.usda")
    adapter.set_dirty("child.usda", True)
    model = LayerModel(adapter)
    child = model.root_item.sublayers[0]
    model.set_selected_items([child])
    app = types.SimpleNamespace(
        _layer_adapter=adapter,
        _layer_window=types.SimpleNamespace(_model=model),
        undo_manager=_FakeUndoManager(),
        selection_bus=object(),
    )
    fake = _fake_ui()
    monkeypatch.setattr(mb, "ui", fake)
    try:
        _FakeMenu._active.append("Layer")
        mb._build_layer_menu(app)
        _FakeMenu._active.pop()

        layer_items = _FakeMenuItem.registry["Layer"]
        for label in (
            "Save Layer",
            "Save All",
            "Save As...",
            "Create Sublayer",
            "Insert Sublayer",
            "Remove Layer",
            "Reload Layer",
        ):
            assert _item(layer_items, label)["enabled"] is True

        authoring_items = _FakeMenuItem.registry["Set Authoring Layer"]
        assert _item(authoring_items, "root")["enabled"] is True
        assert _item(authoring_items, "child.usda")["enabled"] is True
    finally:
        model.destroy()


def test_create_menu_disables_and_noops_when_provider_cannot_create_prims(
    monkeypatch,
) -> None:
    import ovui_widgets.app.create_menu as create_menu

    session = _NoCreateSession()
    app = types.SimpleNamespace(get_adapter_session=lambda: session)
    fake = _fake_ui()
    monkeypatch.setattr(create_menu, "ui", fake)

    create_menu.build_create_menu(app)

    flattened = [
        item
        for menu_items in _FakeMenuItem.registry.values()
        for item in menu_items
    ]
    assert flattened
    assert all(item["enabled"] is False for item in flattened)

    assert create_menu.create_mesh_prim(app, "Cube") is None
    assert create_menu.create_shape_prim(app, "Cube") is None
    assert create_menu.create_light_prim(app, "DistantLight") is None
    assert create_menu.create_camera(app) is None
    assert create_menu.create_scope(app) is None
    assert create_menu.create_xform(app) is None
    assert create_menu.create_usd_preview_surface_material(app) is None
    assert session.calls == []


def test_create_menu_enables_and_dispatches_for_backing_usd_session(
    monkeypatch,
) -> None:
    import ovui_widgets.app.create_menu as create_menu

    session = _BackingCreateSession()
    app = types.SimpleNamespace(get_adapter_session=lambda: session)
    fake = _fake_ui()
    monkeypatch.setattr(create_menu, "ui", fake)

    create_menu.build_create_menu(app)

    flattened = [
        item
        for menu_items in _FakeMenuItem.registry.values()
        for item in menu_items
    ]
    assert flattened
    assert all(item["enabled"] is True for item in flattened)

    _item(_FakeMenuItem.registry["Mesh"], "Cube")["triggered_fn"]()
    _item(_FakeMenuItem.registry["Light"], "Distant Light")["triggered_fn"]()
    _item(_FakeMenuItem.registry[""], "Camera")["triggered_fn"]()
    _item(_FakeMenuItem.registry["USD Materials"], "USD Preview Surface")[
        "triggered_fn"
    ]()
    assert session.calls == [
        "create_mesh_prim",
        "create_light_prim",
        "create_camera",
        "create_usd_preview_surface_material",
    ]


def test_file_save_menu_disables_when_provider_cannot_export(monkeypatch) -> None:
    import ovui_widgets.app.menu_bar as mb

    session = _NoSaveSession()
    app = types.SimpleNamespace(
        _stage_adapter=types.SimpleNamespace(stage=object()),
        _stage_window=types.SimpleNamespace(visible=True),
        _property_window=types.SimpleNamespace(visible=True),
        _viewport_window=types.SimpleNamespace(visible=True),
        _content_window=types.SimpleNamespace(visible=True),
        _layer_window=types.SimpleNamespace(visible=True),
        get_adapter_session=lambda: session,
    )
    fake = _fake_ui(eager_build=False)
    monkeypatch.setattr(mb, "ui", fake)
    monkeypatch.setattr(mb, "_build_product_identity", lambda: None)

    _FakeMenu._active.append("File")
    try:
        mb._build_file_menu(app)
    finally:
        _FakeMenu._active.pop()

    file_items = _FakeMenuItem.registry["File"]
    assert _item(file_items, "Save")["enabled"] is False
    assert _item(file_items, "Save As...")["enabled"] is False


def test_ovstage_provider_session_reports_persistent_and_authoring_gates() -> None:
    session = OvstageProviderSession(runtime=object())

    # The native OVStage session has no OpenUSD bridge: durable export is
    # truthfully unsupported while native prim authoring stays available.
    assert session.can_export_stage() is False
    assert session.can_create_prims() is True
    assert session.can_delete_prims() is True


def test_production_code_keeps_widget_and_adapter_boundaries_clean() -> None:
    root = pathlib.Path(__file__).resolve().parents[2]
    scans = (
        (
            root / "ovui-widgets" / "ovui_widgets",
            (
                "ovui_data_adapters.openusd",
                "ovui_data_adapters.ovstage",
                "pxr",
                "ovstage",
                "ovpopulation",
                "ovhierarchy",
                "ovphysx",
                "ovrtx",
            ),
        ),
        (
            root / "ovui-data-adapters" / "ovui_data_adapters" / "ovstage",
            ("ovui_widgets",),
        ),
    )
    violations: list[str] = []

    for package_root, forbidden_prefixes in scans:
        for path in package_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            rel = path.relative_to(root)
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module:
                        targets.append(module)
                    if module == "ovui_data_adapters":
                        targets.extend(f"{module}.{alias.name}" for alias in node.names)
                for target in targets:
                    if any(
                        target == prefix or target.startswith(prefix + ".")
                        for prefix in forbidden_prefixes
                    ):
                        violations.append(f"{rel}:{node.lineno}: imports {target}")

    assert violations == []
