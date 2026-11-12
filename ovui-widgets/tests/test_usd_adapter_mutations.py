# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for UsdStageAdapter mutations: visibility, rename, reparent, undo."""

import pytest

from pxr import Sdf, Usd, UsdGeom, UsdShade

from ovui_data_adapters.common import ReparentPosition, VisibilityState

from ovui_widgets.common.undo import UndoManager


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
        # Event paths derive from the genuine USD notices: the visibility
        # property path, plus the adapter-owned semantic delta.
        assert "/World/A.visibility" in events[0].changed_paths
        delta = events[0].visibility_delta
        assert delta is not None
        assert "/World/A" in delta["authored"]

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

    def test_rename_to_an_invalid_name_keeps_the_prim_with_a_valid_name(self):
        # "a b/c" is not a prim name. The prim and its child stay, under a
        # valid name made from the text, and undo and redo move them.
        stage = _make_stage()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        events = []
        sub = adapter.subscribe_changes(events.append)

        used = adapter.rename(stage.GetPrimAtPath("/World/A"), "a b/c")

        assert used == "a_b_c"
        assert {p.GetName() for p in stage.GetPrimAtPath("/World").GetChildren()} == {"a_b_c", "B"}
        assert stage.GetPrimAtPath("/World/a_b_c/Child").IsValid()
        assert events[-1].resynced_paths == ("/World/a_b_c",)

        undo.undo()
        assert [p.GetName() for p in stage.GetPrimAtPath("/World").GetChildren()] == ["A", "B"]
        assert stage.GetPrimAtPath("/World/A/Child").IsValid()

        undo.redo()
        assert {p.GetName() for p in stage.GetPrimAtPath("/World").GetChildren()} == {"a_b_c", "B"}
        assert stage.GetPrimAtPath("/World/a_b_c/Child").IsValid()

    def test_rename_to_a_name_that_starts_with_a_digit_keeps_the_prim(self):
        stage = _make_stage()
        adapter = _make_adapter(stage, UndoManager())

        used = adapter.rename(stage.GetPrimAtPath("/World/A"), "1st")

        assert used == "_1st"
        assert stage.GetPrimAtPath("/World/_1st/Child").IsValid()
        assert not stage.GetPrimAtPath("/World/A").IsValid()

    def test_rename_to_a_text_whose_valid_name_is_the_current_name_changes_nothing(self):
        stage = _make_stage()
        stage.DefinePrim("/World/a_b/Child", "Mesh")
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        events = []
        sub = adapter.subscribe_changes(events.append)

        used = adapter.rename(stage.GetPrimAtPath("/World/a_b"), "a b")

        assert used == "a_b"
        assert stage.GetPrimAtPath("/World/a_b/Child").IsValid()
        assert not undo.can_undo()
        assert events == []

    def test_rename_refuses_a_text_that_gives_no_valid_name(self):
        stage = _make_stage()
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)

        with pytest.raises(ValueError, match="No valid prim name"):
            adapter.rename(stage.GetPrimAtPath("/World/A"), "")

        assert layer.ExportToString() == before
        assert not undo.can_undo()

    @pytest.mark.parametrize("text, message", [
        ("Robot Arm Adjust",
         "The prim /World/Robot_Arm_Adjust already exists "
         "('Robot Arm Adjust' gives the name 'Robot_Arm_Adjust')"),
        ("Robot_Arm_Adjust", "The prim /World/Robot_Arm_Adjust already exists"),
    ])
    def test_rename_refuses_a_name_that_a_sibling_has(self, text, message):
        # Sdf does not move a prim onto an existing prim. The rename must
        # fail with the reason, not return the name as if it was used.
        stage = _make_stage()
        stage.DefinePrim("/World/Robot_Arm_Adjust/Arm", "Mesh")
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        events = []
        sub = adapter.subscribe_changes(events.append)

        with pytest.raises(ValueError) as error:
            adapter.rename(stage.GetPrimAtPath("/World/A"), text)

        assert str(error.value) == message
        assert layer.ExportToString() == before
        assert stage.GetPrimAtPath("/World/A/Child").IsValid()
        assert stage.GetPrimAtPath("/World/Robot_Arm_Adjust/Arm").IsValid()
        assert not undo.can_undo()
        assert events == []

    def test_rename_refuses_a_name_that_a_prim_of_a_sublayer_has(self):
        # The edited layer has no spec at the new path, so Sdf would do the
        # move, and the stage would merge A into the prim of the sublayer.
        sublayer = Sdf.Layer.CreateAnonymous()
        Usd.Stage.Open(sublayer).DefinePrim("/World/Robot_Arm_Adjust/Arm", "Mesh")
        stage = _make_stage()
        stage.GetRootLayer().subLayerPaths.append(sublayer.identifier)
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)

        with pytest.raises(ValueError, match="The prim /World/Robot_Arm_Adjust already exists"):
            adapter.rename(stage.GetPrimAtPath("/World/A"), "Robot Arm Adjust")

        assert layer.ExportToString() == before
        assert stage.GetPrimAtPath("/World/A/Child").IsValid()
        robot = stage.GetPrimAtPath("/World/Robot_Arm_Adjust")
        assert [child.GetName() for child in robot.GetChildren()] == ["Arm"]
        assert not undo.can_undo()

    def test_rename_refuses_a_prim_that_the_edited_layer_does_not_hold(self):
        # Only the sublayer has a spec of C, so Sdf cannot move it in the
        # edited layer. The rename must fail with the reason of Sdf.
        sublayer = Sdf.Layer.CreateAnonymous()
        Usd.Stage.Open(sublayer).DefinePrim("/World/C/Part", "Mesh")
        stage = _make_stage()
        stage.GetRootLayer().subLayerPaths.append(sublayer.identifier)
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)

        with pytest.raises(ValueError, match="cannot rename /World/C to 'c_d': .+"):
            adapter.rename(stage.GetPrimAtPath("/World/C"), "c d")

        assert layer.ExportToString() == before
        assert stage.GetPrimAtPath("/World/C/Part").IsValid()
        assert not stage.GetPrimAtPath("/World/c_d").IsValid()
        assert not undo.can_undo()


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


