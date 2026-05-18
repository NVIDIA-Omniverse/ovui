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

import inspect
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

# Eager pxr import: ensure the PYTHONPATH-resolved USD install registers its
# ``SDF_ASSET`` debug symbol before ovrtx loads its bundled pxr (which would
# otherwise trigger a ``multiple debug symbol definitions for SDF_ASSET``
# crash on aarch64 builds where ``LD_LIBRARY_PATH=$USD_BUILD/lib`` is set).
# Up to Step 13 this happened transitively via ``ovwidgets.stage.__init__``
# eagerly importing ``usd_transform_adapter``; Step 14 relocated that file
# to ``ovui_data_adapters.openusd`` and dropped the eager re-export, so we
# now load pxr explicitly here at the application's startup boundary.
try:
    from pxr import Gf, Sdf, Tf, Usd, UsdGeom  # noqa: F401
except ImportError:
    pass


def _resolve_window_size() -> tuple[int, int]:
    """Return ``(width, height)`` for ``ui.init``, honouring env vars.

    ``OVGEAR_HEADLESS_WIDTH`` / ``OVGEAR_HEADLESS_HEIGHT`` let
    ``python -m ovwidgets.app.headless`` boot the offscreen Vulkan platform at a
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

from ovui_data_adapters.common import ChangeEventType, Command

from ovwidgets.app.frame_clock import FrameClock
from ovwidgets.app.settings_dialog import SettingsDialog
from ovwidgets.common import scheduler as _common_scheduler
from ovwidgets.common.recent_files import RecentFileList
from ovwidgets.common.scheduler import CallbackHandle
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.settings import Settings, Subscription
from ovwidgets.common.snap import GridSnapProvider, SnapSystem, SurfaceSnapProvider
from ovwidgets.common.undo import UndoManager

_REQUIRE_OVRTX_ENV = "OVWIDGETS_REQUIRE_OVRTX"
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
_KEY_F2 = 291
# GLFW arrow-key codes — used by the Alt+Left / Alt+Right content-
# browser back/forward shortcut (Content-Browser Step 20). Kept with
# the other GLFW key constants so a future move to an ``ImGuiKey`` enum
# only touches this block.
_KEY_ARROW_RIGHT = 262
_KEY_ARROW_LEFT = 263


# ImGui named-key codes for A-Z. Real GLFW window input reports printable
# letters as ASCII, while the ovui inspector and remote input bridge inject
# ImGuiKey_A..Z. Normalize the printable range so shortcuts such as F-frame
# follow the same path regardless of input source.
_IMGUI_KEY_A = 546
_IMGUI_KEY_Z = _IMGUI_KEY_A + 25


def _normalize_printable_key(key: int) -> int:
    if _IMGUI_KEY_A <= key <= _IMGUI_KEY_Z:
        return ord("A") + (key - _IMGUI_KEY_A)
    return key


def _require_ovrtx_enabled() -> bool:
    return os.environ.get(_REQUIRE_OVRTX_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _should_close() -> bool:
    """Issue #35 Step 7 / Codex Round 1 F9 + F10.

    Return True when ovui's standalone backend reports that its
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
    _instance: Optional["Application"] = None

    def __init__(self, headless: bool = False) -> None:
        assert Application._instance is None, "Application is a singleton"
        Application._instance = self

        self._settings = Settings()
        self._undo_manager = UndoManager()
        self._selection_bus = SelectionBus()
        SelectionBus._instance = self._selection_bus  # register as singleton
        self._pending_callbacks: list[CallbackHandle] = []
        # Register this Application's call_later as the process-wide
        # scheduler backend so widget code can call
        # ``ovwidgets.common.scheduler.call_later`` instead of
        # ``Application.instance().call_later`` (per Rev 8 §5.5 +
        # implementation Step 5). Cleared on shutdown.
        _common_scheduler.set_call_later(self.call_later)
        self._frame_sub: Optional[Any] = None
        self._run_exception: Optional[BaseException] = None
        self._running = False
        self._main_win: Optional[Any] = None
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
        self._snap_system.add_provider(GridSnapProvider(1.0))
        self._snap_system.add_provider(SurfaceSnapProvider())
        self._snap_sub: Optional[Subscription] = self._settings.subscribe(
            "snap.enabled", self._on_snap_enabled_changed
        )
        self._theme_sub: Optional[Subscription] = self._settings.subscribe(
            "ui.theme", self._on_theme_changed
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
        # :meth:`ViewportWidget.update`. See ``ovwidgets.app/frame_clock.py``.
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        self._viewport_render_clock = FrameClock(
            target_fps=float(ViewportWidget.MAX_FPS_FOREGROUND),
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

        # Tier 3 livestream input bridge (issue #34, Step 3.3). ``None``
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

        # Tier 3 custom-message dispatcher (issue #34, Step 3.7).
        # Set by :meth:`_setup_headless_export`; ``None`` in windowed
        # mode and until the headless tap is brought up. The
        # dispatcher owns a queue: the ovstream worker thread parses
        # incoming envelopes and enqueues work items;
        # :meth:`_drain_message_queue` runs them on the main loop
        # ahead of ``await ui.next_frame()`` so application/UI state
        # is only mutated on the main thread (Codex Step 3.7 NOT-GOOD
        # finding 1 fix).
        self._message_dispatcher: Optional[Any] = None

        # Optional external inspector module. When ``ovinspect`` is on
        # ``PYTHONPATH``, :meth:`_setup_optional_ovinspect` imports it
        # during app startup and :meth:`_drain_ovinspect` lets its HTTP
        # worker thread marshal ovui actions onto the frame loop.
        self._ovinspect_module: Optional[Any] = None

        # Filesystem path of the currently-open USD stage. Set by
        # :meth:`open_file` after a successful :meth:`_load_stage` and
        # by :meth:`save_stage_to` after a successful export. Read by
        # :func:`ovwidgets.app.menu_bar._on_save_clicked` to decide whether
        # File > Save writes directly (path present) or re-routes
        # through Save As (path ``None`` — e.g. a mock/in-memory stage
        # or the app's default stage). See the content browser implementation step 55.
        self._current_file_path: Optional[str] = None
        self._scratch_stage_dirs: list[str] = []

    @staticmethod
    def instance() -> "Application":
        """Return the singleton Application. Raises if not created yet."""
        if Application._instance is None:
            raise RuntimeError("Application not created yet")
        return Application._instance

    def request_exit(self) -> None:
        """Request a clean application exit.

        Flips ``self._running = False`` so :meth:`run_async`'s loop
        exits at the next frame boundary; that triggers the
        ``finally:`` clause which calls :meth:`shutdown` while ovui's
        standalone backend is still alive.

        This is the public API every exit trigger should use:
        File → Exit, OS X-button polling, ``Ctrl+Q`` hotkey, etc.
        Issue #35 Step 6 — Codex Round 1 F8.

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

    @property
    def settings(self) -> Settings:
        return self._settings

    def _get_stage_adapter(self) -> Optional[Any]:
        """Return the live :class:`StageAdapter` (or ``None``).

        Step 11.3 added this bound-method accessor so
        :class:`ovwidgets.viewport.viewport_widget.ViewportWidget`
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
        from ovwidgets.common.error_reporter import ErrorReporter
        now = time.monotonic()
        remaining = []
        for handle in self._pending_callbacks:
            if handle._cancelled:
                continue
            if now >= handle._due_time:
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
        self._pending_callbacks = remaining
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
        render_dt = self._viewport_render_clock.should_render(now)
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
            self._viewport_render_clock.commit(now)

    # ── Step 2.6: headless full-UI frame export hook ──

    @staticmethod
    def _headless_export_env_active() -> bool:
        """True iff ``OMNIUI_HEADLESS=1`` and ``OVGEAR_LIVESTREAM`` is set
        to a truthy value. Both must be on for the export pipeline to
        start; flipping either at runtime won't toggle the hook (the
        env is sampled once at setup)."""
        if os.environ.get("OMNIUI_HEADLESS", "").strip() != "1":
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
            from ovui_data_adapters.openusd._livestream_tap import LivestreamTap
        except Exception as exc:
            print(
                f"[ovgear/headless] export setup failed (import): {exc}",
                file=sys.stderr,
            )
            return

        tap = LivestreamTap.maybe_create()
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
            from ovwidgets.app._input_bridge import RemoteInputBridge
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
            from ovwidgets.app._message_dispatcher import MessageDispatcher

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
          (the pipeline's contract is "True on success"; a False
          return means it never queued the V→C wait and any
          subsequent CUDA work would race ovui's render).
        - ``copy_to_linear`` returning ``False`` → permanent disable
          *after* a best-effort ``signal_consumed`` so the V/C
          semaphore pair stays balanced and ovui isn't left
          blocked on its next render.
        - Zero-extent (ovui hasn't rendered yet) → frame skip with
          ``signal_consumed`` to keep the V/C pair balanced. This
          is the only genuinely transient case in the hook.
        - ``tee_linear_to_ovstream`` is exception-safe by contract
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

        Called by :class:`ovui_data_adapters.openusd._livestream_tap.LivestreamTap`
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
        from ovwidgets.app._input_drain import drain_bridge_into_ui
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

        Stage Browser filter bar (DPI=1.0): x in [0, SIDE_PANEL_WIDTH),
        y in [MENU_BAR_HEIGHT, MENU_BAR_HEIGHT + FILTER_BAR_HEIGHT).
        A click in this region arms ``_filter_capture`` so that subsequent
        printable-key events update the filter model directly via
        :meth:`_on_remote_char`.  A click outside the filter bar disarms
        it so accidental keypresses elsewhere do not corrupt the filter.
        """
        from ovwidgets.app.layout import MENU_BAR_HEIGHT, SIDE_PANEL_WIDTH
        _SIDE_PANEL_WIDTH = SIDE_PANEL_WIDTH
        _FILTER_BAR_HEIGHT = 30
        in_filter = (0 <= x < _SIDE_PANEL_WIDTH
                     and MENU_BAR_HEIGHT <= y < MENU_BAR_HEIGHT + _FILTER_BAR_HEIGHT)
        if in_filter and self._stage_window is not None:
            self._filter_capture = True
        else:
            self._filter_capture = False

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

        The inspector is deliberately outside the ovwidgets dependency graph.
        A normal application launch has no ``ovinspect`` module and this is a
        silent no-op; a QA launch can opt in with
        ``PYTHONPATH=/path/to/skill python -m ovwidgets.app...``.
        """
        try:
            import ovinspect
        except ImportError:
            return

        self._ovinspect_module = ovinspect
        attach = getattr(ovinspect, "attach_application", None)
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
        :meth:`ovui_data_adapters.openusd._livestream_tap.LivestreamTap._ensure_server`).

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
            and os.environ.get("OMNIUI_HEADLESS", "").strip() == "1"
            and self._startup_prebuilt_renderer is _NO_PREBUILT_RENDERER
        ):
            self._startup_prebuilt_renderer = self._preconstruct_ovrtx_renderer()

        import omni.ui as ui

        from ovwidgets.app.layout import write_split_ini
        from ovwidgets.app.style import apply_global_styles, set_theme

        # ``max_fps`` caps the OVUI run-loop's tick rate. On hosts where
        # ``glfwSwapBuffers`` doesn't enforce vsync (Mesa software OpenGL
        # under Xvnc / kasmvnc) the loop would otherwise free-run at 200+
        # FPS, which is wasted work and used to starve the viewport's render
        # gate before the FrameClock split.
        #
        # We probe ``ui.init``'s signature with ``inspect.signature`` instead
        # of catching ``TypeError`` from a hopeful call. A blanket TypeError
        # catch would also swallow internal init failures from a new OVUI
        # build that does accept the keyword — silently retrying init with a
        # legacy signature would mask the real bug.
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        target_fps = float(ViewportWidget.MAX_FPS_FOREGROUND)
        win_width, win_height = _resolve_window_size()
        if _ui_init_supports_kwarg(ui.init, "max_fps"):
            ui.init("USD Viewer", width=win_width, height=win_height, max_fps=target_fps)
        else:
            from ovwidgets.common.error_reporter import ErrorReporter
            ErrorReporter.log_warning(
                "Application",
                "ui.init has no max_fps kwarg — running against legacy OVUI; "
                "the FrameClock still gates rendering, but the run-loop tick "
                "rate is uncapped so software-OpenGL hosts will waste cycles. "
                "Upgrade OVUI to NVIDIA-Omniverse/ovui PR #20 to recover the cap.",
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

    async def run_async(self) -> None:
        """Build the main window and run the frame loop.

        Issue #35 Step 5 / Round 2 F2 / Round 6 F2: the ``try`` block
        opens at the very start of the body — BEFORE
        ``self._main_win = ui.MainWindow()`` and the panel/menu/status
        bar constructors. That way a failure in any
        ovui resource construction still drives the ``finally`` clause
        that calls :meth:`shutdown`, which is what guarantees those
        resources don't leak into ``Py_FinalizeEx``.
        """
        import omni.ui as ui

        from ovwidgets.app.layout import MENU_BAR_HEIGHT
        from ovwidgets.app.menu_bar import build_menu_bar
        from ovwidgets.app.status_bar import StatusBar

        # Cache the C-binding submodule so :meth:`_drain_remote_input`
        # doesn't re-resolve it every frame. Installed before any panel
        # construction so the bridge could in principle drain on the
        # very first tick, although in practice no client connects that
        # early.
        from ovwidgets.common.error_reporter import ErrorReporter

        try:
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

            from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
            from ovwidgets.common.testing.mock_stage import MockStageAdapter
            from ovwidgets.content import ContentBrowserWindow
            from ovwidgets.layers import LayerWindow
            from ovwidgets.property import PropertyWidget  # DEPRECATED alias → PropertyWindow
            from ovwidgets.stage.window import StageWindow
            from ovwidgets.viewport.viewport_widget import ViewportWidget

            self._stage_window = StageWindow(adapter=MockStageAdapter())
            self._property_window = PropertyWidget()
            self._viewport_window = ViewportWidget(
                services=self,
                renderer=MockRendererAdapter(),
                on_drop_fn=lambda event: self._on_drop(event, target="viewport"),
                stage_adapter_provider=self._get_stage_adapter,
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
            self._layer_window = LayerWindow(services=self)

            # Wire mock property adapter for selections when no USD stage is loaded.
            self._mock_prop_sub = self._selection_bus.subscribe(self._on_mock_selection)

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
            from ovwidgets.app.layout import apply_default_layout, show_panel_dock_tab_bars
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
                # No file argument — create an empty stage that still has
                # a real root-layer identifier, matching the open-file path.
                prebuilt = self._preconstruct_ovrtx_renderer()
                empty_stage = self._create_empty_startup_stage()
                self._load_stage(
                    empty_stage, title="New Stage", prebuilt_renderer=prebuilt
                )

            # Step 2.6: bring up the headless full-UI export pipeline if
            # ``OMNIUI_HEADLESS=1`` and ``OVGEAR_LIVESTREAM`` are both set.
            # No-op in windowed mode.
            self._setup_headless_export()

            last_tick = time.monotonic()
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
                # Discard the FrameInfo return value (OVUI PR #20). We re-derive
                # tick_dt from time.monotonic() so this loop works against
                # both new and legacy OVUI builds without branching.
                await ui.next_frame()
                # Step 2.6 hook — runs after the frame is rendered and
                # before _on_frame_update so the streamed frame is the
                # most recent ovui tick. No-op when headless export
                # isn't active (windowed mode, no OVGEAR_LIVESTREAM,
                # or a permanent failure has disabled it).
                self._run_headless_export_hook()
                now = time.monotonic()
                tick_dt = max(0.0, now - last_tick)
                last_tick = now
                self._on_frame_update(tick_dt)
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
            except Exception as _shutdown_exc:
                try:
                    ErrorReporter.log_error(
                        "Application",
                        "shutdown raised in run_async finally",
                        _shutdown_exc,
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
        from ovwidgets.common.error_reporter import ErrorReporter
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
            self._undo_manager.undo()
        # Ctrl+Y or Ctrl+Shift+Z — redo
        elif ctrl and (key in (ord("Y"), ord("y")) or
                       (key in (ord("Z"), ord("z")) and shift)):
            self._undo_manager.redo()
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
        # clipboard is empty (Ctrl+V) — matches the fan-out contract
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
        # Same fan-out contract as Ctrl+C / X / V: dispatched to the
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
            if not self._delete_selected_prim_specs_in_layers():
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
        from ovwidgets.layers.commands import RemovePrimSpecsCommand
        from ovwidgets.layers.prim_spec_item import PrimSpecItem
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
        from ovui_data_adapters.openusd import DeletePrimCommand
        try:
            from pxr import Sdf
        except ImportError:
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
            prim_path = Sdf.Path(path)
            cmd = DeletePrimCommand(self._stage_adapter.stage, prim_path)
            self._undo_manager.push(cmd)
        self._undo_manager.end_group()

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
        from ovwidgets.layers.layer_item import LayerItem
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
        :func:`ovwidgets.app.menu_bar._require_stage` wording so keyboard and
        menu paths read identically in the status bar.
        """
        if self._layer_adapter is not None:
            return True
        try:
            from ovwidgets.common.error_reporter import ErrorReporter
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
        from ovwidgets.app.layout import _collect_layout, save_layout_data
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
        from ovwidgets.app.layout import _restore_layout as _apply_windows
        from ovwidgets.app.layout import (
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

    def open_file(self, path: str) -> None:
        """Open a USD file from disk, create a UsdStageAdapter, and wire it to panels.

        Pre-constructs the ovrtx renderer BEFORE ``Usd.Stage.Open`` so ovrtx's
        MDL loader primes its file datasource cache before the pxr USD plugin
        opens a stage. If pxr opens a stage first, ovrtx's ``mdl::Default``
        load fails with a ``C100 "mdl" expected`` parser error and
        ``Failed to create HydraEngine`` — the viewport then renders nothing.
        See :meth:`_preconstruct_ovrtx_renderer` for details.
        """
        prebuilt_renderer = self._startup_prebuilt_renderer
        if prebuilt_renderer is _NO_PREBUILT_RENDERER:
            prebuilt_renderer = self._preconstruct_ovrtx_renderer()
        else:
            # ``None`` is a valid early result here: headless startup already
            # tried before ui.init, and retrying after the Vulkan UI backend is
            # live can hang ovrtx/NGX initialization.
            self._startup_prebuilt_renderer = _NO_PREBUILT_RENDERER
        try:
            from pxr import Usd
            stage = Usd.Stage.Open(path)
        except Exception as e:
            from ovwidgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_error(f"Cannot open file: {e}")
            if prebuilt_renderer is not None:
                try:
                    prebuilt_renderer.shutdown()
                except Exception:
                    pass
            return
        self._load_stage(stage, title=Path(path).name, prebuilt_renderer=prebuilt_renderer)
        self._current_file_path = path
        self._recent_files.add(path)
        self._settings.set("ui.recent_files", self._recent_files.get_ordered())

    def open_stage(self, stage: Any) -> None:
        """Headless/test variant: accepts an in-memory Usd.Stage directly."""
        self._load_stage(stage, title="(in-memory)")

    def _create_empty_startup_stage(self) -> Any:
        """Create the default no-file stage with a file-backed root layer.

        ovrtx can share live USD edits with a stage whose root layer has a
        real identifier. An anonymous ``CreateInMemory`` root is exported to
        a one-time temp snapshot by the renderer, so prims authored later via
        the Create menu do not appear in the viewport.
        """
        from pxr import Usd

        stage_dir = tempfile.mkdtemp(prefix="usdviewer_new_stage_")
        stage_path = os.path.join(stage_dir, "NewStage.usda")
        try:
            stage = Usd.Stage.CreateNew(stage_path)
        except Exception:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise
        if stage is None:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise RuntimeError(
                f"Usd.Stage.CreateNew returned None for {stage_path!r}"
            )
        self._scratch_stage_dirs.append(stage_dir)
        return stage

    def save_stage_to(self, path: str) -> bool:
        """Export the current USD stage to ``path`` — the content browser implementation step 55.

        Calls ``stage.Export(path)`` on the adapter's live
        :class:`pxr.Usd.Stage`. On success, updates
        :attr:`_current_file_path` so a subsequent File > Save writes
        directly to the same path (no dialog), appends ``path`` to the
        recent-files list, and returns ``True``. On failure — no stage
        loaded, ``Export`` raised, empty path — surfaces the reason via
        :class:`ErrorReporter.show_error` and returns ``False``. The
        bool return lets the menu handler branch (e.g. a future "close
        after save" flow) without re-reading the adapter state.
        """
        from ovwidgets.common.error_reporter import ErrorReporter
        if not path:
            ErrorReporter.show_error("Save path is empty")
            return False
        if self._stage_adapter is None:
            ErrorReporter.show_error("No stage loaded — cannot save")
            return False
        stage = getattr(self._stage_adapter, "stage", None)
        if stage is None:
            ErrorReporter.show_error("Stage adapter has no stage — cannot save")
            return False
        try:
            stage.Export(path)
        except Exception as exc:  # noqa: BLE001
            ErrorReporter.log_error("Application", "stage.Export failed", exc)
            ErrorReporter.show_error(
                f"Cannot save file: {type(exc).__name__}: {exc}",
            )
            return False
        self._current_file_path = path
        self._recent_files.add(path)
        self._settings.set("ui.recent_files", self._recent_files.get_ordered())
        return True

    def _load_stage(
        self,
        stage: Any,
        title: str,
        prebuilt_renderer: Any = None,
    ) -> None:
        if self._current_stage_sub is not None:
            self._current_stage_sub.cancel()
            self._current_stage_sub = None
        self._selection_bus.clear()
        # Detach any prior LayerStackAdapter before building the new one so
        # its Tf/Sdf notice keys unwire before the old stage is replaced.
        if self._layer_adapter is not None:
            try:
                self._layer_adapter.detach_stage()
            except Exception:
                pass
            self._layer_adapter = None
        from ovui_data_adapters.openusd import UsdTransformAdapter
        from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        self._stage_adapter = UsdStageAdapter(stage, self._undo_manager, self.call_later)
        self._current_stage_sub = self._stage_adapter.subscribe_changes(self._on_stage_changed)
        if self._stage_window is not None:
            self._stage_window.set_adapter(self._stage_adapter)
        if self._property_window is not None:
            from ovui_data_adapters.openusd import (
                UsdPropertyAdapter,  # path migrates to openusd in Step 12
            )
            factory = lambda paths: UsdPropertyAdapter(
                stage, paths, self._undo_manager, self._stage_adapter
            )
            self._property_window.set_property_adapter_factory(factory)
            self._property_window.set_stage_adapter(self._stage_adapter, self._undo_manager)
        # LAYERS-PLAN Step 9: build the layer-stack adapter, wire its notice
        # handlers through ``call_later``, and hand it to the window so Phase C
        # can rebuild its tree model once the window is populated.
        self._layer_adapter = UsdLayerStackAdapter(stage, self._undo_manager)
        self._layer_adapter.attach_stage(call_later=self.call_later)
        if self._layer_window is not None:
            self._layer_window.set_adapter(self._layer_adapter)
        # Wire the transform gizmo (Step C.2) — the viewport widget owns a
        # ``PrimTransformModel`` that needs these adapters to drive the
        # translate gizmo's drag math + undo pipeline. Step C.5 will fold
        # the selection-bus subscription into the model itself.
        transform_adapter = UsdTransformAdapter(stage)
        if self._viewport_window is not None:
            self._viewport_window.set_scene_name(title)
            self._viewport_window.attach_stage(
                transform_adapter=transform_adapter,
                stage_adapter=self._stage_adapter,
                undo_manager=self._undo_manager,
                snap_system=self._snap_system,
            )
        # Swap the viewport renderer. USD Viewer uses ovrtx and only ovrtx —
        # construction failures surface a warning and leave the previous
        # renderer in place so the stage tree + properties stay usable.
        if self._viewport_window is not None:
            renderer = self._build_renderer_for_stage(stage, prebuilt=prebuilt_renderer)
            if renderer is not None:
                self._viewport_window.set_renderer(renderer)
                # Drop the cadence clock so the next tick paints the freshly
                # attached renderer immediately rather than waiting out the
                # remaining 1 / MAX_FPS_FOREGROUND window.
                self._viewport_render_clock.reset()
            else:
                if _require_ovrtx_enabled():
                    raise RuntimeError(
                        "ovrtx is required, but no ovrtx renderer was returned; "
                        "refusing to use the fallback renderer for proof."
                    )
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
                        pass
            self._viewport_window.update_prim_count(self._get_prim_count())
            # Step 16: pose-based seam. Ask the stage adapter for any
            # authored ``boundCamera`` pose; apply it to the viewport
            # via the new value-object API. Bbox framing is the
            # fallback when no pose is authored or the apply fails
            # (preserves the prior "always frame something safe"
            # contract). The widget no longer receives a raw
            # ``Usd.Stage`` for camera metadata — only a parsed
            # ``BoundCameraPose``.
            pose = self._stage_adapter.read_bound_camera()
            if pose is None or not self._viewport_window.apply_camera_pose(pose):
                self._viewport_window.frame_paths(["/"])

    def _preconstruct_ovrtx_renderer(self) -> Any:
        """Construct an :class:`OvRtxRendererAdapter` early, before pxr stage open.

        ovrtx's ``mdl::Default`` loader stops working if any pxr
        ``Usd.Stage.Open`` has already run in the process — the bundled USD
        plugin's file datasource comes up with the wrong resolver state and
        reads the Default.mdl file as empty, hitting ``C100 "mdl" expected``
        and ``Failed to create HydraEngine``. Constructing ovrtx's
        ``Renderer`` first primes its MDL cache before pxr wakes up.
        Returns ``None`` on import/construction failure — the caller falls
        back to leaving the previous renderer installed.
        """
        from ovui_data_adapters.openusd import renderer_adapter as _ovrtx_mod

        from ovwidgets.common.error_reporter import ErrorReporter

        if not _ovrtx_mod.AVAILABLE:
            import_err = _ovrtx_mod._OVRTX_IMPORT_ERROR
            reason = (
                f"{type(import_err).__name__}: {import_err}"
                if import_err is not None
                else "ovrtx not available on this system"
            )
            if _require_ovrtx_enabled():
                raise RuntimeError(
                    f"ovrtx is required, but the renderer is unavailable ({reason})."
                )
            ErrorReporter.show_warning(f"ovrtx renderer unavailable ({reason})")
            return None
        try:
            return _ovrtx_mod.OvRtxRendererAdapter()
        except Exception as exc:
            ErrorReporter.log_error("Application", "ovrtx renderer failed", exc)
            if _require_ovrtx_enabled():
                raise RuntimeError(
                    "ovrtx is required, but renderer construction failed "
                    f"({type(exc).__name__}: {exc})."
                ) from exc
            ErrorReporter.show_warning(
                f"ovrtx renderer failed ({type(exc).__name__}: {exc})"
            )
            return None

    def _build_renderer_for_stage(self, stage: Any, prebuilt: Any = None) -> Any:
        """Attach ``stage`` to an ovrtx renderer and return it.

        If ``prebuilt`` is supplied (the pre-constructed adapter from
        :meth:`_preconstruct_ovrtx_renderer`), it is loaded with the stage
        and returned. Otherwise a fresh adapter is built — but callers that
        went through :meth:`open_file` should already have pre-constructed
        one to avoid the pxr → ovrtx MDL loader ordering bug. This path is
        kept for the headless :meth:`open_stage` variant.

        On any failure (missing GPU, broken install, load_stage error) we
        surface a warning via :class:`ErrorReporter` and return ``None`` —
        the caller keeps the previous renderer (or the mock).
        """
        from ovwidgets.common.error_reporter import ErrorReporter

        try:
            renderer = prebuilt
            if renderer is None:
                renderer = self._preconstruct_ovrtx_renderer()
            if renderer is None:
                if _require_ovrtx_enabled():
                    raise RuntimeError(
                        "ovrtx is required, but no ovrtx renderer was returned; "
                        "see earlier renderer warning."
                    )
                return None
            renderer.load_stage(stage)
            return renderer
        except Exception as exc:
            ErrorReporter.log_error("Application", "ovrtx renderer failed", exc)
            if _require_ovrtx_enabled():
                raise RuntimeError(
                    "ovrtx is required, but the renderer could not load the stage "
                    f"({type(exc).__name__}: {exc})."
                ) from exc
            ErrorReporter.show_warning(
                f"ovrtx renderer failed ({type(exc).__name__}: {exc})"
            )
            return None

    def _on_stage_changed(self, event: Any) -> None:
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

        from ovwidgets.common.testing.mock_property import MockPropertyAdapter

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

    def shutdown(self) -> None:
        """Clean shutdown. Clear references, reset singleton.

        Idempotent and best-effort (issue #35):

        * Each discrete teardown block is wrapped in ``try/except`` so a
          single block's failure never leaves later resources alive.
          Phase A reproductions showed that the leftover ``ui.Window``
          references were exactly what produced the segfault during
          ``Py_FinalizeEx`` — partial teardown is worse than a noisy
          shutdown.
        * Panel-window teardown uses ``try: w.destroy(); except: pass;
          finally: setattr(self, attr, None)`` so the attribute is
          nulled regardless of whether ``destroy()`` raised — otherwise
          a half-torn-down ``ui.Window`` keeps a strong Python reference
          and survives into ``Py_FinalizeEx``.
        * ``_shutdown_done`` is set after every block has been
          *attempted*; subsequent calls are short-circuited.
          ``_shutdown_in_progress`` short-circuits a recursive call from
          within a destroy() callback.

        Thread affinity: UI thread only. The body touches ovui Python
        bindings and Application singletons; cross-thread invocation is
        not supported.
        """
        if getattr(self, "_shutdown_done", False):
            return
        if getattr(self, "_shutdown_in_progress", False):
            return
        self._shutdown_in_progress = True
        try:
            # ── flags & lightweight Python state ─────────────────────
            try:
                self._running = False
                self._pending_callbacks = []
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
            try:
                self._teardown_headless_export()
            except Exception:
                pass
            # ── stage / property / layer subscriptions ───────────────
            try:
                if self._current_stage_sub is not None:
                    self._current_stage_sub.cancel()
                    self._current_stage_sub = None
                self._mock_prop_sub = None
                self._stage_adapter = None
            except Exception:
                pass
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
            for sub_attr in ("_snap_sub", "_theme_sub", "_frame_sub"):
                try:
                    setattr(self, sub_attr, None)
                except Exception:
                    pass
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
            # ── panel windows: setattr(...None) MUST run even if
            #     w.destroy() raises, otherwise the panel attribute keeps
            #     a reference to the now-half-torn-down ui.Window which
            #     then leaks into Py_FinalizeEx (the exact failure mode
            #     this whole fix is preventing). Pattern: try destroy /
            #     except swallow / finally null the attribute.
            for attr in ("_stage_window", "_property_window",
                         "_viewport_window", "_content_window",
                         "_layer_window"):
                w = getattr(self, attr, None)
                if w is None:
                    continue
                try:
                    w.destroy()
                except Exception:
                    pass
                finally:
                    try:
                        setattr(self, attr, None)
                    except Exception:
                        pass
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
            #     ordering contract is preserved so when Step 4 lands
            #     no further edit to shutdown() is needed.
            try:
                from ovwidgets.common.icon_caches import clear_all  # noqa: WPS433
                clear_all()
            except Exception:
                pass
            # ── singletons reset (LAST, before flag set) ─────────────
            try:
                SelectionBus._instance = None
                Application._instance = None
            except Exception:
                pass

            self._shutdown_done = True
        finally:
            self._shutdown_in_progress = False

    @property
    def snap_system(self) -> SnapSystem:
        return self._snap_system

    def _on_snap_enabled_changed(self, key: str, value: Any) -> None:
        self._snap_system.enable(bool(value))

    def _on_theme_changed(self, key: str, value: str) -> None:
        """React to ui.theme setting change."""
        from ovwidgets.app.style import set_theme
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
        from ovwidgets.app.style.imgui_runtime import apply_imgui_splitter_style

        apply_imgui_splitter_style()
