# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry-point component lifecycle for USD Viewer."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Any

ENTRY_POINT_GROUP = "ovui_widgets.components"

# Failed-registration recovery transfer channel. When a component's
# ``register(app)`` raises but its rollback could NOT finish, the
# component deposits its retained recovery handle (an object whose
# retryable ``unload()`` finishes exactly the outstanding cleanup)
# here via :func:`deposit_component_recovery` BEFORE the exception
# propagates. ``load_all()`` drains the deposit in the same except
# branch that records the initiating failure and adopts it under the
# entry-point identity. The channel is deliberately independent of the
# initiating exception object: an exception that rejects attribute
# attachment (or any other shape) must not be able to strand recovery
# ownership outside the production lifecycle owner.
_PENDING_RECOVERY: list[Any] = []


def deposit_component_recovery(handle: Any) -> None:
    """Transfer one failed-registration recovery handle to the manager.

    Called by a component's failed rollback while its registration
    exception is propagating. The next ``ComponentManager.load_all()``
    except-branch adopts the deposit under the failing entry-point
    identity; the initiating exception itself is never touched.
    """
    if handle is None:
        return
    if any(existing is handle for existing in _PENDING_RECOVERY):
        return
    _PENDING_RECOVERY.append(handle)


def withdraw_component_recovery(handle: Any) -> None:
    """Identity-remove one fully recovered handle from the channel.

    Called by the component's own successful teardown. Without a
    manager to drain the deposit (the documented direct ``register``
    fallback), the channel would otherwise strongly retain the entire
    completed aggregate graph indefinitely. A no-op when the handle was
    already drained/adopted or never deposited.
    """
    _PENDING_RECOVERY[:] = [
        existing for existing in _PENDING_RECOVERY if existing is not handle
    ]


@dataclass
class LoadedComponent:
    """Loaded entry-point record."""

    name: str
    entry_point: Any
    handle: Any


