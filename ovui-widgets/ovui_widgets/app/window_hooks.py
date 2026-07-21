# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Generic lazy window contributions for optional app components."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence

from ovui_widgets.app.menu_hooks import (
    AppMenuContribution,
    AppMenuHandle,
    AppMenuRegistry,
    normalize_menu_path,
)


WindowFactory = Callable[[Any], Any]
WindowPredicate = Callable[[Any], bool]
WindowCallback = Callable[[Any], None]


@dataclass(frozen=True)
class AppWindowContribution:
    """Declarative lazy window supplied by an optional component."""

    id: str
    title: str
    factory: WindowFactory
    menu_label: str = ""
    menu_parent_path: str | Sequence[str] = ("Window",)
    menu_id: str | None = None
    order: float = 1000.0
    capabilities: Iterable[str] = field(default_factory=tuple)
    enabled: bool = True
    visible_fn: WindowPredicate | None = None
    enabled_fn: WindowPredicate | None = None
    on_add: WindowCallback | None = None
    on_remove: WindowCallback | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("AppWindowContribution.id is required")
        if not self.title:
            raise ValueError("AppWindowContribution.title is required")
        if not callable(self.factory):
            raise ValueError("AppWindowContribution.factory must be callable")
        object.__setattr__(self, "menu_parent_path", normalize_menu_path(self.menu_parent_path))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        if self.menu_id is None:
            object.__setattr__(self, "menu_id", f"{self.id}.menu")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class AppWindowHandle:
    """Removable handle returned from ``AppWindowRegistry.add``."""

    def __init__(self, registry: "AppWindowRegistry", contribution_id: str) -> None:
        self._registry = registry
        self._contribution_id = contribution_id

    @property
    def id(self) -> str:
        return self._contribution_id

    def remove(self) -> bool:
        return self._registry.remove(self._contribution_id)


@dataclass
class _WindowRecord:
    contribution: AppWindowContribution
    window: Any = None
    menu_handle: AppMenuHandle | None = None


class AppWindowRegistry:
    """Component-owned lazy window registry with optional menu entries."""

    def __init__(
        self,
        app: Any,
        *,
        menu_registry: AppMenuRegistry | None = None,
        capabilities: Iterable[str] = (),
    ) -> None:
        self._app = app
        self._menu_registry = menu_registry
        self._capabilities: set[str] = set(capabilities)
        self._records: dict[str, _WindowRecord] = {}
        self._failures: dict[str, BaseException] = {}

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    def set_capability(self, capability: str, enabled: bool = True) -> None:
        if enabled:
            self._capabilities.add(capability)
        else:
            self._capabilities.discard(capability)

    def set_capabilities(self, capabilities: Iterable[str]) -> None:
        self._capabilities = set(capabilities)

    def add(self, contribution: AppWindowContribution) -> AppWindowHandle:
        """Register one lazy window contribution and return its handle."""

        existing = self._records.get(contribution.id)
        if existing is not None:
            return AppWindowHandle(self, contribution.id)
        record = _WindowRecord(contribution=contribution)
        self._records[contribution.id] = record
        record.menu_handle = self._register_menu(contribution)
        self._invoke_lifecycle(contribution, "add")
        return AppWindowHandle(self, contribution.id)

    def remove(self, contribution_id: str) -> bool:
        record = self._records.pop(contribution_id, None)
        if record is None:
            return False
        if record.menu_handle is not None:
            record.menu_handle.remove()
            record.menu_handle = None
        self._destroy_window(contribution_id, record.window)
        record.window = None
        self._invoke_lifecycle(record.contribution, "remove")
        return True

    def clear(self) -> None:
        for contribution_id in reversed(tuple(self._records)):
            self.remove(contribution_id)

    def iter_contributions(self) -> tuple[AppWindowContribution, ...]:
        return tuple(
            record.contribution
            for record in self._records.values()
            if self._is_available(record.contribution)
        )

    def get(self, contribution_id: str) -> Any:
        record = self._records.get(contribution_id)
        return None if record is None else record.window

    def open(self, contribution_id: str) -> Any:
        record = self._records.get(contribution_id)
        if record is None:
            return None
        contribution = record.contribution
        if not self._is_available(contribution) or not self._enabled(contribution):
            return None
        if record.window is None:
            try:
                record.window = contribution.factory(self._app)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("open", contribution.id, exc)
                return None
        self._set_visible(record.window, True)
        return record.window

    def close(self, contribution_id: str) -> bool:
        record = self._records.get(contribution_id)
        if record is None or record.window is None:
            return False
        self._set_visible(record.window, False)
        return True

    def toggle(self, contribution_id: str) -> Any:
        record = self._records.get(contribution_id)
        if record is None:
            return None
        window = record.window
        if window is not None and bool(getattr(window, "visible", False)):
            self.close(contribution_id)
            return window
        return self.open(contribution_id)

    def _register_menu(
        self,
        contribution: AppWindowContribution,
    ) -> AppMenuHandle | None:
        if self._menu_registry is None or not contribution.menu_label:
            return None
        menu = AppMenuContribution(
            id=str(contribution.menu_id),
            label=contribution.menu_label,
            parent_path=contribution.menu_parent_path,
            order=contribution.order,
            enabled=contribution.enabled,
            callback=lambda app: self.toggle(contribution.id),
            visible_fn=lambda app: self._is_available(contribution),
            enabled_fn=lambda app: self._enabled(contribution),
        )
        return self._menu_registry.add(menu)

    def _is_available(self, contribution: AppWindowContribution) -> bool:
        if any(capability not in self._capabilities for capability in contribution.capabilities):
            return False
        if contribution.visible_fn is None:
            return True
        try:
            return bool(contribution.visible_fn(self._app))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("visible", contribution.id, exc)
            return False

    def _enabled(self, contribution: AppWindowContribution) -> bool:
        if not contribution.enabled:
            return False
        if contribution.enabled_fn is None:
            return True
        try:
            return bool(contribution.enabled_fn(self._app))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("enabled", contribution.id, exc)
            return False

    def _invoke_lifecycle(self, contribution: AppWindowContribution, action: str) -> None:
        fn = contribution.on_add if action == "add" else contribution.on_remove
        if fn is None:
            return
        try:
            fn(self._app)
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log(action, contribution.id, exc)

    def _destroy_window(self, contribution_id: str, window: Any) -> None:
        if window is None:
            return
        destroy = getattr(window, "destroy", None)
        if not callable(destroy):
            return
        try:
            destroy()
        except Exception as exc:
            self._failures[contribution_id] = exc
            self._log("destroy", contribution_id, exc)

    @staticmethod
    def _set_visible(window: Any, visible: bool) -> None:
        if hasattr(window, "visible"):
            try:
                window.visible = visible
            except Exception:
                pass

    @staticmethod
    def _log(action: str, contribution_id: str, exc: BaseException) -> None:
        print(
            f"[ovui_widgets.app.window_hooks] {action} failed for {contribution_id}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


__all__ = [
    "AppWindowContribution",
    "AppWindowHandle",
    "AppWindowRegistry",
]
