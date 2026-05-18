# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 29, Step 60 and Step 5.2: PropertyWindow filter, debounce,
and the :class:`UiDisplayGroup`-driven nested-frame build pipeline."""

from unittest.mock import MagicMock

import pytest
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.property.parts import UiDisplayGroup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_headless():
    """PropertyWindow with no live ui.Window.

    Step 6.2: also wires a default :class:`AttributesWidget` so the
    thin :meth:`PropertyWindow._compute_display_group` / ``_build_groups``
    delegates resolve.
    """
    from ovwidgets.property.widget.attributes_widget import AttributesWidget
    from ovwidgets.property.window import PropertyWindow
    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = None
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._widgets = []
    w._default_attributes = AttributesWidget(w)
    return w


def _make_mock_adapter(paths=None, attributes=None):
    from ovwidgets.common.testing.mock_property import MockPropertyAdapter
    return MockPropertyAdapter(paths=paths, attributes=attributes)


def _two_group_adapter():
    """Adapter with 3 attrs in 2 groups: Transform (Translate, Rotate) + Geometry (Subdivision)."""
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
    """Adapter whose attrs live under dot-separated nested groups.

    Structure (the tree that Step 5.2 must produce):

        Transform
        ├── Translate
        │   ├── X
        │   └── Y
        └── Rotate
            └── Z
        Geometry
        └── Mesh
            └── Subdivision Scheme

    Used by TestPropertyWindowNestedGroups below.
    """
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


# ---------------------------------------------------------------------------
# Import / structure tests
# ---------------------------------------------------------------------------


class TestPropertyWindowStep29Structure:
    def test_has_compute_display_group_method(self):
        """Step 5.2: ``_compute_groups`` was replaced by the
        tree-returning ``_compute_display_group``."""
        from ovwidgets.property.window import PropertyWindow
        assert callable(PropertyWindow._compute_display_group)

    def test_has_build_groups_method(self):
        from ovwidgets.property.window import PropertyWindow
        assert callable(PropertyWindow._build_groups)

    def test_has_build_group_children_method(self):
        """Step 5.2: recursive walker over the UiDisplayGroup tree."""
        from ovwidgets.property.window import PropertyWindow
        assert callable(PropertyWindow._build_group_children)

    def test_has_build_attribute_row_method(self):
        from ovwidgets.property.window import PropertyWindow
        assert callable(PropertyWindow._build_attribute_row)

    def test_build_attribute_row_delegates_to_widget_builder_table(self, monkeypatch):
        """Step 1.3: PropertyWindow._build_attribute_row goes through
        WidgetBuilderTable.build, not the legacy build_attribute_row."""
        from ovwidgets.property.builders import WidgetBuilderTable

        w = _make_headless()
        w._adapter = _two_group_adapter()
        prop = AttributeMetadata(
            name="xformOp:translate",
            display_name="Translate",
            type_name="double3",
            value_type=None,
            group="Transform",
        )
        calls = []

        def _spy(attr_name, metadata, adapter, **kwargs):
            calls.append((attr_name, metadata, adapter, kwargs))

        monkeypatch.setattr(WidgetBuilderTable, "build", classmethod(
            lambda cls, attr_name, metadata, adapter, **kw: _spy(
                attr_name, metadata, adapter, **kw
            )
        ))

        w._build_attribute_row(prop)

        assert len(calls) == 1
        attr_name, metadata, adapter, _ = calls[0]
        assert attr_name == "xformOp:translate"
        assert metadata is prop
        assert adapter is w._adapter

    def test_has_group_collapse_state_attr(self):
        w = _make_headless()
        assert hasattr(w, "_group_collapse_state")
        assert isinstance(w._group_collapse_state, dict)

    def test_mock_property_adapter_importable(self):
        from ovwidgets.common.testing.mock_property import MockPropertyAdapter
        assert MockPropertyAdapter is not None

    def test_mock_adapter_implements_property_adapter(self):
        from ovui_data_adapters.common import PropertyAdapter

        from ovwidgets.common.testing.mock_property import MockPropertyAdapter
        assert issubclass(MockPropertyAdapter, PropertyAdapter)


# ---------------------------------------------------------------------------
# Headless behaviour tests
# ---------------------------------------------------------------------------


class TestPropertyFilterHeadless:
    # 1. No adapter → rebuild doesn't crash, no groups built
    def test_no_adapter_no_crash(self):
        w = _make_headless()
        w._rebuild_content()  # content is None → early exit; no crash

    # 2. No selection → rebuild doesn't crash, no groups built
    def test_no_selection_no_crash(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._rebuild_content()  # selection is [] → early exit; no crash

    # 3. With adapter+selection → top-level groups built
    def test_with_adapter_and_selection_groups_built(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        root = w._compute_display_group()
        assert set(root.sub_groups.keys()) == {"Transform", "Geometry"}

    # 4. Filter hides non-matching properties
    def test_filter_hides_non_matching_properties(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "translate"
        root = w._compute_display_group()
        for sub in root.sub_groups.values():
            for prop in sub.props:
                assert "translate" in prop.display_name.lower()

    # 5. Filter hides entirely empty groups
    def test_filter_hides_empty_groups(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "translate"  # only matches Transform
        root = w._compute_display_group()
        assert "Geometry" not in root.sub_groups
        assert "Transform" in root.sub_groups

    # 6. Clear filter restores all properties
    def test_clear_filter_restores_all_properties(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "translate"
        filtered = w._compute_display_group()
        w._filter_text = ""
        all_groups = w._compute_display_group()
        assert len(all_groups.sub_groups) > len(filtered.sub_groups)
        assert len(all_groups.sub_groups) == 2

    # 7. Collapse state preserved across rebuild
    def test_collapse_state_preserved_across_rebuild(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._group_collapse_state["Transform"] = True
        root = w._compute_display_group()
        assert "Transform" in root.sub_groups
        # _compute_display_group reads adapter; it does not touch state dict
        assert w._group_collapse_state["Transform"] is True

    # 8. Collapse state preserved across filter clear
    def test_collapse_state_preserved_across_filter_clear(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._group_collapse_state["Transform"] = True
        w._filter_text = "translate"
        w._compute_display_group()
        assert w._group_collapse_state["Transform"] is True
        w._filter_text = ""
        w._compute_display_group()
        assert w._group_collapse_state["Transform"] is True


# ---------------------------------------------------------------------------
# MockPropertyAdapter unit tests
# ---------------------------------------------------------------------------


class TestMockPropertyAdapter:
    def test_empty_adapter_returns_no_attrs(self):
        a = _make_mock_adapter()
        assert a.get_attribute_names() == []

    def test_get_paths_returns_paths(self):
        a = _make_mock_adapter(paths=["/World/A", "/World/B"])
        assert a.get_paths() == ["/World/A", "/World/B"]

    def test_is_valid(self):
        a = _make_mock_adapter()
        assert a.is_valid() is True

    def test_get_scheme(self):
        a = _make_mock_adapter()
        assert a.get_scheme() == "mock"

    def test_get_attribute_names(self):
        attrs = {
            "foo": AttributeMetadata("foo", "Foo", "float", None, "General"),
        }
        a = _make_mock_adapter(attributes=attrs)
        assert "foo" in a.get_attribute_names()

    def test_get_attribute_metadata(self):
        meta = AttributeMetadata("foo", "Foo", "float", None, "General")
        a = _make_mock_adapter(attributes={"foo": meta})
        assert a.get_attribute_metadata("foo") is meta

    def test_set_and_get_value(self):
        a = _make_mock_adapter()
        a.set_value("foo", 42)
        assert a.get_value("foo") == 42

    def test_subscribe_returns_subscription(self):
        a = _make_mock_adapter()
        sub = a.subscribe_changes(lambda: None)
        assert sub is not None
        assert callable(sub.cancel)

    def test_fire_change_invokes_subscribers(self):
        a = _make_mock_adapter()
        calls = []
        sub = a.subscribe_changes(lambda: calls.append(1))  # noqa: F841
        a.fire_change()
        assert calls == [1]

    def test_cancel_stops_future_events(self):
        a = _make_mock_adapter()
        calls = []
        sub = a.subscribe_changes(lambda: calls.append(1))
        sub.cancel()
        a.fire_change()
        assert calls == []


# ---------------------------------------------------------------------------
# Debounce tests (Step 60)
# ---------------------------------------------------------------------------


def _make_model_mock(text):
    """Return a mock StringField model that yields the given text."""
    m = MagicMock()
    m.get_value_as_string.return_value = text
    return m


@pytest.fixture()
def reset_app():
    from ovwidgets.app.application import Application
    app = Application()
    yield app
    app.shutdown()


class TestPropertyWindowDebounce:
    """_on_filter_changed schedules via call_later with 150ms delay; rapid
    calls cancel the previous handle and start a fresh one."""

    def test_on_filter_changed_schedules_call_later(self, reset_app):
        app = reset_app
        w = _make_headless()
        w._on_filter_changed(_make_model_mock("tr"))
        assert w._pending_filter_handle is not None
        # The real Application must have the handle registered
        assert any(
            not h._cancelled for h in app._pending_callbacks
        )

    def test_debounce_delay_is_150ms(self, reset_app):
        import time
        w = _make_headless()
        before = time.monotonic()
        w._on_filter_changed(_make_model_mock("tr"))
        delay = w._pending_filter_handle._due_time - before
        assert abs(delay - 0.15) < 0.05

    def test_rapid_change_cancels_previous_timer(self, reset_app):
        w = _make_headless()
        w._on_filter_changed(_make_model_mock("tr"))
        first_handle = w._pending_filter_handle
        w._on_filter_changed(_make_model_mock("tra"))
        assert first_handle.is_cancelled

    def test_rapid_change_starts_new_timer(self, reset_app):
        w = _make_headless()
        w._on_filter_changed(_make_model_mock("tr"))
        first_handle = w._pending_filter_handle
        w._on_filter_changed(_make_model_mock("tra"))
        assert w._pending_filter_handle is not first_handle
        assert not w._pending_filter_handle.is_cancelled

    def test_multiple_rapid_changes_only_last_survives(self, reset_app):
        w = _make_headless()
        handles = []
        for text in ["t", "tr", "tra", "tran"]:
            w._on_filter_changed(_make_model_mock(text))
            handles.append(w._pending_filter_handle)
        for handle in handles[:-1]:
            assert handle.is_cancelled
        assert not handles[-1].is_cancelled

    def test_empty_text_also_debounces(self, reset_app):
        w = _make_headless()
        w._on_filter_changed(_make_model_mock(""))
        assert w._pending_filter_handle is not None

    def test_timer_fires_applies_filter_text(self, reset_app):
        app = reset_app
        w = _make_headless()
        w._on_filter_changed(_make_model_mock("translate"))
        w._pending_filter_handle._due_time = 0  # force past-due
        app._on_frame_update(0.0)
        assert w._filter_text == "translate"

    def test_timer_fires_clears_pending_handle(self, reset_app):
        app = reset_app
        w = _make_headless()
        w._on_filter_changed(_make_model_mock("translate"))
        w._pending_filter_handle._due_time = 0
        app._on_frame_update(0.0)
        assert w._pending_filter_handle is None

    def test_cancelled_timer_does_not_apply_filter(self, reset_app):
        app = reset_app
        w = _make_headless()
        w._on_filter_changed(_make_model_mock("translate"))
        handle = w._pending_filter_handle
        handle.cancel()
        handle._due_time = 0  # would fire if not cancelled
        app._on_frame_update(0.0)
        assert w._filter_text == ""  # _apply_filter was NOT called

    def test_apply_filter_updates_filter_text(self):
        w = _make_headless()
        w._apply_filter("translate")
        assert w._filter_text == "translate"

    def test_apply_filter_clears_pending_handle(self):
        w = _make_headless()
        mock_handle = MagicMock()
        w._pending_filter_handle = mock_handle
        w._apply_filter("foo")
        assert w._pending_filter_handle is None

    def test_apply_filter_no_crash_with_no_content(self):
        w = _make_headless()
        w._apply_filter("foo")  # _content is None → _rebuild_content exits early

    def test_filter_case_insensitive_uppercase_query(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "TRANSLATE"
        root = w._compute_display_group()
        all_props = [p for sub in root.sub_groups.values() for p in sub.props]
        assert any("Translate" in p.display_name for p in all_props)

    def test_filter_case_insensitive_mixed_case_query(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "TrAnSlAtE"
        root = w._compute_display_group()
        all_props = [p for sub in root.sub_groups.values() for p in sub.props]
        assert any("Translate" in p.display_name for p in all_props)

    def test_filter_no_properties_no_crash(self):
        w = _make_headless()
        w._filter_text = "foo"
        w._rebuild_content()  # no adapter, content=None → exits early

    def test_clear_filter_shows_all_groups(self):
        w = _make_headless()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "nonexistent_xyz"
        root = w._compute_display_group()
        assert len(root.sub_groups) == 0 and not root.props
        w._filter_text = ""
        assert len(w._compute_display_group().sub_groups) == 2


# ---------------------------------------------------------------------------
# Step 5.2 — nested-group tree construction (dot-separated group paths)
# ---------------------------------------------------------------------------


class TestPropertyWindowNestedGroups:
    """Property Window Step 5.2: ``_compute_display_group`` must split
    ``AttributeMetadata.group`` on ``"."`` and build a nested
    :class:`UiDisplayGroup` tree so the ``_build_groups`` walker can
    emit two- and three-level nested ``ui.CollapsableFrame`` hierarchies.

    Together with the :class:`TestPropertyWindowNestedBuild` class below
    these tests pin the Step 5.2 done signals from
    ``the property inspector implementation``: (1) the tree built from a dot-path lands under
    nested groups, (2) root-only props live directly on the root,
    (3) ``_build_groups`` produces an outer frame whose content holds an
    inner frame, (4) collapse state is keyed by full dot-joined path so
    identically-named sub-groups under different parents do not
    collide.
    """

    def test_root_returned_is_ui_display_group(self):
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        root = w._compute_display_group()
        assert isinstance(root, UiDisplayGroup)
        assert root.name == ""

    def test_top_level_groups_are_transform_and_geometry(self):
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        root = w._compute_display_group()
        assert set(root.sub_groups.keys()) == {"Transform", "Geometry"}

    def test_transform_has_nested_translate_and_rotate(self):
        """``"Transform.Translate"`` and ``"Transform.Rotate"`` should
        nest as two sub-groups of a single ``Transform`` frame — not
        two parallel top-level ``Transform.Translate`` /
        ``Transform.Rotate`` siblings."""
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        root = w._compute_display_group()
        transform = root.sub_groups["Transform"]
        assert set(transform.sub_groups.keys()) == {"Translate", "Rotate"}
        assert transform.props == []  # no direct props at this level

    def test_translate_leaf_contains_both_props_in_order(self):
        """Multiple props in ``"Transform.Translate"`` share one
        ``Translate`` leaf node; insertion order is preserved."""
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        root = w._compute_display_group()
        translate = root.sub_groups["Transform"].sub_groups["Translate"]
        assert [p.display_name for p in translate.props] == ["X", "Y"]
        assert translate.sub_groups == {}

    def test_root_level_prop_with_empty_group(self):
        """An attribute with ``group == ""`` must land on the root
        node's ``props`` list, not under a wrapper sub-group."""
        attrs = {
            "orphan": AttributeMetadata(
                name="orphan",
                display_name="Orphan",
                type_name="float",
                value_type=None,
                group="",
            ),
        }
        w = _make_headless()
        w._adapter = _make_mock_adapter(paths=["/World/X"], attributes=attrs)
        w._selection = ["/World/X"]
        root = w._compute_display_group()
        assert [p.name for p in root.props] == ["orphan"]
        assert root.sub_groups == {}

    def test_filter_drops_empty_nested_groups(self):
        """Filtering out every prop of a deep leaf must also drop the
        enclosing sub-groups so Step 5.2's ``_build_groups`` doesn't
        render an empty chain of nested headers."""
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        w._filter_text = "subdivision"
        root = w._compute_display_group()
        assert "Transform" not in root.sub_groups
        # Only the Geometry/Mesh path survives
        assert root.sub_groups["Geometry"].sub_groups["Mesh"].props[0].display_name == "Subdivision Scheme"

    def test_three_level_dot_path_nests_three_frames(self):
        """A prop with ``group == "A.B.C"`` must land at
        ``root.sub_groups["A"].sub_groups["B"].sub_groups["C"].props[0]``."""
        attrs = {
            "deep": AttributeMetadata(
                name="deep",
                display_name="Deep",
                type_name="float",
                value_type=None,
                group="A.B.C",
            ),
        }
        w = _make_headless()
        w._adapter = _make_mock_adapter(paths=["/World/X"], attributes=attrs)
        w._selection = ["/World/X"]
        root = w._compute_display_group()
        assert "A" in root.sub_groups
        assert "B" in root.sub_groups["A"].sub_groups
        assert "C" in root.sub_groups["A"].sub_groups["B"].sub_groups
        leaf = root.sub_groups["A"].sub_groups["B"].sub_groups["C"]
        assert leaf.props[0].name == "deep"


