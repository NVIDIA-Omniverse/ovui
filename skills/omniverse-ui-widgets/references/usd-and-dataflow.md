# USD Open, Wiring, And Dataflow

## USD Open And Wiring Recipe

OpenUSD stages with session sublayers (for example, ovlive participant overlays)
are loaded into the existing `OvRtxRendererAdapter` through a composed snapshot.
This preserves inserted or removed Live geometry on structural reloads without
saving the stored root file. Hosts may suppress duplicate USD notices while a
Live binding applies records, then use `notify_transform_changed` for pose-only
updates and `renderer.load_stage(stage, use_live_root_snapshot=True)` when
geometry is inserted or removed. Both operations run on the USD-owning thread.
Transport acknowledgment is separate from renderer presentation; validate the
receiving viewport with Inspector screenshots.

Every exercise should route CLI positional file opening and File > Open dialog
acceptance through the same `open_usd(path)` or `_wire_open_stage(...)` path.

```python
def _wire_open_stage(self, stage: Any, title: str, renderer: Any) -> None:
    if self.stage_sub is not None:
        self.stage_sub.cancel()
        self.stage_sub = None
    self.selection_bus.clear()
    self.stage = stage
    self.stage_adapter = UsdStageAdapter(stage, self.undo_manager, self.call_later)
    self.stage_sub = self.stage_adapter.subscribe_changes(self._on_stage_changed)

    if self.stage_window is not None:
        self.stage_window.set_adapter(self.stage_adapter)

    if self.property_window is not None:
        self.property_window.set_property_adapter_factory(
            lambda paths: UsdPropertyAdapter(
                stage, paths, self.undo_manager, self.stage_adapter
            )
        )
        self.property_window.set_stage_adapter(self.stage_adapter, self.undo_manager)

    transform_adapter = UsdTransformAdapter(stage)
    self.viewport_window.set_scene_name(title)
    self.viewport_window.attach_stage(
        transform_adapter=transform_adapter,
        stage_adapter=self.stage_adapter,
        undo_manager=self.undo_manager,
        snap_system=self.snap_system,
    )
    self.viewport_window.set_renderer(renderer)
    self.viewport_window.update_prim_count(
        sum(1 for _prim in stage.TraverseAll())
    )
    self.viewport_window.frame_paths(["/"])

def _on_stage_changed(self, event: Any) -> None:
    if self.viewport_window is not None:
        self.viewport_window.notify_stage_changed(event)
        if self.stage is not None:
            self.viewport_window.update_prim_count(
                sum(1 for _prim in self.stage.TraverseAll())
            )
```

Standalone docking:

Verified standalone behavior: runtime-only docking is not enough for this
trial. In a temporary standalone app, `ui.Workspace.get_window("DockSpace")`
is MainWindow's internal host and is not a replacement for the root dock
node IDs in `imgui.ini`. If no split layout is preseeded, Stage Browser and
Viewport both start floating at the same coordinates and Viewport covers
Stage. Therefore call `write_split_ini()` from `ovui_widgets.app.layout` before
`ui.init()`, while the current directory is the temp trial root, so
`imgui.ini` is written outside the repo and loaded by standalone ImGui on
startup.

After creating the requested windows and opening the stage, wait frames and
verify the expected panels are actually docked and visible. Do not require a
non-zero `dock_id` for Stage Browser or Property Inspector: in the verified
standalone runs they report `docked=True` and are visibly split even when
their `dock_id` reads `0`. Do require `docked=True`; without the preseeded
layout, the floating overlapped windows report `docked=False`.

