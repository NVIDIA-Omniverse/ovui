# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Central application singleton for USD Viewer.

Application owns the lifecycle of the entire
USD Viewer process, including Settings, UndoManager, SelectionBus, global styles,
the frame loop, and call_later() deferred execution.
"""

import functools
import inspect
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

from ovui_data_adapters.common import (
    AdapterFactories,
    AdapterProvider,
    AdapterRegistry,
    ChangeEventType,
    Command,
    UnresolvedDeliveryDebtError,
    discover_adapter_modules,
    omniui_headless_enabled,
    select_adapter,
)

from ovui_widgets.app.components import ComponentManager
from ovui_widgets.app.frame_clock import FrameClock
from ovui_widgets.app.menu_hooks import AppMenuRegistry
from ovui_widgets.app.settings_dialog import SettingsDialog
from ovui_widgets.app.widget_registry import AppWidgetRegistry
from ovui_widgets.app.window_hooks import AppWindowRegistry
from ovui_widgets.common import scheduler as _common_scheduler
from ovui_widgets.common.recent_files import RecentFileList
from ovui_widgets.common.scheduler import CallbackHandle
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.settings import (
    DEFAULT_RATE_LIMIT_FPS,
    RATE_LIMIT_FPS_SETTING_KEY as _RATE_LIMIT_FPS_SETTING_KEY,
    Settings,
    Subscription,
    valid_rate_limit_fps,
)
from ovui_widgets.common.snap import GridSnapProvider, SnapSystem, SurfaceSnapProvider
from ovui_widgets.common.undo import UndoManager

_NATIVE_FAST_EXIT_ENV = "OVUI_WIDGETS_NATIVE_FAST_EXIT"
_SHUTDOWN_TRACE_ENV = "OVUI_WIDGETS_TRACE_SHUTDOWN"
_SETTINGS_PATH_ENV = "OVUI_WIDGETS_SETTINGS_PATH"


def _valid_snap_grid_size(value: Any, default: float = 1.0) -> float:
    """Return a positive finite grid size, falling back for bad settings."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(result) or result <= 0.0:
        return float(default)
    return result




