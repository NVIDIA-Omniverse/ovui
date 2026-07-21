# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Smoke tests for shared ovstage-provider fixture data and runtime markers."""

from __future__ import annotations

import pathlib

import pytest
from pxr import Usd, UsdGeom, UsdPhysics

import conftest as adapter_pytest_config


def _open_stage(path: pathlib.Path) -> Usd.Stage:
    stage = Usd.Stage.Open(str(path))
    assert stage is not None, f"OpenUSD could not load {path}"
    return stage


def test_static_fixture_loads_current_openusd(
    ovstage_static_scene_path: pathlib.Path,
) -> None:
    stage = _open_stage(ovstage_static_scene_path)

    assert Usd.GetVersion() == (0, 25, 11)
    assert stage.GetDefaultPrim().GetPath() == "/World"
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y

    required_paths = {
        "/World/Hierarchy/GroupA/BoxA",
        "/World/Hierarchy/GroupA/BallA",
        "/World/Hierarchy/GroupB/TriangleMesh",
        "/World/TransformCases/TranslateOnly",
        "/World/TransformCases/RotateScale",
        "/World/TransformCases/MatrixOnly",
        "/World/TransformCases/NestedParent/NestedChild",
        "/World/VisibilityCases/HiddenParent/InheritedHiddenChild",
        "/World/VisibilityCases/VisibleParent/ExplicitHiddenChild",
        "/World/VisibilityCases/VisibleParent/InheritedVisibleChild",
        "/World/AttributeCases/MirroredValues",
        "/World/Cameras/MainCamera",
    }
    traversed_paths = {str(prim.GetPath()) for prim in stage.Traverse()}
    assert required_paths <= traversed_paths

    translate_only = UsdGeom.Xformable(
        stage.GetPrimAtPath("/World/TransformCases/TranslateOnly")
    )
    translate_ops = translate_only.GetOrderedXformOps()
    assert [op.GetOpName() for op in translate_ops] == ["xformOp:translate"]
    assert tuple(translate_ops[0].Get()) == (1.0, 2.0, 3.0)

    hidden_parent = UsdGeom.Imageable(
        stage.GetPrimAtPath("/World/VisibilityCases/HiddenParent")
    )
    hidden_child = UsdGeom.Imageable(
        stage.GetPrimAtPath(
            "/World/VisibilityCases/VisibleParent/ExplicitHiddenChild"
        )
    )
    assert hidden_parent.GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible
    assert hidden_child.GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible

    mirrored = stage.GetPrimAtPath("/World/AttributeCases/MirroredValues")
    assert mirrored.GetAttribute("test:enabled").Get() is True
    assert mirrored.GetAttribute("test:count").Get() == 7
    assert tuple(mirrored.GetAttribute("test:offset").Get()) == (1.0, 2.0, 3.0)
    assert mirrored.GetAttribute("test:mode").Get() == "preview"
    assert list(mirrored.GetAttribute("test:indices").Get()) == [0, 2, 4, 8]
    assert tuple(mirrored.GetAttribute("test:matrix").Get()[3]) == (
        9.0,
        8.0,
        7.0,
        1.0,
    )

    camera = UsdGeom.Camera.Get(stage, "/World/Cameras/MainCamera")
    assert camera.GetPrim().IsValid()
    assert camera.GetFocalLengthAttr().Get() == 35.0


def test_physics_fixture_loads_current_openusd(
    ovstage_physics_scene_path: pathlib.Path,
) -> None:
    stage = _open_stage(ovstage_physics_scene_path)

    physics_scene = UsdPhysics.Scene.Get(stage, "/World/PhysicsScene")
    assert physics_scene.GetPrim().IsValid()
    assert tuple(physics_scene.GetGravityDirectionAttr().Get()) == (
        0.0,
        -1.0,
        0.0,
    )
    assert physics_scene.GetGravityMagnitudeAttr().Get() == pytest.approx(9.81)

    ground = stage.GetPrimAtPath("/World/Ground")
    dynamic_cube = stage.GetPrimAtPath("/World/DynamicCube")
    assert UsdPhysics.CollisionAPI(ground).GetCollisionEnabledAttr().Get() is True
    assert UsdPhysics.CollisionAPI(dynamic_cube).GetCollisionEnabledAttr().Get() is True
    assert (
        UsdPhysics.RigidBodyAPI(dynamic_cube).GetRigidBodyEnabledAttr().Get()
        is True
    )
    assert UsdPhysics.MassAPI(dynamic_cube).GetMassAttr().Get() == 1.0


@pytest.mark.requires_ovstage
def test_requires_ovstage_marker_runs_when_runtime_is_available() -> None:
    import ovstage

    assert ovstage.__name__ == "ovstage"
    assert callable(ovstage.population.open_usd)


@pytest.mark.requires_ovphysx
def test_requires_ovphysx_marker_runs_when_runtime_is_available() -> None:
    import ovphysx

    assert ovphysx.__name__ == "ovphysx"


@pytest.mark.requires_ovrtx
def test_requires_ovrtx_marker_runs_when_runtime_is_available() -> None:
    import ovrtx

    assert ovrtx.__name__ == "ovrtx"


def test_runtime_marker_skip_reason_reports_missing_modules(monkeypatch) -> None:
    def fake_find_spec(name: str):
        if name == "ovrtx":
            return None
        return object()

    monkeypatch.setattr(
        adapter_pytest_config.importlib.util,
        "find_spec",
        fake_find_spec,
    )

    assert (
        adapter_pytest_config.runtime_skip_reason("requires_ovrtx")
        == "requires_ovrtx: missing runtime module(s): ovrtx"
    )
    assert adapter_pytest_config.runtime_skip_reason("requires_ovphysx") is None


def test_runtime_marker_rejects_collection_namespace_package(monkeypatch) -> None:
    class NamespaceSpec:
        loader = None
        origin = None
        submodule_search_locations = [str(pathlib.Path(__file__).parent / "ovstage")]

    monkeypatch.setattr(
        adapter_pytest_config.importlib.util,
        "find_spec",
        lambda name: NamespaceSpec() if name == "ovstage" else object(),
    )

    assert adapter_pytest_config.missing_runtime_modules("requires_ovstage") == (
        "ovstage",
    )
    assert adapter_pytest_config.runtime_skip_reason("requires_ovstage") == (
        "requires_ovstage: missing runtime module(s): ovstage"
    )


def test_collection_hook_marks_runtime_tests_skipped_when_missing(monkeypatch) -> None:
    def fake_find_spec(name: str):
        if name == "ovstage":
            return None
        return object()

    class DummyItem:
        keywords = {"requires_ovstage": True}

        def __init__(self) -> None:
            self.added_markers = []

        def add_marker(self, marker) -> None:
            self.added_markers.append(marker)

    item = DummyItem()
    monkeypatch.setattr(
        adapter_pytest_config.importlib.util,
        "find_spec",
        fake_find_spec,
    )

    adapter_pytest_config.pytest_collection_modifyitems(None, [item])

    assert len(item.added_markers) == 1
    added_marker = item.added_markers[0].mark
    assert added_marker.name == "skip"
    assert added_marker.kwargs["reason"] == (
        "requires_ovstage: missing runtime module(s): ovstage"
    )
