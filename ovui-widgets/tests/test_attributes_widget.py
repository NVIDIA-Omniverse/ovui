# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 6.2 — :class:`AttributesWidget` extraction.

Covers:

* :class:`ovui_widgets.property.widget.AttributesWidget` is a concrete
  :class:`PropertyWidget` that can be instantiated with a window
  back-reference.
* :meth:`AttributesWidget.on_new_payload` returns ``True`` for every
  payload (this is the catch-all widget).
* :meth:`AttributesWidget.build_items` emits the same group / row tree
  that :class:`PropertyWindow` used to build inline via
  :meth:`_build_groups` — pinned by the `_FakeGroupWidget` double used
  across the Phase 5 filter tests.
* :meth:`AttributesWidget.destroy` clears the window's active context
  menu and drops the back-reference.
* :class:`PropertyWindow` registers exactly one default
  :class:`AttributesWidget` in :meth:`__init__`, exposed at
  :attr:`PropertyWindow._default_attributes`, and that widget is the
  target of the thin delegate methods
  :meth:`PropertyWindow._compute_display_group`,
  :meth:`PropertyWindow._build_groups`, etc.
"""

from typing import Any, List

import pytest
from ovui_data_adapters.common import AttributeMetadata

from ovui_widgets.property.parts import UiDisplayGroup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_adapter(paths=None, attributes=None):
    from ovui_widgets.common.testing.mock_property import MockPropertyAdapter
    return MockPropertyAdapter(paths=paths, attributes=attributes)


def _two_group_adapter():
    """Adapter with 3 attrs in 2 groups (same fixture used in test_property_filter)."""
    attrs = {
        "xformOp:translate": AttributeMetadata(
            name="xformOp:translate",
            display_name="Translate",
            type_name="double3",
            value_type=None,
            group="Transform",
        ),
        "xformOp:rotate": AttributeMetadata(
            name="xformOp:rotate",
            display_name="Rotate",
            type_name="double3",
            value_type=None,
            group="Transform",
        ),
        "mesh:subdivisionScheme": AttributeMetadata(
            name="mesh:subdivisionScheme",
            display_name="Subdivision Scheme",
            type_name="token",
            value_type=None,
            group="Geometry",
        ),
    }
    return _make_mock_adapter(paths=["/World/Sphere"], attributes=attrs)


def _nested_group_adapter():
    """Adapter whose attrs live under dot-separated nested groups."""
    attrs = {
        "transform:translate:x": AttributeMetadata(
            name="transform:translate:x",
            display_name="X",
            type_name="float",
            value_type=None,
            group="Transform.Translate",
        ),
        "transform:translate:y": AttributeMetadata(
            name="transform:translate:y",
            display_name="Y",
            type_name="float",
            value_type=None,
            group="Transform.Translate",
        ),
        "transform:rotate:z": AttributeMetadata(
            name="transform:rotate:z",
            display_name="Z",
            type_name="float",
            value_type=None,
            group="Transform.Rotate",
        ),
        "mesh:subdivisionScheme": AttributeMetadata(
            name="mesh:subdivisionScheme",
            display_name="Subdivision Scheme",
            type_name="token",
            value_type=None,
            group="Geometry.Mesh",
        ),
    }
    return _make_mock_adapter(paths=["/World/Sphere"], attributes=attrs)


def _make_headless_window():
    """PropertyWindow with bypassed ``__init__`` + one default widget.

    Mirrors the headless helper used across the Phase 5 tests, plus the
    Step 6.2 ``_default_attributes`` hookup. Tests can then call the
    widget directly as ``w._default_attributes`` and/or through the
    window's delegate surface.
    """
    from ovui_widgets.property.widget.attributes_widget import AttributesWidget
    from ovui_widgets.property.window import PropertyWindow
    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = None
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._bus_sub = None
    w._stage_adapter = None
    w._stage_change_sub = None
    w._undo_manager_ref = None
    w._widgets = []
    w._default_attributes = AttributesWidget(w)
    # Step 7.3: ``_rebuild_content`` guards on these two fields; bypass-
    # ``__init__`` tests that drive the rebuild directly must seed them
    # as the no-op sentinels so the preserver branch short-circuits.
    w._scroll_frame = None
    w._scroll_preserver = None
    return w


class _FakeGroupWidget:
    """Recording double for :class:`AttributeGroupWidget`.

    Matches the doubles used in :mod:`tests.test_property_filter` and
    :mod:`tests.test_group_context_menu` so this test module can drive
    ``AttributesWidget._build_groups`` without an initialised
    ``omni.ui`` root.
    """

    calls: List["_FakeGroupWidget"] = []

    def __init__(
        self,
        name: str,
        initially_collapsed: bool = False,
        on_collapse_change: Any = None,
        on_context_menu: Any = None,
        level: int = 0,
    ) -> None:
        self.name = name
        self.initially_collapsed = initially_collapsed
        self.on_collapse_change = on_collapse_change
        self.on_context_menu = on_context_menu
        self.level = level
        self.content = self
        _FakeGroupWidget.calls.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture()
def fake_group_widget(monkeypatch):
    """Patch :class:`AttributeGroupWidget` at its source module.

    The lazy ``from ovui_widgets.property.group_widget import AttributeGroupWidget``
    inside :meth:`AttributesWidget._build_group_children` re-executes on
    every call, so patching ``gw_mod`` is sufficient for the fake to
    intercept construction.
    """
    import ovui_widgets.property.group_widget as gw_mod
    _FakeGroupWidget.calls = []
    monkeypatch.setattr(gw_mod, "AttributeGroupWidget", _FakeGroupWidget)
    return _FakeGroupWidget


# ---------------------------------------------------------------------------
# Module / import shape
# ---------------------------------------------------------------------------


class TestAttributesWidgetImportShape:
    def test_attributes_widget_importable_from_subpackage(self):
        from ovui_widgets.property.widget import AttributesWidget
        assert AttributesWidget is not None

    def test_attributes_widget_importable_from_direct_module(self):
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        assert AttributesWidget is not None

    def test_re_export_identity(self):
        """Both import paths must resolve to the same class object."""
        from ovui_widgets.property.widget import AttributesWidget as A
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget as B
        assert A is B

    def test_in_widget_subpackage_all(self):
        import ovui_widgets.property.widget as w_mod
        assert "AttributesWidget" in w_mod.__all__


# ---------------------------------------------------------------------------
# PropertyWidget contract
# ---------------------------------------------------------------------------


class TestAttributesWidgetIsPropertyWidget:
    def test_is_property_widget_subclass(self):
        from ovui_widgets.property.widget import AttributesWidget, PropertyWidget
        assert issubclass(AttributesWidget, PropertyWidget)

    def test_instantiates_with_window_arg(self):
        """Constructor takes a :class:`PropertyWindow` back-reference."""
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        aw = AttributesWidget(w)
        assert aw._window is w

    def test_has_on_new_payload(self):
        from ovui_widgets.property.widget import AttributesWidget
        assert callable(AttributesWidget.on_new_payload)

    def test_has_build_items(self):
        from ovui_widgets.property.widget import AttributesWidget
        assert callable(AttributesWidget.build_items)

    def test_has_destroy(self):
        from ovui_widgets.property.widget import AttributesWidget
        assert callable(AttributesWidget.destroy)


# ---------------------------------------------------------------------------
# on_new_payload — always True
# ---------------------------------------------------------------------------


class TestOnNewPayload:
    def test_returns_true_for_non_empty_payload(self):
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import AttributesWidget
        aw = AttributesWidget(_make_headless_window())
        assert aw.on_new_payload(PropertyPayload(paths=["/World/A"])) is True

    def test_returns_true_for_empty_payload(self):
        """Step 6.2: catch-all widget shows even for empty selection.

        The window's ``_rebuild_content`` gates on ``self._selection``
        being non-empty, so ``on_new_payload`` of the attributes widget
        being ``True`` for an empty payload just means the widget would
        *choose* to draw if the window asked — but the window doesn't
        ask when there's no selection.
        """
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import AttributesWidget
        aw = AttributesWidget(_make_headless_window())
        assert aw.on_new_payload(PropertyPayload(paths=[])) is True

    def test_returns_true_for_non_default_scheme(self):
        """Step 6.2 is scheme-agnostic — accepts every scheme until Step
        6.5 introduces :class:`PropertySchemeRegistry`."""
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import AttributesWidget
        aw = AttributesWidget(_make_headless_window())
        assert aw.on_new_payload(
            PropertyPayload(paths=["/World/A"], scheme="light")
        ) is True


# ---------------------------------------------------------------------------
# destroy — clears active menu and back-ref
# ---------------------------------------------------------------------------


class TestDestroy:
    def test_destroy_clears_active_context_menu_on_window(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._active_context_menu = object()
        aw = AttributesWidget(w)
        aw.destroy()
        assert w._active_context_menu is None

    def test_destroy_drops_window_back_reference(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        aw = AttributesWidget(w)
        aw.destroy()
        assert aw._window is None

    def test_destroy_is_idempotent(self):
        """Calling ``destroy`` twice must not crash even after back-ref
        is already None."""
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        aw = AttributesWidget(w)
        aw.destroy()
        aw.destroy()  # must not raise


# ---------------------------------------------------------------------------
# _compute_display_group — same behaviour as pre-6.2 PropertyWindow
# ---------------------------------------------------------------------------


class TestComputeDisplayGroup:
    def test_no_window_returns_empty_root(self):
        """Defensive: bare widget with no window back-ref still yields
        a valid empty root, not a crash."""
        from ovui_widgets.property.widget import AttributesWidget
        aw = AttributesWidget.__new__(AttributesWidget)
        aw._window = None
        root = aw._compute_display_group()
        assert isinstance(root, UiDisplayGroup)
        assert root.name == ""
        assert root.sub_groups == {}
        assert root.props == []

    def test_no_adapter_returns_empty_root(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()  # _adapter is None
        aw = AttributesWidget(w)
        root = aw._compute_display_group()
        assert root.sub_groups == {}
        assert root.props == []

    def test_top_level_groups_match_adapter(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        root = aw._compute_display_group()
        assert set(root.sub_groups.keys()) == {"Transform", "Geometry"}

    def test_filter_hides_non_matching(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "translate"
        aw = AttributesWidget(w)
        root = aw._compute_display_group()
        assert "Geometry" not in root.sub_groups
        assert "Transform" in root.sub_groups

    def test_nested_dot_path(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        root = aw._compute_display_group()
        assert "Transform" in root.sub_groups
        transform = root.sub_groups["Transform"]
        assert set(transform.sub_groups.keys()) == {"Translate", "Rotate"}

    def test_case_insensitive_filter(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "TRANSLATE"
        aw = AttributesWidget(w)
        root = aw._compute_display_group()
        transforms = root.sub_groups.get("Transform")
        assert transforms is not None
        assert any("Translate" in p.display_name for p in transforms.props)


# ---------------------------------------------------------------------------
# _build_groups / _build_group_children — render the tree
# ---------------------------------------------------------------------------


class TestBuildGroups:
    def test_builds_flat_groups_in_insertion_order(self, fake_group_widget):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        names = [g.name for g in fake_group_widget.calls]
        assert names == ["Transform", "Geometry"]

    def test_builds_nested_groups_outer_before_inner(self, fake_group_widget):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        names = [g.name for g in fake_group_widget.calls]
        assert set(names) == {"Transform", "Translate", "Rotate", "Geometry", "Mesh"}
        assert names.index("Transform") < names.index("Translate")
        assert names.index("Transform") < names.index("Rotate")
        assert names.index("Geometry") < names.index("Mesh")

    def test_collapse_state_keyed_by_full_path(self, fake_group_widget):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        translate = next(
            g for g in fake_group_widget.calls if g.name == "Translate"
        )
        translate.on_collapse_change(True)
        assert w._group_collapse_state.get("Transform.Translate") is True

    def test_initial_collapse_state_read_from_window(self, fake_group_widget):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        w._group_collapse_state["Transform.Translate"] = True
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        translate = next(
            g for g in fake_group_widget.calls if g.name == "Translate"
        )
        assert translate.initially_collapsed is True

    def test_every_group_gets_context_menu_callback(self, fake_group_widget):
        """Step 5.3 wiring survives the Step 6.2 refactor — every frame
        still receives a callable ``on_context_menu``."""
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        assert len(fake_group_widget.calls) > 0
        for g in fake_group_widget.calls:
            assert callable(g.on_context_menu)

    def test_attribute_rows_rendered_for_leaf_props(self, fake_group_widget):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        seen: list = []
        aw._build_attribute_row = lambda prop: seen.append(prop.name)  # type: ignore[method-assign]
        aw._build_groups()
        assert set(seen) == {
            "transform:translate:x",
            "transform:translate:y",
            "transform:rotate:z",
            "mesh:subdivisionScheme",
        }


# ---------------------------------------------------------------------------
# Step 8.2 — ``level`` kwarg threaded through ``_build_group_children``
# ---------------------------------------------------------------------------


class TestBuildGroupsLevel:
    """Step 8.2 — ``AttributesWidget._build_group_children`` threads
    ``level`` so nested groups paint with the ``Property.GroupFrame::inner``
    variant. Top-level frames are ``level=0``; each recursion increments.
    """

    def test_top_level_groups_are_level_zero(self, fake_group_widget):
        """Flat adapter → every group is at the root → ``level == 0``."""
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        assert [g.level for g in fake_group_widget.calls] == [0, 0]

    def test_nested_groups_get_incrementing_level(self, fake_group_widget):
        """Nested adapter → outer groups (Transform, Geometry) are
        ``level=0``; their sub-groups (Translate, Rotate, Mesh) are
        ``level=1``. This is the visual-hierarchy handoff: ``level=0``
        keeps the base ``Property.GroupFrame`` styling; ``level >= 1``
        activates the ``::inner`` variant (dimmer title, hover brightens).
        """
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        aw = AttributesWidget(w)
        aw._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        aw._build_groups()
        levels_by_name = {g.name: g.level for g in fake_group_widget.calls}
        assert levels_by_name["Transform"] == 0
        assert levels_by_name["Geometry"] == 0
        assert levels_by_name["Translate"] == 1
        assert levels_by_name["Rotate"] == 1
        assert levels_by_name["Mesh"] == 1


# ---------------------------------------------------------------------------
# _show_group_context_menu — stores menu on window
# ---------------------------------------------------------------------------


class TestShowGroupContextMenu:
    def test_no_op_when_window_is_none(self):
        from ovui_widgets.property.widget import AttributesWidget
        aw = AttributesWidget.__new__(AttributesWidget)
        aw._window = None
        group = UiDisplayGroup(name="Transform")
        aw._show_group_context_menu(group, 0.0, 0.0)  # must not raise

    def test_no_op_when_adapter_is_none(self, monkeypatch):
        from ovui_widgets.property.widget import AttributesWidget
        called: list = []
        monkeypatch.setattr(
            "ovui_widgets.property.parts.group_context_menu.show_group_context_menu",
            lambda *a, **kw: called.append(a) or object(),
        )
        w = _make_headless_window()  # _adapter is None
        aw = AttributesWidget(w)
        group = UiDisplayGroup(name="Transform")
        aw._show_group_context_menu(group, 1.0, 2.0)
        assert called == []
        assert w._active_context_menu is None

    def test_stores_menu_handle_on_window(self, monkeypatch):
        from ovui_widgets.property.widget import AttributesWidget
        sentinel = object()
        monkeypatch.setattr(
            "ovui_widgets.property.parts.group_context_menu.show_group_context_menu",
            lambda *a, **kw: sentinel,
        )
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        aw = AttributesWidget(w)
        group = UiDisplayGroup(name="Transform")
        aw._show_group_context_menu(group, 0.0, 0.0)
        assert w._active_context_menu is sentinel


# ---------------------------------------------------------------------------
# _build_attribute_row — dispatches to WidgetBuilderTable
# ---------------------------------------------------------------------------


class TestBuildAttributeRow:
    def test_no_op_when_window_is_none(self):
        from ovui_widgets.property.widget import AttributesWidget
        aw = AttributesWidget.__new__(AttributesWidget)
        aw._window = None
        meta = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=None, group="",
        )
        aw._build_attribute_row(meta)  # must not raise

    def test_no_op_when_adapter_is_none(self):
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        aw = AttributesWidget(w)
        meta = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=None, group="",
        )
        aw._build_attribute_row(meta)  # must not raise

    def test_delegates_to_widget_builder_table(self, monkeypatch):
        from ovui_widgets.property.builders import WidgetBuilderTable
        from ovui_widgets.property.widget import AttributesWidget
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        aw = AttributesWidget(w)
        calls: list = []
        monkeypatch.setattr(
            WidgetBuilderTable, "build",
            classmethod(
                lambda cls, attr_name, metadata, adapter, **kw: calls.append(
                    (attr_name, metadata, adapter)
                )
            ),
        )
        meta = AttributeMetadata(
            name="xformOp:translate", display_name="Translate",
            type_name="double3", value_type=None, group="Transform",
        )
        aw._build_attribute_row(meta)
        assert len(calls) == 1
        attr_name, metadata, adapter = calls[0]
        assert attr_name == "xformOp:translate"
        assert metadata is meta
        assert adapter is w._adapter


# ---------------------------------------------------------------------------
# PropertyWindow <-> default AttributesWidget wiring
# ---------------------------------------------------------------------------


def _can_create_window() -> bool:
    try:
        import omni.ui as ui
        w = ui.Window("__probe__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE, reason="ui.Window creation not available"
)


@_skip_no_window
class TestPropertyWindowRegistersDefault:
    def test_init_keeps_thin_delegate_attributes_widget(self):
        """Step 6.5: :class:`PropertyWindow` still owns one
        :class:`AttributesWidget` as its thin-delegate forwarder, but
        the widget is *not* added to :attr:`_widgets` any more — the
        process-wide :class:`PropertySchemeRegistry` owns rebuild
        registration (see :class:`TestPropertyWindowRebuildDrivesDefaultWidget`).
        """
        from ovui_widgets.property.widget import AttributesWidget
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        try:
            assert w._default_attributes is not None
            assert isinstance(w._default_attributes, AttributesWidget)
            assert w._widgets == []
        finally:
            w.destroy()

    def test_default_widget_window_backref_is_owner(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        try:
            assert w._default_attributes._window is w
        finally:
            w.destroy()

    def test_destroy_clears_default_widget(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        w.destroy()
        assert w._default_attributes is None


class TestPropertyWindowDelegates:
    """The five moved methods remain on :class:`PropertyWindow` as thin
    one-line delegates to the default :class:`AttributesWidget`. These
    tests pin the delegation, not the underlying behaviour (which is
    covered in :class:`TestBuildGroups` etc. above)."""

    def test_compute_display_group_delegates(self, monkeypatch):
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        sentinel = UiDisplayGroup(name="sentinel")
        monkeypatch.setattr(
            AttributesWidget, "_compute_display_group",
            lambda self: sentinel,
        )
        w = _make_headless_window()
        assert w._compute_display_group() is sentinel

    def test_build_groups_delegates(self, monkeypatch):
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        called: list = []
        monkeypatch.setattr(
            AttributesWidget, "_build_groups",
            lambda self: called.append(1),
        )
        w = _make_headless_window()
        w._build_groups()
        assert called == [1]

    def test_build_group_children_delegates(self, monkeypatch):
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        called: list = []
        monkeypatch.setattr(
            AttributesWidget, "_build_group_children",
            lambda self, group, path: called.append((group.name, path)),
        )
        w = _make_headless_window()
        group = UiDisplayGroup(name="Transform")
        w._build_group_children(group, "")
        assert called == [("Transform", "")]

    def test_build_attribute_row_delegates(self, monkeypatch):
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        called: list = []
        monkeypatch.setattr(
            AttributesWidget, "_build_attribute_row",
            lambda self, prop: called.append(prop.name),
        )
        w = _make_headless_window()
        meta = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=None, group="",
        )
        w._build_attribute_row(meta)
        assert called == ["x"]

    def test_show_group_context_menu_delegates(self, monkeypatch):
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        called: list = []
        monkeypatch.setattr(
            AttributesWidget, "_show_group_context_menu",
            lambda self, group, x, y: called.append((group.name, x, y)),
        )
        w = _make_headless_window()
        group = UiDisplayGroup(name="Transform")
        w._show_group_context_menu(group, 5.0, 7.0)
        assert called == [("Transform", 5.0, 7.0)]

    def test_delegates_are_no_op_when_default_missing(self):
        """Without the default widget attached (defensive branch) the
        delegate methods must not crash — they just silently no-op."""
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow.__new__(PropertyWindow)
        w._default_attributes = None
        # Methods returning None / empty root must not raise.
        root = w._compute_display_group()
        assert isinstance(root, UiDisplayGroup)
        w._build_groups()
        w._build_group_children(UiDisplayGroup(name="x"), "")
        meta = AttributeMetadata(
            name="n", display_name="N", type_name="float",
            value_type=None, group="",
        )
        w._build_attribute_row(meta)
        w._show_group_context_menu(UiDisplayGroup(name="x"), 0.0, 0.0)


# ---------------------------------------------------------------------------
# End-to-end: PropertyWindow._rebuild_content drives the default widget
# ---------------------------------------------------------------------------


class TestPropertyWindowRebuildDrivesDefaultWidget:
    def test_rebuild_content_calls_default_widget_build_items(self, monkeypatch):
        """Step 6.5: ``_rebuild_content`` drives the default
        :class:`AttributesWidget` through
        :class:`PropertySchemeRegistry`'s module-import registration,
        not through :attr:`PropertyWindow._widgets` — so the fresh
        registry-produced instance's :meth:`build_items` runs exactly
        once on every rebuild."""
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        calls: list = []
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: calls.append(1),
        )

        class _FakeVStack:
            def clear(self):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert calls == [1]

    def test_rebuild_content_no_op_without_selection(self, monkeypatch):
        """No selection → :meth:`_rebuild_content` early-returns before
        it hits the registry, so neither the registry-provided
        :class:`AttributesWidget` nor any locally-registered widget
        builds."""
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        builds: list = []
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: builds.append(1),
        )

        class _FakeVStack:
            def clear(self):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = []
        w._content = _FakeVStack()
        w._rebuild_content()
        assert builds == []
