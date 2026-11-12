# Exact Source Map

Use these existing classes and functions.

For native OVStage integrations, the public `OvstageRendererAdapter` creates
its private viewport product with `viewport_quality=0` by default (progressive
frames after resets, unchanged sampling targets and Eco mode). One-shot capture
callers can explicitly request `viewport_quality=100` for the native full
initial-quality budget, also through the OVStage renderer factories. Do not
apply this policy to authored scene products or repeatedly overwrite quality
on frame, mode, or resize callbacks. Explicitly resetting the private product's
quality setting restores that adapter's configured value through the undoable
authoring path; it does not clear the column to the native quality of `100`.
Other products retain their existing reset semantics. The OpenUSD recipe below is unchanged;
see `ovui-data-adapters/README.md` for the native provider's ownership boundary.

```python
# ovui/runtime
import omni.ui as ui
from ovui_widgets.app.layout import write_split_ini
from ovui_widgets.app.style import apply_global_styles, set_theme
from ovui_widgets.app.frame_clock import FrameClock

# process singletons and app services
from ovui_widgets.common import scheduler as common_scheduler
from ovui_widgets.common.recent_files import RecentFileList
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.settings import Settings
from ovui_widgets.common.snap import GridSnapProvider, SnapSystem, SurfaceSnapProvider
from ovui_widgets.common.undo import UndoManager

# widgets to compose; do not recreate these
from ovui_widgets.viewport.viewport_widget import ViewportWidget
from ovui_widgets.stage.window import StageWindow
from ovui_widgets.property.window import PropertyWindow

# USD adapters and real renderer
from ovui_data_adapters.openusd import (
    AVAILABLE,
    OvRtxRendererAdapter,
    UsdPropertyAdapter,
    UsdStageAdapter,
    UsdTransformAdapter,
)

# menu/file open
from ovui_widgets.content.file_importer import FileImporterHelper
```

Purpose and required calls:

- `ViewportWidget(services=..., renderer=..., bus=selection_bus,
  stage_adapter_provider=...)` is the existing viewport. It owns the rendered
  image, camera controls, picking gestures, selection outline, and transform
  manipulators. After a USD stage opens, call
  `viewport.attach_stage(transform_adapter=UsdTransformAdapter(stage),
  stage_adapter=stage_adapter, undo_manager=undo_manager,
  snap_system=snap_system)`, then `viewport.set_renderer(renderer)`,
  `viewport.update_prim_count(count)`, and `viewport.frame_paths(["/"])`.
- `viewport.subscribe_render_product_change(callback)` (a method of
  `ViewportSurface`, so also of `ViewportWidget`) is for a tool that chooses
  the renderer's render product, for example a render target menu that an
  optional module adds to the viewport. The viewport changes the render product
  itself only when it leaves a bound USD camera for the free camera: H (home),
  or Camera > Perspective or Ortho. Then it first asks the renderer for its own
  render product (`set_active_render_product_path(None)`). When the shown
  render product is then not the one from before, the viewport calls
  `callback(render_product_path)` one time, with the render product that is
  now shown (an empty string when the renderer gives none). This also occurs
  when the step fails and the earlier render product cannot come back. There
  is no call when no USD camera is bound, or when the renderer cannot give its
  active render product (`get_active_render_product_path`). The returned handle
  has `remove()`, which stops the calls; you can call it more than one time.
  `viewport.destroy()` also stops all calls. When a callback raises an error,
  `ErrorReporter` reports the render product and the error, and the other
  callbacks still get the call. A `callback` that is not callable raises
  `TypeError`. Subscribe when the tool attaches to the viewport, and call
  `remove()` when it detaches. In the callback, the tool changes its own state
  and its open windows to the shown render product, so that its edits go to
  the render product that the user sees.
- `StageWindow(adapter=stage_adapter, selection_bus=selection_bus)` is the
  existing Stage Browser shell. It hosts `StageWidget`, which publishes user
  row selections through `SelectionBus.publish(paths, source="stage")` and
  observes bus changes to highlight/expand rows.
- `PropertyWindow()` is the existing Property Inspector. It subscribes to
  `SelectionBus.instance()` in `__init__`. After a stage opens, call
  `property_window.set_property_adapter_factory(lambda paths:
  UsdPropertyAdapter(stage, paths, undo_manager, stage_adapter))` and
  `property_window.set_stage_adapter(stage_adapter, undo_manager)`.
- `SelectionBus` is the single source of truth. Create one per app and set
  `SelectionBus._instance = bus` before constructing `PropertyWindow`.
- `Settings.set_instance(settings)`, `RecentFileList.set_instance(recent)`,
  and `common_scheduler.set_call_later(app.call_later)` must be registered by
  the app shell before widgets are built. Clear them during shutdown.
- `FrameClock(target_fps=float(ViewportWidget.MAX_FPS_FOREGROUND))` gates
  viewport rendering if the shell owns the frame loop. The widget still owns
  the actual render call.
- `OvRtxRendererAdapter` is the only acceptable renderer for visual proof.
  `MockRendererAdapter`, black frames, placeholders, or fallback warnings fail
  the trial.

## Inspector contributions

`ovui_widgets.viewport.inspector.ViewportInspector` packages the existing surface,
renderer and SelectionBus interfaces as discoverable Inspector commands, and
`ovui_widgets.app.media_inspector.media_commands` adds streaming and recording.
The standard USD Viewer registers both through `Application.get_inspector_commands()`.
See [inspector-commands.md](inspector-commands.md) for the vocabulary and host wiring.
Headless applications that host the stock viewport without editor panels (USD
Workbench, maintained in its own repository, is one) build on the same seams.
