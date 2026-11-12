# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Create > Xform and Undo keep the memory of the renderer level.

Each open of a root makes ovrtx keep more process memory, also for the same
file or text. The OpenUSD renderer adapter opened the root again for each
Create-menu prim and again for its Undo, so the memory of the USD Viewer grew
with each create and undo, on an empty scene too. ovrtx also keeps memory on
each render step, and the viewport rendered its settle frames
after each change, also for an Xform, which draws nothing.

The tests run the Create-menu commands and Undo through the real OpenUSD stage
adapter, the real renderer adapter and the installed ovrtx, on the scene of
the issue. Each stage change goes first to ``stage_change_keeps_picture`` and
then to ``notify_stage_changed``, as the viewport sends it. They need an
NVIDIA GPU.
"""

from __future__ import annotations

import ctypes
import gc
import os
import sys

import pytest

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

SCENE = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Z"
)

def Xform "World"
{
}
"""
# A scene with a prim of the opened file that the Stage Browser can rename or move.
GROUP_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Z"
)

def Xform "World"
{
    def Xform "Group"
    {
        def Cube "Box"
        {
            double size = 40
        }
    }

    def Xform "Other"
    {
    }
}
"""
XFORM_PATH = "/World/Xform"
CUBE_PATH = "/World/Cube"
WARM_UP_CYCLES = 5
# Two blocks: memory that the renderer allocates once (work that it starts
# after the first open) can fall into one block; growth that each cycle
# keeps shows in both.
BLOCK_CYCLES = 15
# Each reopen of the root kept about 2 MiB; a reference added and removed
# again keeps no measurable memory.
ALLOWED_GROWTH_KIB_PER_CYCLE = 512


def _resident_kib() -> int:
    """The resident memory of this process, in KiB."""
    if sys.platform == "win32":

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        if not ctypes.windll.psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        ):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.WorkingSetSize // 1024
    with open("/proc/self/statm", encoding="ascii") as statm:
        resident_pages = int(statm.read().split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE") // 1024


class _App:
    """What the Create-menu command reads from the application."""

    def __init__(self, stage, undo_manager) -> None:
        self._stage = stage
        self.undo_manager = undo_manager


class _Changes:
    """Sends each stage change to the renderer adapter as the viewport does."""

    def __init__(self, renderer) -> None:
        self._renderer = renderer
        self.picture_kept: list[bool] = []

    def __call__(self, event) -> None:
        # A renderer adapter without this question renders after every change.
        keeps = getattr(self._renderer, "stage_change_keeps_picture", lambda _event: False)
        self.picture_kept.append(keeps(event))
        self._renderer.notify_stage_changed(event)


# Calls of the ovrtx renderer that change or step nothing.
_NATIVE_READS = ("query_", "read_", "build_info", "version", "config", "resolve_prim_path_id")


def _count_native_calls(native, counts: dict[str, int]) -> None:
    """Count the calls of ``native`` that can change what ovrtx shows or step it."""
    for name in dir(type(native)):
        method = getattr(native, name)
        if name.startswith("_") or name.startswith(_NATIVE_READS) or isinstance(method, type):
            continue
        if not callable(method):
            continue

        def counted(*args, _method=method, _name=name, **kwargs):
            counts[_name] = counts.get(_name, 0) + 1
            return _method(*args, **kwargs)

        setattr(native, name, counted)


def _prims_in_renderer(renderer, prim_type: str) -> list[str]:
    import ovrtx

    return list(
        renderer._renderer.query_prims(require_all=[(ovrtx.FilterKind.PRIM_TYPE, prim_type)])
    )


class _Session:
    """The scene of the issue in a stage adapter and a renderer adapter."""

    def __init__(self, tmp_path, *, new_stage: bool = False, scene: str = SCENE) -> None:
        from pxr import Usd

        from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from ovui_data_adapters.services.undo import UndoManager

        if new_stage:
            # The stage of File > New: a new file with no prim.
            self.stage = Usd.Stage.CreateNew(str(tmp_path / "NewStage.usda"))
        else:
            scene_file = tmp_path / "start_empty.usda"
            scene_file.write_text(scene, encoding="utf-8")
            self.stage = Usd.Stage.Open(str(scene_file))
        self.undo_manager = UndoManager()
        self.renderer = OvRtxRendererAdapter()
        # The application runs the stage notices at its next frame; so do the tests.
        self._pending = []
        self.stage_adapter = UsdStageAdapter(
            self.stage, self.undo_manager, lambda _delay, callback: self._pending.append(callback)
        )
        self.changes = _Changes(self.renderer)
        self._subscription = None
        self.app = _App(self.stage, self.undo_manager)

    def __enter__(self) -> "_Session":
        self.renderer.load_stage(self.stage)
        self._subscription = self.stage_adapter.subscribe_changes(self.changes)
        # The session prims that the renderer authors at load, as at the first frame of the application.
        self.next_frame()
        self.changes.picture_kept.clear()
        return self

    def __exit__(self, *_exc) -> None:
        if self._subscription is not None:
            self._subscription.cancel()
        self.stage_adapter.dispose(force=True)
        self.renderer.shutdown()

    def next_frame(self) -> None:
        while self._pending:
            self._pending.pop(0)()


def _render_until_current(renderer, timeout: float = 300.0) -> None:
    """Render frames as the viewport does until the renderer has built the scene again."""
    import time

    import numpy as np

    view = np.identity(4)
    view[3, 2] = -200.0
    projection = np.array(
        [[1.0, 0.0, 0.0, 0.0], [0.0, 2.0, 0.0, 0.0], [0.0, 0.0, -1.0, -1.0], [0.0, 0.0, -2.0, 0.0]]
    )
    deadline = time.monotonic() + timeout
    while renderer.scene_update_pending():
        assert time.monotonic() < deadline, "the renderer did not finish building the scene"
        renderer.render_frame(64, 32, view, projection)
        time.sleep(0.01)
    renderer.render_frame(64, 32, view, projection)


def test_create_xform_and_undo_leave_ovrtx_as_it_is_and_ask_for_no_render(tmp_path):
    from ovui_data_adapters.openusd.create_prims import create_xform

    with _Session(tmp_path) as session:
        stage = session.stage
        create_xform(session.app)
        session.next_frame()
        assert session.undo_manager.undo()
        session.next_frame()
        counts: dict[str, int] = {}
        _count_native_calls(session.renderer._renderer, counts)
        session.changes.picture_kept.clear()
        outline_may_change = []
        for _ in range(3):
            create_xform(session.app)
            session.next_frame()
            assert stage.GetPrimAtPath(XFORM_PATH), "Create > Xform made no prim"
            assert XFORM_PATH not in _prims_in_renderer(session.renderer, "Xform")
            # The viewport outlines the meshes of the selected Xform: none.
            outline_may_change.append(session.renderer.set_selection_highlight([]))
            assert session.undo_manager.undo()
            session.next_frame()
            assert not stage.GetPrimAtPath(XFORM_PATH)
            # After Undo the viewport gives the removed Xform again, then the empty selection.
            session.renderer.refresh_selection_highlight([XFORM_PATH])
            outline_may_change.append(session.renderer.set_selection_highlight([]))

        assert session.changes.picture_kept and all(session.changes.picture_kept), (
            "a Create > Xform or its Undo asked for a render: "
            f"stage_change_keeps_picture gave {session.changes.picture_kept}"
        )
        assert outline_may_change == [False] * 6, (
            f"a selection that outlines nothing asked for a render: {outline_may_change}"
        )
        assert counts == {}, f"Create > Xform and Undo changed or stepped ovrtx: {counts}"


def test_a_shape_put_under_a_created_xform_shows_and_goes_away(tmp_path):
    from pxr import UsdGeom

    from ovui_data_adapters.openusd.create_prims import create_xform

    cube_path = XFORM_PATH + "/Cube"
    with _Session(tmp_path) as session:
        stage = session.stage
        create_xform(session.app)
        session.next_frame()
        assert session.changes.picture_kept == [True]

        UsdGeom.Cube.Define(stage, cube_path)
        session.next_frame()
        assert session.changes.picture_kept[-1] is False, "a new Cube asked for no render"
        assert cube_path in _prims_in_renderer(session.renderer, "Cube")

        stage.RemovePrim(cube_path)
        session.next_frame()
        assert session.changes.picture_kept[-1] is False, "the removal of a Cube asked for no render"
        assert cube_path not in _prims_in_renderer(session.renderer, "Cube")

        assert session.undo_manager.undo()
        session.next_frame()
        assert session.changes.picture_kept[-1] is True
        assert not stage.GetPrimAtPath(XFORM_PATH)


def test_first_create_on_a_new_stage_adds_no_prim_that_the_renderer_has(tmp_path, capsys):
    # Create > Mesh > Torus on the stage of File > New makes /World and
    # /World/Torus. The renderer refuses a reference where it has a prim, and
    # a reference adds its missing parent prims.
    from ovui_data_adapters.common.create_actions import CreateRequest

    torus_path = "/World/Torus"
    with _Session(tmp_path, new_stage=True) as session:
        counts: dict[str, int] = {}
        _count_native_calls(session.renderer._renderer, counts)
        capsys.readouterr()
        # The request that the Create menu of the application sends.
        result = session.stage_adapter.create_prim(CreateRequest("create.geometry.mesh.torus"))
        assert result.accepted, result
        session.next_frame()

        err = capsys.readouterr().err
        assert "[OvRtxRendererAdapter]" not in err, err
        assert session.stage.GetPrimAtPath(torus_path), "Create > Mesh > Torus made no prim"
        assert torus_path in _prims_in_renderer(session.renderer, "Mesh")
        assert "/World" in _prims_in_renderer(session.renderer, "Xform")
        opens = {name: count for name, count in counts.items() if name.startswith("open_usd")}
        assert opens == {}, f"the first Create on a new stage opened the scene again: {opens}"

        assert session.undo_manager.undo()
        session.next_frame()
        assert "[OvRtxRendererAdapter]" not in capsys.readouterr().err
        assert torus_path not in _prims_in_renderer(session.renderer, "Mesh")


def test_create_cube_and_undo_do_not_keep_more_renderer_memory_each_time(tmp_path):
    from ovui_data_adapters.openusd.create_prims import create_mesh_cube

    with _Session(tmp_path) as session:
        stage = session.stage

        def create_and_undo() -> None:
            create_mesh_cube(session.app)
            session.next_frame()
            assert stage.GetPrimAtPath(CUBE_PATH), "Create > Mesh > Cube made no prim"
            assert session.changes.picture_kept[-1] is False, "a new Cube asked for no render"
            assert CUBE_PATH in _prims_in_renderer(session.renderer, "Mesh"), (
                "the renderer does not have the created Cube"
            )
            assert session.undo_manager.undo()
            session.next_frame()
            assert not stage.GetPrimAtPath(CUBE_PATH)
            assert CUBE_PATH not in _prims_in_renderer(session.renderer, "Mesh"), (
                "the renderer still has the Cube after Undo"
            )

        for _ in range(WARM_UP_CYCLES):
            create_and_undo()
        grown = []
        for _block in range(2):
            gc.collect()
            before = _resident_kib()
            for _ in range(BLOCK_CYCLES):
                create_and_undo()
            gc.collect()
            grown.append(_resident_kib() - before)

    assert min(grown) < BLOCK_CYCLES * ALLOWED_GROWTH_KIB_PER_CYCLE, (
        f"each block of {BLOCK_CYCLES} cycles of Create > Mesh > Cube and Undo added resident memory: "
        f"{grown[0]} and {grown[1]} KiB (allowed: less than {ALLOWED_GROWTH_KIB_PER_CYCLE} KiB a cycle)"
    )


@pytest.mark.parametrize("edit", ["rename", "move"])
def test_a_renamed_or_moved_prim_of_the_opened_file_leaves_no_old_prim_in_the_renderer(tmp_path, edit):
    # The Stage Browser rename and move send one stage change that names only
    # the new path. A prim at that path is not in the opened file, as a
    # created prim is not, but the renderer still has the prim at the old path.
    from ovui_data_adapters.common import ReparentPosition
    from ovui_data_adapters.openusd.create_prims import create_xform

    with _Session(tmp_path, scene=GROUP_SCENE) as session:
        stage = session.stage
        group = stage.GetPrimAtPath("/World/Group")
        if edit == "rename":
            session.stage_adapter.rename(group, "Group2")
            moved_group = "/World/Group2"
        else:
            session.stage_adapter.reparent(
                [group], stage.GetPrimAtPath("/World/Other"), ReparentPosition.CHILD
            )
            moved_group = "/World/Other/Group"
        session.next_frame()
        _render_until_current(session.renderer)
        assert _prims_in_renderer(session.renderer, "Cube") == [moved_group + "/Box"]

        # The reloaded scene has the prim at its new path: Create > Xform and
        # its Undo do not open the scene again and ask for no render. The
        # session prims that the reload authored again reach the renderer at
        # the next frame, as in the application.
        session.next_frame()
        counts: dict[str, int] = {}
        _count_native_calls(session.renderer._renderer, counts)
        session.changes.picture_kept.clear()
        create_xform(session.app)
        session.next_frame()
        assert session.undo_manager.undo()
        session.next_frame()
        assert session.changes.picture_kept and all(session.changes.picture_kept), session.changes.picture_kept
        assert counts == {}, f"Create > Xform and Undo after the reload changed or stepped ovrtx: {counts}"

        # Delete, as the Stage Browser does it.
        assert stage.RemovePrim(moved_group)
        session.next_frame()
        _render_until_current(session.renderer)
        assert _prims_in_renderer(session.renderer, "Cube") == [], "the renderer still draws a deleted Box"
