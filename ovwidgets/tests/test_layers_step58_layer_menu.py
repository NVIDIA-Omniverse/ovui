# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 58 — Main menu bar "Layer" menu.

Covers:

- :func:`build_menu_bar` registers a top-level "Layer" menu between
  Edit and Tools.
- :func:`_build_layer_menu` emits the seven expected entries plus the
  dynamic "Set Authoring Layer" submenu.
- Enabled flags respond to adapter presence, layer writability, dirty
  state, root-ness and anonymity.
- :func:`_build_set_authoring_submenu` lists stack identifiers with
  the current edit target checkmarked; caps at 50 entries with an
  overflow sentinel row.
- Click handlers route through the same model / command paths used by
  the context menu and footer toolbar, and surface a toast when the
  adapter is missing.
- Hotkey hints ("Ctrl+Shift+S", "Ctrl+Shift+Alt+S") are displayed on
  Save All and Save As…; the actual key routing lands in Step 59.
"""

from __future__ import annotations

import types
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock

# ── Fake ovui surface ──────────────────────────────────────────────────


class _FakeMenu:
    """Records Menu entries and dispatches ``on_build_fn`` eagerly."""

    _active: List[str] = []  # class-level stack of menu labels

    def __init__(
        self,
        label: str,
        *_a: Any,
        on_build_fn: Optional[Callable[[], None]] = None,
        **_kw: Any,
    ) -> None:
        self.label = label
        self.on_build_fn = on_build_fn

    def __enter__(self) -> "_FakeMenu":
        _FakeMenu._active.append(self.label)
        if self.on_build_fn is not None:
            # Fire the child builder in the context of this submenu so
            # its entries get recorded under the submenu label.
            self.on_build_fn()
        return self

    def __exit__(self, *_a: Any) -> None:
        _FakeMenu._active.pop()


class _FakeMenuItem:
    """Records MenuItem constructions keyed by menu + label."""

    registry: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(
        self,
        label: str,
        triggered_fn: Optional[Callable[[], None]] = None,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        hotkey_text: str = "",
        **_kw: Any,
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
    def __init__(self, *_a: Any, **_kw: Any) -> None:
        pass


def _patch_ui() -> types.ModuleType:
    """Build the fake ``omni.ui`` substitute and reset the registry."""
    _FakeMenu._active = []
    _FakeMenuItem.registry = {}
    fake = types.ModuleType("omni.ui")
    fake.Menu = _FakeMenu
    fake.MenuItem = _FakeMenuItem
    fake.Separator = _FakeSeparator
    fake.Spacer = lambda *a, **kw: None
    return fake


def _build_with_fake_ui(app: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Run :func:`build_menu_bar` under the fake ovui, return capture."""
    import ovwidgets.app.menu_bar as mb

    fake = _patch_ui()
    original = mb.ui
    original_identity = mb._build_product_identity
    try:
        mb.ui = fake
        mb._build_product_identity = lambda: None
        mb.build_menu_bar(app)
    finally:
        mb.ui = original
        mb._build_product_identity = original_identity
    return _FakeMenuItem.registry


def _build_layer_menu_only(app: Any) -> List[Dict[str, Any]]:
    """Run :func:`_build_layer_menu` under a fake Layer-menu context."""
    import ovwidgets.app.menu_bar as mb

    fake = _patch_ui()
    original = mb.ui
    try:
        mb.ui = fake
        _FakeMenu._active.append("Layer")
        mb._build_layer_menu(app)
        _FakeMenu._active.pop()
    finally:
        mb.ui = original
    return _FakeMenuItem.registry.get("Layer", [])


