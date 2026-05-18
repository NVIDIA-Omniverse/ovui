# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for UsdStageAdapter mutations: visibility, rename, reparent, undo.

All tests are skipped if pxr (usd-core) is not installed.
"""

import pytest

try:
    from pxr import Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

from ovui_data_adapters.common import ReparentPosition, VisibilityState

from ovwidgets.common.undo import UndoManager

pytestmark = pytest.mark.skipif(not HAS_USD, reason="usd-core not installed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stage():
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World", "Xform")
    stage.DefinePrim("/World/A", "Xform")
    stage.DefinePrim("/World/B", "Xform")
    stage.DefinePrim("/World/A/Child", "Mesh")
    return stage


def _make_adapter(stage, undo_manager=None):
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
    return UsdStageAdapter(stage, undo_manager)


def _find_instance_proxy(stage):
    class_prim = stage.CreateClassPrim("/Proto")
    stage.DefinePrim("/Proto/ProtoCube", "Cube")
    inst_root = stage.DefinePrim("/World/InstRoot", "Xform")
    inst_root.GetReferences().AddInternalReference(class_prim.GetPath())
    inst_root.SetInstanceable(True)
    for desc in Usd.PrimRange(inst_root, Usd.TraverseInstanceProxies()):
        if desc != inst_root and desc.IsInstanceProxy():
            return desc
    raise AssertionError("expected an instance proxy child under /World/InstRoot")


# ── Visibility ────────────────────────────────────────────────────────────────

class TestVisibility:
    def test_visible_prim_returns_visible(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        assert adapter.compute_visibility(prim) == VisibilityState.VISIBLE

    def test_invisible_prim_returns_invisible(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        UsdGeom.Imageable(prim).MakeInvisible()
        assert adapter.compute_visibility(prim) == VisibilityState.INVISIBLE

    def test_child_of_invisible_parent_returns_inherited_invisible(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        parent = stage.GetPrimAtPath("/World/A")
        child = stage.GetPrimAtPath("/World/A/Child")
        UsdGeom.Imageable(parent).MakeInvisible()
        assert adapter.compute_visibility(child) == VisibilityState.INHERITED_INVISIBLE

    def test_set_visibility_false_makes_prim_invisible(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.set_visibility(prim, False)
        assert adapter.compute_visibility(prim) == VisibilityState.INVISIBLE

    def test_set_visibility_true_makes_prim_visible(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        UsdGeom.Imageable(prim).MakeInvisible()
        adapter.set_visibility(prim, True)
        assert adapter.compute_visibility(prim) == VisibilityState.VISIBLE

    def test_undo_restores_previous_visibility(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.set_visibility(prim, False)
        assert adapter.compute_visibility(prim) == VisibilityState.INVISIBLE
        undo.undo()
        assert adapter.compute_visibility(prim) == VisibilityState.VISIBLE

    def test_undo_restores_invisible_to_visible(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        prim = stage.GetPrimAtPath("/World/A")
        UsdGeom.Imageable(prim).MakeInvisible()
        adapter.set_visibility(prim, True)
        assert adapter.compute_visibility(prim) == VisibilityState.VISIBLE
        undo.undo()
        assert adapter.compute_visibility(prim) == VisibilityState.INVISIBLE

    def test_pseudo_root_always_visible(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        pseudo_root = stage.GetPseudoRoot()
        assert adapter.compute_visibility(pseudo_root) == VisibilityState.VISIBLE

    def test_set_visibility_fires_change_notification(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        events = []
        sub = adapter.subscribe_changes(events.append)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.set_visibility(prim, False)
        assert len(events) == 1
        assert "/World/A" in events[0].changed_paths

    def test_set_visibility_no_undo_manager_executes_directly(self):
        stage = _make_stage()
        adapter = _make_adapter(stage, undo_manager=None)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.set_visibility(prim, False)
        assert adapter.compute_visibility(prim) == VisibilityState.INVISIBLE

    def test_can_edit_visibility_true_for_imageable_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        assert adapter.can_edit_visibility(prim) is True

    def test_can_edit_visibility_false_for_pseudo_root(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        assert adapter.can_edit_visibility(stage.GetPseudoRoot()) is False

    def test_can_edit_visibility_false_for_non_imageable_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.DefinePrim("/World/Untyped")
        assert adapter.can_edit_visibility(prim) is False

    def test_can_edit_visibility_false_for_inactive_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        prim.SetActive(False)
        assert adapter.can_edit_visibility(prim) is False

    def test_can_edit_visibility_false_for_instance_proxy(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        proxy = _find_instance_proxy(stage)
        assert adapter.can_edit_visibility(proxy) is False

    def test_set_visibility_rejects_non_imageable_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.DefinePrim("/World/Untyped")
        with pytest.raises(ValueError):
            adapter.set_visibility(prim, False)


# ── Rename ────────────────────────────────────────────────────────────────────

class TestRename:
    def test_can_rename_normal_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        assert adapter.can_rename(prim) is True

    def test_can_rename_false_for_pseudo_root(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        pseudo_root = stage.GetPseudoRoot()
        assert adapter.can_rename(pseudo_root) is False

    def test_rename_changes_prim_path(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.rename(prim, "NewA")
        assert stage.GetPrimAtPath("/World/NewA").IsValid()
        assert not stage.GetPrimAtPath("/World/A").IsValid()

    def test_rename_returns_new_name(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        result = adapter.rename(prim, "NewA")
        assert result == "NewA"

    def test_rename_moves_children_with_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.rename(prim, "NewA")
        # Child should be accessible under new parent path
        assert stage.GetPrimAtPath("/World/NewA/Child").IsValid()

    def test_undo_restores_old_path(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.rename(prim, "NewA")
        assert stage.GetPrimAtPath("/World/NewA").IsValid()
        undo.undo()
        assert stage.GetPrimAtPath("/World/A").IsValid()
        assert not stage.GetPrimAtPath("/World/NewA").IsValid()

    def test_rename_fires_resync_notification(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        events = []
        sub = adapter.subscribe_changes(events.append)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.rename(prim, "NewA")
        assert len(events) == 1
        assert "/World/NewA" in events[0].resynced_paths

    def test_rename_no_undo_manager_executes_directly(self):
        stage = _make_stage()
        adapter = _make_adapter(stage, undo_manager=None)
        prim = stage.GetPrimAtPath("/World/A")
        adapter.rename(prim, "RenamedA")
        assert stage.GetPrimAtPath("/World/RenamedA").IsValid()


# ── Reparent ──────────────────────────────────────────────────────────────────

class TestReparent:
    def test_can_reparent_valid_pair(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        child = stage.GetPrimAtPath("/World/A/Child")
        new_parent = stage.GetPrimAtPath("/World/B")
        assert adapter.can_reparent([child], new_parent) is True

    def test_can_reparent_false_for_self(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        prim = stage.GetPrimAtPath("/World/A")
        assert adapter.can_reparent([prim], prim) is False

    def test_can_reparent_false_for_descendant_target(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        parent = stage.GetPrimAtPath("/World/A")
        child = stage.GetPrimAtPath("/World/A/Child")
        # Reparenting parent into its own child is invalid
        assert adapter.can_reparent([parent], child) is False

    def test_reparent_child_moves_prim_under_target(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        item = stage.GetPrimAtPath("/World/A/Child")
        new_parent = stage.GetPrimAtPath("/World/B")
        adapter.reparent([item], new_parent, ReparentPosition.CHILD)
        assert stage.GetPrimAtPath("/World/B/Child").IsValid()
        assert not stage.GetPrimAtPath("/World/A/Child").IsValid()

    def test_undo_restores_original_parent(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        item = stage.GetPrimAtPath("/World/A/Child")
        new_parent = stage.GetPrimAtPath("/World/B")
        adapter.reparent([item], new_parent, ReparentPosition.CHILD)
        assert stage.GetPrimAtPath("/World/B/Child").IsValid()
        undo.undo()
        assert stage.GetPrimAtPath("/World/A/Child").IsValid()
        assert not stage.GetPrimAtPath("/World/B/Child").IsValid()

    def test_reparent_fires_resync_notification(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        events = []
        sub = adapter.subscribe_changes(events.append)
        item = stage.GetPrimAtPath("/World/A/Child")
        new_parent = stage.GetPrimAtPath("/World/B")
        adapter.reparent([item], new_parent, ReparentPosition.CHILD)
        assert len(events) == 1
        assert "/World/B/Child" in events[0].resynced_paths

    def test_reparent_no_undo_manager_executes_directly(self):
        stage = _make_stage()
        adapter = _make_adapter(stage, undo_manager=None)
        item = stage.GetPrimAtPath("/World/A/Child")
        new_parent = stage.GetPrimAtPath("/World/B")
        adapter.reparent([item], new_parent, ReparentPosition.CHILD)
        assert stage.GetPrimAtPath("/World/B/Child").IsValid()

    def test_reparent_before_moves_to_sibling_parent(self):
        stage = _make_stage()
        adapter = _make_adapter(stage)
        item = stage.GetPrimAtPath("/World/A/Child")
        sibling_ref = stage.GetPrimAtPath("/World/B")
        # BEFORE: move to same parent as B (i.e., /World)
        adapter.reparent([item], sibling_ref, ReparentPosition.BEFORE)
        assert stage.GetPrimAtPath("/World/Child").IsValid()


# ── Undo groups ───────────────────────────────────────────────────────────────

class TestUndoGroups:
    def test_begin_end_group_single_undo_reverses_both(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        prim_a = stage.GetPrimAtPath("/World/A")
        prim_b = stage.GetPrimAtPath("/World/B")

        adapter.begin_undo_group("hide both")
        adapter.set_visibility(prim_a, False)
        adapter.set_visibility(prim_b, False)
        adapter.end_undo_group()

        assert adapter.compute_visibility(prim_a) == VisibilityState.INVISIBLE
        assert adapter.compute_visibility(prim_b) == VisibilityState.INVISIBLE

        # Single undo reverses both
        undo.undo()
        assert adapter.compute_visibility(prim_a) == VisibilityState.VISIBLE
        assert adapter.compute_visibility(prim_b) == VisibilityState.VISIBLE

    def test_group_is_one_undo_entry(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        prim = stage.GetPrimAtPath("/World/A")

        adapter.begin_undo_group("group")
        adapter.set_visibility(prim, False)
        adapter.end_undo_group()

        assert undo.can_undo() is True
        undo.undo()
        # After the single undo, nothing left on stack
        assert undo.can_undo() is False

    def test_begin_end_without_undo_manager_is_noop(self):
        stage = _make_stage()
        adapter = _make_adapter(stage, undo_manager=None)
        # Should not raise
        adapter.begin_undo_group("label")
        adapter.end_undo_group()

    def test_group_rename_and_visibility(self):
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        prim_a = stage.GetPrimAtPath("/World/A")

        adapter.begin_undo_group("rename and hide")
        adapter.rename(prim_a, "NewA")
        new_a = stage.GetPrimAtPath("/World/NewA")
        adapter.set_visibility(new_a, False)
        adapter.end_undo_group()

        assert stage.GetPrimAtPath("/World/NewA").IsValid()
        assert adapter.compute_visibility(new_a) == VisibilityState.INVISIBLE

        undo.undo()
        assert stage.GetPrimAtPath("/World/A").IsValid()
        assert not stage.GetPrimAtPath("/World/NewA").IsValid()


# ── UsdCommands unit tests ────────────────────────────────────────────────────

class TestSetVisibilityCommand:
    def test_do_makes_invisible(self):
        from ovui_data_adapters.openusd import SetVisibilityCommand
        stage = _make_stage()
        prim = stage.GetPrimAtPath("/World/A")
        cmd = SetVisibilityCommand(prim, False)
        cmd.do()
        assert UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible

    def test_undo_restores_no_authored_value(self):
        from ovui_data_adapters.openusd import SetVisibilityCommand
        stage = _make_stage()
        prim = stage.GetPrimAtPath("/World/A")
        cmd = SetVisibilityCommand(prim, False)
        cmd.do()
        cmd.undo()
        vis_attr = UsdGeom.Imageable(prim).GetVisibilityAttr()
        assert not vis_attr.HasAuthoredValue()

    def test_undo_restores_authored_invisible(self):
        from ovui_data_adapters.openusd import SetVisibilityCommand
        stage = _make_stage()
        prim = stage.GetPrimAtPath("/World/A")
        UsdGeom.Imageable(prim).MakeInvisible()
        cmd = SetVisibilityCommand(prim, True)
        cmd.do()
        assert UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.inherited
        cmd.undo()
        assert UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible


class TestNamespaceEditCommand:
    def test_do_renames_prim(self):
        from ovui_data_adapters.openusd import NamespaceEditCommand
        stage = _make_stage()
        layer = stage.GetEditTarget().GetLayer()
        old_path = Sdf.Path("/World/A")
        new_path = Sdf.Path("/World/NewA")
        cmd = NamespaceEditCommand(layer, old_path, new_path)
        cmd.do()
        assert stage.GetPrimAtPath("/World/NewA").IsValid()
        assert not stage.GetPrimAtPath("/World/A").IsValid()

    def test_undo_restores_original_path(self):
        from ovui_data_adapters.openusd import NamespaceEditCommand
        stage = _make_stage()
        layer = stage.GetEditTarget().GetLayer()
        old_path = Sdf.Path("/World/A")
        new_path = Sdf.Path("/World/NewA")
        cmd = NamespaceEditCommand(layer, old_path, new_path)
        cmd.do()
        cmd.undo()
        assert stage.GetPrimAtPath("/World/A").IsValid()
        assert not stage.GetPrimAtPath("/World/NewA").IsValid()
