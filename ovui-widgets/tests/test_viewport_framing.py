# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: stage-adapter AABB methods compute correct world bounds.

Step 26 (Rev 4 §10.5 / pre-planning §4.1, §8.3): the data-adapters
refactor moved the BBox iteration out of ``ViewportWidget`` into two
methods on ``UsdStageAdapter``:

  - :meth:`UsdStageAdapter.compute_world_aabb(paths)` — combined AABB
    across one or more prim paths; used by the F-frame keyboard
    shortcut to frame the current selection. Special-cases the
    pseudo-root ``"/"`` to mean "every top-level prim".

  - :meth:`UsdStageAdapter.compute_prim_world_aabb_with_extent_fallback(path)`
    — single-prim AABB that prefers ``UsdGeom.Boundable.
    ComputeExtentFromPlugins`` so a Property-panel ``radius`` / ``size``
    edit invalidates the cached ``extent`` attribute correctly. Falls
    back to ``UsdGeom.BBoxCache`` for non-Boundable selections (Xforms,
    Scopes).

These tests build small in-memory ``Usd.Stage`` instances and exercise
the methods against canonical shapes — the same Sphere / Cube / Xform
fixtures the original viewport-side helper used.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pxr")

from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
from pxr import Sdf, Usd, UsdGeom


def _new_stage_with_prims():
    """Build an in-memory stage with a Cube, Sphere, Xform, and Scope."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    world = UsdGeom.Xform.Define(stage, "/World")
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.GetSizeAttr().Set(2.0)  # default extent ±1.0 → world AABB ±1.0
    sphere = UsdGeom.Sphere.Define(stage, "/World/Sphere")
    sphere.GetRadiusAttr().Set(1.0)
    xform = UsdGeom.Xform.Define(stage, "/World/EmptyXform")
    scope = UsdGeom.Scope.Define(stage, "/World/Group")
    return stage, world, cube, sphere, xform, scope


@pytest.fixture
def adapter():
    stage, *_ = _new_stage_with_prims()
    return UsdStageAdapter(stage)


# ---------------------------------------------------------------------------
# compute_world_aabb
# ---------------------------------------------------------------------------


def test_compute_world_aabb_empty_paths_returns_none(adapter):
    """No paths → ``None``; the caller falls back to default framing."""
    assert adapter.compute_world_aabb([]) is None


def test_compute_world_aabb_single_cube_returns_unit_extent(adapter):
    """A size-2 Cube has world AABB ±1.0 on every axis."""
    aabb = adapter.compute_world_aabb(["/World/Cube"])
    assert aabb is not None
    minp, maxp = aabb
    assert minp == pytest.approx((-1.0, -1.0, -1.0))
    assert maxp == pytest.approx((1.0, 1.0, 1.0))


def test_compute_world_aabb_pseudo_root_combines_top_level_prims(adapter):
    """``"/"`` means "every top-level prim" — the pseudo-root path."""
    aabb = adapter.compute_world_aabb(["/"])
    assert aabb is not None
    # ``/World`` contains Cube (±1) + Sphere (±1) + an empty Xform/Scope;
    # combined world AABB stays within ±1 (Cube and Sphere coincide at
    # origin in this fixture).
    minp, maxp = aabb
    for axis in range(3):
        assert minp[axis] <= maxp[axis], "AABB inverted"
        assert minp[axis] <= -0.999  # at least Cube/Sphere ±1 contribution
        assert maxp[axis] >= 0.999


def test_compute_world_aabb_multi_prim_selection_unions_bounds(adapter):
    """Multi-path AABB unions per-prim bounds — same result as ``"/World"``."""
    aabb = adapter.compute_world_aabb(["/World/Cube", "/World/Sphere"])
    assert aabb is not None
    minp, maxp = aabb
    assert minp == pytest.approx((-1.0, -1.0, -1.0), abs=1e-6)
    assert maxp == pytest.approx((1.0, 1.0, 1.0), abs=1e-6)


def test_compute_world_aabb_invalid_path_yields_none_or_skips(adapter):
    """An unknown path contributes nothing — adapter must not crash."""
    aabb = adapter.compute_world_aabb(["/Nonexistent"])
    # Implementation returns ``None`` when no prim contributes — see
    # ``compute_world_aabb`` rng.IsEmpty() branch.
    assert aabb is None


def test_compute_world_aabb_no_stage_returns_none():
    """A stageless adapter returns ``None`` rather than raising."""
    adapter = UsdStageAdapter.__new__(UsdStageAdapter)
    adapter._stage = None
    assert adapter.compute_world_aabb(["/World/Cube"]) is None


# ---------------------------------------------------------------------------
# compute_prim_world_aabb_with_extent_fallback
# ---------------------------------------------------------------------------


def test_extent_fallback_sphere_default_radius(adapter):
    """Default Sphere (radius=1) → world AABB ±1.0."""
    aabb = adapter.compute_prim_world_aabb_with_extent_fallback("/World/Sphere")
    assert aabb is not None
    minp, maxp = aabb
    assert minp == pytest.approx((-1.0, -1.0, -1.0))
    assert maxp == pytest.approx((1.0, 1.0, 1.0))


def test_extent_fallback_sphere_after_radius_edit(adapter):
    """Editing ``radius`` must invalidate the cached extent so framing
    reflects the new size — the whole reason the method prefers
    ``ComputeExtentFromPlugins`` over a stale ``BBoxCache`` lookup.
    """
    stage = adapter._stage
    sphere = UsdGeom.Sphere(stage.GetPrimAtPath("/World/Sphere"))
    sphere.GetRadiusAttr().Set(2.5)
    aabb = adapter.compute_prim_world_aabb_with_extent_fallback("/World/Sphere")
    assert aabb is not None
    minp, maxp = aabb
    assert minp == pytest.approx((-2.5, -2.5, -2.5), abs=1e-6)
    assert maxp == pytest.approx((2.5, 2.5, 2.5), abs=1e-6)


def test_extent_fallback_non_boundable_xform_falls_back_to_bboxcache(adapter):
    """``/World/EmptyXform`` is not Boundable; the BBoxCache fallback kicks
    in and (since the Xform has no children with extent) returns ``None``.
    """
    aabb = adapter.compute_prim_world_aabb_with_extent_fallback(
        "/World/EmptyXform"
    )
    assert aabb is None


def test_extent_fallback_non_boundable_scope_falls_back(adapter):
    """``Scope`` is also non-Boundable; same fallback path as Xform."""
    aabb = adapter.compute_prim_world_aabb_with_extent_fallback("/World/Group")
    assert aabb is None


def test_extent_fallback_invalid_path_returns_none(adapter):
    """An unknown path returns ``None`` — caller handles missing geometry."""
    aabb = adapter.compute_prim_world_aabb_with_extent_fallback(
        "/World/NotReal"
    )
    assert aabb is None


def test_extent_fallback_no_stage_returns_none():
    """A stageless adapter returns ``None`` rather than raising."""
    adapter = UsdStageAdapter.__new__(UsdStageAdapter)
    adapter._stage = None
    assert (
        adapter.compute_prim_world_aabb_with_extent_fallback("/World/Cube")
        is None
    )