# ---------------------------------------------------------------------------
# Step 5.2 — recursive frame build (nested CollapsableFrame construction)
# ---------------------------------------------------------------------------


class _FakeGroupWidget:
    """Recording double for :class:`AttributeGroupWidget`.

    ``PropertyWindow._build_group_children`` instantiates one
    :class:`AttributeGroupWidget` per :class:`UiDisplayGroup` child and
    writes its rows inside ``group.content`` via a ``with`` block. The
    fake captures the construction arguments plus the
    ``on_collapse_change`` callback so tests can assert on the full
    construction order (outer ``Transform`` before inner ``Translate``,
    siblings in insertion order) and can fire the callback to simulate
    a user collapsing a specific frame.

    ``content`` is a tiny object whose ``__enter__`` / ``__exit__``
    no-op — that's all
    ``with grp.content:`` needs for the recursion to proceed.
    """

    calls: list = []  # class-level list mutated by every construction

    def __init__(
        self,
        name,
        initially_collapsed=False,
        on_collapse_change=None,
        on_context_menu=None,
        level=0,
    ):
        self.name = name
        self.initially_collapsed = initially_collapsed
        self.on_collapse_change = on_collapse_change
        # Step 5.3: accept (and record) the group-header right-click
        # callback so PropertyWindow's wiring keeps working under this
        # recording double. None is the pre-5.3 default; a real callable
        # is passed by ``_build_group_children``.
        self.on_context_menu = on_context_menu
        # Step 8.2: accept (and record) the ``level`` kwarg so the
        # ``_build_group_children`` recursion keeps working under this
        # recording double. ``level=0`` at the root; incremented per
        # recursion — the nested-group styling variant activates at 1.
        self.level = level
        self.content = self  # ``with grp.content:`` re-enters this instance
        _FakeGroupWidget.calls.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture()
