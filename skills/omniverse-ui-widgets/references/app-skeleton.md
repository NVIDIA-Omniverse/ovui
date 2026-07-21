# Minimal Disposable App Skeleton And Initialization

## Minimal Disposable App Skeleton

Implement the app at `$TRIAL_ROOT/trial_app.py`. This is guidance for the
future trial; do not place this source under the repo.

```python
from __future__ import annotations

import argparse
import inspect
import os
import time
from pathlib import Path
from typing import Any, Callable

import omni.ui as ui

from ovui_widgets.app.frame_clock import FrameClock
from ovui_widgets.app.style import apply_global_styles, set_theme
from ovui_widgets.common import scheduler as common_scheduler
from ovui_widgets.common.recent_files import RecentFileList
from ovui_widgets.common.scheduler import CallbackHandle
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.settings import Settings
from ovui_widgets.common.snap import GridSnapProvider, SnapSystem, SurfaceSnapProvider
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.content.file_importer import FileImporterHelper
from ovui_widgets.property.window import PropertyWindow
from ovui_widgets.stage.window import StageWindow
from ovui_widgets.viewport.viewport_widget import ViewportWidget
from ovui_data_adapters.openusd import (
    AVAILABLE,
    OvRtxRendererAdapter,
    UsdPropertyAdapter,
    UsdStageAdapter,
    UsdTransformAdapter,
)


USD_EXTENSION_TYPES = [
    ("*.usd", "USD Binary or Ascii"),
    ("*.usda", "USD Ascii"),
    ("*.usdc", "USD Crate"),
    ("*.usdz", "USD Zip"),
]


class TrialApp:
    def __init__(self, *, include_stage=False, include_property=False, include_menu=False):
        self.include_stage = include_stage
        self.include_property = include_property
        self.include_menu = include_menu
        self.settings = Settings()
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        SelectionBus._instance = self.selection_bus
        Settings.set_instance(self.settings)
        self.recent_files = RecentFileList(self.settings.get("ui.recent_files", []))
        RecentFileList.set_instance(self.recent_files)
        self._pending_callbacks: list[CallbackHandle] = []
        common_scheduler.set_call_later(self.call_later)
        self.snap_system = SnapSystem()
        self.snap_system.add_provider(GridSnapProvider(1.0))
        self.snap_system.add_provider(SurfaceSnapProvider())
        self.stage_adapter = None
        self.stage_sub = None
        self.stage = None
        self.stage_window = None
        self.property_window = None
        self.viewport_window = None
        self.main_window = None
        self._ui_native = None
        self._ovuiinspect_module = None
        self.running = False
        self.frame_clock = FrameClock(target_fps=float(ViewportWidget.MAX_FPS_FOREGROUND))

    def call_later(self, delay_secs: float, callback: Callable) -> CallbackHandle:
        handle = CallbackHandle(time.monotonic() + delay_secs, callback)
        self._pending_callbacks.append(handle)
        return handle

    def _fire_pending_callbacks(self) -> None:
        now = time.monotonic()
        for handle in list(self._pending_callbacks):
            if handle.is_cancelled:
                self._pending_callbacks.remove(handle)
                continue
            if not handle.is_fired and now >= handle._due_time:
                callback = handle._callback
                handle._callback = None
                self._pending_callbacks.remove(handle)
                if callback is not None:
                    callback()

    def _stage_adapter_provider(self):
        return self.stage_adapter
```

Simple `self.selection_bus` and `self.undo_manager` attributes satisfy
`ovui_widgets.common.services.WidgetServices`; do not add duplicate properties
unless you also keep working setters. The widget service surface is exactly
`selection_bus`, `undo_manager`, and `call_later(delay_secs, callback)`.

## App Initialization Pattern

The run loop mirrors the reusable pieces from `ovui_widgets.app.Application` but
constructs only the surfaces requested by the exercise.