# ── Reparent into a native instance ───────────────────────────────────────────

_INSTANCE_REFUSAL = "Inst is an instance, and USD does not show prims under an instance"


def _make_instance_stage():
    """``/World/Inst`` is a native instance of ``/World/Proto``."""
    stage = _make_stage()
    proto = stage.DefinePrim("/World/Proto", "Xform")
    stage.DefinePrim("/World/Proto/Post", "Cylinder")
    inst = stage.DefinePrim("/World/Inst", "Xform")
    inst.GetReferences().AddInternalReference(proto.GetPath())
    inst.SetInstanceable(True)
    stage.DefinePrim("/World/Cube", "Cube")
    assert inst.IsInstance()
    return stage


class TestReparentIntoInstance:
    def test_native_instance_root_is_refused_with_reason(self):
        stage = _make_instance_stage()
        adapter = _make_adapter(stage)
        cube = stage.GetPrimAtPath("/World/Cube")
        inst = stage.GetPrimAtPath("/World/Inst")
        assert adapter.can_reparent([cube], inst) is False
        assert adapter.get_reparent_refusal_reason([cube], inst) == _INSTANCE_REFUSAL

    def test_prim_inside_an_instance_is_refused_with_reason(self):
        stage = _make_instance_stage()
        adapter = _make_adapter(stage)
        cube = stage.GetPrimAtPath("/World/Cube")
        post = stage.GetPrimAtPath("/World/Inst/Post")
        assert post.IsInstanceProxy()
        assert adapter.can_reparent([cube], post) is False
        assert adapter.get_reparent_refusal_reason([cube], post) == (
            "Post is inside an instance, and USD does not show prims under an instance"
        )

    def test_prototype_and_instanceable_prim_without_arcs_stay_valid(self):
        stage = _make_instance_stage()
        adapter = _make_adapter(stage)
        cube = stage.GetPrimAtPath("/World/Cube")
        proto = stage.GetPrimAtPath("/World/Proto")
        # instanceable metadata without a composition arc makes no instance.
        flagged = stage.DefinePrim("/World/Flagged", "Xform")
        flagged.SetInstanceable(True)
        assert not flagged.IsInstance()
        for target in (proto, flagged):
            assert adapter.can_reparent([cube], target) is True
            assert adapter.get_reparent_refusal_reason([cube], target) == ""

    def test_move_of_the_instance_into_itself_has_no_reason(self):
        stage = _make_instance_stage()
        adapter = _make_adapter(stage)
        inst = stage.GetPrimAtPath("/World/Inst")
        assert adapter.can_reparent([inst], inst) is False
        assert adapter.get_reparent_refusal_reason([inst], inst) == ""


