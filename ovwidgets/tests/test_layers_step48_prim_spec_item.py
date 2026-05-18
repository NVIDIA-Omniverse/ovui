# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 48 — ``PrimSpecItem`` + tree integration.

Covers:
  * :class:`PrimSpecItem` construction + identity surface.
  * Lazy child materialisation + cache invalidation.
  * :class:`LayerModel.get_item_children` emits prim-spec children
    when ``settings.show_layer_contents`` is enabled.
  * :class:`LayerModel.can_item_have_children` covers both
    :class:`LayerItem` and :class:`PrimSpecItem`.
  * Prim-spec cache drops on structural (SUBLAYERS_CHANGED) events.
  * Toggling the setting off removes prim specs from the tree.
  * Delegate renders prim-spec rows via :meth:`build_widget` without
    raising.

The test suite seeds the :class:`MockLayerStackAdapter` with
descriptors so the adapter-read path mirrors the USD adapter shape
without requiring ``pxr``.
"""

from __future__ import annotations

import omni.ui as ui
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.layers import LayerDelegate, LayerItem, LayerModel, PrimSpecItem
from ovwidgets.layers.layer_model import DefaultLayerSettings


def _make_adapter_with_specs() -> MockLayerStackAdapter:
    """Seed a mock adapter with a small prim hierarchy on the root layer.

    Structure:
        /World              (Xform, DEF)
            /World/Cube     (Cube, DEF, has_reference=True)
            /World/Sphere   (Sphere, OVER, has_payload=True)
        /Overrides          (empty type, CLASS)
    """
    adapter = MockLayerStackAdapter()
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/World/Cube",
        type_name="Cube",
        has_reference=True,
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/World/Sphere",
        type_name="Sphere",
        specifier=PrimSpecifier.OVER,
        has_payload=True,
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/Overrides",
        specifier=PrimSpecifier.CLASS,
    )
    return adapter


# ─── PrimSpecItem — construction + identity ──────────────────────────────────


class TestPrimSpecItemConstruction:
    def test_subclass_of_ui_abstract_item(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert isinstance(spec, ui.AbstractItem)

    def test_stores_layer_item_and_descriptor(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.layer_item is layer
        assert spec.descriptor is desc

    def test_projects_descriptor_fields(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World/Cube",
            type_name="Cube",
            specifier=PrimSpecifier.OVER,
            has_reference=True,
            has_payload=False,
            is_instanceable=True,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.path == "/World/Cube"
        assert spec.type_name == "Cube"
        assert spec.specifier is PrimSpecifier.OVER
        assert spec.has_reference is True
        assert spec.has_payload is False
        assert spec.is_instanceable is True

    def test_name_is_trailing_path_segment(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World/Cube",
            type_name="Cube",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.name == "Cube"

    def test_name_root_path_is_slash(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/",
            type_name="",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.name == "/"

    def test_default_parent_is_none(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.parent is None

    def test_parent_reference_is_preserved(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        root_desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        child_desc = PrimSpecDescriptor(
            path="/World/Cube",
            type_name="Cube",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        root = PrimSpecItem(layer, root_desc)
        child = PrimSpecItem(layer, child_desc, parent=root)
        assert child.parent is root


# ─── PrimSpecItem — lazy children ────────────────────────────────────────────


class TestPrimSpecItemChildren:
    def test_has_cached_children_false_before_query(self) -> None:
        adapter = _make_adapter_with_specs()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.has_cached_children() is False

    def test_children_queries_adapter(self) -> None:
        adapter = _make_adapter_with_specs()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        children = spec.children(adapter)
        paths = sorted(c.path for c in children)
        assert paths == ["/World/Cube", "/World/Sphere"]

    def test_children_wraps_each_descriptor(self) -> None:
        adapter = _make_adapter_with_specs()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        children = spec.children(adapter)
        for child in children:
            assert isinstance(child, PrimSpecItem)
            assert child.layer_item is layer
            assert child.parent is spec

    def test_children_is_cached(self) -> None:
        """Second call returns the same list instance (no adapter re-read)."""
        adapter = _make_adapter_with_specs()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        first = spec.children(adapter)
        second = spec.children(adapter)
        assert first is second
        assert spec.has_cached_children() is True

    def test_invalidate_children_re_queries(self) -> None:
        adapter = _make_adapter_with_specs()
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        first = spec.children(adapter)
        spec.invalidate_children()
        assert spec.has_cached_children() is False
        second = spec.children(adapter)
        assert first is not second
        # Same descriptor set → same paths survive the re-read.
        assert {c.path for c in first} == {c.path for c in second}

    def test_missing_layer_degrades_to_empty(self) -> None:
        """An adapter ``KeyError`` collapses to an empty child list."""
        adapter = MockLayerStackAdapter()
        layer = LayerItem(adapter, "no-such-layer")
        desc = PrimSpecDescriptor(
            path="/World",
            type_name="Xform",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        spec = PrimSpecItem(layer, desc)
        assert spec.children(adapter) == []


# ─── LayerModel tree integration ─────────────────────────────────────────────


class TestLayerModelPrimSpecChildren:
    def test_layer_item_includes_prim_specs_when_setting_on(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            assert root is not None
            children = model.get_item_children(root)
            specs = [c for c in children if isinstance(c, PrimSpecItem)]
            paths = sorted(s.path for s in specs)
            assert paths == ["/Overrides", "/World"]
        finally:
            model.destroy()

    def test_layer_item_excludes_prim_specs_when_setting_off(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=False)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            assert root is not None
            children = model.get_item_children(root)
            specs = [c for c in children if isinstance(c, PrimSpecItem)]
            assert specs == []
        finally:
            model.destroy()

    def test_prim_specs_follow_sublayers_in_order(self) -> None:
        """Sublayer rows come first, prim specs after (LAYERS-PLAN Step 48)."""
        adapter = _make_adapter_with_specs()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            children = model.get_item_children(root)
            # Sublayer(s) first.
            assert isinstance(children[0], LayerItem)
            # Prim specs after.
            assert all(
                isinstance(c, PrimSpecItem) for c in children[1:]
            )
        finally:
            model.destroy()

    def test_get_item_children_for_prim_spec_returns_nested_specs(
        self,
    ) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            children = model.get_item_children(root)
            (world,) = [
                c
                for c in children
                if isinstance(c, PrimSpecItem) and c.path == "/World"
            ]
            grand = model.get_item_children(world)
            paths = sorted(g.path for g in grand)
            assert paths == ["/World/Cube", "/World/Sphere"]
            assert all(isinstance(g, PrimSpecItem) for g in grand)
        finally:
            model.destroy()

    def test_can_item_have_children_layer_with_prim_specs(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            assert model.can_item_have_children(root) is True
        finally:
            model.destroy()

    def test_can_item_have_children_layer_without_specs_and_setting_off(
        self,
    ) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=False)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            # Root has no sublayers in the stock mock fixture and
            # show_layer_contents is off, so no chevron.
            assert model.can_item_have_children(root) is False
        finally:
            model.destroy()

    def test_can_item_have_children_prim_spec_leaf_is_false(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            (overrides,) = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem) and c.path == "/Overrides"
            ]
            assert model.can_item_have_children(overrides) is False
        finally:
            model.destroy()

    def test_can_item_have_children_prim_spec_with_children(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            (world,) = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem) and c.path == "/World"
            ]
            assert model.can_item_have_children(world) is True
        finally:
            model.destroy()

    def test_prim_specs_lazy_loaded_on_first_access(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=False)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            # Setting off → lazy load never runs.
            assert root._prim_specs_loaded is False
            assert root._prim_specs == []

            # Flip the setting on and ask for children — now it loads.
            model._settings.show_layer_contents = True
            model.get_item_children(root)
            assert root._prim_specs_loaded is True
            assert len(root._prim_specs) == 2
        finally:
            model.destroy()

    def test_prim_specs_cache_survives_repeated_queries(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            first = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem)
            ]
            second = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem)
            ]
            # Identity of each PrimSpecItem is preserved across calls.
            assert [id(s) for s in first] == [id(s) for s in second]
        finally:
            model.destroy()

    def test_invalidate_clears_cache(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            model.get_item_children(root)
            assert root._prim_specs_loaded is True

            root.invalidate_prim_specs()
            assert root._prim_specs_loaded is False
            assert root._prim_specs == []
        finally:
            model.destroy()


# ─── Structural invalidation ─────────────────────────────────────────────────


class TestStructuralInvalidation:
    def test_sublayers_changed_event_invalidates_prim_specs(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            # Prime the prim-spec cache.
            first = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem)
            ]
            assert first
            # Emit a structural event through the flush path (the
            # mock adapter fires SUBLAYERS_CHANGED on add_sublayer).
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
            model._flush_events()

            # After flush the root should have a fresh PrimSpecItem
            # list — same descriptors, new object identities.
            second = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem)
            ]
            assert {s.path for s in first} == {s.path for s in second}
            assert [id(s) for s in first] != [id(s) for s in second]
        finally:
            model.destroy()

    def test_set_adapter_clears_prim_specs(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            model.get_item_children(root)
            assert root._prim_specs_loaded is True

            # Retarget to a fresh adapter — the old tree is destroyed,
            # so we validate that the new root starts cleanly.
            new_adapter = MockLayerStackAdapter()
            model.set_adapter(new_adapter)
            new_root = model.root_item
            assert new_root is not None
            assert new_root._prim_specs_loaded is False
            assert new_root._prim_specs == []
        finally:
            model.destroy()


# ─── Delegate integration ───────────────────────────────────────────────────


class TestLayerDelegatePrimSpec:
    def test_prim_spec_tag_mapping_covers_every_specifier(self) -> None:
        delegate = LayerDelegate()
        # Every PrimSpecifier value maps to a distinct tag so the
        # style block can resolve a name-qualified rule per kind.
        mapping = delegate._PRIM_SPEC_TAG_BY_SPECIFIER
        tags = {mapping[s] for s in PrimSpecifier}
        assert len(tags) == len(list(PrimSpecifier))

    def test_build_widget_does_not_raise_for_prim_spec(self) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            (world,) = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem) and c.path == "/World"
            ]
            delegate = LayerDelegate()
            # ovui accepts cells built outside a ui.Frame as long as a
            # parent container exists; a ui.VStack is cheap and lets
            # the delegate push widgets without constructing the full
            # window. The build must complete without exceptions for
            # every column including the name column where the prim
            # tag + name + type render happens.
            with ui.VStack():
                for col in range(model.get_item_value_model_count(world)):
                    delegate.build_widget(model, world, col, level=1, expanded=False)
        finally:
            model.destroy()

    def test_build_branch_paints_chevron_for_expandable_prim_spec(
        self,
    ) -> None:
        adapter = _make_adapter_with_specs()
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            children = model.get_item_children(root)
            (world,) = [
                c
                for c in children
                if isinstance(c, PrimSpecItem) and c.path == "/World"
            ]
            delegate = LayerDelegate()
            with ui.VStack():
                delegate.build_branch(
                    model, world, column_id=0, level=1, expanded=False
                )
        finally:
            model.destroy()
