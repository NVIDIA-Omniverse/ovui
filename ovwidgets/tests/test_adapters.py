# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.common.adapters — all adapter ABCs and supporting types."""

import dataclasses

import pytest
from ovui_data_adapters.common import (
    AttributeMetadata,
    BadgeFlags,
    ChangeEvent,
    ChangeEventType,
    ItemFlags,
    PropertyAdapter,
    RendererAdapter,
    ReparentPosition,
    SelectionAdapter,
    StageAdapter,
    StageChoice,
    TransformAdapter,
    VisibilityState,
)

from ovwidgets.common.settings import Settings, Subscription

_SETTINGS = Settings()  # single shared instance for producing valid Subscriptions


def _make_sub(callback):
    return _SETTINGS.subscribe("__adapter_test__", callback)


# ──────────────────────────────────────────────────────────────────────────────
# Concrete minimal implementations used only in tests
# ──────────────────────────────────────────────────────────────────────────────

class _ConcreteStage(StageAdapter):
    def get_root(self): return "/"
    def get_children(self, item): return []
    def can_have_children(self, item): return False
    def get_item_path(self, item): return str(item)
    def get_item_at_path(self, path): return path
    def get_display_name(self, item): return str(item)
    def get_type_name(self, item): return "Xform"
    def get_icon_name(self, item): return "xform"
    def get_badge_flags(self, item): return BadgeFlags.NONE
    def get_item_flags(self, item): return ItemFlags.NONE
    def compute_visibility(self, item): return VisibilityState.VISIBLE
    def set_visibility(self, item, visible): pass
    def can_edit_visibility(self, item): return True
    def can_rename(self, item): return True
    def rename(self, item, new_name): return new_name
    def normalize_name(self, name): return name
    def can_reparent(self, items, new_parent): return True
    def reparent(self, items, new_parent, position): pass
    def filter_items(self, items, predicate): return [i for i in items if predicate(i)]
    def subscribe_changes(self, callback): return _make_sub(callback)
    def begin_undo_group(self, label): pass
    def end_undo_group(self): pass
    def suppress_change_notifications(self): pass
    def compute_world_aabb(self, paths):
        return ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    def compute_prim_world_aabb_with_extent_fallback(self, path):
        return ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    def read_bound_camera(self):
        return None


class _ConcreteTransform(TransformAdapter):
    def get_local_transform(self, path): return None
    def get_world_transform(self, path): return None
    def set_local_transform(self, path, matrix): pass
    def can_transform(self, path): return True


class _ConcreteProperty(PropertyAdapter):
    def get_paths(self): return ["/World/Cube"]
    def is_valid(self): return True
    def get_attribute_names(self): return ["xformOp:translate"]
    def get_attribute_metadata(self, attr_name):
        return AttributeMetadata(
            name=attr_name,
            display_name=attr_name,
            type_name="float3",
            value_type=None,
            group="Transform",
        )
    def get_value(self, attr_name): return (0.0, 0.0, 0.0)
    def is_ambiguous(self, attr_name): return False
    def get_per_component_ambiguity(self, attr_name): return [False, False, False]
    def begin_edit(self, attr_name): pass
    def set_value(self, attr_name, value): pass
    def end_edit(self, attr_name): pass
    def subscribe_changes(self, callback): return _make_sub(callback)
    def get_scheme(self): return "mock"


class _ConcreteRenderer(RendererAdapter):
    def load_stage(self, stage): pass
    def render_frame(self, width, height, view_matrix, proj_matrix): return None
    def set_resolution(self, width, height): pass
    def pick(self, x, y, callback, query_name): callback(None, None)
    def cancel_pick(self, query_name): pass
    def pick_rect(self, x0, y0, x1, y1, callback): callback([])
    def set_selection_highlight(self, paths): pass
    def shutdown(self): pass


class _ConcreteSelection(SelectionAdapter):
    def to_adapter_items(self, selection): return []
    def to_selection_items(self, adapter_items): return []


