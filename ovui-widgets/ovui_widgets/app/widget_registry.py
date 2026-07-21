# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Feature-neutral registry for app-owned widget instances."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Callable, Literal


WidgetRegistryAction = Literal["added", "removed"]
WidgetRegistryCallback = Callable[["AppWidgetEvent"], None]


@dataclass(frozen=True)
class AppWidgetEvent:
    """Notification emitted when the app hosts or unhosts a widget."""

    action: WidgetRegistryAction
    widget: Any


@dataclass(frozen=True)
class AppWidgetFailure:
    """Subscriber failure captured without interrupting other subscribers."""

    action: WidgetRegistryAction
    widget: Any
    error: BaseException


class AppWidgetHandle:
    """Removable handle returned by :meth:`AppWidgetRegistry.add`."""

    def __init__(self, registry: "AppWidgetRegistry", widget: Any) -> None:
        self._registry = registry
        self._widget = widget

    @property
    def widget(self) -> Any:
        return self._widget

    def remove(self) -> bool:
        return self._registry.remove(self._widget)


class AppWidgetSubscription:
    """Subscription handle returned by :meth:`AppWidgetRegistry.subscribe`."""

    def __init__(
        self,
        registry: "AppWidgetRegistry",
        callback: WidgetRegistryCallback,
    ) -> None:
        self._registry = registry
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._registry._unsubscribe(self._callback)


class AppWidgetRegistry:
    """Small observable collection of widget instances hosted by the app."""

    def __init__(self) -> None:
        self._widgets: list[Any] = []
        self._subscribers: list[WidgetRegistryCallback] = []
        self._failures: list[AppWidgetFailure] = []

    def add(self, widget: Any) -> AppWidgetHandle:
        """Track ``widget`` once and notify subscribers."""

        if widget not in self._widgets:
            self._widgets.append(widget)
            self._notify(AppWidgetEvent("added", widget))
        return AppWidgetHandle(self, widget)

    def remove(self, widget: Any) -> bool:
        """Stop tracking ``widget`` and notify subscribers when it was present."""

        if widget not in self._widgets:
            return False
        self._widgets.remove(widget)
        self._notify(AppWidgetEvent("removed", widget))
        return True

    def clear(self) -> None:
        """Remove all tracked widgets in reverse hosting order."""

        for widget in reversed(tuple(self._widgets)):
            self.remove(widget)

    def iter_widgets(self) -> tuple[Any, ...]:
        """Return currently hosted widgets in registration order."""

        return tuple(self._widgets)

    @property
    def failures(self) -> tuple[AppWidgetFailure, ...]:
        """Return subscriber failures recorded during notification."""

        return tuple(self._failures)

    def subscribe(
        self,
        callback: WidgetRegistryCallback,
        *,
        replay_existing: bool = True,
    ) -> AppWidgetSubscription:
        """Subscribe to future widget add/remove events.

        ``replay_existing=True`` lets optional components attach to widgets
        that were already constructed before the component entry point loaded.
        """

        self._subscribers.append(callback)
        if replay_existing:
            for widget in tuple(self._widgets):
                self._invoke(callback, AppWidgetEvent("added", widget))
        return AppWidgetSubscription(self, callback)

    def _unsubscribe(self, callback: WidgetRegistryCallback) -> None:
        self._subscribers = [
            subscriber
            for subscriber in self._subscribers
            if subscriber is not callback
        ]

    def _notify(self, event: AppWidgetEvent) -> None:
        for callback in tuple(self._subscribers):
            self._invoke(callback, event)

    def _invoke(
        self,
        callback: WidgetRegistryCallback,
        event: AppWidgetEvent,
    ) -> None:
        try:
            callback(event)
        except Exception as exc:
            failure = AppWidgetFailure(event.action, event.widget, exc)
            self._failures.append(failure)
            print(
                "[ovui_widgets.app.widgets] subscriber failed during "
                f"{event.action}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )


__all__ = [
    "AppWidgetEvent",
    "AppWidgetFailure",
    "AppWidgetHandle",
    "AppWidgetRegistry",
    "AppWidgetSubscription",
]
