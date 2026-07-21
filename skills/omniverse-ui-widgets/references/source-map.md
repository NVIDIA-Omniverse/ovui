# Exact Source Map

Use these existing classes and functions.

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
