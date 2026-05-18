# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for UsdStageAdapter.get_item_flags / get_badge_flags (Step 2).

Covers:
- ItemFlags populated from prim state (IS_ABSTRACT, IS_CLASS, IS_OVER,
  IS_INACTIVE, IS_INSTANCE_PROXY, IS_DEFAULT_PRIM) plus stubbed-False
  flags (IS_OUTDATED, IS_IN_LIVE_SESSION, HAS_MISSING_REFS).
- BadgeFlags populated from composition arcs (REFERENCE, PAYLOAD,
  INSTANCE, INHERITS, SPECIALIZES).
- LAYER_INFO ChangeEvent emission when stage.SetDefaultPrim() flips the
  cached default prim path.
- Hand-crafted .usda fixture parsed from string matches the the stage implementation step 2 verification recipe (defaultPrim="World", a class, an over).
"""

import pytest

try:
    from pxr import Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr (OpenUSD) not available")

from ovui_data_adapters.common import BadgeFlags, ChangeEventType, ItemFlags
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PLAN_USDA = """#usda 1.0
(
    defaultPrim = "World"
)

class Xform "Proto"
{
    def Cube "ProtoCube"
    {
    }
}

def Xform "World"
{
    def Cube "Active"
    {
    }

    def Cube "Sleeping" (
        active = false
    )
    {
    }

    def Xform "InstRoot" (
        instanceable = true
        prepend references = </Proto>
    )
    {
    }

    def Xform "PayloadHost" (
        prepend payload = @./nonexistent_payload.usda@</Inner>
    )
    {
    }

    def Xform "Inheritor" (
        prepend inherits = </Proto>
    )
    {
    }

    def Xform "Specializer" (
        prepend specializes = </Proto>
    )
    {
    }
}