def _native_fast_exit_enabled() -> bool:
    raw = os.environ.get(_NATIVE_FAST_EXIT_ENV, "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    # In-process tests import and call Application.run helpers directly; never
    # terminate the pytest worker. Real subprocess tests inherit this variable.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _fast_exit_after_successful_native_shutdown() -> None:
    if not _native_fast_exit_enabled():
        return
    if os.environ.get(_SHUTDOWN_TRACE_ENV) == "1":
        print(
            "[Application] shutdown complete; native fast exit",
            file=sys.stderr,
            flush=True,
        )
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        # The app has already run Application.shutdown(). Avoid late Python/libc
        # atexit teardown in Carbonite/USDRT stacks after CUDA/Vulkan state has
        # been released by the owning native libraries.
        os._exit(0)


def _resolve_window_size() -> tuple[int, int]:
    """Return ``(width, height)`` for ``ui.init``, honouring env vars.

    ``OVGEAR_HEADLESS_WIDTH`` / ``OVGEAR_HEADLESS_HEIGHT`` let
    ``python -m ovui_widgets.app.headless`` boot the offscreen Vulkan platform at a
    caller-chosen size. With both unset the windowed default stays
    ``1280×720`` (Step 2.3 regression).
    """
    width = int(os.environ.get("OVGEAR_HEADLESS_WIDTH", 1280))
    height = int(os.environ.get("OVGEAR_HEADLESS_HEIGHT", 720))
    return width, height


def _ui_init_supports_kwarg(init_fn: Callable, kwarg: str) -> bool:
    """Return True iff ``init_fn`` accepts ``kwarg`` as a keyword argument.

    We use this in place of catching ``TypeError`` from a speculative call,
    so a real init failure inside a new OVUI build doesn't get masked by a
    silent retry on the legacy signature. ``inspect.signature`` succeeds on
    every Python callable we expect (regular function, method, lambda,
    pybind11 binding); on the rare callable where it raises ``ValueError``
    or ``TypeError`` we conservatively assume the kwarg is unsupported and
    fall through to legacy init.
    """
    try:
        sig = inspect.signature(init_fn)
    except (TypeError, ValueError):
        return False
    params = sig.parameters
    if kwarg in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

class SecondaryFailureRecord:
    """One structured entry of the application-owned fallback diagnostics.

    When a hostile PRIMARY throwable makes normal ``add_note`` attachment
    impossible, each secondary cleanup failure is retained here as the
    ACTUAL exception object — identity, type, attributes, ``__traceback__``
    and ``__cause__`` stay directly inspectable — together with display
    metadata that was generated behind BaseException guards, so reading a
    record never invokes hostile ``__str__``/``__repr__`` formatting.
    """

    __slots__ = ("exception", "display", "attempt")

    def __init__(
        self, exception: BaseException, display: str, attempt: int
    ) -> None:
        self.exception = exception
        self.display = display
        self.attempt = attempt

    def __repr__(self) -> str:
        # ``display`` was pre-formatted with guards; never re-format the
        # retained (possibly hostile) exception object here.
        return (
            f"SecondaryFailureRecord(attempt={self.attempt}, "
            f"display={self.display!r})"
        )


# Bounded fallback-diagnostics policy: the log keeps at most this many
# records by evicting the OLDEST records of PRIOR failed attempts first;
# records of the current failed lifecycle attempt are never evicted, so
# current-attempt evidence stays complete even if it alone exceeds the
# bound. Identity deduplication keeps repeated attempts that re-raise the
# same retained throwables from growing or duplicating the log.
_SECONDARY_FAILURE_LOG_BOUND = 64


def _owns_lifecycle_attempt(method: Callable) -> Callable:
    """Give one PUBLIC lifecycle operation one diagnostic-attempt identity.

    The attempt boundary is the user-observable public operation (open,
    create/new, load, shutdown — each of which may record secondary
    failures through replacement abort or no-document convergence). The
    OUTERMOST decorated frame advances ``_lifecycle_attempt_serial``;
    nested or re-entrant decorated calls that converge through shared
    helpers (``open_file`` → ``_load_stage`` → abort) reuse the owner's
    identity, so a single operation never double-advances or splits
    across attempt identities. Release is BaseException-safe: however
    the operation exits, its records keep their serial and become
    evictable once the NEXT operation advances it.
    """

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        owns = not getattr(self, "_lifecycle_attempt_active", False)
        if owns:
            self._lifecycle_attempt_active = True
            self._lifecycle_attempt_serial = (
                getattr(self, "_lifecycle_attempt_serial", 0) + 1
            )
        try:
            return method(self, *args, **kwargs)
        finally:
            if owns:
                self._lifecycle_attempt_active = False

    return wrapper

_REQUIRE_OVRTX_ENV = "OVUI_WIDGETS_REQUIRE_OVRTX"
_ADAPTER_PROVIDER_ENV = "OVUI_DATA_ADAPTER_PROVIDER"
_NO_PREBUILT_RENDERER = object()

# GLFW modifier bit flags (no omni.ui constants available in this build)
_MOD_CTRL = 2
_MOD_SHIFT = 1
_MOD_ALT = 4
_MOD_META = 8
# Real keyboard modifier bits; used to extract ctrl/shift/alt/super from the
# raw ``modifiers`` value. ``ui.Window::_updateWindow`` OR-s in an
# auxiliary bit (``kModifierFlagWantCaptureKeyboard`` = 1<<30) whenever
# ImGui's global ``io.WantCaptureKeyboard`` is set, which — under ImGui
# 1.92's keyboard-nav path — is true for essentially every real key event
# while the app has focus. Masking on every read keeps hotkey matching
# stable regardless of those auxiliary bits.
_REAL_MODS_MASK = _MOD_SHIFT | _MOD_CTRL | _MOD_ALT | _MOD_META
# GLFW key codes for non-printable keys
_KEY_DELETE = 261
_KEY_BACKSPACE = 259
_KEY_ESCAPE = 256
_KEY_F2 = 291
# GLFW arrow-key codes — used by the Alt+Left / Alt+Right content-
# browser back/forward shortcut (Content-Browser Step 20). Kept with
# the other GLFW key constants so a future move to an ``ImGuiKey`` enum
# only touches this block.
_KEY_ARROW_RIGHT = 262
_KEY_ARROW_LEFT = 263


# ImGui named-key codes. Real GLFW window input reports printable letters and
# non-printable shortcuts as ASCII/GLFW values, while the ovui Inspector and
# remote input bridge inject ImGuiKey values. Normalize both sources before
# application shortcut dispatch so Delete, F2, arrows and letter chords follow
# the same shipped UI path.
_IMGUI_KEY_TAB = 512
_IMGUI_KEY_LEFT_ARROW = 513
_IMGUI_KEY_RIGHT_ARROW = 514
_IMGUI_KEY_UP_ARROW = 515
_IMGUI_KEY_DOWN_ARROW = 516
_IMGUI_KEY_PAGE_UP = 517
_IMGUI_KEY_PAGE_DOWN = 518
_IMGUI_KEY_HOME = 519
_IMGUI_KEY_END = 520
_IMGUI_KEY_INSERT = 521
_IMGUI_KEY_DELETE = 522
_IMGUI_KEY_BACKSPACE = 523
_IMGUI_KEY_SPACE = 524
_IMGUI_KEY_ENTER = 525
_IMGUI_KEY_ESCAPE = 526
_IMGUI_KEY_0 = 536
_IMGUI_KEY_A = 546
_IMGUI_KEY_Z = _IMGUI_KEY_A + 25
_IMGUI_KEY_F1 = 572
_IMGUI_TO_GLFW_KEY = {
    _IMGUI_KEY_TAB: 258,
    _IMGUI_KEY_LEFT_ARROW: _KEY_ARROW_LEFT,
    _IMGUI_KEY_RIGHT_ARROW: _KEY_ARROW_RIGHT,
    _IMGUI_KEY_UP_ARROW: 265,
    _IMGUI_KEY_DOWN_ARROW: 264,
    _IMGUI_KEY_PAGE_UP: 266,
    _IMGUI_KEY_PAGE_DOWN: 267,
    _IMGUI_KEY_HOME: 268,
    _IMGUI_KEY_END: 269,
    _IMGUI_KEY_INSERT: 260,
    _IMGUI_KEY_DELETE: _KEY_DELETE,
    _IMGUI_KEY_BACKSPACE: _KEY_BACKSPACE,
    _IMGUI_KEY_SPACE: ord(" "),
    _IMGUI_KEY_ENTER: 257,
    _IMGUI_KEY_ESCAPE: 256,
}


def _normalize_printable_key(key: int) -> int:
    mapped = _IMGUI_TO_GLFW_KEY.get(key)
    if mapped is not None:
        return mapped
    if _IMGUI_KEY_0 <= key < _IMGUI_KEY_0 + 10:
        return ord("0") + (key - _IMGUI_KEY_0)
    if _IMGUI_KEY_A <= key <= _IMGUI_KEY_Z:
        return ord("A") + (key - _IMGUI_KEY_A)
    if _IMGUI_KEY_F1 <= key < _IMGUI_KEY_F1 + 24:
        return 290 + (key - _IMGUI_KEY_F1)
    return key


def _local_file_url_to_path(path: str) -> str:
    """Convert local ``file://`` URLs to paths accepted by USD."""
    if not path.lower().startswith("file://"):
        return path
    result = path[len("file://") :]
    if (
        os.name == "nt"
        and len(result) >= 3
        and result[0] == "/"
        and result[2] == ":"
    ):
        result = result[1:]
    return os.path.expanduser(result)


def _require_ovrtx_enabled() -> bool:
    raw = os.environ.get(_REQUIRE_OVRTX_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _renderer_required_for_session(session: Any) -> bool:
    """Honor fallback opt-out only when the selected provider supports it."""

    if _require_ovrtx_enabled():
        return True
    allows_fallback = getattr(session, "allows_renderer_fallback", True)
    if callable(allows_fallback):
        allows_fallback = allows_fallback()
    return not bool(allows_fallback)


def _should_close() -> bool:
    """Return True when ovui's standalone backend reports that its
    underlying GLFW window has been requested to close (the user
    clicked the OS-level X button on the title bar). The backend
    exposes this through the private :func:`omni.ui._ui._standalone_should_close`
    function — which we read defensively because:

    1. The import of :mod:`omni.ui._ui` is **lazy** (inside this
       function), not at module top. ``application.py`` is imported
       eagerly by tests, scripts, and the Application bootstrap; if
       this helper imported ``_ui`` at module top, a refactor or
       version skew that removed the symbol would break import-time
       and surface as a startup-time crash rather than a degraded
       X-button path.

    2. The lookup of ``_standalone_should_close`` uses
       ``getattr(..., None)`` so a future ovui release that renames
       or removes the symbol just causes the X-button path to no-op
       silently — the menu File → Exit and programmatic
       :meth:`Application.request_exit` triggers still work.

    3. The call itself is wrapped in ``try/except`` so a runtime
       failure inside ``_standalone_should_close`` (e.g. backend
       partially torn down) doesn't propagate up through
       :meth:`Application.run_async`'s while-condition.

    All three guards together: if any link in the chain fails, this
    helper degrades to ``return False`` and the X-button stops
    producing rc=0 (it would still produce rc=130 via signal
    handling), but the rest of the application keeps running.
    """
    try:
        from omni.ui import _ui as _ovui  # lazy — avoids startup crash
    except ImportError:
        return False
    fn = getattr(_ovui, "_standalone_should_close", None)
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        return False


class Application:
    """
    Central application singleton.

    Application owns the lifecycle of the entire
    USD Viewer process. It creates and holds Settings, UndoManager, SelectionBus,
    applies global styles, manages the frame loop, and provides call_later()
    for deferred execution.
    """

    LAYOUT_SETTINGS_KEY = "ui.layout"
    SETTINGS_SAVE_PATH_KEY = "settings.save_path"
    DEFAULT_SETTINGS_SAVE_PATH = "~/.ovgear/settings.json"
    # Kit-compatible FPS cap for the main run loop (see
    # ovui_widgets.common.settings for the canonical-path provenance).
    # ``--/app/runLoops/main/rateLimitFrequency=N`` works on the app CLI.
    RATE_LIMIT_FPS_SETTING_KEY = _RATE_LIMIT_FPS_SETTING_KEY
    _instance: Optional["Application"] = None

    def __init__(
        self,
        headless: bool = False,
        settings_overrides: Optional[Mapping[str, Any]] = None,
    ) -> None:
        assert Application._instance is None, "Application is a singleton"
        Application._instance = self

        self._settings = Settings()
        self._load_settings()
        # Launch-time overrides (``--/path/to/key=value`` on the command
        # line) are applied after the persisted file so they win over both
        # defaults and persisted values, and before any startup consumer
        # (theme, snap system) reads the store. They are launch-local:
        # never persisted by _save_settings unless explicitly set at
        # runtime afterwards (see Settings.apply_launch_overrides). Invalid
        # values for validated keys (e.g. the FPS cap) are rejected at the
        # store boundary — both here and for persisted-file loads — so the
        # visible value is valid by construction.
        if settings_overrides:
            self._settings.apply_launch_overrides(settings_overrides)
        self._undo_manager = UndoManager()
        self._selection_bus = SelectionBus()
        SelectionBus._instance = self._selection_bus  # register as singleton
        self._menu_registry = AppMenuRegistry(self)
        self._window_registry = AppWindowRegistry(
            self,
            menu_registry=self._menu_registry,
        )
        self._component_manager = ComponentManager(self)
        self._widget_registry = AppWidgetRegistry()
        self._pending_callbacks: list[CallbackHandle] = []
        # Register this Application's call_later as the process-wide
        # scheduler backend so widget code can call
        # ``ovui_widgets.common.scheduler.call_later`` instead of
        # ``Application.instance().call_later`` (per Rev 8 §5.5 +
        # implementation Step 5). Cleared on shutdown.
        _common_scheduler.set_call_later(self.call_later)
        self._frame_sub: Optional[Any] = None
        self._run_exception: Optional[BaseException] = None
        self._running = False
        self._main_win: Optional[Any] = None
        self._file_menu: Optional[Any] = None
        self._layer_menu: Optional[Any] = None
        self._menu_underline_win: Optional[Any] = None
        self._status_win: Optional[Any] = None
        self._dockspace: Optional[Any] = None
        self._status_bar: Optional[Any] = None
        self._stage_window: Optional[Any] = None
        self._property_window: Optional[Any] = None
        self._viewport_window: Optional[Any] = None
        self._content_window: Optional[Any] = None
        self._layer_window: Optional[Any] = None

        self._current_stage_sub: Optional[Subscription] = None
        self._stage_adapter: Optional[Any] = None
        self._layer_adapter: Optional[Any] = None
        self._filter_capture: bool = False  # True while filter bar has remote focus
        self._stage_change_listeners: List[Callable] = []
        self._mock_prop_sub: Optional[Any] = None
        # A namespace undo/redo updates USD + OVStage synchronously but its
        # RESYNC notifications are delivered on the next frame.  Native
        # TreeView can report an empty selection in that gap because its
        # selected HierarchyItem no longer resolves.  Keep the pre-history
        # paths and combine every RESYNC path from the command, then remap once
        # all of those deferred callbacks have drained.
        self._history_selection_reconcile: Optional[dict[str, Any]] = None
        self._history_selection_generation: int = 0
        self._deferred_selection_reconcile: Optional[dict[str, Any]] = None
        self._deferred_selection_generation: int = 0

        # Content-Browser Step 38 — modifier-bit snapshot from the most
        # recent key event (:meth:`_on_key_pressed` writes the masked
        # value here). ovui's :class:`WidgetMouseDropEvent` does not
        # carry modifier state; a drop handler that needs Ctrl at drop
        # time reads this attribute. Press-and-hold of Ctrl lands a
        # key-press event at key-down time with ``_MOD_CTRL`` set, so
        # the value is authoritative for the "Ctrl held while dragging"
        # case a fraction of a second later.
        self._last_modifier_bits: int = 0

        self._settings_dialog = SettingsDialog(self)

        self._snap_system = SnapSystem()
        self._grid_snap_provider = GridSnapProvider(
            _valid_snap_grid_size(self._settings.get("snap.grid_size", 1.0))
        )
        self._snap_system.add_provider(self._grid_snap_provider)
        self._snap_system.add_provider(SurfaceSnapProvider())
        self._snap_system.enable(bool(self._settings.get("snap.enabled", False)))
        self._snap_sub: Optional[Subscription] = self._settings.subscribe(
            "snap.enabled", self._on_snap_enabled_changed
        )
        self._snap_grid_sub: Optional[Subscription] = self._settings.subscribe(
            "snap.grid_size", self._on_snap_grid_size_changed
        )
        self._theme_sub: Optional[Subscription] = self._settings.subscribe(
            "ui.theme", self._on_theme_changed
        )
        self._rate_limit_sub: Optional[Subscription] = self._settings.subscribe(
            self.RATE_LIMIT_FPS_SETTING_KEY, self._on_rate_limit_fps_changed
        )

        initial_recent = self._settings.get("ui.recent_files", [])
        self._recent_files = RecentFileList(initial_recent)
        # Step 10/13: wire common-side singletons so widget reads stop
        # routing through ``Application.instance().{settings,_recent_files}``.
        # Both are cleared in :meth:`shutdown`. Done after the
        # corresponding instance attributes are initialised so the
        # registered objects are the live ones the rest of Application
        # already uses.
        Settings.set_instance(self._settings)
        RecentFileList.set_instance(self._recent_files)

        # USD file to open once the UI is up. Set by run() when a CLI arg is given.
        self._startup_usd_path: Optional[str] = None
        self._startup_prebuilt_renderer: Any = _NO_PREBUILT_RENDERER

        # Render cadence for the viewport. The clock decides when
        # :meth:`ViewportWidget.render` is allowed to run; per-tick physics
        # (flight, tumble inertia) advance every frame regardless via
        # :meth:`ViewportWidget.update`. See ``ovui_widgets.app/frame_clock.py``.
        # The target comes from the Kit-compatible rateLimitFrequency setting
        # (CLI overrides included); the frame loop reads only the clock's
        # cached target — live changes arrive via _on_rate_limit_fps_changed.
        self._viewport_render_clock = FrameClock(
            target_fps=self._effective_rate_limit_fps(),
        )

        # Step 2.6: headless full-UI export state. Initialised by
        # :meth:`_setup_headless_export` once the run-loop starts under
        # ``OMNIUI_HEADLESS=1`` + ``OVGEAR_LIVESTREAM=1``; the
        # per-frame hook (:meth:`_run_headless_export_hook`) reads
        # these to push ovui's offscreen Vulkan frame to NVENC. All
        # ``None`` / ``False`` in windowed mode — the hook is a no-op
        # when ``_headless_export_active`` is False.
        self._headless_tap: Optional[Any] = None
        self._headless_frame_module: Optional[Any] = None
        self._headless_export_active: bool = False
        self._headless_export_disable_logged: bool = False

        # Tier 3 livestream input bridge. ``None``
        # in windowed mode and until the headless livestream tap
        # registers a bridge via :meth:`set_remote_input_bridge`. When
        # set, :meth:`_drain_remote_input` fires once per frame ahead of
        # ``await ui.next_frame()`` and translates the bridge's queued
        # events into ``omni.ui._ui._inject_*`` calls.
        self._remote_input_bridge: Optional[Any] = None
        # Cached reference to ``omni.ui._ui`` populated by
        # :meth:`run_async` before the loop starts so the drain hook
        # doesn't re-import every frame.
        self._ui_native: Optional[Any] = None

        # Tier 3 custom-message dispatcher.
        # Set by :meth:`_setup_headless_export`; ``None`` in windowed
        # mode and until the headless tap is brought up. The
        # dispatcher owns a queue: the ovstream worker thread parses
        # incoming envelopes and enqueues work items;
        # :meth:`_drain_message_queue` runs them on the main loop
        # ahead of ``await ui.next_frame()`` so application/UI state
        # is only mutated on the main thread (Codex Step 3.7 NOT-GOOD
        # finding 1 fix).
        self._message_dispatcher: Optional[Any] = None

        # Optional external inspector module. When ``ovuiinspect`` is on
        # ``PYTHONPATH``, :meth:`_setup_optional_ovinspect` imports it
        # during app startup and :meth:`_drain_ovinspect` lets its HTTP
        # worker thread marshal ovui actions onto the frame loop.
        self._ovinspect_module: Optional[Any] = None

        # Filesystem path of the currently-open USD stage. Set by
        # :meth:`open_file` after a successful :meth:`_load_stage` and
        # by :meth:`save_stage_to` after a successful export. Read by
        # :func:`ovui_widgets.app.menu_bar._on_save_clicked` to decide whether
        # File > Save writes directly (path present) or re-routes
        # through Save As (path ``None`` — e.g. a mock/in-memory stage
        # or the app's default stage). See the content browser implementation step 55.
        self._current_file_path: Optional[str] = None
        self._scratch_stage_dirs: list[str] = []
        self._adapter_registry: AdapterRegistry | None = None
        self._adapter_provider: AdapterProvider | None = None
        self._adapter_factories: AdapterFactories | None = None
        self._adapter_session: Any | None = None
        self._component_module_load_failures: list[Any] = []

    @staticmethod
    def instance() -> "Application":
        """Return the singleton Application. Raises if not created yet."""
        if Application._instance is None:
            raise RuntimeError("Application not created yet")
        return Application._instance

    @staticmethod
    def _requested_adapter_provider_name() -> str | None:
        raw = os.environ.get(_ADAPTER_PROVIDER_ENV, "")
        provider_name = raw.strip()
        return provider_name or None

    def _get_adapter_factories(self) -> AdapterFactories:
        adapter_factories = getattr(self, "_adapter_factories", None)
        if adapter_factories is not None:
            return adapter_factories
        if not hasattr(self, "_adapter_registry"):
            self._adapter_registry = None
        if not hasattr(self, "_adapter_provider"):
            self._adapter_provider = None
        if not hasattr(self, "_adapter_factories"):
            self._adapter_factories = None

        if self._adapter_factories is not None:
            return self._adapter_factories

        requested_provider = self._requested_adapter_provider_name()
        registry = discover_adapter_modules(requested_name=requested_provider)
        provider = select_adapter(registry, requested_provider)
        self._adapter_registry = registry
        self._adapter_provider = provider
        self._adapter_factories = provider.factories
        return self._adapter_factories

    def _require_factory(self, name: str) -> Callable[..., Any]:
        factory = getattr(self._get_adapter_factories(), name, None)
        if not callable(factory):
            provider_name = self._adapter_provider.name if self._adapter_provider else "unknown"
            raise RuntimeError(
                f"data adapter provider {provider_name!r} does not provide {name!r}"
            )
        return factory

    def get_adapter_session(self) -> Any:
        if not hasattr(self, "_adapter_session"):
            self._adapter_session = None
        if self._adapter_session is not None:
            return self._adapter_session
        session_factory = self._require_factory("session")
        self._adapter_session = session_factory(self)
        return self._adapter_session

    @property
    def component_module_load_failures(self) -> tuple[Any, ...]:
        return tuple(self._component_module_load_failures)

    def report_module_load_failure(
        self,
        name: str,
        value: str,
        exc: BaseException,
    ) -> Any:
        from ovui_widgets.app.component_loader import ComponentModuleLoadFailure

        failure = ComponentModuleLoadFailure.from_exception(name, value, exc)
        self._component_module_load_failures.append(failure)
        return failure

    def request_exit(self) -> None:
        """Request a clean application exit.

        Flips ``self._running = False`` so :meth:`run_async`'s loop
        exits at the next frame boundary; that triggers the
        ``finally:`` clause which calls :meth:`shutdown` while ovui's
        standalone backend is still alive.

        This is the public API every exit trigger should use:
        File → Exit, OS X-button polling, ``Ctrl+Q`` hotkey, etc.
        Thread affinity (Round 2 F10): **UI thread only.** This method
        is a single attribute write on the Application instance. CPython
        guarantees attribute writes are atomic at the bytecode level,
        so a stray write from a worker thread will not corrupt state —
        but USD Viewer has no synchronisation around ``_running``,
        ``_pending_callbacks``, or any other Application-side state.
        Every existing ``_running`` read happens on the asyncio/UI
        thread (``run_async``'s ``while`` loop). Calling
        ``request_exit()`` from a worker thread is therefore technically
        a race (the change becomes visible "eventually", subject to the
        GIL) but never a crash. If you need a deterministic exit
        request from a worker thread, marshal the call through
        ``Application.call_later(0.0, app.request_exit)`` (the existing
        callback scheduler).
        """
        self._running = False
        # Wake an in-flight ovui pacing wait so a low-FPS cap can't strand
        # the exit for the remainder of the period. Best-effort — legacy
        # OVUI builds without request_wakeup just wait the period out.
        try:
            import omni.ui as ui
            wake = getattr(ui, "request_wakeup", None)
            if wake is not None:
                wake()
        except Exception:
            pass

    @property
    def settings(self) -> Settings:
        return self._settings

    def _settings_persistence_enabled(self) -> bool:
        """Return whether app settings should load/save for this process."""

        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
            _SETTINGS_PATH_ENV
        ):
            return False
        return True

    def _resolve_settings_save_path(self) -> str:
        """Resolve the JSON app settings path, honoring the QA env override."""

        env_path = os.environ.get(_SETTINGS_PATH_ENV, "").strip()
        if env_path:
            return os.path.expanduser(env_path)
        configured = self._settings.get(
            self.SETTINGS_SAVE_PATH_KEY,
            self.DEFAULT_SETTINGS_SAVE_PATH,
        )
        return os.path.expanduser(str(configured))

    def _load_settings(self) -> None:
        """Load persistent app settings before widgets consume them."""

        if not self._settings_persistence_enabled():
            return
        path = self._resolve_settings_save_path()
        if not path or not os.path.exists(path):
            return
        try:
            self._settings.load_from_file(path)
        except Exception as exc:
            print(
                f"[Application] failed to load settings from {path!r}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    def _save_settings(self) -> None:
        """Save persistent app settings on the normal shutdown path."""

        if not self._settings_persistence_enabled():
            return
        path = self._resolve_settings_save_path()
        if not path:
            return
        try:
            self._settings.save_to_file(path)
        except Exception as exc:
            print(
                f"[Application] failed to save settings to {path!r}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    def _get_stage_adapter(self) -> Optional[Any]:
        """Return the live :class:`StageAdapter` (or ``None``).

        Step 11.3 added this bound-method accessor so
        :class:`ovui_widgets.viewport.viewport_widget.ViewportWidget`
        receives a single-argument callable for stage-adapter access
        instead of reaching into ``Application._stage_adapter``
        directly. Bound-method form is the canonical accessor; a
        lambda wrapping a single attribute access would add no value
        and would make the caller more verbose.
        """
        return self._stage_adapter

    @property
    def undo_manager(self) -> UndoManager:
        return self._undo_manager

    @property
    def selection_bus(self) -> SelectionBus:
        return self._selection_bus

    def call_later(self, delay_secs: float, callback: Callable) -> CallbackHandle:
        """Schedule callback to fire after delay_secs. Returns CallbackHandle."""
        handle = CallbackHandle(time.monotonic() + delay_secs, callback)
        self._pending_callbacks.append(handle)
        return handle

    def _use_viewport_frame_pacing(self) -> None:
        """Let the viewport render clock own foreground render pacing.

        USD Viewer performs ovrtx rendering after ``await ui.next_frame()``.
        If standalone ovui also sleeps at the cap rate, that sleep is added
        on top of the renderer's own frame time and an otherwise cap-rate
        scene settles well below it. Re-reads the rateLimitFrequency setting
        so a CLI override survives this re-assertion.
        """
        self._viewport_render_clock.target_fps = self._effective_rate_limit_fps()

    def _effective_rate_limit_fps(self) -> float:
        """Current usable FPS cap from settings, falling back to the default."""
        return valid_rate_limit_fps(
            self._settings.get(
                self.RATE_LIMIT_FPS_SETTING_KEY, DEFAULT_RATE_LIMIT_FPS
            ),
            default=DEFAULT_RATE_LIMIT_FPS,
        )

    def _apply_rate_limit_to_ui_pump(self, fps: float) -> None:
        """Propagate the FPS cap to ovui's standalone run-loop pump.

        The ovui pump is the actual main loop (``ui.run`` ticks the UI,
        pumps asyncio, then sleeps the remainder of ``1/max_fps`` for the
        iteration — the same per-iteration minimum-loop-time semantics as
        Kit's omni.kit.loop-default). ``set_max_frame_rate`` also wakes an
        in-flight pacing wait so the change takes effect immediately.
        Best-effort: a legacy OVUI build without the setter keeps whatever
        cap ``ui.init`` established.
        """
        try:
            import omni.ui as ui
        except Exception:
            return
        setter = getattr(ui, "set_max_frame_rate", None)
        if setter is not None:
            setter(fps)

    def _use_standalone_frame_pacing(self) -> None:
        """Compatibility alias for older tests/scripts."""
        self._use_viewport_frame_pacing()

    def _on_frame_update(self, tick_dt: float) -> None:
        """Called each frame. Fires call_later() callbacks, drives viewport update + render.

        ``tick_dt`` is the wall-clock interval since the previous outer-loop
        tick. It feeds physics that has to advance every tick regardless of
        whether the viewport renders this frame — flight-mode keyboard
        integration and tumble inertia decay are speed-times-seconds, not
        per-render quantities.

        The viewport's render path is gated separately by
        :attr:`_viewport_render_clock`. ``render_dt`` (returned from
        :meth:`FrameClock.should_render`) is the time since the last *committed*
        render — that's the value the FPS HUD wants and the value the renderer
        sees as its own delta. Only after :meth:`ViewportWidget.render` returns
        ``True`` does the clock get committed, so a zero-size or hidden frame
        does not poison the cadence.

        Every callback / widget step is wrapped in try/except so a bad handler
        can't kill the frame loop — the viewport has to keep rendering even
        when stage notices misroute or a subscription path raises. The
        exception is logged via :class:`ErrorReporter` for diagnosis.
        """
        from ovui_widgets.common.error_reporter import ErrorReporter
        callback_now = time.monotonic()
        render_now = time.perf_counter()
        callbacks_to_drain = self._pending_callbacks
        self._pending_callbacks = []
        remaining = []
        for handle in callbacks_to_drain:
            if handle._cancelled:
                continue
            if callback_now >= handle._due_time:
                cb = handle._callback
                if cb is not None:
                    try:
                        cb()
                    except Exception as exc:
                        ErrorReporter.log_error(
                            "Application", "call_later callback raised", exc
                        )
                handle._callback = None  # mark as fired
            else:
                remaining.append(handle)
        if remaining:
            self._pending_callbacks = remaining + self._pending_callbacks

        self._tick_adapter_physics(tick_dt)
        if self._viewport_window is None:
            return

        # Per-tick wall-clock update — flight + tumble physics advance every
        # tick, never gated by the render cadence. Without this the camera
        # stalls during a tumble whenever the render gate skips a frame.
        try:
            self._viewport_window.update(tick_dt)
        except Exception as exc:
            ErrorReporter.log_error(
                "Application", "viewport update raised", exc
            )

        # Render gate — only call render() when the clock says we're due.
        render_dt = self._viewport_render_clock.should_render(render_now)
        if render_dt is None:
            return
        try:
            rendered = self._viewport_window.render(render_dt)
        except Exception as exc:
            ErrorReporter.log_error(
                "Application", "viewport render raised", exc
            )
            rendered = False
        if rendered:
            self._viewport_render_clock.commit(render_now)

    def _tick_adapter_physics(self, tick_dt: float) -> None:
        session = getattr(self, "_adapter_session", None)
        if session is None:
            return
        controls = getattr(session, "physics_controls", None)
        tick = getattr(controls, "tick", None)
        if not callable(tick):
            return
        try:
            tick(tick_dt)
        except Exception as exc:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.log_error("Application", "adapter physics tick raised", exc)

    # ── Step 2.6: headless full-UI frame export hook ──

    @staticmethod
    def _headless_export_env_active() -> bool:
        """True iff ``OMNIUI_HEADLESS=1`` and ``OVGEAR_LIVESTREAM`` is set
        to a truthy value. Both must be on for the export pipeline to
        start; flipping either at runtime won't toggle the hook (the
        env is sampled once at setup)."""
        if not omniui_headless_enabled():
            return False
        livestream_raw = os.environ.get("OVGEAR_LIVESTREAM", "").strip().lower()
        return livestream_raw in ("1", "true", "yes")

    def _setup_headless_export(self) -> None:
        """Bring up the headless full-UI export pipeline. Idempotent.

        Runs once when ``run_async`` starts, after ovui has rendered
        its first frame. Creates a :class:`LivestreamTap` and calls
        :func:`omni.ui.standalone.headless_frame.init`. A failure at
        any step leaves the hook inactive; the renderer keeps ticking
        as if no export was requested.
        """
        if self._headless_export_active:
            return
        if not self._headless_export_env_active():
            return
        try:
            from omni.ui.standalone import headless_frame
        except Exception as exc:
            print(
                f"[ovgear/headless] export setup failed (import): {exc}",
                file=sys.stderr,
            )
            return

        try:
            tap = self.get_adapter_session().create_livestream_tap()
        except Exception as exc:
            print(
                f"[ovgear/headless] export setup failed (adapter): {exc}",
                file=sys.stderr,
            )
            return
        if tap is None:
            # ``maybe_create`` already logged the reason (env disabled,
            # ovstream missing, init raised). No further action — the
            # main loop will run with no export.
            return

        # ``headless_frame.init`` returns ``True`` on a successful
        # first-time init; ``False`` means the C++ side refused (no
        # platform initialised, env not set, backend not Vulkan) *or*
        # the pipeline was already initialised by a previous call.
        # Either way we can't trust subsequent ``copy_to_linear`` /
        # ``wait_ready`` calls to do anything useful, so treat
        # ``False`` exactly like an exception: tear the tap down and
        # leave the hook inactive.
        try:
            init_ok = bool(headless_frame.init())
        except Exception as exc:
            print(
                f"[ovgear/headless] headless_frame.init raised: {exc}",
                file=sys.stderr,
            )
            try:
                tap.close()
            except Exception:
                pass
            return
        if not init_ok:
            print(
                "[ovgear/headless] headless_frame.init returned False "
                "(pipeline refused or already initialised); export "
                "stays inactive",
                file=sys.stderr,
            )
            try:
                tap.close()
            except Exception:
                pass
            return

        self._headless_tap = tap
        self._headless_frame_module = headless_frame
        self._headless_export_active = True

        # Step 3.6: bring up the Tier 3 input bridge and hand it to
        # both the tap (which registers ``Server.on_input/on_unicode/
        # on_connection`` before ``Server.start``) and the application
        # main loop (which calls :meth:`_drain_remote_input` once per
        # frame ahead of ``await ui.next_frame()``). Initial extents
        # are placeholder; ``LivestreamTap._ensure_server`` calls
        # ``bridge.set_extents`` with the real ovui frame size on
        # every server bring-up.
        try:
            from ovui_widgets.app._input_bridge import RemoteInputBridge
            bridge = RemoteInputBridge(width=1, height=1)
            tap.set_input_bridge(bridge)
            self.set_remote_input_bridge(bridge)
        except Exception as exc:
            # An input-bridge failure must not disable the streaming
            # tap itself — UI streaming without remote control is the
            # original Tier 1/Tier 2 behavior and remains the fallback.
            print(
                f"[ovgear/headless] input bridge setup failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

        # Step 3.7: Kit-style custom-message dispatcher. Drives stage
        # open + live resolution change from web-viewer-sample-style
        # JSON envelopes received over ``Server.on_message``. The
        # dispatcher's worker-thread ``on_message`` only parses and
        # enqueues; ``Application._drain_message_queue`` runs on the
        # main loop and executes the recognised actions. Failures in
        # setup leave the tap streaming with no message channel —
        # same fall-back posture as the input bridge above.
        try:
            from ovui_widgets.app._message_dispatcher import MessageDispatcher

            def _send_message(text: str) -> None:
                # Read the server reference at send-time. The
                # dispatcher only sends in response to an inbound
                # message, by which point ``_ensure_server`` has
                # published the server.
                server = getattr(tap, "_server", None)
                if server is None:
                    return
                server.send_message(text)

            dispatcher = MessageDispatcher(send_message_fn=_send_message)
            tap.set_message_dispatcher(dispatcher)
            self._message_dispatcher = dispatcher
        except Exception as exc:
            print(
                f"[ovgear/headless] message dispatcher setup failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

        print(
            "[ovgear/headless] export pipeline live "
            "(wait_ready → copy_to_linear → tee_linear_to_ovstream → "
            "signal_consumed per frame)",
            file=sys.stderr,
        )

    def _disable_headless_export(self, reason: str) -> None:
        """Permanently disable the export hook for this session.

        Called from :meth:`_run_headless_export_hook` on any
        non-recoverable failure. The renderer + ovui keep ticking; the
        hook becomes a no-op for the rest of the run. Logged once so
        a recurring failure does not spam stderr.
        """
        self._headless_export_active = False
        if not self._headless_export_disable_logged:
            print(
                f"[ovgear/headless] export disabled: {reason}",
                file=sys.stderr,
            )
            self._headless_export_disable_logged = True

    def _run_headless_export_hook(self) -> None:
        """Per-frame headless export. Called between ``await ui.next_frame()``
        and ``_on_frame_update`` in the main loop.

        Strict ordering on a successful tick:

        1. ``headless_frame.wait_ready(10ms)`` — schedules a CUDA wait
           on the V→C semaphore so subsequent CUDA work observes the
           rendered frame.
        2. ``headless_frame.extent()`` — current width/height of the
           offscreen render target.
        3. ``tap.acquire_linear_scratch(w, h)`` — next slot in the
           pitched ring (lazy-allocated on first call).
        4. ``headless_frame.copy_to_linear(ptr, pitch, stream=0)`` —
           ``cudaMemcpy2DFromArrayAsync`` from the V→C-synced
           ``cudaArray`` into the slot.
        5. ``tap.tee_linear_to_ovstream(ptr, w, h, pitch)`` — runs the
           R/B swap kernel in place, ``cudaStreamSynchronize(0)``,
           builds the ``VideoFrame`` and calls ``Server.stream_video``
           (all internal to the tap; see Step 2.5).
        6. ``headless_frame.signal_consumed()`` — fires the C→V
           semaphore so ovui's next tick can reuse the offscreen image.

        Failure isolation:

        - ``wait_ready`` / ``extent`` / ``acquire_linear_scratch`` /
          ``copy_to_linear`` / ``signal_consumed`` raising →
          permanent disable (:meth:`_disable_headless_export`); the
          next frame is a no-op.
        - ``wait_ready`` returning ``False`` → permanent disable
          (the pipeline reports success with ``True``; a False
          return means it never queued the V→C wait and any
          subsequent CUDA work would race ovui's render).
        - ``copy_to_linear`` returning ``False`` → permanent disable
          *after* a best-effort ``signal_consumed`` so the V/C
          semaphore pair stays balanced and ovui isn't left
          blocked on its next render.
        - Zero-extent (ovui hasn't rendered yet) → frame skip with
          ``signal_consumed`` to keep the V/C pair balanced. This
          is the only genuinely transient case in the hook.
        - ``tee_linear_to_ovstream`` is exception-safe by design
          (Step 2.5); its return value records pushed/skipped state
          but never propagates a failure here.
        """
        if not self._headless_export_active:
            return
        tap = self._headless_tap
        headless_frame = self._headless_frame_module
        if tap is None or headless_frame is None:
            self._disable_headless_export("setup state missing")
            return

        # 1. wait_ready — 10 ms timeout in nanoseconds (per the plan).
        try:
            ready = bool(headless_frame.wait_ready(10_000_000))
        except Exception as exc:
            self._disable_headless_export(
                f"wait_ready raised: {type(exc).__name__}: {exc}"
            )
            return
        if not ready:
            # ``wait_ready`` returning False means the V→C wait was
            # never queued; subsequent CUDA work would race ovui's
            # render. Permanent disable. Skip ``signal_consumed`` —
            # there's no V→C wait outstanding to balance.
            self._disable_headless_export("wait_ready returned False")
            return

        # 2. extent — refuse to drive the rest of the pipeline until
        # ovui has rendered a non-zero frame.
        try:
            w, h = headless_frame.extent()
        except Exception as exc:
            self._disable_headless_export(
                f"extent raised: {type(exc).__name__}: {exc}"
            )
            return
        if w <= 0 or h <= 0:
            self._signal_consumed_safely(headless_frame)
            return

        # 3. acquire next ring slot.
        try:
            dev_ptr, pitch = tap.acquire_linear_scratch(int(w), int(h))
        except Exception as exc:
            self._disable_headless_export(
                f"acquire_linear_scratch raised: {type(exc).__name__}: {exc}"
            )
            return

        # 4. copy ovui's offscreen frame into the slot.
        try:
            copied = bool(headless_frame.copy_to_linear(int(dev_ptr), int(pitch), 0))
        except Exception as exc:
            self._disable_headless_export(
                f"copy_to_linear raised: {type(exc).__name__}: {exc}"
            )
            return
        if not copied:
            # ``copy_to_linear`` returning False means the pipeline
            # is in a state where the copy can't run (uninitialised
            # or invalid params per the wrapper docstring). The V→C
            # wait was already queued by ``wait_ready``, so we MUST
            # issue ``signal_consumed`` first to keep the pair
            # balanced; otherwise ovui's next tick deadlocks waiting
            # for a C→V signal that never comes. Then permanent
            # disable.
            self._signal_consumed_safely(headless_frame)
            self._disable_headless_export("copy_to_linear returned False")
            return

        # 5. publish — tap method is exception-safe (Step 2.5). It
        # runs the R/B swap kernel + cudaStreamSynchronize(0) +
        # VideoFrame + Server.stream_video internally, with its own
        # disable / skip handling.
        tap.tee_linear_to_ovstream(int(dev_ptr), int(w), int(h), int(pitch))

        # 6. signal_consumed — must run regardless of whether
        # stream_video pushed or skipped, so the next ovui tick can
        # reuse the offscreen image.
        try:
            headless_frame.signal_consumed()
        except Exception as exc:
            self._disable_headless_export(
                f"signal_consumed raised: {type(exc).__name__}: {exc}"
            )
            return

    @staticmethod
    def _signal_consumed_safely(headless_frame: Any) -> None:
        """Best-effort ``signal_consumed`` for the skip paths. Never
        raises; a failure here is logged but does not flip the
        disable flag (the caller has already decided this frame is a
        skip and the next tick will retry)."""
        try:
            headless_frame.signal_consumed()
        except Exception as exc:
            print(
                f"[ovgear/headless] signal_consumed (skip path) raised: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    def _teardown_headless_export(self) -> None:
        """Tear down the export pipeline. Idempotent. Called from
        :meth:`shutdown`."""
        tap = self._headless_tap
        headless_frame = self._headless_frame_module
        self._headless_tap = None
        self._headless_frame_module = None
        self._headless_export_active = False
        if tap is not None:
            try:
                tap.close()
            except Exception:
                pass
        if headless_frame is not None:
            try:
                headless_frame.shutdown()
            except Exception:
                pass

    def set_remote_input_bridge(self, bridge: Optional[Any]) -> None:
        """Register the Tier 3 livestream input bridge.

        Called by the selected provider's livestream tap
        once the ovstream ``Server`` has been brought up but **before**
        ``Server.start`` (Step 3.6). Pass ``None`` to detach. The
        per-tick :meth:`_drain_remote_input` hook is a no-op while the
        bridge is unset.
        """
        self._remote_input_bridge = bridge

    def _drain_remote_input(self) -> None:
        """Pre-tick drain of the Tier 3 input bridge.

        Must run **before** ``await ui.next_frame()`` so the injected
        events land in the same tick's ``applyInjectedInput`` pass
        (``HeadlessVulkanPlatform.cpp:485``, immediately before
        ``ImGui::NewFrame`` at ``:487``). Calling after the await would
        defer the events to the next tick.
        """
        bridge = self._remote_input_bridge
        if bridge is None:
            return
        ui_native = self._ui_native
        if ui_native is None:
            return
        from ovui_widgets.app._input_drain import drain_bridge_into_ui
        drain_bridge_into_ui(
            bridge,
            ui_native,
            on_left_click=self._on_remote_left_click,
            on_char=self._on_remote_char,
        )

    def _on_remote_left_click(self, x: int, y: int) -> None:
        """Synthesise widget focus for left-click events from the remote.

        omni.ui ``set_mouse_pressed_fn`` callbacks do not fire from ImGui
        IO injection (they run in ovui's own event dispatch layer, not via
        ``io.AddMouseButtonEvent``).  This method tracks whether a click
        landed in a region whose widget requires direct model updates for
        keyboard input to register.

        The live Stage Browser filter widget supplies its actual screen rect;
        a fixed layout fallback is used only before layout has completed.
        A click in that rect arms ``_filter_capture`` so that subsequent
        printable-key events update the filter model directly via
        :meth:`_on_remote_char`.  A click outside the filter bar disarms
        it so accidental keypresses elsewhere do not corrupt the filter.
        """
        widget = getattr(getattr(self, "_stage_window", None), "_widget", None)
        border = getattr(widget, "_filter_border_rect", None)
        try:
            left = float(getattr(border, "screen_position_x", 0.0) or 0.0)
            top = float(getattr(border, "screen_position_y", 0.0) or 0.0)
            width = float(getattr(border, "computed_width", 0.0) or 0.0)
            height = float(getattr(border, "computed_height", 0.0) or 0.0)
        except (TypeError, ValueError):
            width = height = 0.0
            left = top = 0.0
        if width > 0.0 and height > 0.0:
            in_filter = left <= x < left + width and top <= y < top + height
        else:
            from ovui_widgets.app.layout import MENU_BAR_HEIGHT, SIDE_PANEL_WIDTH

            in_filter = (
                0 <= x < SIDE_PANEL_WIDTH
                and MENU_BAR_HEIGHT <= y < MENU_BAR_HEIGHT + 30
            )
        self._filter_capture = bool(in_filter and widget is not None)
        if self._filter_capture:
            focus = getattr(widget, "_focus_filter_field", None)
            if callable(focus):
                focus()

    def _on_remote_char(self, ch: str) -> None:
        """Route a printable character from the remote to the focused widget.

        When the Stage Browser filter bar is armed (``_filter_capture``),
        each synthesised character is appended directly to the filter
        model.  ``StringField.model.set_value`` triggers the
        ``add_value_changed_fn`` chain, which hides the placeholder label
        and re-runs the tree filter — producing an immediate visible state
        change without requiring ImGui keyboard focus to be set.
        """
        if not self._filter_capture:
            return
        if self._stage_window is None:
            return
        widget = getattr(self._stage_window, "_widget", None)
        if widget is None:
            return
        field = getattr(widget, "_filter_field", None)
        if field is None:
            return
        # Modern ovui builds deliver injected ImGui text to a focused
        # StringField. The direct-model path is only a compatibility fallback;
        # using both would duplicate every character.
        border = getattr(widget, "_filter_border_rect", None)
        if str(getattr(border, "name", "")) == "focused":
            return
        current = field.model.get_value_as_string()
        field.model.set_value(current + ch)

    def _drain_message_queue(self) -> None:
        """Pre-tick drain of the Tier 3 custom-message queue.

        Runs the application action and emits the reply for each
        envelope the ovstream worker thread parsed during the previous
        tick. Calling on the main loop is the load-bearing fix from
        the Codex Step 3.7 review — :meth:`Application.open_file` and
        the resize path both touch app/UI state and must not be driven
        from the SDK callback thread.

        No-op when no dispatcher is registered (windowed mode or
        before :meth:`_setup_headless_export` has run).
        """
        dispatcher = self._message_dispatcher
        if dispatcher is None:
            return
        try:
            dispatcher.drain_pending(
                open_stage_fn=self.open_file,
                resize_fn=self._do_resize,
            )
        except Exception as exc:
            # The dispatcher itself catches per-action exceptions and
            # turns them into structured "error" replies; this guard
            # only catches an internal failure of the dispatcher's
            # bookkeeping. Either way the main loop must not unwind.
            print(
                f"[ovgear/livestream] message drain raised: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    def _setup_optional_ovinspect(self) -> None:
        """Import and attach the optional ovui HTTP inspector.

        The inspector is deliberately outside the ovui-widgets dependency graph.
        A normal application launch has no ``ovuiinspect`` module and this is
        a silent no-op; a QA launch can opt in with
        ``PYTHONPATH=/path/to/skill python -m ovui_widgets.app...``.
        """
        try:
            import ovuiinspect as inspector
        except ImportError:
            try:
                import ovinspect as inspector
            except ImportError:
                return

        self._ovinspect_module = inspector
        attach = getattr(inspector, "attach_application", None)
        if callable(attach):
            try:
                attach(self)
            except Exception as exc:
                print(
                    f"[ovinspect] attach_application raised: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

    def _drain_ovinspect(self) -> None:
        """Drain pending inspector actions onto the ovui frame loop."""
        inspector = self._ovinspect_module
        if inspector is None:
            return
        ui_native = self._ui_native
        if ui_native is None:
            return
        drain = getattr(inspector, "drain_pending", None)
        if not callable(drain):
            return
        try:
            drain(ui_native, application=self)
        except Exception as exc:
            print(
                f"[ovinspect] drain_pending raised: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    def get_inspector_state(self) -> dict[str, Any]:
        """Return a read-only provider/adapter/UI snapshot for automated QA.

        The ovui Inspector marshals this call onto the application's frame
        loop.  User actions still arrive exclusively through Inspector mouse
        and keyboard endpoints; this method only supplies independent evidence
        that the visible action reached the active provider's scene state
        (native OVStage, or the OpenUSD provider's stage when that provider
        is selected) and the widget adapter hierarchy.
        """

        from ovui_widgets.app.inspector_state import capture_application_state

        return capture_application_state(self)

    def _do_resize(self, width: int, height: int) -> bool:
        """Apply a Step 3.7 ``changeResolutionRequest``.

        Two-tier strategy that resizes the **active streamed frame**:

        1. ``omni.ui.standalone.set_window_size(width, height)`` —
           works in **windowed** mode (GLFW backend). Returns ``True``
           when the framebuffer matches the request after the next
           ``glfwPollEvents`` (``StandaloneInit.cpp:209–238``).

        2. ``omni.ui.standalone.headless_frame.resize(width, height)``
           — works in **headless** mode. Tears down the CUDA-Vulkan
           interop, updates the headless platform extent, drives one
           tick to recreate the Vulkan framebuffer, verifies the new
           extent, and re-imports the new image into CUDA. Returns
           ``False`` (and best-effort restores the prior interop
           state) on any of: no headless platform active, framebuffer
           extent mismatch after tick, or CUDA re-import failure.

        After **either** path succeeds, the actual streamed-frame
        extent is read back via :func:`headless_frame.extent` and
        propagated to ``RemoteInputBridge.set_extents`` so input
        clamping tracks the **real** new resolution. The
        :class:`LivestreamTap` rebuilds its scratch ring on the next
        frame because its ``_ensure_server`` checks
        ``headless_frame.extent()`` per tick (see
        that tap's per-frame server check).

        Returns ``True`` only when one of the two paths reported
        success. Returns ``False`` when both refuse — the dispatcher
        then emits ``changeResolutionConfirmation{result:"error"}``.
        """
        try:
            from omni.ui.standalone import set_window_size as _ovui_set_window_size
        except Exception:
            _ovui_set_window_size = None

        windowed_ok = False
        if _ovui_set_window_size is not None:
            try:
                windowed_ok = bool(_ovui_set_window_size(width, height))
            except Exception as exc:
                print(
                    f"[ovgear/livestream] set_window_size raised: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                windowed_ok = False

        headless_ok = False
        if not windowed_ok:
            try:
                from omni.ui.standalone import headless_frame as _headless_frame
            except Exception:
                _headless_frame = None
            if _headless_frame is not None and hasattr(_headless_frame, "resize"):
                try:
                    headless_ok = bool(_headless_frame.resize(width, height))
                except Exception as exc:
                    print(
                        f"[ovgear/livestream] headless_frame.resize raised: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    headless_ok = False

        if not (windowed_ok or headless_ok):
            return False

        # The active extent may differ from the request when the
        # backend clamps (e.g. Vulkan caps to device limits). Read
        # back so the bridge clamps to the *actual* streamed-frame
        # extent — Codex Step 3.7 review #2 demanded the bridge
        # follow the real frame, not the requested size.
        actual_w, actual_h = width, height
        try:
            from omni.ui.standalone import headless_frame as _headless_frame
            ext = _headless_frame.extent()
            if isinstance(ext, tuple) and len(ext) == 2:
                ext_w, ext_h = ext
                if ext_w > 0 and ext_h > 0:
                    actual_w, actual_h = int(ext_w), int(ext_h)
        except Exception:
            # Windowed mode (no headless_frame extent) — keep the
            # requested dimensions, which set_window_size already
            # confirmed match the framebuffer.
            pass

        bridge = self._remote_input_bridge
        if bridge is not None:
            try:
                bridge.set_extents(actual_w, actual_h)
            except Exception as exc:
                print(
                    f"[ovgear/livestream] bridge.set_extents raised: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        # The tap reads ``headless_frame.extent()`` at the top of every
        # ``_ensure_server`` call, so it self-rebuilds at the new
        # extent on the next frame; no explicit notify needed here.
        return True

    def run(self, usd_path: Optional[str] = None) -> None:
        """Main entry point. Initializes ovui, applies styles, runs the event loop.

        If ``usd_path`` is given, the stage is opened after the UI is built so the
        ovrtx renderer and real USD adapters take over from the mock defaults.
        """
        if (
            usd_path
            and omniui_headless_enabled()
            and self._startup_prebuilt_renderer is _NO_PREBUILT_RENDERER
        ):
            self._startup_prebuilt_renderer = self._preconstruct_ovrtx_renderer()

        import omni.ui as ui

        from ovui_widgets.app.layout import write_split_ini
        from ovui_widgets.app.style import apply_global_styles, set_theme

        # ``max_fps`` caps the OVUI run-loop's tick rate — this IS the
        # Kit-style main-loop enforcement of rateLimitFrequency. The pump's
        # budget is start-to-start (frame_start is captured before the tick,
        # and the app coroutine's work runs inside the same iteration's
        # asyncio pump), so the sleep only tops the iteration up to
        # ``1/max_fps``; it is never added on top of renderer work. Live
        # setting changes propagate via ui.set_max_frame_rate from
        # _on_rate_limit_fps_changed.
        #
        # We probe ``ui.init``'s signature with ``inspect.signature`` instead
        # of catching ``TypeError`` from a hopeful call. A blanket TypeError
        # catch would also swallow internal init failures from a new OVUI
        # build that does accept the keyword — silently retrying init with a
        # legacy signature would mask the real bug.
        win_width, win_height = _resolve_window_size()
        if _ui_init_supports_kwarg(ui.init, "max_fps"):
            ui.init(
                "USD Viewer",
                width=win_width,
                height=win_height,
                max_fps=self._effective_rate_limit_fps(),
            )
            self._use_viewport_frame_pacing()
        else:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.log_warning(
                "Application",
                "ui.init has no max_fps kwarg — running against legacy OVUI; "
                "the FrameClock still gates viewport rendering, but the "
                "run-loop tick rate itself is uncapped.",
            )
            ui.init("USD Viewer", width=win_width, height=win_height)
        # Write the canonical split layout AFTER ui.init so the GLFW
        # platform has reported the monitor's content scale and
        # ``Workspace.get_dpi_scale`` returns the real value. Writing
        # before ui.init pinned the dock tree at DPI=1.0 (the fallback
        # before any window exists), which made every side panel
        # render at logical half-width on a 200% display. ImGui defers
        # loading imgui.ini until its first NewFrame, so we still land
        # ahead of the first frame the panels render into.
        write_split_ini()
        self._setup_optional_ovinspect()
        apply_global_styles()
        set_theme(self._settings.get("ui.theme", "dark"))

        self._startup_usd_path = usd_path
        self._run_exception = None
        self._running = True
        self._frame_sub = self.run_async()
        try:
            ui.run(self._frame_sub)
        finally:
            self._running = False
        if self._run_exception is not None:
            raise self._run_exception
        if not getattr(self, "_shutdown_done", False):
            raise RuntimeError(
                "application event loop ended before native shutdown completed"
            )
        _fast_exit_after_successful_native_shutdown()

    async def run_async(self) -> None:
        """Build the main window and run the frame loop.

        The ``try`` block opens at the very start of the body — BEFORE
        ``self._main_win = ui.MainWindow()`` and the panel/menu/status
        bar constructors. That way a failure in any
        ovui resource construction still drives the ``finally`` clause
        that calls :meth:`shutdown`, which is what guarantees those
        resources don't leak into ``Py_FinalizeEx``.
        """
        import omni.ui as ui

        from ovui_widgets.app.layout import MENU_BAR_HEIGHT
        from ovui_widgets.app.menu_bar import build_menu_bar
        from ovui_widgets.app.status_bar import StatusBar

        # Cache the C-binding submodule so :meth:`_drain_remote_input`
        # doesn't re-resolve it every frame. Installed before any panel
        # construction so the bridge could in principle drain on the
        # very first tick, although in practice no client connects that
        # early.
        from ovui_widgets.common.error_reporter import ErrorReporter

        try:
            # Cooperative/shared hosts (``_main_async``) reach here without
            # :meth:`run`'s ``ui.init(max_fps=...)`` bootstrap, so the
            # embedder's already-initialized pump may still carry a
            # different cap (ovui's library default is 60). Install the
            # current effective settings-derived cap before the first
            # controlled tick. On the windowed path this re-asserts the
            # value run() already passed to ui.init — a harmless no-op.
            self._apply_rate_limit_to_ui_pump(self._effective_rate_limit_fps())
            # Cache the C-binding submodule so :meth:`_drain_remote_input`
            # doesn't re-resolve it every frame. Installed before any panel
            # construction so the bridge could in principle drain on the
            # very first tick, although in practice no client connects that
            # early.
            self._ui_native = ui._ui
            # MainWindow owns the application chrome and root docker:
            # main_menu_bar for the top menu, the internal "DockSpace" host for
            # docked panels, and status_bar_frame for status messages.
            self._main_win = ui.MainWindow()

            from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
            from ovui_widgets.common.testing.mock_stage import MockStageAdapter
            from ovui_widgets.content import ContentBrowserWindow
            from ovui_widgets.layers import LayerWindow
            from ovui_widgets.property import PropertyWidget  # DEPRECATED alias → PropertyWindow
            from ovui_widgets.stage.window import StageWindow
            from ovui_widgets.viewport.viewport_widget import ViewportWidget

            self._stage_window = StageWindow(adapter=MockStageAdapter())
            self._property_window = PropertyWidget()
            self._viewport_window = ViewportWidget(
                services=self,
                renderer=MockRendererAdapter(),
                on_drop_fn=lambda event: self._on_drop(event, target="viewport"),
                stage_adapter_provider=self._get_stage_adapter,
            )
            # Share the render cadence gate: event-driven direct renders
            # (resize / resolution refresh) go through the same FrameClock
            # as the frame loop, so repeated events cannot exceed the
            # rateLimitFrequency cap.
            self._viewport_window.set_shared_render_clock(
                self._viewport_render_clock
            )
            # Step 11.4/13: pass the open-file callback explicitly so
            # ``FileBrowserWidget._on_file_item_double_clicked`` no
            # longer reaches into ``Application.instance().open_file``.
            self._content_window = ContentBrowserWindow(
                open_file_fn=self.open_file,
                recent_files=self._recent_files,
                settings=self._settings,
            )
            # LayerWindow has no stage adapter yet — Step 9 will wire the
            # UsdLayerStackAdapter through ``set_adapter`` on file open.
            self._layer_window = LayerWindow(
                services=self,
                before_save_all_fn=self._persist_layer_state_before_save,
            )
            for widget in (
                self._stage_window,
                self._property_window,
                self._viewport_window,
                self._content_window,
                self._layer_window,
            ):
                self._widget_registry.add(widget)

            # Wire mock property adapter for selections when no USD stage is loaded.
            self._mock_prop_sub = self._selection_bus.subscribe(self._on_mock_selection)
            self._component_manager.load_all()

            # Keep the existing menu content and top-strip dimensions, but build
            # it in MainWindow's main menu bar instead of in a separate window.
            self._main_win.main_menu_bar.height = ui.Pixel(MENU_BAR_HEIGHT)
            with self._main_win.main_menu_bar:
                build_menu_bar(self)

            self._status_bar = StatusBar(
                self._main_win.status_bar_frame,
                call_later_fn=self.call_later,
            )

            self._register_shortcuts()
            self._register_drop_handler()
            ErrorReporter._set_status_bar(self._status_bar)
            ErrorReporter.initialize(self, self._status_bar.label)

            # Wait one frame so ImGui renders all windows and assigns dock node IDs.
            # dock_in() requires non-zero DockIds which are only assigned after the
            # first rendered frame.
            await ui.next_frame()

            self._restore_layout()
            from ovui_widgets.app.layout import apply_default_layout, show_panel_dock_tab_bars
            for _ in range(4):
                await ui.next_frame()
                apply_default_layout()
                show_panel_dock_tab_bars()

            # If a USD path was passed on the command line, open it now that the
            # panels exist. open_file() wires real adapters and swaps the renderer.
            if self._startup_usd_path:
                self.open_file(self._startup_usd_path)
                self._startup_usd_path = None
            else:
                # No file argument — create a file-backed empty stage when
                # the active adapter supports it. Adapters without scene
                # creation launch with no active document.
                self._load_empty_startup_stage()

            # Step 2.6: bring up the headless full-UI export pipeline if
            # ``OMNIUI_HEADLESS=1`` and ``OVGEAR_LIVESTREAM`` are both set.
            # No-op in windowed mode.
            self._setup_headless_export()

            last_tick = time.perf_counter()
            while self._running and not _should_close():
                # Step 3.3 — Tier 3 input drain. Runs BEFORE
                # ``next_frame`` so injected events feed into this
                # tick's ``applyInjectedInput`` pass
                # (``HeadlessVulkanPlatform.cpp:485``, before
                # ``ImGui::NewFrame`` at ``:487``). No-op when no
                # remote bridge is registered.
                self._drain_remote_input()
                # Step 3.7 — Tier 3 custom-message drain. Runs on the
                # main thread so application/UI mutations
                # (``open_file``, ``set_window_size``) never happen on
                # the ovstream worker thread that fires
                # ``Server.on_message``.
                self._drain_message_queue()
                # Optional inspector input drain. When the ovui-inspector
                # skill is on PYTHONPATH, this runs before ``next_frame`` so
                # injected mouse/keyboard events are visible to the same tick.
                self._drain_ovinspect()
                # Discard the FrameInfo return value. We re-derive
                # tick_dt from time.perf_counter() so this loop works against
                # both new and legacy OVUI builds without branching.
                await ui.next_frame()
                # Step 2.6 hook runs after the frame is rendered and before
                # _on_frame_update so the streamed frame is the most recent
                # ovui tick. No-op when headless export isn't active.
                self._run_headless_export_hook()
                now = time.perf_counter()
                tick_dt = max(0.0, now - last_tick)
                last_tick = now
                self._on_frame_update(tick_dt)
                # Main-loop pacing is NOT done here: the ovui pump that
                # drives ``ui.next_frame`` enforces rateLimitFrequency for
                # the whole iteration (ui.init max_fps +
                # ui.set_max_frame_rate on live changes). One cap, one
                # place — no nested throttling around this coroutine.
        except Exception as exc:
            self._run_exception = exc
            self._running = False
        finally:
            # Always tear down — even if construction at the top raised.
            # Two inner try/excepts so a raise in _clear_status_bar()
            # doesn't skip shutdown(), and vice versa. The shutdown()
            # body itself is best-effort (Step 1 / Round 2 F3) — the
            # outer wrapper here just keeps a late-breaking exception
            # out of asyncio's "Task exception was never retrieved"
            # chatter, NOT for retry purposes.
            try:
                ErrorReporter._clear_status_bar()
            except Exception:
                pass
            try:
                self.shutdown()
            except Exception as shutdown_exc:
                if self._run_exception is None:
                    self._run_exception = shutdown_exc
                else:
                    add_note = getattr(self._run_exception, "add_note", None)
                    if callable(add_note):
                        add_note(
                            "application shutdown also failed: "
                            f"{type(shutdown_exc).__name__}: {shutdown_exc}"
                        )
                try:
                    ErrorReporter.log_error(
                        "Application",
                        "shutdown raised in run_async finally",
                        shutdown_exc,
                    )
                except Exception:
                    pass

    def _register_shortcuts(self) -> None:
        """Wire keyboard shortcuts on every panel window.

        ``ui.Window::_updateWindow`` only invokes ``key_pressed_fn`` on the
        currently-focused window (``IsWindowFocused``). Binding a single
        handler to ``menu_win`` means W/E/R/Ctrl+Z stop working the moment
        the user clicks into any panel — which is the normal interaction
        pattern. Attach the same handler to every panel window so the
        shortcut dispatcher runs regardless of which panel owns focus.
        Only one window is focused at a time, so no duplicate events fire.
        """
        handler = self._on_key_pressed
        if self._main_win is not None and hasattr(self._main_win, "set_key_pressed_fn"):
            self._main_win.set_key_pressed_fn(handler)
        for mw in (
            self._stage_window,
            self._property_window,
            self._viewport_window,
            self._content_window,
            self._layer_window,
        ):
            if mw is None:
                continue
            win = getattr(mw, "window", None)
            if win is not None and hasattr(win, "set_key_pressed_fn"):
                win.set_key_pressed_fn(handler)

    def _register_drop_handler(self) -> None:
        """Register drag-and-drop handlers on the main window and per-panel
        windows that accept cross-window drops (Content-Browser Step 40 —
        the content browser behavior).

        The main window catches drops on the menu strip (bare OS-level
        drop onto the app). The viewport window catches drops aimed at
        the 3D view — the primary "drag-to-use" workflow for a USD file
        dragged from the content browser. The stage window catches drops
        aimed at the prim tree; v1 logs "Add Reference not yet
        implemented" and falls back to open-as-stage. Each hook is
        behind a ``hasattr(win, "set_drop_fn")`` guard because ovui's
        test build exposes :class:`ui.Window` without the C++-only
        :meth:`set_drop_fn` surface.
        """
        if self._main_win is not None and hasattr(self._main_win, "set_drop_fn"):
            self._main_win.set_drop_fn(self._on_drop)
        # Step 40 — per-window drop hooks for cross-window routing. The
        # stage window uses a lambda target so the drop dispatcher can
        # branch on origin; the viewport owns its own drop shim (see
        # :meth:`ViewportWidget._on_drop`) that delegates back here with
        # the viewport target.
        if self._stage_window is not None:
            win = getattr(self._stage_window, "window", None)
            if win is not None and hasattr(win, "set_drop_fn"):
                win.set_drop_fn(lambda ev: self._on_drop(ev, target="stage"))

    _USD_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")

    def _on_drop(self, event: Any, target: str = "main") -> None:
        """Handle a file/URL dropped onto an USD Viewer window.

        ``target`` identifies the window that received the drop so
        cross-window routing (the content browser behavior) can
        branch semantics:

        * ``"main"``  — drop on the menu-bar strip (legacy bare OS drop).
        * ``"viewport"`` — drop on the 3D viewport; first USD URL opens
          as the active stage.
        * ``"stage"`` — drop on the Stage Browser tree; v1 logs
          ``"[ovgear] Add Reference not yet implemented"`` and falls
          back to open-as-stage (per the content browser implementation step 40 — content-
          layer USD reference ops are out of scope until a later step).

        The ``event.mime_data`` payload is parsed as a ``"\\n"``-joined
        URL list (matches the content browser's internal-drag MIME
        format — see :meth:`FileBrowserWidget._tree_drag_payload`).
        Empty / missing payloads and payloads whose segments are all
        whitespace-only silently no-op. For multi-URL drops the first
        USD URL is opened as the new stage; the remaining URLs are
        ignored in v1 (future step: add them as references on the
        newly-opened stage). Non-USD URLs surface a single status-bar
        warning per URL via :class:`ErrorReporter.show_status`.
        """
        raw = getattr(event, "mime_data", None)
        if not raw:
            return
        urls = [u for u in raw.split("\n") if u and u.strip()]
        if not urls:
            return
        if target == "stage":
            print(
                "[ovgear] Add Reference not yet implemented — "
                "falling back to open as stage",
            )
        from ovui_widgets.common.error_reporter import ErrorReporter
        opened = False
        for url in urls:
            if any(url.lower().endswith(ext) for ext in self._USD_EXTENSIONS):
                if not opened:
                    self.open_file(url)
                    opened = True
            else:
                ErrorReporter.show_status(
                    f"Unsupported file type: {Path(url).suffix}",
                    level="warning",
                )

    def _on_key_pressed(self, key: int, modifiers: int, pressed: bool) -> None:
        # Forward every key event (press AND release) to the viewport's
        # flight-mode keyboard so it can track W/A/S/D/Q/E/Space/C.
        # Releases are ignored by the app-level shortcut dispatch below
        # but are essential for flight mode to know when a key comes up.
        if self._viewport_window is not None:
            flight_kb = getattr(self._viewport_window, "_flight_keyboard", None)
            if flight_kb is not None:
                flight_kb.handle_key_event(key, modifiers, pressed)
        # Step 10/13: forward the masked modifier mask to the content
        # browser on every key event (press AND release) so the
        # ``FileBrowserWidget._modifier_bits`` snapshot used by
        # ``_is_ctrl_drop`` reflects a Ctrl release between drag-start
        # and drop. Routed through a dedicated
        # ``forward_modifier_bits`` method so the existing
        # ``_on_key_pressed`` shortcut-dispatch path stays press-only.
        if self._content_window is not None and hasattr(
            self._content_window, "forward_modifier_bits",
        ):
            self._content_window.forward_modifier_bits(
                modifiers & _REAL_MODS_MASK,
            )
        if not pressed:
            return
        key = _normalize_printable_key(int(key))
        # Mask out auxiliary bits (``kModifierFlagWantCaptureKeyboard`` and
        # any future nav flags) so only the real ctrl/shift/alt/super bits
        # drive shortcut matching. See ``_REAL_MODS_MASK`` comment above.
        modifiers &= _REAL_MODS_MASK
        # Step 38 — expose masked modifier state so widgets whose event
        # surfaces do not carry modifiers (ovui's
        # :class:`WidgetMouseDropEvent`, specifically) can read Ctrl at
        # drop time. Written on every real key press, so the value is
        # never stale at drop-time under the "Ctrl-press then drag"
        # sequence that a user performs.
        self._last_modifier_bits = modifiers
        ctrl = modifiers & _MOD_CTRL
        shift = modifiers & _MOD_SHIFT
        alt = modifiers & _MOD_ALT
        # Ctrl+Z — undo
        if ctrl and key in (ord("Z"), ord("z")) and not shift:
            self._run_history_action(self._undo_manager.undo)
        # Ctrl+Y or Ctrl+Shift+Z — redo
        elif ctrl and (key in (ord("Y"), ord("y")) or
                       (key in (ord("Z"), ord("z")) and shift)):
            self._run_history_action(self._undo_manager.redo)
        # Ctrl+Shift+S — save-as on the root layer (LAYERS-PLAN Step 59).
        # Must sit before the bare Ctrl+S branch because Ctrl+Shift+S
        # also has the Ctrl bit set and the plain save-all route would
        # otherwise swallow it.
        elif ctrl and shift and not alt and key in (ord("S"), ord("s")):
            self.save_stage_as()
        # Ctrl+Alt+S — save-as on the focused LayerItem (Layers window
        # focused only). Same "match-before-plain-S" ordering reason.
        elif ctrl and alt and not shift and key in (ord("S"), ord("s")):
            self.save_focused_layer_as()
        # Ctrl+S — save every dirty layer in one undo group.
        elif ctrl and not shift and not alt and key in (ord("S"), ord("s")):
            self.save_stage()
        # Ctrl+L — toggle Layers window visibility.
        elif ctrl and not shift and not alt and key in (ord("L"), ord("l")):
            self._toggle_layers_window()
        # Ctrl+C / Ctrl+X / Ctrl+V — content-browser clipboard ops
        # (Content-Browser Step 36). Dispatched to the
        # :class:`ContentBrowserWindow` which proxies to
        # :class:`FileBrowserWidget`'s selection resolver. Each is a
        # no-op when nothing is selected (Ctrl+C / Ctrl+X) or the
        # clipboard is empty (Ctrl+V) — matches the fan-out rule
        # used by F2 and Del so the shortcut reaches the user's active
        # surface without needing a focus signal. ``not alt`` / ``not
        # shift`` guard against a future Ctrl-Alt / Ctrl-Shift chord
        # accidentally firing the clipboard op.
        elif (ctrl and not alt and not shift
              and key in (ord("C"), ord("c"))):
            if self._content_window is not None:
                self._content_window.copy_selected()
        elif (ctrl and not alt and not shift
              and key in (ord("X"), ord("x"))):
            if self._content_window is not None:
                self._content_window.cut_selected()
        elif (ctrl and not alt and not shift
              and key in (ord("V"), ord("v"))):
            if self._content_window is not None:
                self._content_window.paste_into_current()
        # Ctrl+D — content-browser duplicate (Content-Browser Step 37).
        # Same fan-out rule as Ctrl+C / X / V: dispatched to the
        # :class:`ContentBrowserWindow`'s ``duplicate_selected`` which
        # proxies to the widget's selection resolver. No-op when
        # nothing is selected. ``not alt and not shift`` guards the
        # future Ctrl+Shift+D / Ctrl+Alt+D chords from accidentally
        # firing Duplicate.
        elif (ctrl and not alt and not shift
              and key in (ord("D"), ord("d"))):
            if self._content_window is not None:
                self._content_window.duplicate_selected()
        # Delete / Backspace — Layers panel takes priority when it has
        # selected prim specs (Step 50: ``RemovePrimSpecsCommand``);
        # otherwise the stage prim-delete path runs and the content
        # browser independently fires its own confirm-and-delete dialog.
        # Stage and content selections are independent models, so both
        # are notified — Del fires wherever the user's selection lives.
        elif key in (_KEY_DELETE, _KEY_BACKSPACE):
            # When the Stage Browser filter text field owns keyboard input, a
            # Backspace/Delete belongs to that field's inline text editing and
            # must not also fire the destructive selection-delete fan-out
            # (Layers prim-spec / Stage prim / Content Browser). When the filter
            # is not editing, the intentional delete shortcut runs unchanged.
            filter_editing = (
                self._stage_window is not None
                and self._stage_window.is_filter_editing()
            )
            if not filter_editing and not self._delete_selected_prim_specs_in_layers():
                self._delete_selected()
                if self._content_window is not None:
                    self._content_window.delete_selected()
        # F — frame selected in viewport
        elif key in (ord("F"), ord("f")):
            self._frame_selected()
        # F2 — rename selected in stage browser or content browser.
        # Both begin_rename_selected calls are guarded: each window's
        # widget reads its own selection surface and no-ops when it is
        # empty. Dispatching to both means F2 fires the rename in
        # whichever pane the user is actually interacting with —
        # Stage's selection tracks prims, Content's tracks files, and
        # the two are independent selection models.
        elif key == _KEY_F2:
            if self._stage_window is not None:
                self._stage_window.begin_rename_selected()
            if self._content_window is not None:
                self._content_window.begin_rename_selected()
        # Alt+Left / Alt+Right — content-browser visited-history
        # back/forward (Content-Browser Step 20). Dispatched to the
        # :class:`ContentBrowserWindow`'s ``go_back`` / ``go_forward``
        # which proxy to the widget's :class:`BrowserBar`. Guarded on
        # ``alt and not ctrl and not shift`` so a future
        # Ctrl-Alt-Shift chord does not accidentally fire the nav.
        elif alt and not ctrl and not shift and key == _KEY_ARROW_LEFT:
            if self._content_window is not None:
                self._content_window.go_back()
        elif alt and not ctrl and not shift and key == _KEY_ARROW_RIGHT:
            if self._content_window is not None:
                self._content_window.go_forward()
        # W / E / R — transform-tool switch (the viewport behavior).
        # Gated on RMB not being held so W/E in flight mode still reach
        # the camera flight keyboard unambiguously.
        elif key in (ord("W"), ord("E"), ord("R"),
                     ord("w"), ord("e"), ord("r")) and not ctrl and not shift:
            self._dispatch_tool_hotkey(key, modifiers)
        else:
            # Escape cancels an active gizmo drag (preview rolls back;
            # mouse-up cannot commit); otherwise normal routing below.
            if key == _KEY_ESCAPE and not ctrl and not shift and not alt:
                cancel = getattr(self._viewport_window,
                                 "cancel_active_transform_drag", None)
                if callable(cancel):
                    try:
                        if cancel(reason="escape"):
                            return
                    except Exception:
                        pass
            # Content-Browser Step 58 — Alt+Up / F5 / Ctrl+F / Ctrl+Home /
            # Escape. Dispatch is owned by
            # :meth:`ContentBrowserWindow._on_key_pressed` so the
            # content-browser-scoped shortcut surface lives in one
            # place; this fan-out hook forwards any key the existing
            # branches above did not match. The dispatcher's own
            # per-shortcut predicates decide whether to act; everything
            # else falls through to a silent no-op (``return False``).
            # The ``hasattr`` guard protects the test harnesses that
            # stub :attr:`_content_window` with a minimal fake that
            # does not implement :meth:`_on_key_pressed`.
            if self._content_window is not None and hasattr(
                self._content_window, "_on_key_pressed",
            ):
                self._content_window._on_key_pressed(key, modifiers, pressed)

    def _dispatch_tool_hotkey(self, key: int, modifiers: int) -> None:
        """Route W/E/R to the viewport's :class:`ToolRegistry`.

        Suppressed while RMB is held so ``W`` / ``E`` keep their camera
        flight-mode semantics (forward / roll). Normalises lowercase key
        codes to uppercase before forwarding, since the tool registry's
        key table uses uppercase (GLFW-style) codes.
        """
        if self._viewport_window is None:
            return
        flight_kb = getattr(self._viewport_window, "_flight_keyboard", None)
        if flight_kb is not None and flight_kb.rmb_held:
            return
        tool_registry = getattr(self._viewport_window, "_tool_registry", None)
        if tool_registry is None:
            return
        # Uppercase the key so lowercase 'w'/'e'/'r' also dispatches.
        upper = key - 32 if ord("a") <= key <= ord("z") else key
        tool_registry.handle_key_event(upper, modifiers, True)

    def _run_history_action(self, action: Callable[[], Any]) -> Any:
        """Run undo/redo and reconcile selection after deferred RESYNCs.

        OVStage change subscribers intentionally use ``call_later`` so native
        topology is never rebuilt from inside a USD authoring callback.  The
        TreeView may therefore clear its stale item selection after ``action``
        returns but before Application receives the matching old/new namespace
        paths.  Capturing the canonical bus selection here lets the final
        callback restore or remap it only after all command notices have run.
        """

        bus = getattr(self, "_selection_bus", None)
        selected: tuple[str, ...] = ()
        if bus is not None:
            try:
                selected = tuple(
                    str(path)
                    for path in bus.get_snapshot().paths()
                    if str(path).startswith("/")
                )
            except Exception:
                selected = ()

        if selected:
            generation = int(
                getattr(self, "_history_selection_generation", 0)
            ) + 1
            self._history_selection_generation = generation
            self._history_selection_reconcile = {
                "generation": generation,
                "selected": selected,
                "event_paths": [],
            }
        else:
            generation = 0
            self._history_selection_reconcile = None

        try:
            return action()
        finally:
            if generation:
                self.call_later(
                    0.0,
                    lambda g=generation: self._finish_history_selection_reconcile(g),
                )

    def _finish_history_selection_reconcile(self, generation: int) -> None:
        pending = getattr(self, "_history_selection_reconcile", None)
        if not pending or int(pending.get("generation", 0)) != int(generation):
            return
        self._history_selection_reconcile = None
        Application._reconcile_selection_paths(
            self,
            pending.get("selected", ()),
            pending.get("event_paths", ()),
        )

    def _finish_deferred_selection_reconcile(self, generation: int) -> None:
        pending = getattr(self, "_deferred_selection_reconcile", None)
        if not pending or int(pending.get("generation", 0)) != int(generation):
            return
        self._deferred_selection_reconcile = None
        bus = getattr(self, "_selection_bus", None)
        if bus is not None:
            current = tuple(str(path) for path in bus.get_snapshot().paths())
            captured = tuple(str(path) for path in pending.get("selected", ()))
            # A non-empty, different selection is a real user/peer update, not
            # the TreeView's transient stale-item clear. Never overwrite it.
            if current and current != captured:
                return
        Application._reconcile_selection_paths(
            self,
            pending.get("selected", ()),
            pending.get("event_paths", ()),
        )

    def _delete_selected_prim_specs_in_layers(self) -> bool:
        """Handle Del when the Layers window owns focus (Step 50).

        Returns ``True`` when the key was consumed by the Layers path —
        either a command was pushed, or the window was focused but
        either the adapter was missing or no ``PrimSpecItem`` sat in
        the selection. Either way, Del must not propagate to the
        Stage prim-delete path while Layers is the focused panel, or
        the user would see a prim vanish from the stage for a
        Layers-window keystroke.

        When ``layer_window`` is absent or unfocused, returns
        ``False`` so the caller falls through to :meth:`_delete_selected`.
        """
        lw = self._layer_window
        if lw is None or not lw.is_focused:
            return False
        if self._layer_adapter is None:
            return True
        from ovui_widgets.layers.commands import RemovePrimSpecsCommand
        from ovui_widgets.layers.prim_spec_item import PrimSpecItem
        selected = [
            s for s in lw.get_selected_items() if isinstance(s, PrimSpecItem)
        ]
        if not selected:
            return True
        entries = [(s.layer_item.identifier, s.path) for s in selected]
        cmd = RemovePrimSpecsCommand(
            self._layer_adapter, self._selection_bus, entries
        )
        self._undo_manager.push(cmd)
        return True

    def _delete_selected(self) -> None:
        snap = self._selection_bus.get_snapshot()
        if snap is None or not snap.items or self._stage_adapter is None:
            return

        # Capture the selection paths BEFORE any mutation so a future
        # ``Undo`` can restore them. Without this, deleting the selected
        # prim leaves the selection bus pointing at a path whose backing
        # ``Usd.Prim`` is now invalid — the next ``call_later`` notice
        # flush iterates that stale selection, calls
        # ``stage.GetPrimAtPath(deleted_path)`` for change-tracking, and
        # raises ``RuntimeError: Accessed invalid null prim``. The Stage
        # tree row also remains visibly highlighted because its model
        # subscribes to the selection bus and was never told the
        # selection changed. Codex final-UI-QA rerun (2026-05-08)
        # caught this regression on `tests/data/simple_scene.usda` →
        # `/World/Cube`.
        prior_paths = [item.path for item in snap.items]
        prior_source = snap.items[0].source if snap.items else "delete"
        bus = self._selection_bus
        session = self.get_adapter_session()
        can_delete = getattr(session, "can_delete_prims", None)
        if callable(can_delete) and not can_delete():
            return

        class _SelectionDuringDeleteCommand(Command):
            """Clear selection on ``do``; restore the prior selection on ``undo``.

            Pushed FIRST inside the Delete undo-group so its ``do`` runs
            before any ``DeletePrimCommand.do``. Inside an :class:`UndoGroup`
            commands undo in reverse, so this command's ``undo`` runs LAST,
            after every deleted prim has been restored — selection then
            re-targets a real prim.
            """

            def do(self) -> None:
                bus.clear()

            def undo(self) -> None:
                bus.publish(prior_paths, source=prior_source)

        self._undo_manager.begin_group("Delete")
        self._undo_manager.push(_SelectionDuringDeleteCommand())
        for path in prior_paths:
            cmd = session.make_delete_prim_command(self._stage_adapter.stage, path)
            self._undo_manager.push(cmd)
        self._undo_manager.end_group()

    def _persist_layer_state_before_save(self) -> bool:
        """Persist layer-window state for providers that support it.

        The OpenUSD layer adapter stores the current authoring-layer identifier
        and advisory lock map in root-layer ``customLayerData``. The hook is
        provider-optional: adapters without it — including the native OVStage
        provider, which has no backing USD stage or layer persistence — retain
        their existing save behavior.

        ``False`` means the save must stop: writing source layers after a
        failed metadata update would produce an artifact that silently forgets
        the user's authoring-layer choice.
        """

        layer_adapter = self._layer_adapter
        persist = getattr(layer_adapter, "persist_layer_state_before_save", None)
        if not callable(persist):
            return True
        stage = getattr(self._stage_adapter, "stage", None)
        if stage is None:
            return False
        try:
            persist(stage)
        except Exception as exc:  # noqa: BLE001
            from ovui_widgets.common.error_reporter import ErrorReporter

            ErrorReporter.log_error(
                "Application",
                "layer state persistence before save failed",
                exc,
            )
            ErrorReporter.show_error(
                "Cannot save layer state: "
                f"{type(exc).__name__}: {exc}",
            )
            return False
        return True

    def save_stage(self) -> None:
        """Save every dirty layer in the current stage (LAYERS-PLAN Step 59).

        Global Ctrl+S entry point. Routes through
        :meth:`LayerModel._request_save_all` so anonymous layers are
        skipped (they have no file path) and every dirty, concrete
        layer saves inside a single ``"Save All"`` undo group — same
        path the Save-All toolbar button uses. Shows a "No stage open"
        toast when invoked before any stage is loaded; this is the
        Logic M6 gap the step closes (users coming from Kit muscle-
        memory Ctrl+S and expect feedback).
        """
        if not self._require_layer_stage_or_warn():
            return
        model = self._layer_window._model if self._layer_window else None
        if model is None:
            return
        model._request_save_all()

    def save_stage_as(self) -> None:
        """Save-as dialog for the stage's root layer (LAYERS-PLAN Step 59).

        Global Ctrl+Shift+S entry point. Targets the Layers tree root
        item and passes ``replace_in_parent=False`` so the root layer
        is cloned to a new path without rewriting any parent reference
        (the root has no parent in the sublayer stack). No-op when no
        stage is loaded (surfaces a toast).
        """
        if not self._require_layer_stage_or_warn():
            return
        model = self._layer_window._model if self._layer_window else None
        if model is None or model.root_item is None:
            return
        model._request_save_as(model.root_item, replace_in_parent=False)

    def save_focused_layer_as(self) -> None:
        """Save-as on the Layers-window focused LayerItem (Step 59).

        Ctrl+Alt+S entry point — scoped to Layers window focus so the
        shortcut is ambiguous-free with :meth:`save_stage_as`. Uses
        :attr:`LayerModel.selected_items` single-LayerItem rule; a
        no-selection or multi-selection falls back to the root layer
        so the gesture is never a silent no-op. No-op (with toast) if
        no stage is loaded or the Layers window is unfocused.
        """
        lw = self._layer_window
        if lw is None or not lw.is_focused:
            return
        if not self._require_layer_stage_or_warn():
            return
        model = lw._model
        if model is None:
            return
        from ovui_widgets.layers.layer_item import LayerItem
        single_layers = [
            i for i in model.selected_items if isinstance(i, LayerItem)
        ]
        target = single_layers[0] if len(single_layers) == 1 else model.root_item
        if target is None:
            return
        model._request_save_as(target, replace_in_parent=True)

    def _toggle_layers_window(self) -> None:
        """Flip the Layers window's visibility (Ctrl+L, Step 59)."""
        if self._layer_window is None:
            return
        self._layer_window.visible = not self._layer_window.visible

    def _require_layer_stage_or_warn(self) -> bool:
        """Return ``True`` when a stage is loaded; show an error toast if not.

        Shared guard for the three save shortcuts so each entry point
        surfaces the same user-visible message when Ctrl+S / Ctrl+Shift
        +S / Ctrl+Alt+S fire before a file is open — matches
        :func:`ovui_widgets.app.menu_bar._require_stage` wording so keyboard and
        menu paths read identically in the status bar.
        """
        if self._layer_adapter is not None:
            return True
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_error("No stage open")
        except Exception:
            pass
        return False

    def _frame_selected(self) -> None:
        snap = self._selection_bus.get_snapshot()
        if snap is None or self._viewport_window is None:
            return
        paths = [item.path for item in snap.items]
        self._viewport_window.frame_paths(paths)

    def _save_layout(self) -> None:
        """Persist current window layout to settings and JSON file."""
        from ovui_widgets.app.layout import _collect_layout, save_layout_data
        data = _collect_layout()
        if not data:
            return
        self._settings.set(self.LAYOUT_SETTINGS_KEY, data)
        save_path = self._settings.get("layout.save_path", "~/.ovgear/layout.json")
        try:
            save_layout_data(save_path, data)
        except Exception:
            pass

    def _restore_layout(self) -> None:
        """Restore window layout from settings, JSON file, or apply default."""
        from ovui_widgets.app.layout import _restore_layout as _apply_windows
        from ovui_widgets.app.layout import (
            apply_default_layout,
            load_layout,
            show_panel_dock_tab_bars,
        )
        data = self._settings.get(self.LAYOUT_SETTINGS_KEY)
        if data:
            _apply_windows(data)
            apply_default_layout()
            show_panel_dock_tab_bars()
            return
        save_path = self._settings.get("layout.save_path", "~/.ovgear/layout.json")
        expanded = os.path.expanduser(save_path)
        if os.path.exists(expanded):
            try:
                load_layout(save_path)
                apply_default_layout()
            except Exception:
                apply_default_layout()
        else:
            apply_default_layout()
        show_panel_dock_tab_bars()

    def _preflight_stage_replacement(self) -> None:
        """Refuse replacement BEFORE any provider/path/history mutation.

        A replacement requested while the current adapter is inside an
        active authoring notification (a real sender-scoped ``Tf.Notice``
        callback on this very stack) cannot be performed safely: opening
        the new provider stage may already destroy the old native scene,
        and clearing the shared history would drop the open undo group out
        from under the in-flight command. When it refuses, NOTHING has
        been opened, changed, cleared, disposed, or deferred: the old
        adapter, application state, and the in-flight operation
        (including its undo group) remain fully functional, and the
        caller may retry after the operation completes.

        For adapters exposing the settlement contract, a SUCCESSFUL
        preflight is the PREPARE phase of a two-phase transition: owed
        delivery settles and the outgoing adapter is RESERVED, all
        strictly before any provider/document/history/session mutation.
        While reserved, no new backing authoring can create delivery
        debt, but the adapter's delivery intake stays fully operational
        — it remains the coherent current document until the replacement
        is definitely ready and dispose() commits the transition. Every
        failure path in between must abort the reservation via
        :meth:`_abort_stage_transition`.
        """
        adapter = getattr(self, "_stage_adapter", None)
        if adapter is None:
            return
        # The ownership contract returns REAL booleans; identity comparison
        # keeps arbitrary truthy stand-ins (test doubles without the
        # contract) from being misread as live ownership.
        if (
            getattr(adapter, "ownership_busy", False) is True
            or getattr(adapter, "disposal_pending", False) is True
        ):
            raise RuntimeError(
                "stage replacement refused: the current stage adapter is "
                "inside an active authoring notification and its ownership "
                "is unresolved; retry after the in-flight operation "
                "completes"
            )
        # BOUNDED cancellation ownership: retry the retained handles and
        # REFUSE the transition rather than accumulate more unrevoked
        # provider registrations — a refused replacement leaks nothing
        # and stays retryable after the provider recovers.
        self._drain_orphaned_stage_subs()
        if len(getattr(self, "_orphaned_adapters", ())) >= 32:
            raise RuntimeError(
                "stage replacement refused: too many outgoing adapters "
                "with unrevoked provider registrations are retained; "
                "retry after the provider allows revocation"
            )
        if len(getattr(self, "_orphaned_stage_subs", ())) >= 32:
            raise RuntimeError(
                "stage replacement refused: too many provider "
                "subscriptions with failed cancellation are retained; "
                "retry after the provider allows revocation"
            )
        # The outgoing adapter's delivery obligations SETTLE HERE —
        # before any provider open/create, document/history mutation, or
        # session teardown. Scope/attempt finalization that would first
        # create delivery debt inside dispose() happens now instead,
        # while the complete old application/provider state is untouched;
        # an unprovable delivery refuses non-destructively (adapter,
        # listeners, subscribers, and debt stay usable) and the same
        # entry point may be retried after the provider recovers, when
        # one retry delivers the complete owed union first.
        settle = getattr(adapter, "settle_delivery_obligations", None)
        if callable(settle):
            try:
                settled = settle()
            except UnresolvedDeliveryDebtError:
                raise
            except Exception as exc:
                raise UnresolvedDeliveryDebtError(
                    "stage replacement refused: the current stage adapter "
                    "could not prove its owed visibility delivery; retry "
                    "after the provider recovers"
                ) from exc
            # The settlement contract returns REAL booleans; identity
            # comparison keeps arbitrary stand-ins (test doubles whose
            # attributes auto-create) from being misread as refusals,
            # while genuinely retained debt always refuses.
            if settled is False or getattr(
                adapter, "delivery_debt_pending", False
            ) is True:
                raise UnresolvedDeliveryDebtError(
                    "stage replacement refused: the current stage adapter "
                    "still owes proven visibility delivery to the provider "
                    "stream; retry after the provider recovers"
                )
            # PREPARE phase of the two-phase transition: RESERVE the
            # outgoing adapter. The reservation re-verifies settlement
            # truth from the adapter's REAL state (an inconsistent
            # wrapper can never reserve) and, while held, refuses any
            # new backing authoring — so no delivery debt can be created
            # across the prepared transition. The delivery intake
            # (notice listener, probe, subscribers) stays fully
            # operational: the old document remains coherent until the
            # replacement is definitely ready and dispose() COMMITS.
            # Every failure in between aborts the reservation, restoring
            # normal authoring with nothing detached.
            reserve = getattr(
                adapter, "begin_replacement_transition", None)
            if callable(reserve) and reserve() is False:
                raise UnresolvedDeliveryDebtError(
                    "stage replacement refused: the current stage adapter "
                    "could not be reserved for replacement (live authoring "
                    "or unproven delivery); retry after the in-flight "
                    "operation completes or the provider recovers"
                )
        elif getattr(adapter, "delivery_debt_pending", False) is True:
            retry = getattr(adapter, "retry_delivery_debt", None)
            if callable(retry):
                try:
                    retry()
                except Exception:
                    pass  # the refusal below reports the retained debt
            if getattr(adapter, "delivery_debt_pending", False) is True:
                raise UnresolvedDeliveryDebtError(
                    "stage replacement refused: the current stage adapter "
                    "still owes proven visibility delivery to the provider "
                    "stream; retry after the provider recovers"
                )

    @staticmethod
    def _abort_stage_transition(adapter: Any) -> None:
        """Release a prepared replacement reservation after a failure.

        The old adapter was never detached during the prepared phase, so
        releasing the reservation restores completely normal operation —
        authoring, undo/redo, and provider event delivery included.
        """
        abort = getattr(adapter, "abort_replacement_transition", None)
        if callable(abort):
            try:
                abort()
            except BaseException as exc:  # noqa: BLE001 — the abort's
                # publication machinery re-owes any affected roots as
                # delivery debt before raising, so nothing is lost; the
                # failure is returned for attachment to the caller's
                # PRIMARY throwable instead of displacing it.
                return exc
        return None

    def _note_secondary_failures(self, primary: Any, failures: Any) -> None:
        """Attach cleanup failures to the PRIMARY throwable, inspectably.

        BaseException-proof end to end: lookup, formatting, and
        attachment can never displace the active primary — a hostile
        primary that refuses ``add_note`` (during attribute LOOKUP or
        invocation) gets its secondaries preserved as structured
        :class:`SecondaryFailureRecord` entries on the application's
        ``_secondary_failure_log`` instead, retaining the ACTUAL
        exception objects. See ``_SECONDARY_FAILURE_LOG_BOUND`` for the
        eviction policy; a successful shutdown retires the log.
        """
        attempt = getattr(self, "_lifecycle_attempt_serial", 0)
        for failure in failures or ():
            if failure is None:
                continue
            try:
                text = (
                    "secondary cleanup failure: "
                    f"{type(failure).__name__}: {failure}"
                )
            except BaseException:  # noqa: BLE001 — hostile repr: keep
                # the inspectable identity even without a message.
                text = (
                    "secondary cleanup failure: "
                    f"{type(failure).__name__} id=0x{id(failure):x}: "
                    "<unprintable>"
                )
            attached = False
            try:
                # Hostile primaries can raise during ATTRIBUTE LOOKUP,
                # not only during the call — both fall to the fallback.
                add_note = getattr(primary, "add_note", None)
                if callable(add_note):
                    # Ordinary reporting stays NONDUPLICATED: a retried
                    # attempt that re-collects the same failure does not
                    # append the same note again.
                    notes = getattr(primary, "__notes__", None) or ()
                    if not any(note == text for note in notes):
                        add_note(text)
                    attached = True
            except BaseException:  # noqa: BLE001 — safe fallback below
                attached = False
            if not attached:
                try:
                    log = getattr(self, "_secondary_failure_log", None)
                    if log is None:
                        log = []
                        self._secondary_failure_log = log
                    existing = next(
                        (
                            record for record in log
                            if getattr(record, "exception", None)
                            is failure
                        ),
                        None,
                    )
                    if existing is not None:
                        # Same retained throwable re-raised by a retried
                        # attempt: it is current-attempt evidence again,
                        # so refresh its eviction protection instead of
                        # duplicating the entry.
                        existing.attempt = attempt
                        continue
                    log.append(
                        SecondaryFailureRecord(failure, text, attempt))
                    # BOUNDED lifecycle diagnostics: evict the oldest
                    # PRIOR-attempt records first and never a record of
                    # the current attempt (see the policy note on
                    # _SECONDARY_FAILURE_LOG_BOUND).
                    overflow = len(log) - _SECONDARY_FAILURE_LOG_BOUND
                    if overflow > 0:
                        kept = []
                        for record in log:
                            if overflow > 0 and getattr(
                                record, "attempt", None
                            ) != attempt:
                                overflow -= 1
                                continue
                            kept.append(record)
                        log[:] = kept
                except BaseException:  # noqa: BLE001 — never mask
                    pass

    def _drain_orphaned_stage_subs(self) -> None:
        """Retry revocation of old subscriptions whose cancel failed.

        A live provider-stream callback must be DEFINITIVELY revoked or
        safely retained for retry — never silently dropped. Handles land
        here when their cancellation raised; every subsequent transition
        boundary and shutdown retries them.
        """
        adapters = getattr(self, "_orphaned_adapters", None)
        if adapters:
            still_pending = []
            for orphan in adapters:
                try:
                    orphan.dispose()
                except Exception:
                    pass
                if getattr(
                    orphan, "provider_registrations_pending", False
                ) is True:
                    still_pending.append(orphan)
            self._orphaned_adapters = still_pending
        orphans = getattr(self, "_orphaned_stage_subs", None)
        if not orphans:
            return
        remaining = []
        for handle in orphans:
            try:
                handle.cancel()
            except BaseException:  # noqa: BLE001 — retained for retry
                remaining.append(handle)
        # NEVER drop a handle: every live registration stays revocable.
        # Boundedness comes from _preflight_stage_replacement refusing
        # new transitions once the retained set exceeds its bound.
        self._orphaned_stage_subs = remaining

    def _enter_no_document_state(self) -> list:
        """Converge on ONE explicit, coherent no-document outcome.

        Used when the provider/session has ALREADY switched away from the
        old stage (open/create succeeded) but replacement construction
        then failed: the old document's owner chain no longer exists —
        for native providers its scene was destroyed inside the provider
        call — so retaining the old adapter would be a split document.
        The old adapter is disposed best-effort (its owed delivery was
        settled at the prepare boundary), all document wiring AND every
        real consumer — Stage Browser, Property Inspector/footer, layer
        window, viewport — converge to the same explicit no-document
        state with no resolvable stale row or subscription. Every step is
        BaseException-safe; failures are returned for the caller to
        attach to its primary throwable.
        """
        failures: list = []

        def _step(fn: Any) -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 — collected
                failures.append(exc)

        old = getattr(self, "_stage_adapter", None)
        if old is not None:
            dispose = getattr(old, "dispose", None)
            if callable(dispose):
                _step(dispose)
            # If disposal refused, release the reservation so the
            # (now uninstalled) adapter is at least internally coherent.
            failures.append(self._abort_stage_transition(old))
        sub = getattr(self, "_current_stage_sub", None)
        if sub is not None:
            def _cancel_old_sub() -> None:
                try:
                    sub.cancel()
                except BaseException:
                    # Retained for retry: the callback must never leak.
                    self._orphaned_stage_subs = list(
                        getattr(self, "_orphaned_stage_subs", ())) + [sub]
                    raise
            _step(_cancel_old_sub)
        self._current_stage_sub = None
        _step(self._selection_bus.clear)
        layer_adapter = getattr(self, "_layer_adapter", None)
        if layer_adapter is not None:
            _step(layer_adapter.detach_stage)
        self._layer_adapter = None
        if old is not None and getattr(
            old, "provider_registrations_pending", False
        ) is True:
            # Retain the outgoing adapter as an explicit retry owner for
            # its unrevoked private provider registration.
            orphans = list(getattr(self, "_orphaned_adapters", ()))
            if not any(a is old for a in orphans):
                orphans.append(old)
            self._orphaned_adapters = orphans
        self._stage_adapter = None
        self._current_file_path = None
        self._document_epoch = None
        # Commands of the destroyed document must not stay undoable.
        undo_manager = getattr(self, "_undo_manager", None)
        if undo_manager is not None:
            _step(undo_manager.clear)
        # REAL consumers converge too — no stale document ownership may
        # survive in any panel.
        stage_window = getattr(self, "_stage_window", None)
        detach_widget = getattr(stage_window, "detach_document", None)
        if callable(detach_widget):
            _step(detach_widget)
        property_window = getattr(self, "_property_window", None)
        if property_window is not None:
            _step(lambda: property_window.set_property_adapter_factory(None))
            _step(lambda: property_window.set_stage_adapter(
                None, getattr(self, "_undo_manager", None)))
        layer_window = getattr(self, "_layer_window", None)
        if layer_window is not None:
            _step(lambda: layer_window.set_adapter(None))
        viewport_window = getattr(self, "_viewport_window", None)
        if viewport_window is not None:
            _step(lambda: viewport_window.set_renderer(None))
            attach = getattr(viewport_window, "attach_stage", None)
            if callable(attach):
                # Detach the transform gizmo's stage/transform/undo
                # references — the destroyed document must not remain
                # reachable through viewport state.
                _step(lambda: attach(
                    transform_adapter=None,
                    stage_adapter=None,
                    undo_manager=None,
                ))
        _step(self._drain_orphaned_stage_subs)
        return [f for f in failures if f is not None]

    @_owns_lifecycle_attempt
    def open_file(self, path: str) -> None:
        """Open a scene file from disk, create provider adapters, and wire panels.

        Pre-constructs OVRTX before the selected provider opens the file.  The
        Kit OVStage/OVRTX cohort requires OVRTX to establish the process's
        Carbonite/plugin framework before OVStage (or ``omni.ui``) initializes.
        A failed early attempt is represented by ``None`` and is deliberately
        not retried after the Stage exists.
        See :meth:`_preconstruct_ovrtx_renderer` for details.
        """
        # NON-MUTATING preflight FIRST: for a native provider,
        # ``open_stage`` below may already destroy the prior scene, so a
        # blocked replacement must be refused before it (and before the
        # file path or shared history change).
        self._preflight_stage_replacement()
        # release/0.2 renderer-debt admission: an unproven prior renderer
        # shutdown blocks every load route BEFORE any side effect.
        if not self._admit_stage_load():
            return
        # EVERYTHING after the prepare boundary runs inside one abort
        # envelope: any throwable — including BaseException — releases
        # the reservation and any unconsumed replacement renderer, so a
        # failure can never leave the old document refusing authoring.
        prebuilt_renderer = _NO_PREBUILT_RENDERER
        # A reused renderer is owned by the viewport, not this replacement:
        # its lifecycle (including teardown on no-document) belongs to the
        # viewport, so no abort path here may ever shut it down.
        renderer_is_reused = False
        try:
            # Prefer transitioning the already-attached renderer IN PLACE:
            # constructing a second live ovrtx renderer here (after ui.init)
            # while the first is still frame-ticked can freeze the frame
            # loop. Only cold start (no reusable viewport renderer) builds
            # or consumes a fresh one.
            prebuilt_renderer = self._reusable_document_renderer()
            if prebuilt_renderer is not None:
                renderer_is_reused = True
            else:
                prebuilt_renderer = self._startup_prebuilt_renderer
                if prebuilt_renderer is _NO_PREBUILT_RENDERER:
                    prebuilt_renderer = self._preconstruct_ovrtx_renderer()
                elif prebuilt_renderer is not None:
                    # Consume a successfully preconstructed renderer exactly
                    # once. ``None`` is deliberately sticky: it records that
                    # bootstrap already failed before ui.init, and retrying on
                    # any later file open after the UI/OVStage runtime is live
                    # can hang OVRTX/NGX initialization.
                    self._startup_prebuilt_renderer = _NO_PREBUILT_RENDERER
            try:
                stage = self.get_adapter_session().open_stage(path)
            except Exception as e:
                from ovui_widgets.common.error_reporter import ErrorReporter
                ErrorReporter.show_error(f"Cannot open file: {e}")
                # The replacement FAILED before the provider switched:
                # release the prepared transition so the still-current
                # document stays fully authorable with its delivery
                # intake intact.
                self._abort_stage_transition(
                    getattr(self, "_stage_adapter", None))
                if prebuilt_renderer is not None and not renderer_is_reused:
                    try:
                        prebuilt_renderer.shutdown()
                    except Exception:
                        pass
                    prebuilt_renderer = _NO_PREBUILT_RENDERER
                return
            # The provider now owns ``stage`` and, for native OVStage, has
            # already shut down the prior scene. Commands from that
            # document must become unreachable before renderer/widget
            # wiring begins; a later wiring failure cannot make the
            # destroyed scene valid again.
            self._current_file_path = path
            self._undo_manager.clear()
            try:
                self._load_stage(
                    stage,
                    title=Path(path).name,
                    prebuilt_renderer=prebuilt_renderer,
                )
            except BaseException as primary:
                # The provider ALREADY switched to the replacement stage
                # (native providers destroy the prior scene inside
                # open_stage). The old document no longer exists as a
                # coherent owner chain, so retaining its adapter would be
                # a SPLIT document: converge on the explicit no-document
                # state instead, then surface the failure.
                self._note_secondary_failures(
                    primary, self._enter_no_document_state())
                raise
            prebuilt_renderer = _NO_PREBUILT_RENDERER  # consumed
            self._recent_files.add(path)
            self._settings.set(
                "ui.recent_files", self._recent_files.get_ordered())
        except BaseException as primary:
            failures = [self._abort_stage_transition(
                getattr(self, "_stage_adapter", None))]
            if (
                prebuilt_renderer is not _NO_PREBUILT_RENDERER
                and prebuilt_renderer is not None
                and not renderer_is_reused
            ):
                try:
                    prebuilt_renderer.shutdown()
                except BaseException as exc:  # noqa: BLE001 — collected
                    failures.append(exc)
            self._note_secondary_failures(primary, failures)
            raise

    @_owns_lifecycle_attempt
    def open_stage(self, stage: Any) -> None:
        """Headless/test variant: accepts an in-memory Usd.Stage directly."""
        self._load_stage(stage, title="(in-memory)")

    @_owns_lifecycle_attempt
    def new_stage(self) -> bool:
        """Create and load a new file-backed stage through the active provider."""

        from ovui_widgets.common.error_reporter import ErrorReporter

        try:
            return self._load_empty_startup_stage()
        except Exception as exc:  # noqa: BLE001
            ErrorReporter.log_error("Application", "new stage creation failed", exc)
            ErrorReporter.show_error(
                f"Cannot create stage: {type(exc).__name__}: {exc}",
            )
            return False

    @_owns_lifecycle_attempt
    def _load_empty_startup_stage(self) -> bool:
        """Load a default no-file stage when the active adapter can create one."""
        # Same non-mutating preflight as open_file: ``create_stage`` enters
        # the provider replacement path and may destroy the prior scene.
        self._preflight_stage_replacement()
        # release/0.2 renderer-debt admission before ANY side effect.
        if not self._admit_stage_load():
            return False
        # One abort envelope for everything after the prepare boundary
        # (capability probes included): any throwable releases the
        # reservation so the current document never stays frozen.
        try:
            return self._load_empty_startup_stage_prepared()
        except BaseException as primary:
            self._note_secondary_failures(primary, [
                self._abort_stage_transition(
                    getattr(self, "_stage_adapter", None))])
            raise

    def _load_empty_startup_stage_prepared(self) -> bool:
        prebuilt = None
        empty_stage = None
        # A reused renderer is viewport-owned; no abort path here shuts it
        # down (see open_file / _reusable_document_renderer).
        renderer_is_reused = False
        if self._can_create_empty_startup_stage():
            # After the first document is loaded, File > New transitions the
            # ALREADY-ATTACHED renderer in place rather than constructing a
            # second one. Constructing a second renderer after UI
            # initialization while the first is still frame-ticked can wedge
            # the first attached step call as RenderSettings repeatedly fails
            # to resolve the borrowed Stage ID — the observed accumulated-
            # state File > New freeze. Cold start (no reusable viewport
            # renderer yet) still consumes the standalone-launcher's
            # pre-established OVRTX, which shares the first Kit/Carbonite
            # cohort.
            prebuilt = self._reusable_document_renderer()
            if prebuilt is not None:
                renderer_is_reused = True
            else:
                prebuilt = getattr(
                    self,
                    "_startup_prebuilt_renderer",
                    _NO_PREBUILT_RENDERER,
                )
                if prebuilt is _NO_PREBUILT_RENDERER:
                    prebuilt = self._preconstruct_ovrtx_renderer()
                elif prebuilt is not None:
                    self._startup_prebuilt_renderer = _NO_PREBUILT_RENDERER
            try:
                empty_stage = self._create_empty_startup_stage()
            except BaseException:
                # Replacement creation FAILED before commit: the prepared
                # transition aborts; the current document stays coherent.
                self._abort_stage_transition(
                    getattr(self, "_stage_adapter", None))
                if prebuilt is not None and not renderer_is_reused:
                    try:
                        prebuilt.shutdown()
                    except Exception:
                        pass
                raise
        if empty_stage is not None:
            # ``create_stage`` enters the same provider replacement path as an
            # ordinary open and may already have destroyed the prior native
            # scene. Clear the old save destination and commands before any
            # fallible UI/renderer wiring.
            self._current_file_path = None
            self._undo_manager.clear()
            try:
                self._load_stage(
                    empty_stage, title="New Stage", prebuilt_renderer=prebuilt
                )
            except BaseException as primary:
                # The provider already switched to the created stage: a
                # construction failure must not leave a split document.
                self._note_secondary_failures(
                    primary, self._enter_no_document_state())
                raise
            return True
        elif prebuilt is not None and not renderer_is_reused:
            try:
                prebuilt.shutdown()
            except Exception:
                pass
        # NO replacement happened (creation unsupported or unavailable):
        # abort the prepared transition — the current document remains
        # installed and must stay fully operational.
        self._abort_stage_transition(getattr(self, "_stage_adapter", None))
        return False

    def _can_create_empty_startup_stage(self) -> bool:
        """Return whether the active adapter explicitly supports startup stage creation."""
        try:
            stage_capabilities = self.get_adapter_session().get_capabilities().stage
        except (AttributeError, RuntimeError, NotImplementedError):
            return True
        create_stage = getattr(stage_capabilities, "create_stage", None)
        if create_stage is None:
            return True
        return bool(create_stage.is_supported)

    def _create_empty_startup_stage(self) -> Any | None:
        """Create the default no-file stage with a file-backed root layer.

        ovrtx can share live USD edits with a stage whose root layer has a
        real identifier. An anonymous ``CreateInMemory`` root is exported to
        a one-time temp snapshot by the renderer, so prims authored later via
        the Create menu do not appear in the viewport.
        """
        if not self._can_create_empty_startup_stage():
            return None
        stage_dir = tempfile.mkdtemp(prefix="usdviewer_new_stage_")
        stage_path = os.path.join(stage_dir, "NewStage.usda")
        session = self.get_adapter_session()
        create_stage = getattr(session, "create_stage", None)
        if not callable(create_stage):
            shutil.rmtree(stage_dir, ignore_errors=True)
            return None
        try:
            stage = create_stage(stage_path)
        except NotImplementedError:
            shutil.rmtree(stage_dir, ignore_errors=True)
            return None
        except Exception:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise
        self._scratch_stage_dirs.append(stage_dir)
        return stage

    def save_stage_to(self, path: str) -> bool:
        """Export the current USD stage to ``path`` — the content browser implementation step 55.

        Delegates to the selected provider's ``export_stage(stage, path)``
        operation using the adapter's live stage. On success, updates
        :attr:`_current_file_path` so a subsequent File > Save writes
        directly to the same path (no dialog), appends ``path`` to the
        recent-files list, and returns ``True``. On failure — no stage
        loaded, provider export raised, or empty path — surfaces the reason via
        :class:`ErrorReporter.show_error` and returns ``False``. The
        bool return lets the menu handler branch (e.g. a future "close
        after save" flow) without re-reading the adapter state.
        """
        from ovui_widgets.common.error_reporter import ErrorReporter
        save_path = _local_file_url_to_path(
            path.strip() if isinstance(path, str) else str(path)
        )
        if not save_path:
            ErrorReporter.show_error("Save path is empty")
            return False
        if self._stage_adapter is None:
            ErrorReporter.show_error("No stage loaded — cannot save")
            return False
        session = self.get_adapter_session()
        try:
            capabilities = session.get_capabilities()
        except (AttributeError, RuntimeError):
            can_export_stage = False
        else:
            can_export_stage = bool(
                capabilities.stage.export_stage.is_supported
            )
        if not can_export_stage:
            ErrorReporter.show_warning(
                "Save is unavailable for the active data adapter"
            )
            return False
        stage = getattr(self._stage_adapter, "stage", None)
        if stage is None:
            ErrorReporter.show_error("Stage adapter has no stage — cannot save")
            return False
        current_path = getattr(self, "_current_file_path", None)
        is_current_document_save = bool(current_path) and (
            _local_file_url_to_path(str(current_path)) == save_path
        )
        if is_current_document_save and not self._persist_layer_state_before_save():
            return False
        try:
            session.export_stage(stage, save_path)
        except Exception as exc:  # noqa: BLE001
            ErrorReporter.log_error("Application", "stage export failed", exc)
            ErrorReporter.show_error(
                f"Cannot save file: {type(exc).__name__}: {exc}",
            )
            return False
        self._current_file_path = save_path
        self._recent_files.add(save_path)
        self._settings.set("ui.recent_files", self._recent_files.get_ordered())
        return True

    @property
    def unresolved_renderer(self) -> Any:
        """Renderer owned here because its shutdown is unproven."""
        return getattr(self, "_unresolved_renderer", None)

    @property
    def unresolved_renderer_error(self) -> Optional[BaseException]:
        """Exact latest throwable from the owned renderer's failed cleanup."""
        return getattr(self, "_unresolved_renderer_error", None)

    def _resolve_unresolved_renderer(self) -> bool:
        """Retry the owned renderer's shutdown; True when none remains."""
        pending = getattr(self, "_unresolved_renderer", None)
        if pending is None:
            self._unresolved_renderer_error = None
            return True
        from ovui_widgets.common.error_reporter import ErrorReporter

        try:
            pending.shutdown()
        except BaseException as exc:
            self._unresolved_renderer_error = exc
            ErrorReporter.log_error(
                "Application", "unresolved renderer shutdown retry", exc)
            return False
        self._unresolved_renderer = None
        self._unresolved_renderer_error = None
        return True

    def _admit_stage_load(self) -> bool:
        """One admission contract for every load route: unproven renderer
        shutdown blocks all work before any side effect."""
        if self._resolve_unresolved_renderer():
            return True
        from ovui_widgets.common.error_reporter import ErrorReporter

        ErrorReporter.show_error(
            "Stage load blocked: a previous renderer's shutdown is "
            "still unresolved."
        )
        return False

    @_owns_lifecycle_attempt
    def _load_stage(
        self,
        stage: Any,
        title: str,
        prebuilt_renderer: Any = _NO_PREBUILT_RENDERER,
    ) -> None:
        # PREPARE (also covers the in-memory ``open_stage`` path, which
        # reaches here directly): a blocked replacement refuses BEFORE any
        # subscription, adapter, history, or panel mutation; a successful
        # preflight reserves the outgoing adapter with its delivery
        # intake still fully operational.
        self._preflight_stage_replacement()
        # release/0.2: renderer-debt admission is equally pre-mutation —
        # refuse before the outgoing adapter below is reserved.
        if not self._admit_stage_load():
            return
        old_adapter = getattr(self, "_stage_adapter", None)
        # FALLIBLE replacement work FIRST: EVERY replacement resource the
        # committed document requires — adapter, application
        # subscription, layer adapter, transform adapter, renderer — is
        # prepared while the old document is still completely coherent.
        # Any failure here (BaseException included) discards the prepared
        # resources and aborts the transition: nothing has been disposed,
        # cancelled, or cleared, so authoring/undo/redo and provider
        # event delivery on the old document continue unharmed.
        new_adapter: Any = None
        new_sub: Any = None
        new_layer_adapter: Any = None
        transform_adapter: Any = None
        new_renderer: Any = _NO_PREBUILT_RENDERER  # sentinel: not built

        def _discard_replacement() -> list:
            # The replacement will not be installed; ATTEMPT every
            # prepared resource, BaseException-safe, and return the
            # collected failures for attachment to the caller's PRIMARY
            # throwable — cleanup must never displace it.
            failures: list = []

            def _step(fn: Any) -> None:
                try:
                    fn()
                except BaseException as exc:  # noqa: BLE001 — collected
                    failures.append(exc)

            if new_sub is not None:
                _step(new_sub.cancel)
            if new_layer_adapter is not None:
                _step(new_layer_adapter.detach_stage)
            if new_adapter is not None:
                new_dispose = getattr(new_adapter, "dispose", None)
                if callable(new_dispose):
                    _step(new_dispose)
            if (
                new_renderer is not _NO_PREBUILT_RENDERER
                and new_renderer is not None
                and not self._is_reused_document_renderer(new_renderer)
            ):
                # A reused viewport renderer is never shut down by the
                # discarded replacement: it is the live document renderer and
                # its own ``load_stage`` already self-restored the old scene
                # on a failed trial.
                shutdown_renderer = getattr(new_renderer, "shutdown", None)
                if callable(shutdown_renderer):
                    _step(shutdown_renderer)
            return failures

        try:
            stage_factory = self._require_factory("stage")
            new_adapter = stage_factory(
                stage,
                self._undo_manager,
                self.call_later,
            )
            # The application subscription is part of the committed
            # contract: a document that cannot notify consumers must
            # never install. The callback is IDENTITY-GUARDED to its own
            # adapter, so a retained old-stream subscription (failed
            # cancellation, pending retry) can never mutate a newer
            # document — an old callback is harmless the moment the
            # replacement becomes observable.
            # A fresh EPOCH sentinel per install: reinstalling the same
            # adapter OBJECT later mints a new epoch, so a stale callback
            # from a past document can never regain authority.
            document_epoch = object()

            def _guarded_on_stage_changed(
                event: Any, _epoch: Any = document_epoch
            ) -> None:
                if getattr(self, "_document_epoch", None) is _epoch:
                    self._on_stage_changed(event)

            new_sub = new_adapter.subscribe_changes(_guarded_on_stage_changed)
            layer_factory = self._require_factory("layers")
            new_layer_adapter = layer_factory(stage, self._undo_manager)
            new_layer_adapter.attach_stage(call_later=self.call_later)
            transform_factory = self._require_factory("transforms")
            transform_adapter = transform_factory(stage)
            if self._viewport_window is not None:
                # A build failure propagates to the abort path below with
                # the old document — INCLUDING its published renderer —
                # untouched: the failed attempt owns nothing in the
                # viewport, so the complete old document stays usable.
                # Routes where the transition has already irreversibly
                # invalidated that renderer (native providers destroy the
                # prior scene inside the session's open/create call)
                # converge through ``_enter_no_document_state`` in their
                # caller, which clears the viewport coherently.
                new_renderer = self._build_renderer_for_stage(
                    stage,
                    prebuilt=prebuilt_renderer,
                )
                if new_renderer is None and _renderer_required_for_session(
                    self.get_adapter_session()
                ):
                    raise RuntimeError(
                        "ovrtx is required, but no ovrtx renderer was "
                        "returned; refusing to use the fallback renderer "
                        "for proof."
                    )
        except BaseException as primary:
            # Cleanup attempts EVERY resource, the reservation is
            # unconditionally released, and the PRIMARY throwable
            # propagates with cleanup failures attached as notes.
            failures = _discard_replacement()
            failures.append(self._abort_stage_transition(old_adapter))
            self._note_secondary_failures(primary, failures)
            raise

        # COMMIT: finalize the outgoing adapter FIRST — an open visibility
        # scope's retained genuine roots must be truthfully delivered to
        # the OLD subscribers before any of them detach.
        teardown_primary: BaseException | None = None
        replacement_refused = False
        if old_adapter is not None:
            dispose = getattr(old_adapter, "dispose", None)
            if callable(dispose):
                try:
                    completed = dispose()
                    if completed is False:
                        # EXPLICIT contract: ownership (scope/attempt/
                        # manager group/listeners) is NOT yet released.
                        # Replacement must not proceed over live old
                        # ownership — escalate to the bounded forced
                        # finalization. Forced disposal itself DEFERS while
                        # an authoring notification is on the current call
                        # stack (replacement requested from inside a
                        # Tf.Notice callback): in that case ownership is
                        # explicitly UNRESOLVED and the replacement is
                        # refused rather than performed over a live owner —
                        # the caller may retry after the authoring call
                        # completes (the deferred disposal finishes itself).
                        from ovui_widgets.common.error_reporter import (
                            ErrorReporter,
                        )
                        ErrorReporter.log_error(
                            "Application",
                            "stage adapter disposal deferred at replacement;"
                            " forcing bounded finalization",
                            RuntimeError("disposal pending"),
                        )
                        if dispose(force=True) is False:
                            # Withdraw OUR OWN deferral request so the
                            # refused replacement leaves the old adapter
                            # fully alive (its deferred teardown must not
                            # fire when the in-flight operation exits).
                            cancel = getattr(
                                old_adapter, "cancel_deferred_disposal", None
                            )
                            if callable(cancel):
                                cancel()
                            replacement_refused = True
                except UnresolvedDeliveryDebtError:
                    # NON-DESTRUCTIVE refusal: disposal detached nothing —
                    # the old adapter, its notice listener, subscribers,
                    # and the owed roots are all intact. Replacement must
                    # not proceed over undelivered visibility debt, and
                    # generic disposal logging must never swallow this.
                    refusal_failures = _discard_replacement()
                    refusal_failures.append(
                        self._rollback_reused_renderer_to_old(
                            new_renderer, old_adapter))
                    refusal_failures.append(
                        self._abort_stage_transition(old_adapter))
                    exc = sys.exc_info()[1]
                    self._note_secondary_failures(exc, refusal_failures)
                    raise
                except Exception as exc:  # noqa: BLE001 — replacement proceeds
                    from ovui_widgets.common.error_reporter import ErrorReporter
                    ErrorReporter.log_error(
                        "Application", "stage adapter disposal failed", exc
                    )
                except BaseException as exc:  # KeyboardInterrupt/SystemExit
                    if getattr(
                        old_adapter, "delivery_debt_pending", False
                    ) is True:
                        # Disposal REFUSED before detaching anything: the
                        # old adapter is deliberately still live and owed.
                        # Keep it fully installed — subscription, selection,
                        # notice/proof listeners, and debt intact — and let
                        # the primary throwable propagate for a later
                        # retry. No cleanup below may detach it.
                        guard_failures = _discard_replacement()
                        guard_failures.append(
                            self._rollback_reused_renderer_to_old(
                                new_renderer, old_adapter))
                        guard_failures.append(
                            self._abort_stage_transition(old_adapter))
                        self._note_secondary_failures(exc, guard_failures)
                        raise
                    # Otherwise finish the structured detach below, THEN
                    # rethrow the primary throwable — a half-detached old
                    # adapter must not be left installed.
                    teardown_primary = exc
        if replacement_refused:
            # Ownership is explicitly UNRESOLVED: the old adapter is inside
            # an active authoring notification on this very call stack (its
            # deferred disposal completes when that call exits). Replacing
            # the stage now would detach live ownership — refuse instead of
            # proceeding; the old adapter stays installed and functional.
            _discard_replacement()
            renderer_rollback = self._rollback_reused_renderer_to_old(
                new_renderer, old_adapter)
            self._abort_stage_transition(old_adapter)
            refusal = RuntimeError(
                "stage replacement refused: the current stage adapter is "
                "inside an active authoring notification and its ownership "
                "is unresolved; retry after the in-flight operation "
                "completes"
            )
            if renderer_rollback is not None:
                add_note = getattr(refusal, "add_note", None)
                if callable(add_note):
                    add_note(
                        "reused renderer could not be rolled back to the old "
                        f"stage: {renderer_rollback!r}")
            raise refusal
        self._drain_orphaned_stage_subs()
        if self._current_stage_sub is not None:
            try:
                self._current_stage_sub.cancel()
            except BaseException as exc:  # noqa: BLE001 — retained
                # The old provider stream callback is still LIVE (adapter
                # disposal does not revoke stream-level subscriptions):
                # retain the only handle for retry at every later
                # boundary, log, and continue to the coherent NEW
                # document.
                self._orphaned_stage_subs = list(
                    getattr(self, "_orphaned_stage_subs", ())
                ) + [self._current_stage_sub]
                from ovui_widgets.common.error_reporter import ErrorReporter
                try:
                    ErrorReporter.log_error(
                        "Application",
                        "old stage subscription cancellation failed; "
                        "handle retained for retry",
                        exc,
                    )
                except Exception:
                    pass
            self._current_stage_sub = None
        try:
            self._selection_bus.clear()
        except Exception:
            pass
        # Detach the prior layer adapter; the replacement's layer adapter
        # was already prepared and attached against the NEW stage.
        if self._layer_adapter is not None:
            try:
                self._layer_adapter.detach_stage()
            except Exception:
                pass
            self._layer_adapter = None
        if teardown_primary is not None:
            _discard_replacement()
            self._stage_adapter = None  # never keep a disposed adapter
            raise teardown_primary

        if old_adapter is not None and getattr(
            old_adapter, "provider_registrations_pending", False
        ) is True:
            # The outgoing adapter still holds an unrevoked private
            # provider registration: keep it as an EXPLICIT reachable
            # retry owner — a completed transition may never abandon a
            # live registration.
            orphans = list(getattr(self, "_orphaned_adapters", ()))
            if not any(a is old_adapter for a in orphans):
                orphans.append(old_adapter)
            self._orphaned_adapters = orphans
        # INSTALL the fully-prepared replacement: the document and its
        # consumer notification channel become current atomically.
        self._stage_adapter = new_adapter
        self._current_stage_sub = new_sub
        self._layer_adapter = new_layer_adapter
        self._document_epoch = document_epoch
        renderer_handoff_started = False
        replacement_renderer_is_reused = self._is_reused_document_renderer(
            new_renderer
        )

        def _reclaim_unoffered_fresh_renderer() -> Optional[BaseException]:
            """Resolve the replacement-owned renderer if WIRE failed before
            the viewport ever received it.

            After handoff, the viewport owns either the published renderer or
            its retryable shutdown debt and ``_enter_no_document_state``
            clears it. Before handoff, only this transaction owns a freshly
            built renderer, so it must shut it down or retain it in the
            application's single unresolved slot.
            """
            if renderer_handoff_started:
                return None
            if (
                new_renderer is _NO_PREBUILT_RENDERER
                or new_renderer is None
                or replacement_renderer_is_reused
            ):
                return None
            shutdown_renderer = getattr(new_renderer, "shutdown", None)
            if not callable(shutdown_renderer):
                return None
            try:
                shutdown_renderer()
            except BaseException as exc:  # noqa: BLE001 — retained for retry
                self._unresolved_renderer = new_renderer
                self._unresolved_renderer_error = exc
                return exc
            return None

        # WIRE consumers against the committed document. A wiring
        # failure here cannot retain the old document (it is disposed):
        # it converges EVERYTHING — application fields and every real
        # consumer — to the explicit no-document state, then surfaces
        # the primary failure with cleanup notes attached.
        try:
            file_menu_invalidate = getattr(getattr(self, "_file_menu", None), "invalidate", None)
            if callable(file_menu_invalidate):
                file_menu_invalidate()
            if self._stage_window is not None:
                self._stage_window.set_adapter(self._stage_adapter)
            if self._property_window is not None:
                property_factory = self._require_factory("properties")
                factory = lambda paths: property_factory(
                    stage,
                    paths,
                    self._undo_manager,
                    self._stage_adapter,
                )
                self._property_window.set_property_adapter_factory(factory)
                self._property_window.set_stage_adapter(self._stage_adapter, self._undo_manager)
            # LAYERS-PLAN Step 9: the layer-stack adapter was prepared and
            # attached before commit; hand it to the window so Phase C can
            # rebuild its tree model once the window is populated.
            if self._layer_window is not None and self._layer_adapter is not None:
                try:
                    self._layer_window.set_adapter(self._layer_adapter)
                except NotImplementedError:
                    try:
                        self._layer_adapter.detach_stage()
                    except Exception:
                        pass
                    self._layer_adapter = None
            layer_menu_invalidate = getattr(getattr(self, "_layer_menu", None), "invalidate", None)
            if callable(layer_menu_invalidate):
                layer_menu_invalidate()
            # Wire the transform gizmo (Step C.2) — the viewport widget owns a
            # ``PrimTransformModel`` that needs these adapters (prepared
            # before commit) to drive the translate gizmo's drag math + undo
            # pipeline. Step C.5 will fold the selection-bus subscription
            # into the model itself.
            if self._viewport_window is not None:
                self._viewport_window.set_scene_name(title)
                self._viewport_window.attach_stage(
                    transform_adapter=transform_adapter,
                    stage_adapter=self._stage_adapter,
                    undo_manager=self._undo_manager,
                    snap_system=self._snap_system,
                )
            # Swap the viewport renderer. USD Viewer uses ovrtx and only ovrtx.
            # The renderer was PREPARED before the commit (build/transition
            # failures and the renderer-required refusal all aborted with the
            # old document intact). When a live renderer supports in-place
            # stage swap it is REUSED: ``new_renderer`` is then the viewport's
            # current renderer, already transitioned to the new stage, so
            # ``set_renderer`` recognizes the identity and re-publishes it
            # without constructing/tearing down a second renderer. Cold start
            # still installs a freshly loaded renderer.
            if self._viewport_window is not None:
                if new_renderer is not None:
                    renderer_handoff_started = True
                    installed = self._viewport_window.set_renderer(new_renderer)
                    if installed is False:
                        # release/0.2: the viewport REFUSED installation
                        # (unproven predecessor shutdown). Exactly one owner
                        # keeps the incoming renderer — the viewport iff it
                        # filled the debt slot, else this application slot —
                        # and the viewport stays unavailable until the next
                        # admitted load.
                        from ovui_widgets.common.error_reporter import (
                            ErrorReporter,
                        )

                        vp = self._viewport_window
                        if vp.unresolved_predecessor is not new_renderer:
                            self._unresolved_renderer = new_renderer
                            self._unresolved_renderer_error = None
                        ErrorReporter.show_error(
                            "Viewport refused renderer installation; the "
                            "viewport is unavailable until the next load.")
                        return
                    # Drop the cadence clock so the next tick paints the freshly
                    # attached renderer immediately rather than waiting out the
                    # remaining rateLimitFrequency period.
                    self._viewport_render_clock.reset()
                else:
                    # Keep the already-visible fallback renderer stage-aware so
                    # selection highlight and viewport picking still use real USD
                    # paths when ovrtx is unavailable.
                    active_renderer = getattr(self._viewport_window, "_renderer", None)
                    load_stage = getattr(active_renderer, "load_stage", None)
                    if callable(load_stage):
                        try:
                            load_stage(stage)
                            self._viewport_render_clock.reset()
                        except Exception:
                            self._viewport_window.set_renderer(None)
                    elif active_renderer is not None:
                        self._viewport_window.set_renderer(None)
                self._viewport_window.update_prim_count(self._get_prim_count())
                # Step 16: pose-based seam. Ask the stage adapter for any
                # authored ``boundCamera`` pose; apply it to the viewport
                # via the new value-object API. Bbox framing is the
                # fallback when no pose is authored or the apply fails
                # (preserves the prior "always frame something safe"
                # rule). The widget no longer receives a raw
                # ``Usd.Stage`` for camera metadata — only a parsed
                # ``BoundCameraPose``.
                pose = self._stage_adapter.read_bound_camera()
                if pose is None or not self._viewport_window.apply_camera_pose(pose):
                    self._viewport_window.frame_paths(["/"])
        except BaseException as primary:
            failures = self._enter_no_document_state()
            failures.append(_reclaim_unoffered_fresh_renderer())
            self._note_secondary_failures(primary, failures)
            raise

    def _converge_shutdown_teardown(self) -> list:
        """Best-effort completion of shutdown after a mid-teardown throwable.

        The provider/session is already gone, so the frozen half-shutdown
        state (reserved adapter, live listeners, ``_shutdown_done``
        False) must not survive: dispose the adapter (committing any held
        reservation), release the reservation if disposal refuses, cancel
        the application subscription, and drop the document wiring. Every
        step is BaseException-safe; the collected failures are returned
        so the caller can attach them to the preserved PRIMARY throwable.
        """
        failures: list = []

        def _step(fn: Any) -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 — collected
                failures.append(exc)

        adapter = getattr(self, "_stage_adapter", None)
        if adapter is not None:
            dispose = getattr(adapter, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except BaseException as exc:  # noqa: BLE001 — collected
                    failures.append(exc)
                    failures.append(self._abort_stage_transition(adapter))
        sub = getattr(self, "_current_stage_sub", None)
        if sub is not None:
            try:
                sub.cancel()
            except BaseException as exc:  # noqa: BLE001 — retained
                failures.append(exc)
                # The live registration stays OWNED for retry; its
                # callback is epoch-neutralized below.
                self._orphaned_stage_subs = list(
                    getattr(self, "_orphaned_stage_subs", ())) + [sub]
        self._current_stage_sub = None
        if getattr(
            self, "_stage_adapter", None
        ) is not None and getattr(
            self._stage_adapter, "provider_registrations_pending", False
        ) is True:
            pass  # reachable ownership until revocation is confirmed
        else:
            self._stage_adapter = None
        self._document_epoch = None
        layer_adapter = getattr(self, "_layer_adapter", None)
        if layer_adapter is not None:
            _step(layer_adapter.detach_stage)
        self._layer_adapter = None
        # Panels and chrome converge too: completion may never be
        # reported while an undestroyed window still owns document UI.
        for attr in (
            "_stage_window", "_property_window", "_viewport_window",
            "_content_window", "_layer_window", "_main_win",
            "_menu_underline_win", "_status_win", "_status_bar",
        ):
            owner = getattr(self, attr, None)
            if owner is None:
                continue
            destroy = getattr(owner, "destroy", None)
            destroyed = True
            if callable(destroy):
                try:
                    destroy()
                except BaseException as exc:  # noqa: BLE001 — collected
                    failures.append(exc)
                    destroyed = False
            if destroyed:
                # Ownership is released ONLY after a proven teardown; a
                # still-operative panel keeps its reference so shutdown
                # stays truthfully incomplete and retryable.
                try:
                    setattr(self, attr, None)
                except Exception:
                    pass
        _step(self._drain_orphaned_stage_subs)
        return [f for f in failures if f is not None]

    def _shutdown_ownership_clear(self) -> bool:
        """True only when no live document/panel ownership remains."""
        if getattr(self, "_orphaned_adapters", None):
            return False  # unrevoked provider registrations remain owned
        for name in (
            "_snap_sub", "_snap_grid_sub", "_theme_sub",
            "_rate_limit_sub", "_frame_sub",
        ):
            if getattr(self, name, None) is not None:
                return False  # an unprocessed service handle remains
        stale_service = []
        for handle in getattr(self, "_stale_service_subs", ()):
            try:
                handle.cancel()
            except BaseException:  # noqa: BLE001 — still owned
                stale_service.append(handle)
        self._stale_service_subs = stale_service
        if stale_service:
            return False  # an operative retained callback survives
        owners = (
            "_stage_adapter", "_current_stage_sub", "_layer_adapter",
            "_stage_window", "_property_window", "_viewport_window",
            "_content_window", "_layer_window", "_main_win",
        )
        return all(getattr(self, name, None) is None for name in owners)

    def _reusable_document_renderer(self) -> Any:
        """Return the viewport's live renderer when it can transition to a
        new stage IN PLACE, so a document replacement reuses it instead of
        constructing a second ovrtx renderer.

        Two live GPU renderers — the still-attached one being frame-ticked
        plus a freshly constructed one loading a new native scene — contend
        for native scene / RenderSettings resolution and can freeze the frame
        loop mid-replacement (observed after a full edit/reload session on
        File > New). The renderer's own ``load_stage`` transaction preserves
        an authoritative complete OLD-or-NEW identity; cleanup debt may still
        be reported after NEW commits, so :meth:`_build_renderer_for_stage`
        inspects that identity and converges fail-closed when necessary.
        Renderers that cannot swap an attached stage (default
        ``supports_in_place_stage_swap`` is ``False``) keep the
        construct-fresh path.
        """
        viewport = getattr(self, "_viewport_window", None)
        if viewport is None:
            return None
        renderer = getattr(viewport, "_renderer", None)
        if renderer is None:
            return None
        supports = getattr(renderer, "supports_in_place_stage_swap", None)
        if not callable(supports):
            return None
        try:
            reusable = supports() is True
        except Exception:  # noqa: BLE001 — a probe failure declines reuse
            return None
        return renderer if reusable else None

    def _is_reused_document_renderer(self, renderer: Any) -> bool:
        """True when ``renderer`` is the viewport-owned live renderer being
        transitioned in place.

        The replacement transaction does not directly shut such a renderer
        down: it is owned by the viewport (not the prospective replacement).
        A throwing load that proves it stayed OLD leaves that ownership
        untouched; a committed/unknown identity converges through the
        viewport's explicit no-document teardown. Identity against the
        viewport's published renderer is the whole ownership test — during
        the transition the viewport still holds it until either the no-op
        install or fail-closed convergence.
        """
        if renderer is None or renderer is _NO_PREBUILT_RENDERER:
            return False
        viewport = getattr(self, "_viewport_window", None)
        if viewport is None:
            return False
        return renderer is getattr(viewport, "_renderer", None)

    @staticmethod
    def _renderer_stage_status(renderer: Any, stage: Any) -> Optional[bool]:
        """Ask an in-place renderer for authoritative logical-stage identity.

        Only a literal bool is trusted. An absent, raising, or ambiguous probe
        is unknown and therefore takes the fail-closed no-document path after
        a throwing load rather than preserving a possibly split old adapter.
        """
        probe = getattr(renderer, "is_stage_current", None)
        if not callable(probe):
            return None
        try:
            result = probe(stage)
        except BaseException:  # noqa: BLE001 — inability to prove is unknown
            return None
        return result if type(result) is bool else None

    def _rollback_reused_renderer_to_old(
        self, renderer: Any, old_adapter: Any
    ) -> Optional[BaseException]:
        """Undo a committed reuse-transition when a refused disposal aborts.

        A reused renderer is transitioned to the new stage during PREPARE;
        if the outgoing adapter's disposal then REFUSES (delivery debt /
        active authoring), the old document is deliberately kept installed,
        so the renderer must return to the old document's stage — otherwise
        the old adapter would pair with a new-scene renderer. Its own
        ``load_stage`` transition is atomic, so this restore is itself
        old-or-new. Returns any throwable to chain into the abort's
        secondary failures (never displacing the primary refusal).
        """
        if not self._is_reused_document_renderer(renderer):
            return None
        old_stage = getattr(old_adapter, "stage", None)
        if old_stage is None:
            return None
        load_stage = getattr(renderer, "load_stage", None)
        if not callable(load_stage):
            return None
        try:
            load_stage(old_stage)
            return None
        except BaseException as exc:  # noqa: BLE001 — chained, not raised
            return exc

    def _preconstruct_ovrtx_renderer(self) -> Any:
        """Construct the selected provider renderer early, before scene open.

        Kit OVRTX and OVStage must share the first Carbonite/plugin framework
        established in the process. Constructing OVRTX after ``omni.ui`` or an
        OVStage has initialized can lose USDRT population interfaces or fail
        Hydra/MDL startup. Standalone entrypoints perform this even earlier,
        before importing :class:`Application`.
        Returns ``None`` on import/construction failure only when the selected
        provider permits renderer fallback. OVStage requires BORROW and raises.
        """
        from ovui_widgets.common.error_reporter import ErrorReporter

        session = self.get_adapter_session()
        renderer_required = _renderer_required_for_session(session)
        if not session.renderer_available():
            reason = session.renderer_unavailable_reason()
            if renderer_required:
                raise RuntimeError(
                    f"ovrtx is required, but the renderer is unavailable ({reason})."
                )
            ErrorReporter.show_warning(f"ovrtx renderer unavailable ({reason})")
            return None
        try:
            return session.create_renderer()
        except Exception as exc:
            ErrorReporter.log_error("Application", "ovrtx renderer failed", exc)
            if renderer_required:
                raise RuntimeError(
                    "ovrtx is required, but renderer construction failed "
                    f"({type(exc).__name__}: {exc})."
                ) from exc
            ErrorReporter.show_warning(
                f"ovrtx renderer failed ({type(exc).__name__}: {exc})"
            )
            return None

    def _build_renderer_for_stage(
        self,
        stage: Any,
        prebuilt: Any = _NO_PREBUILT_RENDERER,
    ) -> Any:
        """Attach ``stage`` to an ovrtx renderer and return it.

        If ``prebuilt`` is supplied (the pre-constructed adapter from
        :meth:`_preconstruct_ovrtx_renderer`), it is loaded with the stage
        and returned. The private ``_NO_PREBUILT_RENDERER`` sentinel means no
        attempt happened and permits construction; ``None`` means an early
        attempt already failed and must never be retried after Stage creation.
        Callers that go through :meth:`open_file` always supply one of those
        attempted outcomes.

        On failure (missing GPU, broken install, load-stage error), providers
        that permit fallback surface a warning and return ``None``. Providers
        such as OVStage that require their renderer fail closed instead.
        """
        from ovui_widgets.common.error_reporter import ErrorReporter

        renderer_required = _require_ovrtx_enabled()
        if not renderer_required:
            renderer_required = _renderer_required_for_session(
                self.get_adapter_session()
            )
        renderer = _NO_PREBUILT_RENDERER
        try:
            renderer = prebuilt
            if renderer is _NO_PREBUILT_RENDERER:
                # Prefer transitioning the already-attached renderer in place
                # (open_file/new_stage supply it directly; the in-memory
                # open_stage path reaches it here) before constructing a
                # second live renderer that would contend with the first.
                renderer = self._reusable_document_renderer()
                if renderer is None:
                    renderer = self._preconstruct_ovrtx_renderer()
            if renderer is None:
                if renderer_required:
                    raise RuntimeError(
                        "ovrtx is required, but no ovrtx renderer was returned; "
                        "see earlier renderer warning."
                    )
                return None
            renderer.load_stage(stage)
            return renderer
        except BaseException as exc:
            cleanup_error: BaseException | None = None
            reused = self._is_reused_document_renderer(renderer)
            if reused and self._renderer_stage_status(renderer, stage) is not False:
                # The throwing renderer either proves it committed NEW or
                # cannot prove it stayed OLD. The prospective adapter is not
                # installed yet, so retaining the old adapter would create a
                # split document. Converge the whole application/viewport to
                # explicit no-document; a failed renderer shutdown remains
                # viewport-owned and retryable.
                convergence_failures = self._enter_no_document_state()
                self._note_secondary_failures(exc, convergence_failures)
            # A reused viewport renderer is NOT shut down on a load failure:
            # when it proves it remained on the old stage, the viewport still
            # owns it. A committed/unknown result converged above. Only a
            # freshly constructed/consumed renderer is torn down here.
            if (
                renderer is not _NO_PREBUILT_RENDERER
                and renderer is not None
                and not reused
            ):
                shutdown_renderer = getattr(renderer, "shutdown", None)
                if callable(shutdown_renderer):
                    try:
                        shutdown_renderer()
                    except BaseException as error:
                        cleanup_error = error
                        self._unresolved_renderer = renderer
                        self._unresolved_renderer_error = error
                        self._note_secondary_failures(exc, [error])
            ErrorReporter.log_error("Application", "ovrtx renderer failed", exc)
            if not isinstance(exc, Exception):
                # Interrupt-class operation failures stay primary by identity;
                # every cleanup step above has already run and any unresolved
                # fresh renderer remains in the retry slot.
                raise
            if cleanup_error is not None:
                raise RuntimeError(
                    "ovrtx renderer failed to load the stage and could not be "
                    "safely shut down"
                ) from exc
            if renderer_required:
                raise RuntimeError(
                    "ovrtx is required, but the renderer could not load the stage "
                    f"({type(exc).__name__}: {exc})."
                ) from exc
            ErrorReporter.show_warning(
                f"ovrtx renderer failed ({type(exc).__name__}: {exc})"
            )
            return None

    def _on_stage_changed(self, event: Any) -> None:
        if event.event_type is ChangeEventType.RESYNC:
            pending = getattr(self, "_history_selection_reconcile", None)
            if pending is not None:
                pending["event_paths"].extend(
                    Application._selection_resync_paths(event)
                )
            else:
                pending = getattr(self, "_deferred_selection_reconcile", None)
                if pending is not None:
                    pending["event_paths"].extend(
                        Application._selection_resync_paths(event)
                    )
                else:
                    self._reconcile_selection_after_resync(event)
        for cb in self._stage_change_listeners:
            cb(event)
        if self._viewport_window is not None:
            # Let the renderer refresh its cache for any edit (including
            # INFO_CHANGE from Property Inspector writes) so the viewport shows
            # the new state on the next frame.
            self._viewport_window.notify_stage_changed(event)
            if event.event_type is ChangeEventType.RESYNC:
                self._viewport_window.update_prim_count(self._get_prim_count())
        if event.event_type is ChangeEventType.RESYNC and self._layer_window is not None:
            refresh = getattr(self._layer_window, "refresh_layer_contents", None)
            if callable(refresh):
                refresh()

    def _reconcile_selection_after_resync(self, event: Any) -> None:
        """Remap or clear stale selected paths after namespace/topology edits."""

        bus = self._selection_bus
        if bus is None:
            return
        snapshot = bus.get_snapshot()
        selected = [str(path) for path in snapshot.paths()]
        if not selected:
            return
        event_paths = Application._selection_resync_paths(event)
        reconciled, unresolved = Application._resolved_selection_paths(
            self,
            selected,
            event_paths,
        )
        if not unresolved:
            Application._publish_reconciled_selection(self, reconciled)
            return

        generation = int(
            getattr(self, "_deferred_selection_generation", 0)
        ) + 1
        self._deferred_selection_generation = generation
        self._deferred_selection_reconcile = {
            "generation": generation,
            "selected": tuple(selected),
            "event_paths": list(event_paths),
        }
        schedule = getattr(self, "call_later", None)
        if callable(schedule):
            schedule(
                0.0,
                lambda g=generation: self._finish_deferred_selection_reconcile(g),
            )
        else:
            # Isolated selection-resync unit tests deliberately use a minimal
            # Application-like object with no frame scheduler.
            Application._finish_deferred_selection_reconcile(self, generation)

    @staticmethod
    def _selection_resync_paths(event: Any) -> tuple[str, ...]:
        """Return de-duplicated prim paths carried by one change event."""

        return tuple(
            dict.fromkeys(
                str(path).partition(".")[0]
                for path in (
                    *(getattr(event, "changed_paths", ()) or ()),
                    *(getattr(event, "resynced_paths", ()) or ()),
                )
                if str(path).startswith("/")
            )
        )

    def _reconcile_selection_paths(
        self,
        selected_paths: Any,
        event_paths: Any,
    ) -> None:
        """Map stale selections across a combined topology change set."""

        reconciled, _unresolved = Application._resolved_selection_paths(
            self,
            selected_paths,
            event_paths,
        )
        Application._publish_reconciled_selection(self, reconciled)

    def _resolved_selection_paths(
        self,
        selected_paths: Any,
        event_paths: Any,
    ) -> tuple[list[str], bool]:
        """Return mapped paths and whether any stale path remains ambiguous."""

        adapter = self._stage_adapter
        if adapter is None:
            return [], bool(tuple(selected_paths))
        selected = list(dict.fromkeys(str(path) for path in selected_paths))
        if not selected:
            return [], False
        normalized_event_paths = tuple(
            dict.fromkeys(
                str(path).partition(".")[0]
                for path in event_paths
                if str(path).startswith("/")
            )
        )

        def exists(path: str) -> bool:
            try:
                return adapter.get_item_at_path(path) is not None
            except Exception:
                return False

        existing_events = [path for path in normalized_event_paths if exists(path)]
        missing_events = [path for path in normalized_event_paths if not exists(path)]
        reconciled: list[str] = []
        unresolved = False
        for old_path in selected:
            if exists(old_path):
                reconciled.append(old_path)
                continue
            options: set[str] = set()
            old_parent, _, old_name = old_path.rpartition("/")
            for new_path in existing_events:
                new_parent, _, new_name = new_path.rpartition("/")
                if old_name == new_name or old_parent == new_parent:
                    options.add(new_path)
                for old_root in missing_events:
                    if old_path != old_root and not old_path.startswith(old_root + "/"):
                        continue
                    root_parent, _, root_name = old_root.rpartition("/")
                    if root_name != new_name and root_parent != new_parent:
                        continue
                    mapped = new_path + old_path[len(old_root) :]
                    if exists(mapped):
                        options.add(mapped)
            if len(options) == 1:
                reconciled.append(next(iter(options)))
            else:
                unresolved = True

        return reconciled, unresolved

    def _publish_reconciled_selection(self, reconciled: list[str]) -> None:
        bus = self._selection_bus
        if bus is None:
            return
        current = [str(path) for path in bus.get_snapshot().paths()]
        if reconciled != current:
            bus.publish(reconciled, source="stage-resync")

    def _get_prim_count(self) -> int:
        """Count prims in the current stage via the adapter's public hierarchy API."""
        if self._stage_adapter is None:
            return 0
        try:
            def _count(item: Any) -> int:
                return 1 + sum(_count(c) for c in self._stage_adapter.get_children(item))
            return _count(self._stage_adapter.get_root())
        except Exception:
            return 0

    def _on_mock_selection(self, event: Any) -> None:
        """Update PropertyWindow with a MockPropertyAdapter when in mock-stage mode."""
        if self._stage_adapter is not None:
            return  # USD stage active — its own adapter handles properties
        if self._property_window is None:
            return
        paths = event.snapshot.paths()
        if not paths:
            self._property_window.set_adapter(None)
            return
        self._property_window.set_adapter(self._make_mock_property_adapter(paths))

    def _make_mock_property_adapter(self, paths: List[str]) -> Any:
        """Build a MockPropertyAdapter with a representative attribute set."""
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.common.testing.mock_property import MockPropertyAdapter

        attrs = {
            "xformOp:translate": AttributeMetadata(
                name="xformOp:translate", display_name="Translate",
                type_name="double3", value_type=float, group="Transform",
            ),
            "xformOp:rotateXYZ": AttributeMetadata(
                name="xformOp:rotateXYZ", display_name="Rotate",
                type_name="float3", value_type=float, group="Transform",
            ),
            "xformOp:scale": AttributeMetadata(
                name="xformOp:scale", display_name="Scale",
                type_name="float3", value_type=float, group="Transform",
            ),
            "visibility": AttributeMetadata(
                name="visibility", display_name="Visibility",
                type_name="token", value_type=str, group="Display",
            ),
            "purpose": AttributeMetadata(
                name="purpose", display_name="Purpose",
                type_name="token", value_type=str, group="Display",
            ),
            "doubleSided": AttributeMetadata(
                name="doubleSided", display_name="Double Sided",
                type_name="bool", value_type=bool, group="Geometry",
            ),
            "radius": AttributeMetadata(
                name="radius", display_name="Radius",
                type_name="float", value_type=float, group="Geometry",
                soft_range_min=0.0, soft_range_max=100.0,
            ),
        }
        adapter = MockPropertyAdapter(paths=paths, attributes=attrs)
        adapter.set_value("xformOp:translate", (1.0, 0.0, 0.5))
        adapter.set_value("xformOp:rotateXYZ", (0.0, 45.0, 0.0))
        adapter.set_value("xformOp:scale", (1.0, 1.0, 1.0))
        adapter.set_value("visibility", "inherited")
        adapter.set_value("purpose", "default")
        adapter.set_value("doubleSided", False)
        adapter.set_value("radius", 1.0)
        return adapter

    @_owns_lifecycle_attempt
    def shutdown(self) -> None:
        """Clean shutdown. Clear references, reset singleton.

        Idempotent and best-effort for owners that are proven inert:

        * Each discrete teardown block is wrapped in ``try/except`` so a
          single block's failure never leaves later resources alive.
          Phase A reproductions showed that the leftover ``ui.Window``
          references were exactly what produced the segfault during
          ``Py_FinalizeEx`` — partial teardown is worse than a noisy
          shutdown.
        * Panel UI teardown continues across independent windows. A panel
          whose ``destroy()`` refuses remains referenced and the exact first
          refusal propagates, because it may still own a retryable renderer.
        * ``_shutdown_done`` is set after every block has been
          *attempted*; subsequent calls are short-circuited.
          ``_shutdown_in_progress`` short-circuits a recursive call from
          within a destroy() callback.
        * Native scene shutdown is the one fail-closed exception: if a BORROW
          renderer cannot detach, shutdown propagates immediately and retains
          the provider session, scene, viewport, and renderer for a safe retry.
          Dropping those owners would allow OVStage finalization while OVRTX
          still holds its native pointer.

        Thread affinity: UI thread only. The body touches ovui Python
        bindings and Application singletons; cross-thread invocation is
        not supported.
        """
        if getattr(self, "_shutdown_done", False):
            return
        if getattr(self, "_shutdown_in_progress", False):
            return
        # PURELY OBSERVATIONAL ownership preflight FIRST — before provider
        # scene shutdown, session/singleton/scheduler clearing, component
        # unloading, history mutation, or any adapter teardown. A shutdown
        # requested from inside an active authoring notification (a real
        # sender-scoped Tf.Notice callback on this very stack) is REFUSED
        # while the complete application/provider state is still untouched
        # and fully usable; the caller retries after the in-flight
        # operation completes. For a native provider, ``shutdown_scene``
        # below may already destroy the current scene — a later refusal
        # could never restore that.
        adapter = getattr(self, "_stage_adapter", None)
        if adapter is not None and (
            getattr(adapter, "ownership_busy", False) is True
            or getattr(adapter, "disposal_pending", False) is True
        ):
            raise RuntimeError(
                "application shutdown refused: the stage adapter is "
                "inside an active authoring notification and its "
                "ownership is unresolved; retry after the in-flight "
                "operation completes"
            )
        # The adapter's delivery obligations SETTLE HERE — before the
        # provider scene, sessions, singletons, or any adapter detach.
        # Scope/attempt finalization that would first create delivery
        # debt inside dispose() happens now instead, while the complete
        # application/provider/session state is untouched; an unprovable
        # delivery refuses non-destructively and shutdown may simply be
        # retried after the provider recovers, when one retry delivers
        # the complete owed union first.
        if adapter is not None:
            settle = getattr(adapter, "settle_delivery_obligations", None)
            if callable(settle):
                try:
                    settled = settle()
                except UnresolvedDeliveryDebtError:
                    raise
                except Exception as exc:
                    raise UnresolvedDeliveryDebtError(
                        "application shutdown refused: the stage adapter "
                        "could not prove its owed visibility delivery; "
                        "retry after the provider recovers"
                    ) from exc
                # REAL booleans, identity-compared: test doubles with
                # auto-created attributes never read as refusals, while
                # genuinely retained debt always refuses.
                if settled is False or getattr(
                    adapter, "delivery_debt_pending", False
                ) is True:
                    raise UnresolvedDeliveryDebtError(
                        "application shutdown refused: the stage adapter "
                        "still owes proven visibility delivery to the "
                        "provider stream; retry after the provider "
                        "recovers"
                    )
                # PREPARE phase, exactly like replacement: RESERVE the
                # adapter (settlement truth re-verified from its REAL
                # state; new backing authoring refuses while reserved).
                # The delivery intake stays fully operational — a failed
                # shutdown_scene below aborts the reservation so the
                # still-current document remains coherent for the retry;
                # the later dispose() call COMMITS the transition.
                reserve = getattr(
                    adapter, "begin_replacement_transition", None)
                if callable(reserve) and reserve() is False:
                    raise UnresolvedDeliveryDebtError(
                        "application shutdown refused: the stage adapter "
                        "could not be reserved for shutdown (live "
                        "authoring or unproven delivery); retry after "
                        "the in-flight operation completes or the "
                        "provider recovers"
                    )
            elif getattr(adapter, "delivery_debt_pending", False) is True:
                retry = getattr(adapter, "retry_delivery_debt", None)
                if callable(retry):
                    try:
                        retry()
                    except Exception:
                        pass  # the refusal below reports the retained debt
                if getattr(
                    adapter, "delivery_debt_pending", False
                ) is True:
                    raise UnresolvedDeliveryDebtError(
                        "application shutdown refused: the stage adapter "
                        "still owes proven visibility delivery to the "
                        "provider stream; retry after the provider "
                        "recovers"
                    )
        if not self._resolve_unresolved_renderer():
            # Fail closed: the unproven renderer may still reference the
            # backing chain — retain every owner; stay retryable.
            return
        self._shutdown_in_progress = True
        try:
            # ── adapter scene / native provider resources ───────────────
            # This runs before any best-effort teardown.  In OVRTX BORROW mode
            # a detach failure is not recoverable by dropping references, so
            # preserve the entire owner chain and let the caller retry.
            session = getattr(self, "_adapter_session", None)
            shutdown_scene = getattr(session, "shutdown_scene", None)
            if callable(shutdown_scene):
                try:
                    shutdown_scene()
                except BaseException:
                    # Fail-closed: the owner chain is retained for a
                    # retry. Abort the prepared transition too, so the
                    # still-current document keeps authoring, undo/redo,
                    # and provider event delivery fully operational in
                    # the meantime.
                    self._abort_stage_transition(
                        getattr(self, "_stage_adapter", None))
                    raise
            self._adapter_session = None
            self._adapter_factories = None
            self._adapter_provider = None
            self._adapter_registry = None

            # Everything from here on runs inside ONE convergence
            # envelope: the provider/session is already gone, so a
            # BaseException below must not freeze a half-shutdown
            # application (reserved adapter, live listeners,
            # _shutdown_done False). Intentional refusals re-raise
            # with their established semantics; anything else
            # converges on one complete shutdown and then surfaces
            # the original throwable.
            try:
                # ── flags & lightweight Python state ─────────────────────
                try:
                    self._running = False
                    self._pending_callbacks = []
                    self._component_manager.unload_all()
                    self._widget_registry.clear()
                    self._window_registry.clear()
                    self._menu_registry.clear()
                    # Clear the process-wide common.scheduler backend so any
                    # widget call_later issued after shutdown raises
                    # RuntimeError (matches Rev 8 §5.5 expected post-shutdown
                    # behavior; existing widget try/except guards continue
                    # to fall back synchronously where applicable).
                    _common_scheduler.set_call_later(None)
                    # Step 10/13: clear the common-side Settings /
                    # RecentFileList singletons so widget reads after
                    # shutdown fall back to the lazy-default constructor
                    # path (same pattern as the scheduler clear above).
                    Settings.set_instance(None)
                    RecentFileList.set_instance(None)
                    if self._ovinspect_module is not None:
                        detach = getattr(self._ovinspect_module, "detach_application", None)
                        if callable(detach):
                            try:
                                detach(self)
                            except Exception:
                                pass
                        self._ovinspect_module = None
                except Exception:
                    pass
                # A prebuilt renderer can exist before a stage is loaded. Drop it
                # here so GPU-backed adapters do not survive into interpreter exit.
                try:
                    prebuilt_renderer = self._startup_prebuilt_renderer
                    self._startup_prebuilt_renderer = _NO_PREBUILT_RENDERER
                    if (
                        prebuilt_renderer is not _NO_PREBUILT_RENDERER
                        and prebuilt_renderer is not None
                    ):
                        shutdown_renderer = getattr(prebuilt_renderer, "shutdown", None)
                        if callable(shutdown_renderer):
                            shutdown_renderer()
                except Exception:
                    pass
                try:
                    self._teardown_headless_export()
                except Exception:
                    pass
                # ── stage / property / layer subscriptions ───────────────
                shutdown_primary: BaseException | None = None
                shutdown_refused = False
                try:
                    # Finalize before detach: retained visibility-scope roots
                    # flush to the still-subscribed consumers first.
                    adapter_dispose = getattr(
                        self._stage_adapter, "dispose", None
                    )
                    if callable(adapter_dispose):
                        if adapter_dispose() is False:
                            # Shutdown cannot leave old ownership live either.
                            # Forced disposal itself DEFERS while an authoring
                            # notification is on the current call stack.
                            if adapter_dispose(force=True) is False:
                                cancel = getattr(
                                    self._stage_adapter,
                                    "cancel_deferred_disposal",
                                    None,
                                )
                                if callable(cancel):
                                    cancel()
                                shutdown_refused = True
                except UnresolvedDeliveryDebtError:
                    # Debt that only became owed DURING this shutdown (the
                    # top preflight saw none): disposal detached nothing, so
                    # surface the refusal instead of silently discarding the
                    # owed roots — ``_shutdown_done`` stays False and the
                    # shutdown can be retried after the provider recovers.
                    self._abort_stage_transition(self._stage_adapter)
                    raise
                except Exception:
                    pass
                except BaseException as exc:  # KeyboardInterrupt/SystemExit
                    if getattr(
                        self._stage_adapter, "delivery_debt_pending", False
                    ) is True:
                        # Disposal REFUSED before detaching anything: the
                        # adapter is deliberately still live and owed. Keep it
                        # installed with its listeners and debt for a retried
                        # shutdown; the primary throwable propagates.
                        self._abort_stage_transition(self._stage_adapter)
                        raise
                    # Otherwise finish the structured detach, then rethrow
                    # the primary.
                    shutdown_primary = exc
                if shutdown_refused:
                    # Shutdown requested from INSIDE an active authoring
                    # notification: ownership is explicitly unresolved and must
                    # not be torn down over a live owner — refuse, exactly like
                    # replacement. The deferred disposal completes when the
                    # in-flight operation exits; shutdown can then be retried.
                    raise RuntimeError(
                        "application shutdown refused: the stage adapter is "
                        "inside an active authoring notification and its "
                        "ownership is unresolved; retry after the in-flight "
                        "operation completes"
                    )
                sub = getattr(self, "_current_stage_sub", None)
                if sub is not None:
                    try:
                        sub.cancel()
                    except BaseException:  # noqa: BLE001 — retained for
                        # retry; ownership must still CLEAR so shutdown
                        # cannot report completion over a live document.
                        self._orphaned_stage_subs = list(
                            getattr(self, "_orphaned_stage_subs", ())
                        ) + [sub]
                    self._current_stage_sub = None
                self._mock_prop_sub = None
                if getattr(
                    getattr(self, "_stage_adapter", None),
                    "provider_registrations_pending", False
                ) is True:
                    # A private provider registration is still unrevoked:
                    # ownership stays REACHABLE and shutdown remains
                    # incomplete/retryable.
                    pass
                else:
                    self._stage_adapter = None
                self._document_epoch = None
                try:
                    self._drain_orphaned_stage_subs()
                except Exception:
                    pass
                if shutdown_primary is not None:
                    try:
                        if self._layer_adapter is not None:
                            self._layer_adapter.detach_stage()
                            self._layer_adapter = None
                    except Exception:
                        pass
                    raise shutdown_primary
                # ── layer-stack adapter detach (Tf notice revoke) ────────
                try:
                    if self._layer_adapter is not None:
                        try:
                            self._layer_adapter.detach_stage()
                        except Exception:
                            pass
                        self._layer_adapter = None
                except Exception:
                    pass
                # ── settings subscriptions (each in its own try; some fire
                #     RAII destructors via Subscription.__del__)
                pending_service_primary = None
                service_cleanup_failures = []
                for sub_attr in (
                    "_snap_sub",
                    "_snap_grid_sub",
                    "_theme_sub",
                    "_rate_limit_sub",
                    "_frame_sub",
                ):
                    handle = getattr(self, sub_attr, None)
                    revoked = True
                    try:
                        cancel = getattr(handle, "cancel", None)
                        if callable(cancel):
                            # A failed removal stays owned by its store
                            # (GC-safe owner retention) AND by the
                            # application: shutdown may not complete
                            # while it remains operative.
                            cancel()
                    except BaseException as exc:  # noqa: BLE001 — retained
                        revoked = False
                        stale = list(
                            getattr(self, "_stale_service_subs", ()))
                        if not any(h is handle for h in stale):
                            stale.append(handle)
                        self._stale_service_subs = stale
                        if not isinstance(exc, Exception) and (
                            pending_service_primary is None
                        ):
                            # ONE preserved-primary disposition: keep
                            # processing every remaining handle
                            # best-effort, then re-raise the first
                            # non-Exception throwable.
                            pending_service_primary = exc
                        else:
                            service_cleanup_failures.append(exc)
                    if revoked:
                        try:
                            setattr(self, sub_attr, None)
                        except Exception:
                            pass
                if pending_service_primary is not None:
                    # Every other cleanup failure — Exception AND
                    # BaseException alike — stays inspectable on the
                    # preserved primary before it rethrows.
                    self._note_secondary_failures(
                        pending_service_primary, service_cleanup_failures)
                    raise pending_service_primary
                # ── MainWindow/chrome references (each in its own try) ───
                try:
                    main_win = self._main_win
                    if main_win is not None and hasattr(main_win, "destroy"):
                        main_win.destroy()
                except Exception:
                    pass
                for win_attr in (
                    "_main_win",
                    "_menu_underline_win",
                    "_status_win",
                    "_status_bar",
                ):
                    try:
                        setattr(self, win_attr, None)
                    except Exception:
                        pass
                # ── Legacy DockSpace reference (kept for older tests/scripts)
                #     MainWindow now owns the live root docker, but leave this
                #     cleanup guard so stale external assignments cannot leak.
                try:
                    try:
                        _ = self._dockspace
                    finally:
                        self._dockspace = None
                except Exception:
                    pass
                # ── layout save (read-only against still-live panel windows)
                try:
                    self._save_layout()
                except Exception:
                    pass
                # ── app settings save (JSON Settings lifecycle) ──────────
                try:
                    self._save_settings()
                except Exception:
                    pass
                # ── panel windows: release the application reference only
                #     after destroy proves completion. Viewport.destroy still
                #     releases its UI window in finally, while a native
                #     renderer refusal deliberately keeps this Python owner.
                panel_shutdown_primary = None
                for attr in ("_stage_window", "_property_window",
                             "_viewport_window", "_content_window",
                             "_layer_window"):
                    w = getattr(self, attr, None)
                    if w is None:
                        continue
                    destroyed = True
                    try:
                        w.destroy()
                    except BaseException as exc:  # noqa: BLE001
                        destroyed = False
                        if panel_shutdown_primary is None:
                            panel_shutdown_primary = exc
                    if destroyed:
                        # Release ownership only after a PROVEN teardown:
                        # a still-operative panel keeps its reference so
                        # shutdown stays truthfully incomplete/retryable.
                        try:
                            setattr(self, attr, None)
                        except Exception:
                            pass
                if panel_shutdown_primary is not None:
                    # At least one panel still owns a retryable resource.
                    # Surface the exact refusal; the outer convergence pass
                    # attempts the remaining owners without reporting success.
                    raise panel_shutdown_primary
                # ── temporary roots for startup "New Stage" files ────────
                try:
                    for stage_dir in list(getattr(self, "_scratch_stage_dirs", [])):
                        shutil.rmtree(stage_dir, ignore_errors=True)
                    self._scratch_stage_dirs = []
                except Exception:
                    pass
                # ── transient SettingsDialog (Step 4b lands its destroy()
                #     method; until then the attribute simply gets nulled).
                #     try/except/finally so the attribute clears regardless
                #     of whether destroy() exists or raises.
                try:
                    sd = getattr(self, "_settings_dialog", None)
                    if sd is not None:
                        destroy_fn = getattr(sd, "destroy", None)
                        if callable(destroy_fn):
                            destroy_fn()
                except Exception:
                    pass
                finally:
                    try:
                        self._settings_dialog = None
                    except Exception:
                        pass
                # ── module-scope provider holders (Steps 2/3/4 add the
                #     icon_caches module and its registrations). Until then
                #     this is a guarded no-op via ImportError catch — the
                #     ordering is preserved so when Step 4 lands
                #     no further edit to shutdown() is needed.
                try:
                    from ovui_widgets.common.icon_caches import clear_all  # noqa: WPS433
                    clear_all()
                except Exception:
                    pass
                # ── singletons reset (LAST, before flag set) ─────────────
                try:
                    SelectionBus._instance = None
                    Application._instance = None
                except Exception:
                    pass

            except UnresolvedDeliveryDebtError:
                # Deliberate refusal from the dispose block: the
                # adapter is intact and shutdown stays retryable.
                raise
            except BaseException as primary:
                if getattr(
                    getattr(self, "_stage_adapter", None),
                    "delivery_debt_pending", False
                ) is True:
                    # Indebted-guard outcome: the still-live owed
                    # adapter stays installed and retryable.
                    raise
                # The PRIMARY throwable identity is preserved; every
                # convergence failure is attached as an inspectable note.
                self._note_secondary_failures(
                    primary, self._converge_shutdown_teardown())
                # Completion is TRUTHFUL: only when no live document or
                # panel ownership remains; otherwise shutdown stays
                # explicitly incomplete and retryable.
                self._shutdown_done = self._shutdown_ownership_clear()
                raise
            # Completion is TRUTHFUL: shutdown reports done only when
            # no live document or panel ownership remains; otherwise it
            # stays explicitly incomplete and retryable.
            self._shutdown_done = self._shutdown_ownership_clear()
            if self._shutdown_done:
                # Defined lifecycle boundary: a successful shutdown
                # retires the prior secondary-failure diagnostics.
                self._secondary_failure_log = []
        finally:
            self._shutdown_in_progress = False

    @property
    def snap_system(self) -> SnapSystem:
        return self._snap_system

    @property
    def menus(self) -> AppMenuRegistry:
        return self._menu_registry

    @property
    def components(self) -> ComponentManager:
        return self._component_manager

    @property
    def widgets(self) -> AppWidgetRegistry:
        return self._widget_registry

    @property
    def window_hooks(self) -> AppWindowRegistry:
        return self._window_registry

    def _on_snap_enabled_changed(self, key: str, value: Any) -> None:
        self._snap_system.enable(bool(value))

    def _on_snap_grid_size_changed(self, key: str, value: Any) -> None:
        """Apply a persisted Settings grid size to the live snap provider."""

        try:
            self._grid_snap_provider.set_grid_size(value)
        except (TypeError, ValueError):
            # External settings sources are not constrained by the dialog's
            # positive FloatDrag range. Keep the last valid provider value.
            return

    def _on_rate_limit_fps_changed(self, key: str, value: Any) -> None:
        """Apply a live rateLimitFrequency change to the cadence state.

        The frame loop only reads the clock's cached ``target_fps`` /
        ``target_period``; this retained subscription is the sole updater,
        so there is no per-frame settings lookup. Invalid values never
        arrive here — the Settings store rejects them at the write boundary
        (see ``_KEY_VALIDATORS`` in ovui_widgets.common.settings) — but a
        defensive check keeps a hand-constructed store from breaking the
        clock.
        """
        fps = valid_rate_limit_fps(value, default=None)
        if fps is None:
            return
        self._viewport_render_clock.target_fps = fps
        self._apply_rate_limit_to_ui_pump(fps)

    def _on_theme_changed(self, key: str, value: str) -> None:
        """React to ui.theme setting change."""
        from ovui_widgets.app.style import set_theme
        set_theme(value)
        # Re-apply frame backgrounds on all panel windows — frame.set_style()
        # stores a resolved integer, so it must be re-called after each shade switch.
        for win in (
            self._stage_window,
            self._property_window,
            self._viewport_window,
            self._content_window,
            self._layer_window,
        ):
            if win is not None:
                win.on_theme_changed()
        # ImGui-owned docking separators are outside omni.ui's regular
        # style-selector path. set_theme() applies the sanctioned binding
        # immediately, but a user-triggered shade change can resolve during the
        # active frame; refresh once more on the next frame so existing dock
        # nodes pick up the new light/dark splitter color.
        self.call_later(0.0, self._refresh_imgui_docking_style)

    def _refresh_imgui_docking_style(self) -> None:
        """Re-apply resolved docking style tokens through the public binding."""
        from ovui_widgets.app.style.imgui_runtime import apply_imgui_splitter_style

        apply_imgui_splitter_style()