# ── Links to a moved prim ─────────────────────────────────────────────────────

def _make_bound_material_stage():
    """A material, connected to its shader, bound to a cube and a torus."""
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World", "Xform")
    stage.DefinePrim("/World/Xform", "Xform")
    material = UsdShade.Material.Define(stage, "/World/Looks/M")
    shader = UsdShade.Shader.Define(stage, "/World/Looks/M/Shader")
    material.CreateSurfaceOutput().ConnectToSource(
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    )
    for path in ("/World/Cube", "/World/Torus"):
        prim = stage.DefinePrim(path, "Mesh")
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
    # A list op that is not explicit: the undo must restore it too.
    stage.GetPrimAtPath("/World/Torus").CreateRelationship("look").AddTarget(
        "/World/Looks/M/Shader"
    )
    return stage


def _bound_material_path(stage, path):
    prim = stage.GetPrimAtPath(path)
    material, _relationship = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


def _surface_source_path(stage, material_path):
    material = UsdShade.Material(stage.GetPrimAtPath(material_path))
    sources, _invalid = material.GetSurfaceOutput().GetConnectedSources()
    return str(sources[0].source.GetPath()) if sources else None


# The sublayer defines the material Blue.
_MIXED_SUBLAYER = """#usda 1.0
def Xform "World"
{
    def Scope "Looks"
    {
        def Material "Blue"
        {
        }
    }
}
"""

# The root layer defines the material Red in the same folder, and has only an
# over of Blue.
_MIXED_ROOT = """#usda 1.0
(
    subLayers = [@./sub.usda@]
)

def Xform "World"
{
    def Scope "Looks"
    {
        def Material "Red"
        {
            token outputs:surface.connect = </World/Looks/Red/Shader.outputs:surface>

            def Shader "Shader"
            {
                token outputs:surface
            }
        }

        over "Blue"
        {
        }
    }

    def Cube "RedCube" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </World/Looks/Red>
    }

    def Cube "BlueCube" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </World/Looks/Blue>
    }
}
"""

# Lists that are not explicit, as a text layer keeps them: without target or
# connection child specs.
_LIST_OP_LINKS = """#usda 1.0
def Xform "World"
{
    def Scope "Looks"
    {
        def Material "M"
        {
            prepend token outputs:surface.connect = </World/Looks/M/Shader.outputs:surface>

            def Shader "Shader"
            {
                token outputs:surface
            }
        }
    }

    def Cube "Cube" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        prepend rel material:binding = </World/Looks/M>
        prepend rel look = </World/Looks/M>
        append rel looks = [</World/Looks/M>, </World/Looks/M/Shader>]
        prepend token userLink.connect = </World/Looks/M/Shader.outputs:surface>
    }
}
"""