```python
def _panel_docked_visible(self, title: str, *, min_width: float = 80.0) -> bool:
    handle = ui.Workspace.get_window(title)
    if handle is None:
        return False
    if not bool(getattr(handle, "docked", False)):
        return False
    if getattr(handle, "visible", True) is False:
        return False
    return (
        float(getattr(handle, "width", 0.0) or 0.0) >= min_width
        and float(getattr(handle, "height", 0.0) or 0.0) >= 100.0
    )

def _dock_windows(self) -> bool:
    vp = ui.Workspace.get_window("Viewport")
    if vp is None:
        return False

    # Primary path: write_split_ini() pre-docked the requested panels.
    stage_ok = (
        self.stage_window is None
        or self._panel_docked_visible("Stage Browser", min_width=160.0)
    )
    prop_ok = (
        self.property_window is None
        or self._panel_docked_visible("Property Inspector", min_width=160.0)
    )
    vp_ok = self._panel_docked_visible("Viewport", min_width=300.0)
    if stage_ok and prop_ok and vp_ok:
        return True

    # Last-chance runtime repair for environments that expose the special
    # "DockSpace" target. Do not use "DockSpace0" as a replacement; verified
    # standalone runs show that handle has dock_id == 0 and does not anchor
    # windows into the root dock node.
    dockspace = ui.Workspace.get_window("DockSpace")
    if dockspace is not None and not bool(getattr(vp, "docked", False)):
        self.viewport_window.window.dock_in(dockspace, ui.DockPosition.SAME)
        vp = ui.Workspace.get_window("Viewport")
        if vp is None:
            return False

    if self.stage_window is not None and not self._panel_docked_visible(
        "Stage Browser", min_width=160.0
    ):
        self.stage_window.window.dock_in(vp, ui.DockPosition.LEFT, ratio=0.25)
        vp = ui.Workspace.get_window("Viewport") or vp

    if self.property_window is not None and not self._panel_docked_visible(
        "Property Inspector", min_width=160.0
    ):
        self.property_window.window.dock_in(vp, ui.DockPosition.RIGHT, ratio=0.28)

    return (
        (
            self.stage_window is None
            or self._panel_docked_visible("Stage Browser", min_width=160.0)
        )
        and (
            self.property_window is None
            or self._panel_docked_visible("Property Inspector", min_width=160.0)
        )
        and self._panel_docked_visible("Viewport", min_width=300.0)
    )
```

The verified call sequence is:

1. Change to `$TRIAL_ROOT`.
2. Call `write_split_ini()` before `ui.init()` so the generated `imgui.ini`
   is loaded by standalone ImGui and does not pollute the repo.
3. Create `ui.MainWindow()`, then `StageWindow`, `PropertyWindow` when
   requested, and `ViewportWidget`; build menu content inside
   `main_window.main_menu_bar` when the trial includes a menu.
4. After `_wire_open_stage(...)`, run up to six
   `drain -> await ui.next_frame() -> _dock_windows()` attempts.
5. Raise `RuntimeError("Stage Browser / Viewport / Property docking did not become visible")`
   if the expected panels are not docked and visible.

This was verified with screenshots for Stage+Viewport and
Stage+Viewport+Property. The Exercise 2 proof screenshot must visibly show
both `Stage Browser` and `Viewport`. If the screenshot shows only the
Viewport/geometry, the docking recipe failed and the skill trial must stop.

The app should run one of these cumulative configurations:

- Exercise 1: `include_stage=False, include_property=False, include_menu=False`
- Exercise 2: `include_stage=True, include_property=False, include_menu=False`
- Exercise 3: `include_stage=True, include_property=True, include_menu=False`
- Exercise 4: `include_stage=True, include_property=True, include_menu=True`

Add this CLI entrypoint so the documented launch commands work exactly:

```python
EXERCISE_CONFIGS = {
    1: dict(include_stage=False, include_property=False, include_menu=False),
    2: dict(include_stage=True, include_property=False, include_menu=False),
    3: dict(include_stage=True, include_property=True, include_menu=False),
    4: dict(include_stage=True, include_property=True, include_menu=True),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disposable ovui-widgets skill trial")
    parser.add_argument("usd_path", help="USD file to open at startup")
    parser.add_argument("--exercise", type=int, choices=tuple(EXERCISE_CONFIGS), required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args(argv)

    usd_path = Path(args.usd_path).expanduser()
    if not usd_path.exists():
        parser.error(f"USD file does not exist: {usd_path}")

    app = TrialApp(**EXERCISE_CONFIGS[args.exercise])
    app.run(str(usd_path), width=args.width, height=args.height)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Selection And Dataflow Wiring

Use one `SelectionBus` for all surfaces.

For the native OVStage provider, `OvstageRendererAdapter` retains one activation
reset after the first successfully applied non-empty selection, including on
native OVRTX 0.5 or newer. `load_stage()` arms activation without directly
resetting the renderer. Once the outline pass is active, the dedicated
selection membership APIs consume completed writes on the next render step
without another membership reset when the loaded native `Renderer.version`
is 0.5 or newer. The first selection can still incur renderer-reset latency.
Resolution-change resets remain unchanged; resizing with no applied outline
re-arms activation for the next non-empty selection. Do not add per-selection
renderer resets in the application. The adapter retains compatibility handling
for older/unknown native runtimes and legacy transports, including
reserved-attribute writes. Validate first selection in a fresh cube/sphere
scene before any camera movement, then replacement, clear/reselect, and
clear → resize → select. Also exercise select A → pan → zoom → select B, with
only B outlined afterward. Check real rendered outlines as well as callback
timings; callback completion alone does not prove that the outline is visible.

Stage row -> viewport -> Property:

1. `StageWidget` inside `StageWindow` calls
   `selection_bus.publish(paths, source="stage")` from user row selection.
2. `ViewportWidget._on_bus_selection_changed(event)` receives the event,
   calls `renderer.set_selection_highlight(paths)` (it renders again unless
   that returns `False`: no outline before and none now), updates
   `ManipulatorRegistry`, updates `PrimTransformModel.set_selection(paths)`,
   and invalidates the transform manipulator and selection outline.
3. `PropertyWindow._on_bus_selection_changed(event)` calls
   `PropertyWindow.set_selection(paths)`, builds a
   `UsdPropertyAdapter(stage, paths, undo_manager, stage_adapter)`, and
   rebuilds visible rows.

Viewport pick -> Stage row -> Property:

1. `ViewportWidget` point and rectangle pick gestures call `renderer.pick(...)`
   or `renderer.pick_rect(...)`. The renderer reports geometry only. For a point
   pick, the viewport then calls `resolve_pick_path(render_x, render_y, path)`:
   a click on a drawn line of the light gizmo selects that light instead of the
   renderer's answer. Only the single selected UsdLux light draws a gizmo, so a
   light that is not selected never takes a click. The gizmo of a dome or
   distant light does not take a click from a mesh under it. A hidden light
   (also through a hidden parent) is skipped. Lights that the app adds under
   `/OvGearSession` (the fallback dome light of a scene that has no light) are
   not picked. When a read of the selected light or the camera fails, the
   viewport reports the cause through `ErrorReporter` and keeps the renderer's
   answer.
   Rectangle picks do not include lights.
2. The viewport merges hits and calls
   `selection_bus.publish(merged, source="viewport")`.
3. `StageWidget._on_bus_selection_changed(event)` expands ancestors, sets the
   tree selection, and refreshes row highlighting.
4. `PropertyWindow` follows the same bus event and rebuilds for the selected
   prim paths.

Viewport manipulation -> Property -> renderer:

1. `ViewportWidget.attach_stage(...)` wires `UsdTransformAdapter`,
   `UsdStageAdapter`, `UndoManager`, and `SnapSystem` into
   `PrimTransformModel`.
2. Transform gizmo drag updates `PrimTransformModel`.
3. `PrimTransformModel.on_drag_moved(...)`,
   `PrimTransformModel.on_drag_rotated(...)`, and
   `PrimTransformModel.on_drag_scaled(...)` write USD transforms through
   `UsdTransformAdapter.set_local_transform(...)` while suppressing raw USD
   stage notices, then emit an explicit live transform event with
   `source="viewport-manipulator-live"`. `set_local_transform` writes the
   new values into the translate, rotate and scale operations of the prim;
   it writes one matrix operation only when those operations cannot give the
   matrix (for example a shear). Then it returns a note with the prim and
   the cause, and `PrimTransformModel.on_drag_ended()` shows the note in the
   status bar and writes it to the log.
4. The app's `stage_adapter.subscribe_changes(self._on_stage_changed)` callback
   forwards each live event to `ViewportWidget.notify_stage_changed(event)`.
5. `OvRtxRendererAdapter.notify_stage_changed(event)` mirrors live transform
   changes to ovrtx via `renderer.write_attribute(..., "omni:xform", ...)`.
6. `PrimTransformModel.on_drag_ended()` pushes undo commands and calls
   `UsdStageAdapter.notify_transform_changed(paths,
   source="viewport-manipulator")`.
7. `PropertyWindow._on_stage_changed(event)` rebuilds selected rows when a
   selected path changed.
8. The final event gives observers a committed mouse-up transform state after
   undo grouping closes.

Property edit -> viewport (property-to-viewport flow):

1. Property row widgets use `AttributeModelBase.begin_edit()`,
   `set_value(value)`, and `end_edit()`. A vector row uses
   `set_component_value(index, vector)` in place of `set_value(value)`.
   The row of a matrix transform operation (`xformOp:transform`) has
   Translate, Rotate and Scale fields above its 4x4 grid; a field uses
   `set_matrix_part_value(part, index, value, matrix)`. The parts come from
   `ovui_data_adapters.common.matrix_transform`: Rotate is in degrees, X
   first, then Y, then Z; an edit of Rotate or Scale keeps the shear, the
   translation and the other channels of the matrix. A flat object (a zero
   scale) shows its true parts and can be edited. Rotate and Scale of a
   matrix with nan show nan, and an edit of them is refused with a message
   (`MatrixPartError` gives the cause).
   When the user presses Escape in a decimal number field (the float,
   vector, color and matrix rows), its model reports `is_edit_cancelled()`
   in the end-edit callback, and the row calls `cancel_edit()` in place of
   `end_edit()`: the adapter puts back the exact value from before the edit
   and records no undo step. An integer field puts back its exact old text
   on Escape and still calls `end_edit()`; the adapter sees the start value
   of every object and does the same. In both cases a layer that had no
   unsaved change before the edit shows as not modified again, with no
   reload of the layer.
2. `AttributeModelBase.set_value()` delegates to
   `UsdPropertyAdapter.set_value(attr_name, value)`.
   `AttributeModelBase.set_component_value()` delegates to
   `UsdPropertyAdapter.set_component_value(attr_name, index, value)`, which
   changes only that channel: each selected prim keeps its other channels.
   `AttributeModelBase.set_matrix_part_value()` delegates to
   `UsdPropertyAdapter.set_matrix_part_value(attr_name, part, index, value)`,
   which changes one channel of one part of the matrix of each selected
   prim, from its matrix at the start of the edit.
   Before it delegates, the model refuses a value that cannot be stored: a
   number that is not finite (nan, inf) for a transform operation
   (`xformOp:*`), and a value outside the range of a 16-bit or 32-bit float
   attribute. The old value stays: when the drag field already wrote values
   while the user typed, the model cancels the edit (`cancel_edit`) and
   starts a new one. A message in the status bar names the field and the
   cause.
3. `UsdPropertyAdapter` writes the USD attribute with
   `attr.Set(usd_value)` and notifies adapter subscribers. A float vector
   keeps the precision of the USD type of each selected attribute
   (`double3` is written as `Gf.Vec3d`, `half4` as `Gf.Vec4h`).
4. USD `Tf.Notice` flows through `UsdStageAdapter.subscribe_changes(...)` to
   the app's `_on_stage_changed`.
5. `_on_stage_changed` calls `ViewportWidget.notify_stage_changed(event)`.
6. `ViewportWidget.notify_stage_changed(event)` forwards to
   `OvRtxRendererAdapter.notify_stage_changed(event)` and invalidates overlays.
   It asks for a render unless `RendererAdapter.stage_change_keeps_picture(event)`
   returns `True` (for example an edit of a created Xform that draws nothing):
   ovrtx keeps memory on each render step.
7. The next viewport render shows the changed attribute or transform. For
   transform fields such as `xformOp:translate`, the selected prim moves in the
   real ovrtx viewport.