```python
def _ui_init_supports_kwarg(init_fn: Callable, kwarg: str) -> bool:
    try:
        sig = inspect.signature(init_fn)
    except (TypeError, ValueError):
        return False
    params = sig.parameters
    if kwarg in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

def run(self, usd_path: str, *, width: int = 1280, height: int = 720):
    target_fps = float(ViewportWidget.MAX_FPS_FOREGROUND)
    old_cwd = os.getcwd()
    try:
        trial_root = Path(os.environ.get("TRIAL_ROOT", Path(__file__).parent)).resolve()
        trial_root.mkdir(parents=True, exist_ok=True)
        os.chdir(trial_root)
        write_split_ini()
        if _ui_init_supports_kwarg(ui.init, "max_fps"):
            ui.init("OvuiWidgetsTrial", width=width, height=height, max_fps=None)
        else:
            ui.init("OvuiWidgetsTrial", width=width, height=height)
        self._ui_native = ui._ui
        self._setup_optional_ovuiinspect()
        apply_global_styles()
        set_theme(self.settings.get("ui.theme", "dark"))
        self.running = True
        ui.run(self.run_async(usd_path))
    finally:
        self.running = False
        self._detach_ovuiinspect()
        os.chdir(old_cwd)

async def run_async(self, usd_path: str):
    self.main_window = ui.MainWindow()

    if self.include_stage:
        self.stage_window = StageWindow(selection_bus=self.selection_bus)
    if self.include_property:
        self.property_window = PropertyWindow()

    stage, renderer = open_usd_with_required_ovrtx(usd_path)
    self.viewport_window = ViewportWidget(
        services=self,
        renderer=renderer,
        bus=self.selection_bus,
        stage_adapter_provider=self._stage_adapter_provider,
    )

    if self.include_menu:
        with self.main_window.main_menu_bar:
            self._build_menu_bar()

    self._wire_open_stage(stage, Path(usd_path).name, renderer)
    for attempt in range(1, 7):
        self._drain_ovuiinspect()
        await ui.next_frame()
        if self._dock_windows():
            break
    else:
        raise RuntimeError(
            "Stage Browser / Viewport / Property docking did not become visible"
        )
    self.viewport_window.frame_paths(["/"])

    while self.running:
        self._fire_pending_callbacks()
        self._render_viewport_if_due()
        self._drain_ovuiinspect()
        await ui.next_frame()
```

Inspector attachment and frame-loop drain for screenshots:

Attaching without draining is broken: `ovui-inspect` CLI commands enqueue work
and wait for the ovui frame loop to run `drain_pending(...)`. If the app only
calls `attach_application(self)`, screenshot, mouse, and keyboard commands
will time out with "command timed out before the ovui frame loop drained it".

```python
def _setup_optional_ovuiinspect(self) -> None:
    try:
        import ovuiinspect
    except ImportError:
        self._ovuiinspect_module = None
        return
    self._ovuiinspect_module = ovuiinspect
    attach = getattr(ovuiinspect, "attach_application", None)
    if callable(attach):
        attach(self)

def _drain_ovuiinspect(self) -> None:
    inspector = self._ovuiinspect_module
    if inspector is None or self._ui_native is None:
        return
    drain = getattr(inspector, "drain_pending", None)
    if callable(drain):
        drain(self._ui_native, application=self)

def _detach_ovuiinspect(self) -> None:
    inspector = self._ovuiinspect_module
    if inspector is None:
        return
    detach = getattr(inspector, "detach_application", None)
    if callable(detach):
        detach(self)
    self._ovuiinspect_module = None

def request_exit(self) -> None:
    self.running = False
```

Frame rendering:

```python
def _render_viewport_if_due(self) -> None:
    if self.viewport_window is None:
        return
    now = time.monotonic()
    render_dt = self.frame_clock.should_render(now)
    if render_dt is None:
        self.viewport_window.update(0.0)
        return
    self.viewport_window.update(render_dt)
    rendered = self.viewport_window.render(render_dt)
    if rendered:
        self.frame_clock.commit(now)
```