def fake_group_widget(monkeypatch):
    """Patch :class:`AttributeGroupWidget` with
    :class:`_FakeGroupWidget`. Resets the call log before each test."""
    import ovwidgets.property.group_widget as gw_mod
    import ovwidgets.property.window as pw_mod
    _FakeGroupWidget.calls = []
    monkeypatch.setattr(gw_mod, "AttributeGroupWidget", _FakeGroupWidget)
    # ``_build_group_children`` imports lazily inside the method body;
    # patch the module attribute so the import resolves to the fake.
    monkeypatch.setattr(pw_mod, "AttributeGroupWidget", _FakeGroupWidget, raising=False)
    return _FakeGroupWidget


class TestPropertyWindowNestedBuild:
    """Exercises the :class:`ui.CollapsableFrame` recursion in
    :meth:`PropertyWindow._build_groups` and
    :meth:`PropertyWindow._build_group_children`. These are the Step 5.2
    done-signal tests: a two-level dot path must emit an outer frame
    whose content holds an inner frame, collapse state must key by full
    dot-joined path, and the recursive ``_build_group_children``
    dispatch must cover both :class:`UiDisplayGroup` and
    :class:`AttributeMetadata` children.

    The tests replace :class:`AttributeGroupWidget` with a recording
    fake (see :class:`_FakeGroupWidget`) so they don't need an
    initialised ``omni.ui`` root — construction order and
    ``on_collapse_change`` callback wiring are sufficient to pin the
    observable behaviour the plan calls out.
    """

    def test_build_groups_emits_nested_frames(self, fake_group_widget):
        """Two-level dot path → the group widget constructor is called
        for ``Transform`` *before* ``Translate``, and again for
        ``Translate`` *before* ``Rotate`` at the same depth."""
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        w._build_attribute_row = lambda prop: None  # type: ignore[method-assign]

        w._build_groups()

        names = [g.name for g in fake_group_widget.calls]
        # Five frames total: Transform, Translate, Rotate, Geometry, Mesh.
        assert set(names) == {"Transform", "Translate", "Rotate", "Geometry", "Mesh"}
        # Outer frame comes before its inner; Translate outruns Rotate (insertion order).
        assert names.index("Transform") < names.index("Translate")
        assert names.index("Transform") < names.index("Rotate")
        assert names.index("Translate") < names.index("Rotate")
        assert names.index("Geometry") < names.index("Mesh")

    def test_collapse_state_keyed_by_full_path(self, fake_group_widget):
        """Simulating a collapse on the inner ``Translate`` frame must
        write the key ``"Transform.Translate"`` (dot-joined path), not
        the leaf name."""
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        w._build_attribute_row = lambda prop: None  # type: ignore[method-assign]

        w._build_groups()

        translate = next(g for g in fake_group_widget.calls if g.name == "Translate")
        translate.on_collapse_change(True)

        assert w._group_collapse_state.get("Transform.Translate") is True
        assert "Translate" not in w._group_collapse_state

    def test_sibling_sub_groups_of_same_name_dont_collide(self, fake_group_widget):
        """Two different parents each containing a sub-group named
        ``"X"`` must occupy separate entries in the collapse-state
        dict — keyed by ``"Transform.X"`` vs ``"Material.X"``."""
        attrs = {
            "a": AttributeMetadata(
                name="a", display_name="A", type_name="float",
                value_type=None, group="Transform.X",
            ),
            "b": AttributeMetadata(
                name="b", display_name="B", type_name="float",
                value_type=None, group="Material.X",
            ),
        }
        w = _make_headless()
        w._adapter = _make_mock_adapter(paths=["/World/Sphere"], attributes=attrs)
        w._selection = ["/World/Sphere"]
        w._build_attribute_row = lambda prop: None  # type: ignore[method-assign]

        w._build_groups()

        # Two inner ``X`` frames exist (same name, different parents).
        x_frames = [g for g in fake_group_widget.calls if g.name == "X"]
        assert len(x_frames) == 2
        # Fire collapse callbacks on each — they carry *different* keys
        # in their closure (via the ``p=child_path`` default argument
        # pinned at build-time).
        x_frames[0].on_collapse_change(True)
        x_frames[1].on_collapse_change(False)

        assert w._group_collapse_state.get("Transform.X") is True
        assert w._group_collapse_state.get("Material.X") is False

    def test_initial_collapse_state_read_from_dict_by_full_path(self, fake_group_widget):
        """Seeding ``_group_collapse_state["Transform.Translate"] =
        True`` must make the ``Translate`` sub-frame construct with
        ``initially_collapsed=True`` — the leaf-name key does not
        leak through."""
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        w._build_attribute_row = lambda prop: None  # type: ignore[method-assign]
        w._group_collapse_state["Transform.Translate"] = True
        # A leaf-only entry must *not* affect nested Translate —
        # pinning the by-path key semantics.
        w._group_collapse_state["Translate"] = False

        w._build_groups()

        translate = next(g for g in fake_group_widget.calls if g.name == "Translate")
        assert translate.initially_collapsed is True

    def test_attribute_rows_rendered_in_innermost_frame(self, fake_group_widget):
        """Every :class:`AttributeMetadata` in the tree must flow
        through :meth:`_build_attribute_row`. The nested-frame walker
        must not accidentally swallow leaf props.

        Step 6.2: the leaf-row dispatch moved onto
        :class:`AttributesWidget`, so the intercept now patches the
        widget instance rather than the window — the window's delegate
        method forwards unconditionally and never reads its own
        ``_build_attribute_row``.
        """
        w = _make_headless()
        w._adapter = _nested_group_adapter()
        w._selection = ["/World/Sphere"]
        seen = []
        w._default_attributes._build_attribute_row = lambda prop: seen.append(prop.name)  # type: ignore[method-assign]

        w._build_groups()

        assert set(seen) == {
            "transform:translate:x",
            "transform:translate:y",
            "transform:rotate:z",
            "mesh:subdivisionScheme",
        }