class TestMovedPrimKeepsLinks:
    def test_rename_keeps_material_binding_and_undo_redo(self):
        stage = _make_bound_material_stage()
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        events = []
        sub = adapter.subscribe_changes(events.append)

        adapter.rename(stage.GetPrimAtPath("/World/Looks/M"), "Glass2")

        assert _bound_material_path(stage, "/World/Cube") == "/World/Looks/Glass2"
        assert _bound_material_path(stage, "/World/Torus") == "/World/Looks/Glass2"
        assert _surface_source_path(stage, "/World/Looks/Glass2") == "/World/Looks/Glass2/Shader"
        look = stage.GetPrimAtPath("/World/Torus").GetRelationship("look")
        assert look.GetTargets() == [Sdf.Path("/World/Looks/Glass2/Shader")]
        assert "/World/Cube.material:binding" in events[-1].changed_paths
        assert "/World/Torus.material:binding" in events[-1].changed_paths

        undo.undo()
        assert layer.ExportToString() == before

        undo.redo()
        assert _bound_material_path(stage, "/World/Cube") == "/World/Looks/Glass2"
        assert _bound_material_path(stage, "/World/Torus") == "/World/Looks/Glass2"

    def test_reparent_keeps_material_binding_and_undo(self):
        stage = _make_bound_material_stage()
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)

        adapter.reparent(
            [stage.GetPrimAtPath("/World/Looks/M")],
            stage.GetPrimAtPath("/World/Xform"),
            ReparentPosition.CHILD,
        )

        assert _bound_material_path(stage, "/World/Cube") == "/World/Xform/M"
        assert _bound_material_path(stage, "/World/Torus") == "/World/Xform/M"
        assert _surface_source_path(stage, "/World/Xform/M") == "/World/Xform/M/Shader"

        undo.undo()
        assert layer.ExportToString() == before

    def test_reparent_of_two_prims_reports_the_current_property_paths(self):
        stage = _make_bound_material_stage()
        adapter = _make_adapter(stage, UndoManager())
        events = []
        sub = adapter.subscribe_changes(events.append)

        # The move of M changes the binding of the cube; then the cube moves.
        adapter.reparent(
            [stage.GetPrimAtPath("/World/Looks/M"), stage.GetPrimAtPath("/World/Cube")],
            stage.GetPrimAtPath("/World/Xform"),
            ReparentPosition.CHILD,
        )

        assert _bound_material_path(stage, "/World/Xform/Cube") == "/World/Xform/M"
        changed = events[-1].changed_paths
        assert "/World/Xform/Cube.material:binding" in changed
        assert "/World/Cube.material:binding" not in changed

    def test_rename_of_scope_that_holds_the_material_keeps_binding(self):
        stage = _make_bound_material_stage()
        adapter = _make_adapter(stage, UndoManager())

        adapter.rename(stage.GetPrimAtPath("/World/Looks"), "Materials")

        assert _bound_material_path(stage, "/World/Cube") == "/World/Materials/M"
        assert _surface_source_path(stage, "/World/Materials/M") == "/World/Materials/M/Shader"

    def test_rename_of_an_over_of_the_material_keeps_binding_target(self):
        # The sublayer defines the material. The edited layer has only an
        # over of it and the binding. The rename moves the over only, so the
        # material stays at its path, and so must the binding.
        sublayer = Sdf.Layer.CreateAnonymous()
        sub_stage = Usd.Stage.Open(sublayer)
        UsdShade.Material.Define(sub_stage, "/World/Looks/M")
        stage = Usd.Stage.CreateInMemory()
        stage.GetRootLayer().subLayerPaths.append(sublayer.identifier)
        Sdf.CreatePrimInLayer(stage.GetRootLayer(), "/World/Looks/M")
        cube = stage.DefinePrim("/World/Cube", "Mesh")
        UsdShade.MaterialBindingAPI.Apply(cube).Bind(
            UsdShade.Material(stage.GetPrimAtPath("/World/Looks/M"))
        )
        adapter = _make_adapter(stage, UndoManager())

        adapter.rename(stage.GetPrimAtPath("/World/Looks/M"), "Glass2")

        assert _bound_material_path(stage, "/World/Cube") == "/World/Looks/M"

    def test_rename_of_a_folder_with_a_local_and_a_sublayer_material(self, tmp_path):
        # The rename of the folder moves Red. Blue stays at its path in the
        # sublayer, so the binding of BlueCube must keep that path.
        (tmp_path / "sub.usda").write_text(_MIXED_SUBLAYER)
        (tmp_path / "root.usda").write_text(_MIXED_ROOT)
        stage = Usd.Stage.Open(str(tmp_path / "root.usda"))
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        events = []
        sub = adapter.subscribe_changes(events.append)

        adapter.rename(stage.GetPrimAtPath("/World/Looks"), "Materials")

        assert _bound_material_path(stage, "/World/RedCube") == "/World/Materials/Red"
        assert _bound_material_path(stage, "/World/BlueCube") == "/World/Looks/Blue"
        assert _surface_source_path(stage, "/World/Materials/Red") == "/World/Materials/Red/Shader"
        assert "/World/BlueCube.material:binding" not in events[-1].changed_paths

        undo.undo()
        assert layer.ExportToString() == before

        undo.redo()
        assert _bound_material_path(stage, "/World/RedCube") == "/World/Materials/Red"
        assert _bound_material_path(stage, "/World/BlueCube") == "/World/Looks/Blue"

    def test_rename_of_a_bound_material_to_an_invalid_name_keeps_it_bound(self):
        # "a b/c" is not a prim name. The material gets the valid name
        # "a_b_c" and stays bound. The edit is on the undo stack with its
        # event, and undo puts back the layer as it was.
        stage = _make_bound_material_stage()
        layer = stage.GetRootLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)
        events = []
        sub = adapter.subscribe_changes(events.append)

        adapter.rename(stage.GetPrimAtPath("/World/Looks/M"), "a b/c")

        assert _bound_material_path(stage, "/World/Cube") == "/World/Looks/a_b_c"
        assert undo.can_undo()
        assert len(events) == 1
        assert "/World/Cube.material:binding" in events[0].changed_paths

        undo.undo()
        assert layer.ExportToString() == before

        undo.redo()
        assert _bound_material_path(stage, "/World/Cube") == "/World/Looks/a_b_c"

    def test_rename_repairs_list_op_links_read_from_a_text_layer(self):
        layer = Sdf.Layer.CreateAnonymous(".usda")
        layer.ImportFromString(_LIST_OP_LINKS)
        stage = Usd.Stage.Open(layer)
        before = layer.ExportToString()
        undo = UndoManager()
        adapter = _make_adapter(stage, undo)

        adapter.rename(stage.GetPrimAtPath("/World/Looks/M"), "Glass2")

        cube = stage.GetPrimAtPath("/World/Cube")
        assert _bound_material_path(stage, "/World/Cube") == "/World/Looks/Glass2"
        assert cube.GetRelationship("look").GetTargets() == [Sdf.Path("/World/Looks/Glass2")]
        assert cube.GetRelationship("looks").GetTargets() == [
            Sdf.Path("/World/Looks/Glass2"),
            Sdf.Path("/World/Looks/Glass2/Shader"),
        ]
        assert cube.GetAttribute("userLink").GetConnections() == [
            Sdf.Path("/World/Looks/Glass2/Shader.outputs:surface")
        ]
        assert _surface_source_path(stage, "/World/Looks/Glass2") == "/World/Looks/Glass2/Shader"

        undo.undo()
        assert layer.ExportToString() == before

    def test_only_a_move_of_a_shading_prim_scans_the_layer(self, monkeypatch):
        from ovui_data_adapters.openusd import NamespaceEditCommand, commands

        scans = []
        retarget = commands._retarget_moved_paths

        def _counted(layer, stage, old_path, new_path):
            scans.append(str(old_path))
            return retarget(layer, stage, old_path, new_path)

        monkeypatch.setattr(commands, "_retarget_moved_paths", _counted)
        stage = _make_bound_material_stage()
        stage.DefinePrim("/World/Group/Mesh", "Mesh")
        adapter = _make_adapter(stage, UndoManager())

        adapter.rename(stage.GetPrimAtPath("/World/Cube"), "Box")
        adapter.reparent(
            [stage.GetPrimAtPath("/World/Group")],
            stage.GetPrimAtPath("/World/Xform"),
            ReparentPosition.CHILD,
        )
        assert scans == []

        adapter.rename(stage.GetPrimAtPath("/World/Looks/M"), "Glass2")
        assert scans == ["/World/Looks/M"]

        # Without a stage, the command cannot tell which links a move
        # breaks, so it moves only the specs.
        NamespaceEditCommand(
            stage.GetRootLayer(), Sdf.Path("/World/Looks"), Sdf.Path("/World/Materials")
        ).do()
        assert scans == ["/World/Looks/M"]
        binding = stage.GetPrimAtPath("/World/Box").GetRelationship("material:binding")
        assert binding.GetTargets() == [Sdf.Path("/World/Looks/Glass2")]


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
        assert [p.GetName() for p in stage.GetPrimAtPath("/World").GetChildren()] == ["A", "B"]

    def test_push_refuses_a_new_path_that_is_not_a_prim_path(self):
        # An invalid name gives the empty path. Sdf would remove the prim,
        # and undo could not bring it back.
        from ovui_data_adapters.openusd import NamespaceEditCommand
        stage = _make_stage()
        layer = stage.GetEditTarget().GetLayer()
        before = layer.ExportToString()
        undo = UndoManager()
        cmd = NamespaceEditCommand(layer, Sdf.Path("/World/A"), Sdf.Path(), stage=stage)

        with pytest.raises(ValueError, match="not a prim path"):
            undo.push(cmd)

        assert layer.ExportToString() == before
        assert stage.GetPrimAtPath("/World/A/Child").IsValid()
        assert not undo.can_undo()
