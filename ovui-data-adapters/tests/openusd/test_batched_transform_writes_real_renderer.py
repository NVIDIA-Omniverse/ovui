# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Transforms that one stage change moves reach ovrtx in one write call.

An application that moves many prims each frame (for example 100 actors) made
one ovrtx write call for each prim; each call has a fixed cost. The moved
transforms go to ovrtx in one call. A failed call, and a prim whose local
transform cannot be computed, are reported once while they repeat, and again
after a change without a failure.

Each test runs in a process of its own with the real renderer. The actors sit
under a moved parent, so a world matrix in place of the local one is caught.
"""

from __future__ import annotations

import numpy as np
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_ACTORS = [f"/World/Actor{i}" for i in range(12)]
_BAD = "/World/Bad"

_VIEW = np.identity(4)
_VIEW[3, 2] = -200.0
_PROJECTION = np.array(
    [[1.0, 0.0, 0.0, 0.0], [0.0, 2.0, 0.0, 0.0], [0.0, 0.0, -1.0, -1.0], [0.0, 0.0, -2.0, 0.0]]
)


class _CountingRenderer:
    """The real ovrtx renderer; records the prim paths of each ``omni:xform`` write.

    ``refusals`` holds one value for each ``omni:xform`` write: True refuses
    that write, as a failing renderer does.
    """

    def __init__(self, renderer, refusals=()):
        self._renderer = renderer
        self._refusals = list(refusals)
        self.transform_writes = []

    def write_attribute(self, *args, **kwargs):
        if kwargs.get("attribute_name") == "omni:xform":
            self.transform_writes.append(sorted(kwargs["prim_paths"]))
            if self._refusals and self._refusals.pop(0):
                raise RuntimeError("write refused")
        return self._renderer.write_attribute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._renderer, name)


def _scene(tmp_path, with_bad: bool):
    path = tmp_path / "actors.usda"
    stage = Usd.Stage.CreateNew(str(path))
    world = UsdGeom.Xform.Define(stage, "/World")
    # A moved parent: the local matrix of each actor differs from its world matrix.
    world.AddTranslateOp().Set(Gf.Vec3d(100.0, 0.0, 0.0))
    stage.SetDefaultPrim(world.GetPrim())
    for actor in _ACTORS:
        UsdGeom.Xform.Define(stage, actor).AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))
        UsdGeom.Cube.Define(stage, actor + "/Body")
    if with_bad:
        # A translate op of the wrong value type: its local transform cannot be computed.
        bad = UsdGeom.Xform.Define(stage, _BAD)
        bad.GetPrim().CreateAttribute("xformOp:translate", Sdf.ValueTypeNames.String).Set("start")
        bad.GetXformOpOrderAttr().Set(["xformOp:translate"])
    stage.GetRootLayer().Save()
    return Usd.Stage.Open(str(path))


def _move(stage, offset: float, with_bad: bool):
    with Sdf.ChangeBlock():
        for index, path in enumerate(_ACTORS):
            UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()[0].Set(
                Gf.Vec3d(offset + index, 2.0 * index, -float(index))
            )
        if with_bad:
            stage.GetPrimAtPath(_BAD).GetAttribute("xformOp:translate").Set(f"moved {offset}")


def _expected(offset: float):
    return [(offset + index, 2.0 * index, -float(index)) for index in range(len(_ACTORS))]


def _renderer_translations(adapter, paths):
    matrices = np.from_dlpack(adapter._renderer.read_attribute("omni:xform", list(paths))).reshape(-1, 4, 4)
    return [tuple(float(v) for v in matrix[3, :3]) for matrix in matrices]


def _run(tmp_path, offsets, refusals=(), with_bad: bool = False):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

    stage = _scene(tmp_path, with_bad)
    queued = []
    stage_adapter = UsdStageAdapter(stage, call_later=lambda delay, callback: queued.append(callback))
    adapter = OvRtxRendererAdapter()
    subscription = None
    try:
        adapter.load_stage(stage)
        assert adapter.render_frame(64, 32, _VIEW, _PROJECTION) is not None
        counting = _CountingRenderer(adapter._renderer, refusals)
        adapter._renderer = counting
        subscription = stage_adapter.subscribe_changes(adapter.notify_stage_changed)
        for offset in offsets:
            _move(stage, offset, with_bad)
            while queued:
                queued.pop(0)()
        adapter._renderer = counting._renderer
        return adapter, counting.transform_writes
    except BaseException:
        adapter.shutdown()
        raise
    finally:
        if subscription is not None:
            subscription.cancel()
        stage_adapter.dispose()


def test_moved_prims_reach_the_renderer_in_one_write(tmp_path):
    adapter, writes = _run(tmp_path, offsets=(5.0,))
    try:
        assert writes == [sorted(_ACTORS)], "all moved prims go to ovrtx in one call"
        assert _renderer_translations(adapter, _ACTORS) == _expected(5.0), "the renderer has the local transforms"
    finally:
        adapter.shutdown()


def test_a_failed_write_is_reported_once_and_again_after_a_write_that_worked(tmp_path, capfd):
    # Writes 1, 2 and 4 are refused; write 3 reaches the renderer.
    adapter, writes = _run(tmp_path, offsets=(3.0, 4.0, 5.0, 6.0), refusals=(True, True, False, True))
    try:
        assert writes == [sorted(_ACTORS)] * 4, "each change tries one call for all moved prims"
        assert _renderer_translations(adapter, _ACTORS) == _expected(5.0), "the renderer keeps the last written values"
        report = capfd.readouterr().err
        assert report.count(
            f"the ovrtx write of the transforms of {len(_ACTORS)} moved prims failed (RuntimeError: write refused)"
        ) == 2, "the repeated failure is reported once, and again when it comes back after a write that worked"
    finally:
        adapter.shutdown()


def test_a_prim_without_a_local_transform_is_reported_and_the_others_move(tmp_path, capfd):
    adapter, writes = _run(tmp_path, offsets=(4.0, 5.0), with_bad=True)
    try:
        assert writes == [sorted(_ACTORS)] * 2, "the other moved prims still go to ovrtx in one call"
        assert _renderer_translations(adapter, _ACTORS) == _expected(5.0)
        report = capfd.readouterr().err
        assert report.count(f"the local transform of {_BAD} cannot be computed") == 1, (
            "the prim is reported, and the same failure on the next change is not reported again"
        )
    finally:
        adapter.shutdown()
