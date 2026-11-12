# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression: the Property Inspector kept the rows of each earlier build.

The value model of a row field holds callbacks of the row, and the row holds
its fields. That loop goes through native code, so Python never freed it after
the panel was cleared. The state glyph of a row also put a click callback on
its cleared widget when a value change came late. Each Create > Xform and Undo
built rows for the new Xform and kept them.
"""

import gc
import weakref

from ovui_data_adapters.openusd.create_prims import create_xform
from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
from ovui_widgets.common import scheduler as widget_scheduler
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.property.window import PropertyWindow
from pxr import Usd

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Z"
)

def Xform "World"
{
}
"""
_XFORM = "/World/Xform"


class _App:
    """What the Create-menu command reads from the application."""

    def __init__(self, stage, undo_manager):
        self._stage = stage
        self.undo_manager = undo_manager


def test_create_and_undo_free_the_rows_of_the_created_prim(tmp_path):
    scene = tmp_path / "start_empty.usda"
    scene.write_text(_SCENE, encoding="utf-8")
    stage = Usd.Stage.Open(str(scene))
    undo = UndoManager()
    # The application runs these callbacks at its next frame.
    pending = []

    def call_later(delay, callback):
        handle = widget_scheduler.CallbackHandle(delay, callback)
        pending.append(handle)
        return handle

    def next_frame():
        while pending:
            handle = pending.pop(0)
            if not handle.is_cancelled:
                handle._callback()

    widget_scheduler.set_call_later(call_later)
    stage_adapter = UsdStageAdapter(stage, undo_manager=undo, call_later=call_later)
    window = PropertyWindow()
    try:
        window._build_ui()
        window.set_property_adapter_factory(
            lambda paths: UsdPropertyAdapter(
                stage, paths, undo_manager=undo, stage_adapter=stage_adapter
            )
        )

        # As the application does: a removed prim leaves the selection
        # while the stage event is delivered.
        def drop_removed_prims(event):
            kept = [path for path in window._selection if stage.GetPrimAtPath(path)]
            if kept != window._selection:
                window.set_selection(kept)

        reconcile = stage_adapter.subscribe_changes(drop_removed_prims)
        window.set_stage_adapter(stage_adapter, undo)
        app = _App(stage, undo)
        built = []
        for _ in range(3):
            create_xform(app)
            window.set_selection([_XFORM])
            next_frame()
            rows = list(window._inspector_attribute_rows.values())
            assert {"xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"} <= set(
                window._inspector_attribute_rows
            )
            built.extend(weakref.ref(row) for row in rows)
            del rows
            assert undo.undo()
            next_frame()
            assert window._selection == []
        gc.collect()
        alive = [ref() for ref in built if ref() is not None]
        assert not alive, (
            f"{len(alive)} of {len(built)} rows of the created Xform are still alive "
            f"after Undo: {sorted({type(row).__name__ for row in alive})}"
        )
        reconcile.cancel()
    finally:
        window.destroy()
        stage_adapter.dispose(force=True)
        widget_scheduler.set_call_later(None)
