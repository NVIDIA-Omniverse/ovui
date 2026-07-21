# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral selection state and eventing service.

``SelectionBus`` is the central selection coordinator that broadcasts
``SelectionChangedEvent`` to subscribers. It supports source-tagged events,
named selection layers, reentrancy protection, singleton compatibility, and
RAII subscription lifetime without importing ovui_widgets or UI runtime modules.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Any, Callable


class Subscription:
    """RAII subscription handle for selection-bus change notifications."""

    def __init__(
        self,
        bus_ref: "weakref.ReferenceType[Any]",
        callback: Callable[["SelectionChangedEvent"], None],
    ) -> None:
        self._bus_ref = bus_ref
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this callback from the subscribed selection bus."""
        if self._cancelled:
            return
        bus = self._bus_ref()
        if bus is not None:
            # Mark cancelled only AFTER removal succeeded, so a failed
            # revocation remains owned and a retry genuinely removes.
            bus._remove_subscriber(self._callback)
        self._cancelled = True

    def __del__(self) -> None:
        self.cancel()


@dataclass(frozen=True)
class SelectionItem:
    """A single selected item."""

    path: str
    source: str


@dataclass(frozen=True)
class SelectionSnapshot:
    """Immutable snapshot of current selection state."""

    items: tuple[SelectionItem, ...]
    layer: str = "primary"

    def paths(self) -> list[str]:
        return [item.path for item in self.items]

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return len(self.items) > 0


@dataclass
class SelectionChangedEvent:
    """Event fired when selection changes."""

    snapshot: SelectionSnapshot
    source: str


class SelectionBusError(Exception):
    """Raised on reentrancy violation."""


class SelectionBus:
    """Central selection state manager."""

    _instance: "SelectionBus | None" = None

    def __init__(self) -> None:
        self._layers: dict[str, SelectionSnapshot] = {
            "primary": SelectionSnapshot(items=(), layer="primary")
        }
        self._subscribers: list[Callable[[SelectionChangedEvent], None]] = []
        self._publishing: bool = False

    def publish(
        self,
        paths: list[str],
        source: str,
        layer: str = "primary",
    ) -> None:
        """Publish a new selection and notify subscribers.

        Raises :class:`SelectionBusError` if called reentrantly during
        notification dispatch.
        """
        if self._publishing:
            raise SelectionBusError("Reentrant publish is not allowed")
        items = tuple(SelectionItem(path=path, source=source) for path in paths)
        snapshot = SelectionSnapshot(items=items, layer=layer)
        self._layers[layer] = snapshot
        event = SelectionChangedEvent(snapshot=snapshot, source=source)
        self._publishing = True
        try:
            for callback in list(self._subscribers):
                callback(event)
        finally:
            self._publishing = False

    def clear(self, layer: str = "primary") -> None:
        """Clear selection in ``layer`` and notify subscribers."""
        self.publish([], source="api", layer=layer)

    def get_snapshot(self, layer: str = "primary") -> SelectionSnapshot:
        """Return the current selection snapshot for ``layer``."""
        return self._layers.get(layer, SelectionSnapshot(items=(), layer=layer))

    def subscribe(
        self,
        callback: Callable[[SelectionChangedEvent], None],
    ) -> Subscription:
        """Subscribe to selection changes."""
        self._subscribers.append(callback)
        return Subscription(weakref.ref(self), callback)

    def _remove_subscriber(
        self,
        callback: Callable[[SelectionChangedEvent], None],
    ) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def push_layer(self, name: str) -> None:
        """Push a named selection layer and initialize it as empty."""
        if name not in self._layers:
            self._layers[name] = SelectionSnapshot(items=(), layer=name)

    def pop_layer(self, name: str) -> None:
        """Pop a named selection layer. The ``primary`` layer cannot be popped."""
        if name == "primary":
            raise ValueError("Cannot pop the 'primary' layer")
        self._layers.pop(name, None)

    @staticmethod
    def instance() -> "SelectionBus":
        """Return the application singleton. Creates one if none exists."""
        if SelectionBus._instance is None:
            SelectionBus._instance = SelectionBus()
        return SelectionBus._instance


__all__ = [
    "SelectionBus",
    "SelectionBusError",
    "SelectionChangedEvent",
    "SelectionItem",
    "SelectionSnapshot",
    "Subscription",
]