# ──────────────────────────────────────────────────────────────────────────────
# Import tests
# ──────────────────────────────────────────────────────────────────────────────

class TestImports:
    def test_stage_adapter_importable(self):
        assert StageAdapter is not None

    def test_transform_adapter_importable(self):
        assert TransformAdapter is not None

    def test_property_adapter_importable(self):
        assert PropertyAdapter is not None

    def test_renderer_adapter_importable(self):
        assert RendererAdapter is not None

    def test_selection_adapter_importable(self):
        assert SelectionAdapter is not None

    def test_visibility_state_importable(self):
        assert VisibilityState is not None

    def test_item_flags_importable(self):
        assert ItemFlags is not None

    def test_badge_flags_importable(self):
        assert BadgeFlags is not None

    def test_reparent_position_importable(self):
        assert ReparentPosition is not None

    def test_change_event_type_importable(self):
        assert ChangeEventType is not None

    def test_change_event_importable(self):
        assert ChangeEvent is not None

    def test_attribute_metadata_importable(self):
        assert AttributeMetadata is not None

    def test_stage_choice_importable(self):
        assert StageChoice is not None

    def test_package_all_includes_stage_choice(self):
        import ovui_data_adapters.common as pkg
        assert "StageChoice" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# ABC instantiation guard
# ──────────────────────────────────────────────────────────────────────────────

class TestAbstractInstantiation:
    def test_stage_adapter_cannot_instantiate(self):
        with pytest.raises(TypeError):
            StageAdapter()

    def test_transform_adapter_cannot_instantiate(self):
        with pytest.raises(TypeError):
            TransformAdapter()

    def test_property_adapter_cannot_instantiate(self):
        with pytest.raises(TypeError):
            PropertyAdapter()

    def test_renderer_adapter_cannot_instantiate(self):
        with pytest.raises(TypeError):
            RendererAdapter()

    def test_selection_adapter_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SelectionAdapter()


# ──────────────────────────────────────────────────────────────────────────────
# StageAdapter — abstract method presence
# ──────────────────────────────────────────────────────────────────────────────

class TestStageAdapterMethods:
    REQUIRED = [
        "get_root", "get_children", "can_have_children", "get_item_path",
        "get_item_at_path", "get_display_name", "get_type_name", "get_icon_name",
        "get_badge_flags", "get_item_flags", "compute_visibility", "set_visibility",
        "can_edit_visibility", "can_rename", "rename", "normalize_name",
        "can_reparent", "reparent", "filter_items", "subscribe_changes",
        "begin_undo_group", "end_undo_group", "suppress_change_notifications",
        # Step 7 — world AABB / framing / bound-camera
        "compute_world_aabb",
        "compute_prim_world_aabb_with_extent_fallback",
        "read_bound_camera",
    ]

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_exists(self, method_name):
        assert hasattr(StageAdapter, method_name)

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_is_abstract(self, method_name):
        assert method_name in StageAdapter.__abstractmethods__

    def test_concrete_subclass_instantiable(self):
        adapter = _ConcreteStage()
        assert adapter.get_root() == "/"

    def test_get_children_returns_list(self):
        adapter = _ConcreteStage()
        result = adapter.get_children("/World")
        assert isinstance(result, list)

    def test_filter_items_applies_predicate(self):
        adapter = _ConcreteStage()
        items = ["/A", "/B", "/C"]
        result = adapter.filter_items(items, lambda x: x != "/B")
        assert result == ["/A", "/C"]

    def test_compute_visibility_returns_enum(self):
        adapter = _ConcreteStage()
        result = adapter.compute_visibility("/World")
        assert isinstance(result, VisibilityState)

    def test_get_item_flags_returns_flag(self):
        adapter = _ConcreteStage()
        result = adapter.get_item_flags("/World")
        assert isinstance(result, ItemFlags)

    def test_subscribe_changes_returns_subscription(self):
        adapter = _ConcreteStage()
        sub = adapter.subscribe_changes(lambda e: None)
        assert isinstance(sub, Subscription)

    def test_get_type_category_is_concrete(self):
        # Step 3: get_type_category has a built-in default so adapters
        # only need to override for performance. Must NOT be abstract.
        assert "get_type_category" not in StageAdapter.__abstractmethods__
        assert hasattr(StageAdapter, "get_type_category")

    @pytest.mark.parametrize(
        "method_name",
        ["list_cameras", "read_camera_pose", "list_render_products"],
    )
    def test_selector_contract_method_is_concrete(self, method_name):
        assert hasattr(StageAdapter, method_name)
        assert method_name not in StageAdapter.__abstractmethods__

    def test_selector_contract_defaults_are_empty_or_none(self):
        adapter = _ConcreteStage()
        assert adapter.list_cameras() == []
        assert adapter.read_camera_pose("/World/Camera") is None
        assert adapter.list_render_products() == []

    def test_selector_list_defaults_return_fresh_lists(self):
        adapter = _ConcreteStage()
        cameras = adapter.list_cameras()
        cameras.append(StageChoice("/World/Camera", "Camera"))
        render_products = adapter.list_render_products()
        render_products.append(StageChoice("/Render/Product", "Product"))
        assert adapter.list_cameras() == []
        assert adapter.list_render_products() == []