over "Foo"
{
}
"""


@pytest.fixture
def plan_stage():
    """Stage described in the stage implementation step 2 verification recipe."""
    layer = Sdf.Layer.CreateAnonymous(".usda")
    assert layer.ImportFromString(PLAN_USDA)
    stage = Usd.Stage.Open(layer)
    return stage


@pytest.fixture
def plan_adapter(plan_stage):
    return UsdStageAdapter(plan_stage)


# ---------------------------------------------------------------------------
# ItemFlags
# ---------------------------------------------------------------------------

class TestItemFlagsFromUsd:
    def test_default_prim_flagged(self, plan_adapter, plan_stage):
        world = plan_stage.GetPrimAtPath("/World")
        flags = plan_adapter.get_item_flags(world)
        assert ItemFlags.IS_DEFAULT_PRIM in flags
        assert ItemFlags.IS_ABSTRACT not in flags
        assert ItemFlags.IS_INACTIVE not in flags
        assert ItemFlags.IS_CLASS not in flags
        assert ItemFlags.IS_OVER not in flags

    def test_non_default_prim_not_flagged(self, plan_adapter, plan_stage):
        proto = plan_stage.GetPrimAtPath("/Proto")
        flags = plan_adapter.get_item_flags(proto)
        assert ItemFlags.IS_DEFAULT_PRIM not in flags

    def test_class_prim_flags(self, plan_adapter, plan_stage):
        proto = plan_stage.GetPrimAtPath("/Proto")
        flags = plan_adapter.get_item_flags(proto)
        assert ItemFlags.IS_CLASS in flags
        # Class prims are also abstract in USD.
        assert ItemFlags.IS_ABSTRACT in flags
        assert ItemFlags.IS_OVER not in flags

    def test_over_prim_flagged(self, plan_adapter, plan_stage):
        foo = plan_stage.GetPrimAtPath("/Foo")
        flags = plan_adapter.get_item_flags(foo)
        assert ItemFlags.IS_OVER in flags
        assert ItemFlags.IS_CLASS not in flags
        assert ItemFlags.IS_ABSTRACT not in flags

    def test_inactive_prim_flagged(self, plan_adapter, plan_stage):
        sleeping = plan_stage.GetPrimAtPath("/World/Sleeping")
        flags = plan_adapter.get_item_flags(sleeping)
        assert ItemFlags.IS_INACTIVE in flags

    def test_active_prim_not_flagged_inactive(self, plan_adapter, plan_stage):
        active = plan_stage.GetPrimAtPath("/World/Active")
        flags = plan_adapter.get_item_flags(active)
        assert ItemFlags.IS_INACTIVE not in flags

    def test_instance_proxy_flagged(self, plan_adapter, plan_stage):
        # Descend into an instance — children of an instanceable prim are
        # instance proxies once traversed with the instance-proxy predicate.
        inst_root = plan_stage.GetPrimAtPath("/World/InstRoot")
        assert inst_root.IsInstance()
        # Walk the instance proxies beneath InstRoot.
        found_proxy = False
        for desc in Usd.PrimRange(inst_root, Usd.TraverseInstanceProxies()):
            if desc == inst_root:
                continue
            if desc.IsInstanceProxy():
                found_proxy = True
                flags = plan_adapter.get_item_flags(desc)
                assert ItemFlags.IS_INSTANCE_PROXY in flags
                break
        assert found_proxy, "expected at least one instance proxy under /World/InstRoot"

    def test_live_session_stubs_are_false(self, plan_adapter, plan_stage):
        world = plan_stage.GetPrimAtPath("/World")
        flags = plan_adapter.get_item_flags(world)
        assert ItemFlags.IS_OUTDATED not in flags
        assert ItemFlags.IS_IN_LIVE_SESSION not in flags
        assert ItemFlags.HAS_MISSING_REFS not in flags

    def test_returns_itemflags_instance(self, plan_adapter, plan_stage):
        world = plan_stage.GetPrimAtPath("/World")
        assert isinstance(plan_adapter.get_item_flags(world), ItemFlags)

    def test_no_default_prim_clears_is_default(self):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        adapter = UsdStageAdapter(stage)
        world = stage.GetPrimAtPath("/World")
        flags = adapter.get_item_flags(world)
        assert ItemFlags.IS_DEFAULT_PRIM not in flags


# ---------------------------------------------------------------------------
# BadgeFlags
# ---------------------------------------------------------------------------

class TestBadgeFlagsFromUsd:
    def test_no_arcs_returns_none(self, plan_adapter, plan_stage):
        world = plan_stage.GetPrimAtPath("/World")
        assert plan_adapter.get_badge_flags(world) == BadgeFlags.NONE

    def test_reference_badge(self, plan_adapter, plan_stage):
        inst = plan_stage.GetPrimAtPath("/World/InstRoot")
        flags = plan_adapter.get_badge_flags(inst)
        assert BadgeFlags.REFERENCE in flags

    def test_payload_badge(self, plan_adapter, plan_stage):
        payload = plan_stage.GetPrimAtPath("/World/PayloadHost")
        flags = plan_adapter.get_badge_flags(payload)
        assert BadgeFlags.PAYLOAD in flags

    def test_instance_badge(self, plan_adapter, plan_stage):
        inst = plan_stage.GetPrimAtPath("/World/InstRoot")
        flags = plan_adapter.get_badge_flags(inst)
        assert BadgeFlags.INSTANCE in flags

    def test_inherits_badge(self, plan_adapter, plan_stage):
        heir = plan_stage.GetPrimAtPath("/World/Inheritor")
        flags = plan_adapter.get_badge_flags(heir)
        assert BadgeFlags.INHERITS in flags

    def test_specializes_badge(self, plan_adapter, plan_stage):
        spec = plan_stage.GetPrimAtPath("/World/Specializer")
        flags = plan_adapter.get_badge_flags(spec)
        assert BadgeFlags.SPECIALIZES in flags

    def test_returns_badgeflags_instance(self, plan_adapter, plan_stage):
        world = plan_stage.GetPrimAtPath("/World")
        assert isinstance(plan_adapter.get_badge_flags(world), BadgeFlags)


# ---------------------------------------------------------------------------
# LAYER_INFO listener
# ---------------------------------------------------------------------------

class TestLayerInfoListener:
    def test_default_prim_path_cached_at_construction(self, plan_adapter):
        assert plan_adapter._default_prim_path == "/World"

    def test_no_default_prim_caches_none(self):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        adapter = UsdStageAdapter(stage)
        assert adapter._default_prim_path is None

    def test_set_default_prim_emits_layer_info_event(self):
        events = []
        deferred = []

        def fake_call_later(_delay, fn):
            deferred.append(fn)

        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        other = stage.DefinePrim("/Other", "Xform")
        stage.SetDefaultPrim(world)

        adapter = UsdStageAdapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)
        assert sub is not None  # Keep subscription alive for the test duration.

        stage.SetDefaultPrim(other)

        # Flush is deferred via call_later.
        assert len(deferred) >= 1
        for fn in deferred:
            fn()

        layer_events = [e for e in events if e.event_type == ChangeEventType.LAYER_INFO]
        assert len(layer_events) == 1
        paths = set(layer_events[0].changed_paths)
        assert "/World" in paths
        assert "/Other" in paths
        # Resynced paths stays empty for layer-info events.
        assert layer_events[0].resynced_paths == ()
        # Cache updated.
        assert adapter._default_prim_path == "/Other"

    def test_clear_default_prim_emits_event_with_only_old_path(self):
        events = []
        deferred = []

        def fake_call_later(_delay, fn):
            deferred.append(fn)

        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        stage.SetDefaultPrim(world)

        adapter = UsdStageAdapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)
        assert sub is not None  # Keep subscription alive for the test duration.

        stage.ClearDefaultPrim()

        for fn in deferred:
            fn()

        layer_events = [e for e in events if e.event_type == ChangeEventType.LAYER_INFO]
        assert len(layer_events) == 1
        assert layer_events[0].changed_paths == ("/World",)
        assert adapter._default_prim_path is None

    def test_is_default_prim_updates_after_event(self):
        deferred = []

        def fake_call_later(_delay, fn):
            deferred.append(fn)

        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        other = stage.DefinePrim("/Other", "Xform")
        stage.SetDefaultPrim(world)

        adapter = UsdStageAdapter(stage, call_later=fake_call_later)

        # Pre-flip: /World is default.
        assert ItemFlags.IS_DEFAULT_PRIM in adapter.get_item_flags(world)
        assert ItemFlags.IS_DEFAULT_PRIM not in adapter.get_item_flags(other)

        stage.SetDefaultPrim(other)
        for fn in deferred:
            fn()

        # Post-flip: /Other is default.
        assert ItemFlags.IS_DEFAULT_PRIM not in adapter.get_item_flags(world)
        assert ItemFlags.IS_DEFAULT_PRIM in adapter.get_item_flags(other)

    def test_unrelated_layer_info_change_does_not_emit_layer_event(self):
        events = []
        deferred = []

        def fake_call_later(_delay, fn):
            deferred.append(fn)

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")

        adapter = UsdStageAdapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)
        assert sub is not None  # Keep subscription alive for the test duration.

        # Touch a non-defaultPrim layer field. Should not produce a LAYER_INFO
        # event because the cached default prim path has not changed.
        stage.GetRootLayer().comment = "hello"

        for fn in deferred:
            fn()

        layer_events = [e for e in events if e.event_type == ChangeEventType.LAYER_INFO]
        assert layer_events == []

    def test_layer_notice_key_stored(self, plan_adapter):
        # Step 2 plan requires handle stored next to _notice_key.
        assert hasattr(plan_adapter, "_notice_key")
        assert hasattr(plan_adapter, "_layer_notice_key")
        assert plan_adapter._layer_notice_key is not None
