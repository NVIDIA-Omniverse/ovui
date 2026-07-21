# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Entry-point component lifecycle for USD Viewer."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import sys
from typing import Any


ENTRY_POINT_GROUP = "ovui_widgets.components"


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

    @property
    def group(self) -> str:
        return self._group

    @property
    def loaded_names(self) -> tuple[str, ...]:
        return tuple(self._loaded)

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

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
            try:
                register = entry_point.load()
                handle = register(self._app)
            except Exception as exc:
                self._failures[name] = exc
                self._report_load_failure(name, entry_point, exc)
                self._log("load", name, exc)
                continue
            record = LoadedComponent(
                name=name,
                entry_point=entry_point,
                handle=handle,
            )
            self._loaded[name] = record
            loaded.append(record)
        return tuple(loaded)

    def unload(self, name: str) -> bool:
        """Unload one loaded component by entry-point name."""
        record = self._loaded.pop(name, None)
        if record is None:
            return False
        try:
            self._unload_handle(record.handle)
        except Exception as exc:
            self._failures[name] = exc
            self._log("unload", name, exc)
        return True

    def unload_all(self) -> None:
        """Unload all loaded components in reverse load order."""
        for name in reversed(tuple(self._loaded)):
            self.unload(name)

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
]