class TestStageChoice:
    def test_is_frozen_dataclass(self):
        assert dataclasses.is_dataclass(StageChoice)
        params = getattr(StageChoice, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_exact_field_set(self):
        names = [f.name for f in dataclasses.fields(StageChoice)]
        assert names == ["path", "display_name"]

    def test_mutation_raises(self):
        choice = StageChoice("/World/Camera", "Camera")
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            choice.display_name = "Other"


class TestGetTypeCategoryDefault:
    """The default StageAdapter.get_type_category mapping."""

    class _StageWithType(_ConcreteStage):
        def __init__(self, type_name: str):
            self._tn = type_name
        def get_type_name(self, item):
            return self._tn

    @pytest.mark.parametrize(
        "type_name,expected",
        [
            ("Mesh", "Mesh"), ("Sphere", "Mesh"), ("Cube", "Mesh"),
            ("Cone", "Mesh"), ("Cylinder", "Mesh"), ("Capsule", "Mesh"),
            ("Plane", "Mesh"), ("BasisCurves", "Mesh"), ("Points", "Mesh"),
            ("NurbsCurves", "Mesh"), ("NurbsPatch", "Mesh"),
            ("Light", "Light"), ("DomeLight", "Light"),
            ("DistantLight", "Light"), ("DiskLight", "Light"),
            ("RectLight", "Light"), ("SphereLight", "Light"),
            ("CylinderLight", "Light"),
            ("Camera", "Camera"),
            ("Xform", "Xform"),
            ("Scope", "Scope"),
        ],
    )
    def test_maps_to_expected_category(self, type_name, expected):
        adapter = self._StageWithType(type_name)
        assert adapter.get_type_category("anything") == expected

    def test_unknown_type_returns_other(self):
        adapter = self._StageWithType("SomethingWeird")
        assert adapter.get_type_category("x") == "Other"

    def test_empty_returns_other(self):
        adapter = self._StageWithType("")
        assert adapter.get_type_category("x") == "Other"

    def test_case_insensitive(self):
        adapter = self._StageWithType("SPHERE")
        assert adapter.get_type_category("x") == "Mesh"

    def test_returns_only_valid_category_names(self):
        valid = {"Mesh", "Light", "Camera", "Xform", "Scope", "Other"}
        for tn in ("Mesh", "DomeLight", "Camera", "Xform", "Scope", "UnknownThing"):
            adapter = self._StageWithType(tn)
            assert adapter.get_type_category("x") in valid


# ──────────────────────────────────────────────────────────────────────────────
# TransformAdapter — abstract method presence
# ──────────────────────────────────────────────────────────────────────────────

class TestTransformAdapterMethods:
    REQUIRED = [
        "get_local_transform", "get_world_transform",
        "set_local_transform", "can_transform",
    ]

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_exists(self, method_name):
        assert hasattr(TransformAdapter, method_name)

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_is_abstract(self, method_name):
        assert method_name in TransformAdapter.__abstractmethods__

    def test_concrete_subclass_instantiable(self):
        adapter = _ConcreteTransform()
        assert adapter.can_transform("/World/Cube") is True


# ──────────────────────────────────────────────────────────────────────────────
# PropertyAdapter — abstract method presence
# ──────────────────────────────────────────────────────────────────────────────

class TestPropertyAdapterMethods:
    REQUIRED = [
        "get_paths", "is_valid", "get_attribute_names", "get_attribute_metadata",
        "get_value", "is_ambiguous", "get_per_component_ambiguity",
        "begin_edit", "set_value", "end_edit", "subscribe_changes", "get_scheme",
    ]

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_exists(self, method_name):
        assert hasattr(PropertyAdapter, method_name)

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_is_abstract(self, method_name):
        assert method_name in PropertyAdapter.__abstractmethods__

    def test_concrete_subclass_instantiable(self):
        adapter = _ConcreteProperty()
        assert adapter.is_valid() is True

    def test_get_attribute_metadata_returns_metadata(self):
        adapter = _ConcreteProperty()
        meta = adapter.get_attribute_metadata("xformOp:translate")
        assert isinstance(meta, AttributeMetadata)
        assert meta.type_name == "float3"

    def test_subscribe_changes_returns_subscription(self):
        adapter = _ConcreteProperty()
        sub = adapter.subscribe_changes(lambda: None)
        assert isinstance(sub, Subscription)

    def test_get_scheme_returns_string(self):
        adapter = _ConcreteProperty()
        assert isinstance(adapter.get_scheme(), str)

    def test_get_resolved_asset_path_exists(self):
        """Step 3.6 added ``get_resolved_asset_path`` as a concrete (not
        abstract) method on :class:`PropertyAdapter` so every existing
        adapter inherits a ``None`` default without breaking the ABC
        contract."""
        assert hasattr(PropertyAdapter, "get_resolved_asset_path")

    def test_get_resolved_asset_path_not_abstract(self):
        """Concrete-by-default: adapters that don't back asset paths don't
        need to implement this."""
        assert "get_resolved_asset_path" not in PropertyAdapter.__abstractmethods__

    def test_get_resolved_asset_path_default_returns_none(self):
        """The ABC-level default surfaces ``None`` so
        :class:`AssetPathAttributeRow` can always call it without
        branching on adapter scheme."""
        adapter = _ConcreteProperty()
        assert adapter.get_resolved_asset_path("anything") is None


# ──────────────────────────────────────────────────────────────────────────────
# RendererAdapter — abstract method presence
# ──────────────────────────────────────────────────────────────────────────────

class TestRendererAdapterMethods:
    REQUIRED = [
        "load_stage", "render_frame", "set_resolution",
        "pick", "cancel_pick", "pick_rect", "set_selection_highlight", "shutdown",
    ]

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_exists(self, method_name):
        assert hasattr(RendererAdapter, method_name)

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_is_abstract(self, method_name):
        assert method_name in RendererAdapter.__abstractmethods__

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            RendererAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_instantiable(self):
        renderer = _ConcreteRenderer()
        renderer.set_resolution(800, 600)

    def test_pick_invokes_callback_with_none(self):
        renderer = _ConcreteRenderer()
        results = []
        renderer.pick(0.0, 0.0, lambda path, pos: results.append((path, pos)), "q1")
        assert results == [(None, None)]

    def test_pick_rect_invokes_callback_with_empty(self):
        renderer = _ConcreteRenderer()
        results = []
        renderer.pick_rect(0, 0, 100, 100, lambda paths: results.append(paths))
        assert results == [[]]


# ──────────────────────────────────────────────────────────────────────────────
# SelectionAdapter — abstract method presence
# ──────────────────────────────────────────────────────────────────────────────

class TestSelectionAdapterMethods:
    REQUIRED = ["to_adapter_items", "to_selection_items"]

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_exists(self, method_name):
        assert hasattr(SelectionAdapter, method_name)

    @pytest.mark.parametrize("method_name", REQUIRED)
    def test_method_is_abstract(self, method_name):
        assert method_name in SelectionAdapter.__abstractmethods__

    def test_concrete_subclass_instantiable(self):
        adapter = _ConcreteSelection()
        assert adapter.to_adapter_items(None) == []

    def test_to_selection_items_returns_list(self):
        adapter = _ConcreteSelection()
        assert adapter.to_selection_items([]) == []


# ──────────────────────────────────────────────────────────────────────────────
# VisibilityState
# ──────────────────────────────────────────────────────────────────────────────

class TestVisibilityState:
    def test_all_members_exist(self):
        assert VisibilityState.VISIBLE
        assert VisibilityState.INVISIBLE
        assert VisibilityState.INHERITED_INVISIBLE

    def test_members_are_distinct(self):
        assert VisibilityState.VISIBLE != VisibilityState.INVISIBLE
        assert VisibilityState.INVISIBLE != VisibilityState.INHERITED_INVISIBLE

    def test_is_enum(self):
        from enum import Enum
        assert issubclass(VisibilityState, Enum)


# ──────────────────────────────────────────────────────────────────────────────
# ItemFlags
# ──────────────────────────────────────────────────────────────────────────────

class TestItemFlags:
    def test_none_is_zero(self):
        assert ItemFlags.NONE.value == 0

    def test_flags_combine(self):
        combined = ItemFlags.IS_ABSTRACT | ItemFlags.IS_OVER
        assert ItemFlags.IS_ABSTRACT in combined
        assert ItemFlags.IS_OVER in combined
        assert ItemFlags.IS_INSTANCE_PROXY not in combined

    def test_all_members_exist(self):
        assert ItemFlags.IS_INSTANCE_PROXY
        assert ItemFlags.IS_ABSTRACT
        assert ItemFlags.IS_OVER
        assert ItemFlags.IS_INACTIVE
        assert ItemFlags.IS_CLASS
        assert ItemFlags.IS_DEFAULT_PRIM
        assert ItemFlags.IS_OUTDATED
        assert ItemFlags.IS_IN_LIVE_SESSION
        assert ItemFlags.HAS_MISSING_REFS

    def test_all_members_distinct(self):
        members = [
            ItemFlags.IS_INSTANCE_PROXY,
            ItemFlags.IS_ABSTRACT,
            ItemFlags.IS_OVER,
            ItemFlags.IS_INACTIVE,
            ItemFlags.IS_CLASS,
            ItemFlags.IS_DEFAULT_PRIM,
            ItemFlags.IS_OUTDATED,
            ItemFlags.IS_IN_LIVE_SESSION,
            ItemFlags.HAS_MISSING_REFS,
        ]
        assert len({m.value for m in members}) == len(members)

    def test_new_flags_combine_with_existing(self):
        combined = ItemFlags.IS_CLASS | ItemFlags.IS_DEFAULT_PRIM | ItemFlags.IS_ABSTRACT
        assert ItemFlags.IS_CLASS in combined
        assert ItemFlags.IS_DEFAULT_PRIM in combined
        assert ItemFlags.IS_ABSTRACT in combined
        assert ItemFlags.IS_INACTIVE not in combined

    def test_is_flag(self):
        from enum import Flag
        assert issubclass(ItemFlags, Flag)

    def test_is_not_intflag(self):
        # Plan §Step 1: "Store as a Flag, not IntFlag, to avoid implicit coercions."
        from enum import IntFlag
        assert not issubclass(ItemFlags, IntFlag)


# ──────────────────────────────────────────────────────────────────────────────
# BadgeFlags
# ──────────────────────────────────────────────────────────────────────────────

class TestBadgeFlags:
    def test_none_is_zero(self):
        assert BadgeFlags.NONE.value == 0

    def test_all_members_exist(self):
        assert BadgeFlags.REFERENCE
        assert BadgeFlags.PAYLOAD
        assert BadgeFlags.INSTANCE
        assert BadgeFlags.INHERITS
        assert BadgeFlags.SPECIALIZES
        assert BadgeFlags.OVERRIDE

    def test_all_members_distinct(self):
        members = [
            BadgeFlags.REFERENCE,
            BadgeFlags.PAYLOAD,
            BadgeFlags.INSTANCE,
            BadgeFlags.INHERITS,
            BadgeFlags.SPECIALIZES,
            BadgeFlags.OVERRIDE,
        ]
        assert len({m.value for m in members}) == len(members)

    def test_flags_combine(self):
        combined = BadgeFlags.REFERENCE | BadgeFlags.PAYLOAD
        assert BadgeFlags.REFERENCE in combined
        assert BadgeFlags.PAYLOAD in combined
        assert BadgeFlags.INSTANCE not in combined

    def test_none_is_falsy(self):
        assert not BadgeFlags.NONE

    def test_non_none_is_truthy(self):
        assert BadgeFlags.REFERENCE

    def test_is_flag(self):
        from enum import Flag
        assert issubclass(BadgeFlags, Flag)

    def test_is_not_intflag(self):
        from enum import IntFlag
        assert not issubclass(BadgeFlags, IntFlag)

    def test_get_badge_flags_returns_badgeflags(self):
        adapter = _ConcreteStage()
        result = adapter.get_badge_flags("/World")
        assert isinstance(result, BadgeFlags)


# ──────────────────────────────────────────────────────────────────────────────
# ReparentPosition
# ──────────────────────────────────────────────────────────────────────────────

class TestReparentPosition:
    def test_all_members_exist(self):
        assert ReparentPosition.CHILD
        assert ReparentPosition.BEFORE
        assert ReparentPosition.AFTER

    def test_members_distinct(self):
        assert ReparentPosition.CHILD != ReparentPosition.BEFORE
        assert ReparentPosition.BEFORE != ReparentPosition.AFTER


# ──────────────────────────────────────────────────────────────────────────────
# ChangeEventType
# ──────────────────────────────────────────────────────────────────────────────

class TestChangeEventType:
    def test_all_members_exist(self):
        assert ChangeEventType.INFO_CHANGE
        assert ChangeEventType.RESYNC
        assert ChangeEventType.LAYER_INFO

    def test_string_values(self):
        assert ChangeEventType.INFO_CHANGE.value == "info"
        assert ChangeEventType.RESYNC.value == "resync"
        assert ChangeEventType.LAYER_INFO.value == "layer"


# ──────────────────────────────────────────────────────────────────────────────
# ChangeEvent
# ──────────────────────────────────────────────────────────────────────────────

class TestChangeEvent:
    def test_construction(self):
        evt = ChangeEvent(
            changed_paths=("/World/Cube",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert evt.changed_paths == ("/World/Cube",)
        assert evt.resynced_paths == ()
        assert evt.event_type == ChangeEventType.INFO_CHANGE

    def test_is_frozen(self):
        evt = ChangeEvent(
            changed_paths=("/A",),
            resynced_paths=(),
            event_type=ChangeEventType.RESYNC,
        )
        with pytest.raises((AttributeError, TypeError)):
            evt.changed_paths = ("/B",)

    def test_hashable(self):
        evt = ChangeEvent(
            changed_paths=("/A",),
            resynced_paths=("/B",),
            event_type=ChangeEventType.RESYNC,
        )
        s = {evt}
        assert evt in s

    def test_get_common_prefix_empty(self):
        evt = ChangeEvent(
            changed_paths=(),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert evt.get_common_prefix() == "/"

    def test_get_common_prefix_single_path(self):
        evt = ChangeEvent(
            changed_paths=("/World/Cube",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert evt.get_common_prefix() == "/World/Cube"

    def test_get_common_prefix_siblings(self):
        evt = ChangeEvent(
            changed_paths=("/World/Cube", "/World/Sphere"),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert evt.get_common_prefix() == "/World"

    def test_get_common_prefix_no_common(self):
        evt = ChangeEvent(
            changed_paths=("/WorldA/Cube",),
            resynced_paths=("/WorldB/Sphere",),
            event_type=ChangeEventType.RESYNC,
        )
        assert evt.get_common_prefix() == "/"

    def test_get_common_prefix_path_component_match(self):
        # '/WorldA' and '/WorldB' share '/' not '/World' (string prefix trap)
        evt = ChangeEvent(
            changed_paths=("/WorldA",),
            resynced_paths=("/WorldB",),
            event_type=ChangeEventType.RESYNC,
        )
        assert evt.get_common_prefix() == "/"

    def test_get_common_prefix_mixed_changed_resynced(self):
        evt = ChangeEvent(
            changed_paths=("/World/Lights",),
            resynced_paths=("/World/Cameras",),
            event_type=ChangeEventType.RESYNC,
        )
        assert evt.get_common_prefix() == "/World"

    def test_equality(self):
        e1 = ChangeEvent(("/A",), (), ChangeEventType.INFO_CHANGE)
        e2 = ChangeEvent(("/A",), (), ChangeEventType.INFO_CHANGE)
        assert e1 == e2

    def test_inequality_event_type(self):
        e1 = ChangeEvent(("/A",), (), ChangeEventType.INFO_CHANGE)
        e2 = ChangeEvent(("/A",), (), ChangeEventType.RESYNC)
        assert e1 != e2


# ──────────────────────────────────────────────────────────────────────────────
# AttributeMetadata
# ──────────────────────────────────────────────────────────────────────────────

class TestAttributeMetadata:
    def test_required_fields(self):
        meta = AttributeMetadata(
            name="xformOp:translate",
            display_name="Translate",
            type_name="float3",
            value_type=None,
            group="Transform",
        )
        assert meta.name == "xformOp:translate"
        assert meta.display_name == "Translate"
        assert meta.type_name == "float3"
        assert meta.group == "Transform"

    def test_optional_field_defaults(self):
        meta = AttributeMetadata(
            name="radius",
            display_name="Radius",
            type_name="float",
            value_type=None,
            group="Geometry",
        )
        assert meta.soft_range_min is None
        assert meta.soft_range_max is None
        assert meta.hard_range_min is None
        assert meta.hard_range_max is None
        assert meta.allowed_values is None
        assert meta.is_big_array is False
        assert meta.change_on_edit_end is True
        assert meta.custom_model_class is None
        assert meta.custom_widget_class is None
        assert meta.is_time_sampled is False
        assert meta.is_locked is False
        assert meta.is_authored is True

    def test_range_fields(self):
        meta = AttributeMetadata(
            name="roughness",
            display_name="Roughness",
            type_name="float",
            value_type=None,
            group="Material",
            soft_range_min=0.0,
            soft_range_max=1.0,
            hard_range_min=0.0,
            hard_range_max=1.0,
        )
        assert meta.soft_range_min == 0.0
        assert meta.soft_range_max == 1.0
        assert meta.hard_range_min == 0.0
        assert meta.hard_range_max == 1.0

    def test_allowed_values(self):
        meta = AttributeMetadata(
            name="purpose",
            display_name="Purpose",
            type_name="token",
            value_type=None,
            group="Visibility",
            allowed_values=["default", "render", "proxy", "guide"],
        )
        assert "render" in meta.allowed_values

    def test_mutable(self):
        meta = AttributeMetadata(
            name="x", display_name="X", type_name="float", value_type=None, group="G"
        )
        meta.is_locked = True
        assert meta.is_locked is True