def _item(menu: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    for entry in menu:
        if entry["label"] == label:
            return entry
    raise AssertionError(f"item not found: {label} in {[e['label'] for e in menu]}")


# ── App / target fakes ─────────────────────────────────────────────────


from ovwidgets.layers.layer_item import LayerItem


class _FakeLayerItem(LayerItem):
    """Minimal LayerItem stub — real subclass so ``isinstance`` matches.

    Real :class:`LayerItem` would pull flags from a live adapter; this
    variant stores the flag values directly and short-circuits the
    refresh path so menu-driven state checks are deterministic.
    """

    def __init__(
        self,
        identifier: str = "root.usda",
        is_dirty: bool = False,
        is_writable: bool = True,
        is_anonymous: bool = False,
        parent: Optional["_FakeLayerItem"] = None,
    ) -> None:
        # Call through to the real constructor with a ``None`` adapter;
        # the property overrides below never exercise the adapter path,
        # so no adapter calls fire during the test.
        LayerItem.__init__(
            self, adapter=None, identifier=identifier, parent=parent
        )
        self._dirty_override = is_dirty
        self._writable_override = is_writable
        self._anon_override = is_anonymous

    @property
    def is_dirty(self) -> bool:  # type: ignore[override]
        return self._dirty_override

    @property
    def is_writable(self) -> bool:  # type: ignore[override]
        return self._writable_override

    @property
    def is_anonymous(self) -> bool:  # type: ignore[override]
        return self._anon_override


class _FakeModel:
    def __init__(
        self,
        root: Optional[_FakeLayerItem],
        selected: Optional[List[Any]] = None,
    ) -> None:
        self.root_item = root
        self.selected_items = selected or []
        # Recorded calls — tests assert against these rather than the
        # adapter, matching the context-menu / footer dispatch contract.
        self.save_calls: List[Any] = []
        self.save_all_calls: int = 0
        self.save_as_calls: List[Any] = []
        self.reload_calls: List[Any] = []
        self.remove_calls: List[Any] = []

    def _request_save(self, item: Any) -> None:
        self.save_calls.append(item)

    def _request_save_all(self) -> None:
        self.save_all_calls += 1

    def _request_save_as(self, item: Any) -> None:
        self.save_as_calls.append(item)

    def _request_reload(self, item: Any) -> None:
        self.reload_calls.append(item)

    def _request_remove_sublayer(self, parent_id: str, position: int) -> None:
        self.remove_calls.append((parent_id, position))


class _FakeAdapter:
    def __init__(
        self,
        identifiers: Optional[List[str]] = None,
        current_target: str = "root.usda",
        display_names: Optional[Dict[str, str]] = None,
        sublayer_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self._ids = identifiers or ["root.usda"]
        self._current_target = current_target
        self._names = display_names or {}
        self._sublayer_map = sublayer_map or {}
        self.pushed_commands: List[Any] = []

    def get_layer_stack_identifiers(
        self,
        include_session: bool = False,
        include_anonymous: bool = True,
    ) -> List[str]:
        return list(self._ids)

    def get_edit_target_identifier(self) -> str:
        return self._current_target

    def find_layer(self, identifier: str) -> Any:
        return types.SimpleNamespace(identifier=identifier)

    def get_display_name(self, handle: Any) -> str:
        return self._names.get(handle.identifier, handle.identifier)

    def get_sublayer_identifiers(self, parent_handle: Any) -> List[str]:
        return list(self._sublayer_map.get(parent_handle.identifier, []))


class _FakeUndoManager:
    def __init__(self) -> None:
        self.pushed: List[Any] = []

    def push(self, cmd: Any) -> None:
        self.pushed.append(cmd)

    # ``_build_edit_menu`` reads these when the full menu bar is built;
    # returning ``False`` keeps the Undo/Redo items cleanly disabled.
    def can_undo(self) -> bool:
        return False

    def can_redo(self) -> bool:
        return False

    def begin_group(self, _label: str) -> None:
        pass

    def end_group(self) -> None:
        pass


class _FakeWindow:
    def __init__(self, model: Optional[_FakeModel]) -> None:
        self._model = model


def _make_app(
    *,
    adapter: Optional[_FakeAdapter] = None,
    selected: Optional[List[Any]] = None,
    root: Optional[_FakeLayerItem] = None,
) -> Any:
    app = MagicMock()
    app._layer_adapter = adapter
    if adapter is None and root is None:
        app._layer_window = None
    else:
        model = _FakeModel(root=root, selected=selected)
        app._layer_window = _FakeWindow(model)
    app.undo_manager = _FakeUndoManager()
    app.selection_bus = MagicMock()
    # ``_build_edit_menu`` / ``_build_tools_menu`` / ``_build_view_menu``
    # all expect a ``Settings`` surface with ``.get``; return a real
    # string for the active-tool setting so their checkmark branch is
    # deterministic.
    app.settings.get.return_value = "translate"
    app._recent_files.get_ordered.return_value = []
    return app


# ── Menu-structure tests ───────────────────────────────────────────────


class TestLayerMenuPresent:
    def test_layer_menu_is_registered_between_edit_and_tools(self) -> None:
        """``build_menu_bar`` must create a top-level "Layer" menu."""
        app = _make_app()
        registry = _build_with_fake_ui(app)
        # The Layer menu's on_build_fn fires on __enter__ — its items
        # land under the "Layer" bucket regardless of whether a child
        # adapter exists.
        assert "Layer" in registry, (
            f"Layer menu missing; got {sorted(registry)}"
        )

    def test_layer_menu_position_between_edit_and_tools(self) -> None:
        """Source order: File, Edit, Layer, Tools, View, Window, Help."""
        # We capture Menu construction order via a side-list on the fake.
        import ovwidgets.app.menu_bar as mb

        labels: List[str] = []
        orig_menu = _FakeMenu

        class _RecordingMenu(_FakeMenu):
            def __init__(self, label: str, *a: Any, **kw: Any) -> None:
                labels.append(label)
                super().__init__(label, *a, **kw)

        fake = _patch_ui()
        fake.Menu = _RecordingMenu
        original = mb.ui
        original_identity = mb._build_product_identity
        app = _make_app()
        try:
            mb.ui = fake
            mb._build_product_identity = lambda: None
            mb.build_menu_bar(app)
        finally:
            mb.ui = original
            mb._build_product_identity = original_identity
        # Top-level labels appear once each; submenu labels may repeat.
        top = [lbl for lbl in labels if lbl in {"File", "Edit", "Layer", "Tools", "View", "Window", "Help"}]
        assert top.index("Edit") < top.index("Layer") < top.index("Tools")


class TestLayerMenuEntries:
    EXPECTED_MENU_ITEMS = [
        "Save Layer",
        "Save All",
        "Save As...",
        "Create Sublayer",
        "Insert Sublayer",
        "Remove Layer",
        "Reload Layer",
    ]

    def test_all_menu_items_present(self) -> None:
        app = _make_app(
            adapter=_FakeAdapter(),
            root=_FakeLayerItem(),
        )
        items = _build_layer_menu_only(app)
        labels = [e["label"] for e in items]
        for exp in self.EXPECTED_MENU_ITEMS:
            assert exp in labels, f"{exp!r} missing from {labels}"

    def test_set_authoring_layer_submenu_present(self) -> None:
        """``Set Authoring Layer`` is a nested Menu, not a MenuItem."""
        app = _make_app(adapter=_FakeAdapter(), root=_FakeLayerItem())
        _build_layer_menu_only(app)
        # The fake Menu dispatches on_build_fn on __enter__; any entries
        # it produced land under the submenu's bucket.
        assert "Set Authoring Layer" in _FakeMenuItem.registry

    def test_hotkey_hints_shown(self) -> None:
        """Step 59 wires: Save Layer ↔ Ctrl+Alt+S; Save All ↔ Ctrl+S;
        Save As... ↔ Ctrl+Shift+S."""
        app = _make_app(adapter=_FakeAdapter(), root=_FakeLayerItem())
        items = _build_layer_menu_only(app)
        assert _item(items, "Save Layer")["hotkey_text"] == "Ctrl+Alt+S"
        assert _item(items, "Save All")["hotkey_text"] == "Ctrl+S"
        assert _item(items, "Save As...")["hotkey_text"] == "Ctrl+Shift+S"


# ── Enabled-flag tests ─────────────────────────────────────────────────


class TestEnabledFlags:
    def test_no_stage_disables_everything_except_submenu_header(self) -> None:
        """Without a loaded stage every action grays out."""
        app = _make_app(adapter=None)
        items = _build_layer_menu_only(app)
        # Set Authoring Layer is a submenu header — built even without
        # an adapter so the user sees the affordance (its children show
        # a "(no stage open)" sentinel).
        for label in [
            "Save Layer",
            "Save All",
            "Save As...",
            "Create Sublayer",
            "Insert Sublayer",
            "Remove Layer",
            "Reload Layer",
        ]:
            assert _item(items, label)["enabled"] is False, (
                f"{label} should be disabled without a stage"
            )

    def test_save_layer_enabled_only_when_dirty(self) -> None:
        dirty = _FakeLayerItem(is_dirty=True)
        app = _make_app(adapter=_FakeAdapter(), root=dirty)
        items = _build_layer_menu_only(app)
        assert _item(items, "Save Layer")["enabled"] is True

        clean = _FakeLayerItem(is_dirty=False)
        app = _make_app(adapter=_FakeAdapter(), root=clean)
        items = _build_layer_menu_only(app)
        assert _item(items, "Save Layer")["enabled"] is False

    def test_create_insert_require_writable(self) -> None:
        locked = _FakeLayerItem(is_writable=False)
        app = _make_app(adapter=_FakeAdapter(), root=locked)
        items = _build_layer_menu_only(app)
        assert _item(items, "Create Sublayer")["enabled"] is False
        assert _item(items, "Insert Sublayer")["enabled"] is False

        writable = _FakeLayerItem(is_writable=True)
        app = _make_app(adapter=_FakeAdapter(), root=writable)
        items = _build_layer_menu_only(app)
        assert _item(items, "Create Sublayer")["enabled"] is True
        assert _item(items, "Insert Sublayer")["enabled"] is True

    def test_remove_disabled_on_root(self) -> None:
        """With no selection the target falls back to root — Remove grays out."""
        root = _FakeLayerItem(identifier="root.usda")
        app = _make_app(adapter=_FakeAdapter(), root=root)
        items = _build_layer_menu_only(app)
        assert _item(items, "Remove Layer")["enabled"] is False

    def test_remove_enabled_on_single_non_root_selection(self) -> None:
        root = _FakeLayerItem(identifier="root.usda")
        child = _FakeLayerItem(identifier="child.usda", parent=root)
        app = _make_app(
            adapter=_FakeAdapter(
                sublayer_map={"root.usda": ["child.usda"]},
            ),
            selected=[child],
            root=root,
        )
        items = _build_layer_menu_only(app)
        assert _item(items, "Remove Layer")["enabled"] is True

    def test_reload_disabled_for_anonymous_layer(self) -> None:
        anon = _FakeLayerItem(identifier="anon:123", is_anonymous=True)
        app = _make_app(adapter=_FakeAdapter(), root=anon)
        items = _build_layer_menu_only(app)
        assert _item(items, "Reload Layer")["enabled"] is False

    def test_reload_enabled_for_concrete_layer(self) -> None:
        concrete = _FakeLayerItem(identifier="root.usda", is_anonymous=False)
        app = _make_app(adapter=_FakeAdapter(), root=concrete)
        items = _build_layer_menu_only(app)
        assert _item(items, "Reload Layer")["enabled"] is True


# ── Set Authoring Layer submenu ────────────────────────────────────────


class TestSetAuthoringSubmenu:
    def test_submenu_lists_stack_identifiers(self) -> None:
        adapter = _FakeAdapter(
            identifiers=["root.usda", "child_a.usda", "child_b.usda"],
            current_target="child_a.usda",
        )
        app = _make_app(adapter=adapter, root=_FakeLayerItem())
        items = _build_layer_menu_only(app)
        # The submenu entries land under a child bucket keyed by the
        # submenu label.
        sub = _FakeMenuItem.registry.get("Set Authoring Layer", [])
        labels = [e["label"] for e in sub]
        assert "root.usda" in labels
        assert "child_a.usda" in labels
        assert "child_b.usda" in labels

    def test_submenu_checks_current_edit_target(self) -> None:
        adapter = _FakeAdapter(
            identifiers=["root.usda", "child_a.usda"],
            current_target="child_a.usda",
        )
        app = _make_app(adapter=adapter, root=_FakeLayerItem())
        _build_layer_menu_only(app)
        sub = _FakeMenuItem.registry["Set Authoring Layer"]
        current = _item(sub, "child_a.usda")
        other = _item(sub, "root.usda")
        assert current["checkable"] is True
        assert current["checked"] is True
        assert other["checked"] is False

    def test_submenu_shows_no_stage_sentinel_when_adapter_missing(self) -> None:
        app = _make_app(adapter=None)
        _build_layer_menu_only(app)
        sub = _FakeMenuItem.registry.get("Set Authoring Layer", [])
        assert len(sub) == 1
        assert sub[0]["label"] == "(no stage open)"
        assert sub[0]["enabled"] is False

    def test_submenu_caps_long_stacks_with_overflow_sentinel(self) -> None:
        ids = [f"layer_{i}.usda" for i in range(60)]
        adapter = _FakeAdapter(identifiers=ids, current_target=ids[0])
        app = _make_app(adapter=adapter, root=_FakeLayerItem())
        _build_layer_menu_only(app)
        sub = _FakeMenuItem.registry["Set Authoring Layer"]
        # 50 concrete layers + one overflow sentinel = 51 total.
        assert len(sub) == 51
        assert sub[-1]["label"].startswith("(+10 more")
        assert sub[-1]["enabled"] is False


# ── Click handlers ─────────────────────────────────────────────────────


class TestClickHandlers:
    def test_save_layer_calls_model_request_save(self) -> None:
        target = _FakeLayerItem(is_dirty=True)
        app = _make_app(adapter=_FakeAdapter(), root=target)
        items = _build_layer_menu_only(app)
        _item(items, "Save Layer")["triggered_fn"]()
        assert app._layer_window._model.save_calls == [target]

    def test_save_all_calls_model_request_save_all(self) -> None:
        app = _make_app(adapter=_FakeAdapter(), root=_FakeLayerItem())
        items = _build_layer_menu_only(app)
        _item(items, "Save All")["triggered_fn"]()
        assert app._layer_window._model.save_all_calls == 1

    def test_save_as_calls_model_request_save_as(self) -> None:
        target = _FakeLayerItem()
        app = _make_app(adapter=_FakeAdapter(), root=target)
        items = _build_layer_menu_only(app)
        _item(items, "Save As...")["triggered_fn"]()
        assert app._layer_window._model.save_as_calls == [target]

    def test_create_sublayer_pushes_create_command(self) -> None:
        from ovwidgets.layers.commands import CreateSublayerCommand
        target = _FakeLayerItem(identifier="root.usda")
        app = _make_app(adapter=_FakeAdapter(), root=target)
        items = _build_layer_menu_only(app)
        _item(items, "Create Sublayer")["triggered_fn"]()
        assert len(app.undo_manager.pushed) == 1
        assert isinstance(app.undo_manager.pushed[0], CreateSublayerCommand)

    def test_set_authoring_pushes_set_edit_target_command(self) -> None:
        from ovwidgets.layers.commands import SetEditTargetCommand
        adapter = _FakeAdapter(
            identifiers=["root.usda", "child.usda"],
            current_target="root.usda",
        )
        app = _make_app(adapter=adapter, root=_FakeLayerItem())
        _build_layer_menu_only(app)
        sub = _FakeMenuItem.registry["Set Authoring Layer"]
        _item(sub, "child.usda")["triggered_fn"]()
        assert len(app.undo_manager.pushed) == 1
        assert isinstance(app.undo_manager.pushed[0], SetEditTargetCommand)

    def test_remove_layer_routes_through_model(self) -> None:
        root = _FakeLayerItem(identifier="root.usda")
        child = _FakeLayerItem(identifier="child.usda", parent=root)
        app = _make_app(
            adapter=_FakeAdapter(
                sublayer_map={"root.usda": ["child.usda"]},
            ),
            selected=[child],
            root=root,
        )
        items = _build_layer_menu_only(app)
        _item(items, "Remove Layer")["triggered_fn"]()
        assert app._layer_window._model.remove_calls == [("root.usda", 0)]

    def test_reload_calls_model_request_reload(self) -> None:
        concrete = _FakeLayerItem()
        app = _make_app(adapter=_FakeAdapter(), root=concrete)
        items = _build_layer_menu_only(app)
        _item(items, "Reload Layer")["triggered_fn"]()
        assert app._layer_window._model.reload_calls == [concrete]


# ── Toast guards ───────────────────────────────────────────────────────


class TestToastGuards:
    def _reset_reporter(self) -> List[str]:
        """Install a message sink on ErrorReporter for the call path."""
        from ovwidgets.common.error_reporter import ErrorReporter
        bucket: List[str] = []

        def _sink(message: str, *_a: Any, **_kw: Any) -> None:
            bucket.append(message)

        ErrorReporter.show_error = _sink  # type: ignore[assignment]
        ErrorReporter.show_warning = _sink  # type: ignore[assignment]
        return bucket

    def test_click_without_stage_surfaces_toast(self) -> None:
        bucket = self._reset_reporter()
        import ovwidgets.app.menu_bar as mb
        app = _make_app(adapter=None)
        mb._on_save_layer(app)
        mb._on_save_all(app)
        mb._on_set_authoring(app, "root.usda")
        assert any("No stage" in m for m in bucket)


# ── Target resolution helper ───────────────────────────────────────────


class TestCurrentLayerTarget:
    def test_falls_back_to_root_without_selection(self) -> None:
        import ovwidgets.app.menu_bar as mb
        root = _FakeLayerItem(identifier="root.usda")
        app = _make_app(adapter=_FakeAdapter(), root=root, selected=[])
        assert mb._current_layer_target(app) is root

    def test_prefers_single_layer_selection_over_root(self) -> None:
        import ovwidgets.app.menu_bar as mb
        root = _FakeLayerItem(identifier="root.usda")
        child = _FakeLayerItem(identifier="child.usda")
        app = _make_app(
            adapter=_FakeAdapter(),
            root=root,
            selected=[child],
        )
        assert mb._current_layer_target(app) is child

    def test_falls_back_to_root_when_multi_selected(self) -> None:
        """Multi-select disambiguates to root so actions operate on a
        single definite target (mirrors footer logic)."""
        import ovwidgets.app.menu_bar as mb
        root = _FakeLayerItem(identifier="root.usda")
        app = _make_app(
            adapter=_FakeAdapter(),
            root=root,
            selected=[
                _FakeLayerItem(identifier="a.usda"),
                _FakeLayerItem(identifier="b.usda"),
            ],
        )
        assert mb._current_layer_target(app) is root

    def test_returns_none_without_layer_window(self) -> None:
        import ovwidgets.app.menu_bar as mb
        app = MagicMock()
        app._layer_window = None
        app._layer_adapter = None
        assert mb._current_layer_target(app) is None