class ComponentManager:
    """Discover, load, and unload optional app components."""

    def __init__(self, app: Any, *, group: str = ENTRY_POINT_GROUP) -> None:
        self._app = app
        self._group = group
        self._loaded: dict[str, LoadedComponent] = {}
        self._failures: dict[str, BaseException] = {}
        # Last known layout state of the component windows. Shutdown
        # unloads components before the application saves its layout.
        self._layout_state: dict[str, dict] = {}
        # Retryable ownership ledger: a component whose unload FAILED is
        # moved here (never dropped) so the exact generation stays
        # operationally owned. While an entry is unresolved, loading a
        # new generation with the same entry-point name is blocked;
        # calling unload(name) again retries exactly the outstanding
        # teardown through the same handle.
        self._unresolved: dict[str, LoadedComponent] = {}

    @property
    def group(self) -> str:
        return self._group

    @property
    def loaded_names(self) -> tuple[str, ...]:
        return tuple(self._loaded)

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    @property
    def unresolved_names(self) -> tuple[str, ...]:
        """Entry-point names whose failed unload still awaits retry."""
        return tuple(self._unresolved)

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded

    def discover(self) -> tuple[Any, ...]:
        """Return entry points from the configured group in stable order."""
        points = metadata.entry_points()
        if hasattr(points, "select"):
            selected = points.select(group=self._group)
        else:
            selected = points.get(self._group, ())
        return tuple(sorted(selected, key=lambda item: getattr(item, "name", "")))

    def load_all(self) -> tuple[LoadedComponent, ...]:
        """Load all discovered components exactly once per manager."""
        loaded: list[LoadedComponent] = []
        for entry_point in self.discover():
            name = str(getattr(entry_point, "name", ""))
            if not name or name in self._loaded:
                continue
            if name in self._unresolved:
                # The previous generation's teardown is still owned here;
                # stacking a fresh generation over its live callbacks and
                # registrations would leak both. Retry unload(name) first.
                self._log(
                    "load",
                    name,
                    RuntimeError(
                        "blocked: the previous generation's unload is "
                        "unresolved; retry unload() until it succeeds"
                    ),
                )
                continue
            # Stale deposits (e.g. from a failed direct register() call
            # outside any manager) must not be misattributed to this
            # entry point; the module fallback ledger still owns those.
            del _PENDING_RECOVERY[:]
            try:
                register = entry_point.load()
                handle = register(self._app)
            except Exception as exc:
                self._failures[name] = exc
                recovery = list(_PENDING_RECOVERY)
                del _PENDING_RECOVERY[:]
                if recovery:
                    # The failed registration still OWNS live resources
                    # its rollback could not release. Adopt the exact
                    # deposited recovery handle(s) under this entry-point
                    # identity so the same-name guard blocks a stacking
                    # generation and unload(name) retries the outstanding
                    # cleanup. (_unload_handle unloads a list in reverse.)
                    self._unresolved[name] = LoadedComponent(
                        name=name,
                        entry_point=entry_point,
                        handle=(
                            recovery[0] if len(recovery) == 1 else recovery
                        ),
                    )
                self._report_load_failure(name, entry_point, exc)
                self._log("load", name, exc)
                continue
            del _PENDING_RECOVERY[:]
            record = LoadedComponent(
                name=name,
                entry_point=entry_point,
                handle=handle,
            )
            self._loaded[name] = record
            loaded.append(record)
        return tuple(loaded)

    def unload(self, name: str) -> bool:
        """Unload one loaded component by entry-point name.

        A failed unload does NOT discard the generation: the exact
        record moves to the unresolved ledger (`unresolved_names`),
        loading that name again is blocked, and calling this method
        again retries exactly the outstanding teardown through the same
        handle (component teardown is retryable end to end). The record
        is removed exactly once — on the attempt whose teardown
        succeeded.
        """
        retried = False
        if name in self._loaded:
            # Keep the window state of this generation before it goes.
            try:
                self.layout_state()
            except Exception as exc:
                self._log("layout_state", name, exc)
        record = self._loaded.pop(name, None)
        if record is None:
            record = self._unresolved.pop(name, None)
            retried = record is not None
        if record is None:
            return False
        try:
            self._unload_handle(record.handle)
        except Exception as exc:
            self._unresolved[name] = record
            self._failures[name] = exc
            self._log("unload", name, exc)
            return True
        if retried:
            self._failures.pop(name, None)
        return True

    def unload_all(self) -> None:
        """Unload all loaded components in reverse load order.

        Previously-unresolved generations are retried too; whatever
        still fails stays owned in the unresolved ledger rather than
        being silently discarded.
        """
        for name in reversed(tuple(self._loaded)):
            self.unload(name)
        for name in tuple(self._unresolved):
            self.unload(name)

    def tick(self) -> None:
        """Advance opt-in loaded components once per ordinary UI update."""

        for record in tuple(self._loaded.values()):
            tick = getattr(record.handle, "tick", None)
            if not callable(tick):
                continue
            try:
                tick()
            except Exception as exc:
                self._failures[f"{record.name}:tick"] = exc
                self._log("tick", record.name, exc)

    def apply_default_layout(self) -> None:
        """Let loaded components dock their windows into the default layout.

        Called after the application applies its own default layout, at
        startup and from Window > Reset Layout.
        """

        for record in tuple(self._loaded.values()):
            apply = getattr(record.handle, "apply_default_layout", None)
            if not callable(apply):
                continue
            try:
                apply()
            except Exception as exc:
                self._failures[f"{record.name}:apply_default_layout"] = exc
                self._log("apply_default_layout", record.name, exc)

    def layout_state(self) -> dict[str, dict]:
        """The saved layout state of the component windows.

        Each component may supply ``layout_windows()`` that returns a map
        of window title to managed window. Shutdown unloads components
        before the application saves its layout, so the last known state
        is kept here.
        """

        from ovui_widgets.app.layout import window_layout_state

        result: dict[str, dict] = {}
        for record in tuple(self._loaded.values()):
            collect = getattr(record.handle, "layout_windows", None)
            if not callable(collect):
                continue
            try:
                windows = collect() or {}
            except Exception as exc:
                self._failures[f"{record.name}:layout_windows"] = exc
                self._log("layout_windows", record.name, exc)
                continue
            for title, window in dict(windows).items():
                state = window_layout_state(window)
                if state is not None:
                    result[str(title)] = state
        if result:
            self._layout_state.update(result)
        return dict(self._layout_state)

    def restore_layout_window(self, title: str, data: dict) -> bool:
        """Give the saved state of one window back to its component.

        Called for a saved window title that is not an application panel.
        A component returns ``True`` when it owns that title.
        """

        for record in tuple(self._loaded.values()):
            restore = getattr(record.handle, "restore_layout_window", None)
            if not callable(restore):
                continue
            try:
                if restore(title, data):
                    return True
            except Exception as exc:
                self._failures[f"{record.name}:restore_layout_window"] = exc
                self._log("restore_layout_window", record.name, exc)
        return False

    def _unload_handle(self, handle: Any) -> None:
        if handle is None:
            return
        if isinstance(handle, (list, tuple)):
            for child in reversed(handle):
                self._unload_handle(child)
            return
        if callable(handle):
            handle()
            return
        for attr in ("unload", "shutdown", "close", "destroy"):
            fn = getattr(handle, attr, None)
            if callable(fn):
                fn()
                return

    def _report_load_failure(
        self,
        name: str,
        entry_point: Any,
        exc: BaseException,
    ) -> None:
        report = getattr(self._app, "report_module_load_failure", None)
        if not callable(report):
            return
        try:
            report(name, str(getattr(entry_point, "value", "")), exc)
        except Exception as report_exc:
            self._failures[f"{name}:report"] = report_exc
            self._log("report", name, report_exc)

    @staticmethod
    def _log(action: str, name: str, exc: BaseException) -> None:
        print(
            f"[ovui_widgets.components] {action} failed for {name}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


__all__ = [
    "ComponentManager",
    "ENTRY_POINT_GROUP",
    "LoadedComponent",
    "deposit_component_recovery",
    "withdraw_component_recovery",
]
