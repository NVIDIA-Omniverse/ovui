# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage selection bus.

SelectionBus is the central selection coordinator that
broadcasts SelectionChangedEvent to all subscribers. Supports named layers
for tool selections and reentrancy protection.
"""

import weakref
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ovwidgets.common.settings import Subscription


@dataclass(frozen=True)
class SelectionItem:
    """A single selected item."""

    path: str
    source: str


@dataclass(frozen=True)
class SelectionSnapshot:
    """Immutable snapshot of current selection state."""

    items: Tuple[SelectionItem, ...]
    layer: str = "primary"

    def paths(self) -> List[str]:
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

    pass


class SelectionBus:
    """
    Central selection state manager.

    SelectionBus is the single source of truth for selection.
    All modules publish to and subscribe from the same bus. This prevents
    circular updates — the source field lets subscribers skip updates they
    originated.

    Layer support: The bus supports named selection layers. The "primary"
    layer is always present. Tools can push temporary layers (e.g., a
    lasso selection tool might use a "tool" layer while dragging, then
    merge into primary on release).
    """

    _instance: Optional["SelectionBus"] = None

    def __init__(self) -> None:
        self._layers: dict[str, SelectionSnapshot] = {
            "primary": SelectionSnapshot(items=(), layer="primary")
        }
        self._subscribers: list[Callable] = []
        self._publishing: bool = False

    def publish(self, paths: List[str], source: str, layer: str = "primary") -> None:
        """Publish a new selection. Creates SelectionItems, stores snapshot,
        notifies all subscribers.

        Raises SelectionBusError if called reentrantly (during notification)."""
        if self._publishing:
            raise SelectionBusError("Reentrant publish is not allowed")
        items = tuple(SelectionItem(path=p, source=source) for p in paths)
        snapshot = SelectionSnapshot(items=items, layer=layer)
        self._layers[layer] = snapshot
        event = SelectionChangedEvent(snapshot=snapshot, source=source)
        self._publishing = True
        try:
            for cb in list(self._subscribers):
                cb(event)
        finally:
            self._publishing = False

    def clear(self, layer: str = "primary") -> None:
        """Clear selection in the given layer. Notifies subscribers."""
        self.publish([], source="api", layer=layer)

    def get_snapshot(self, layer: str = "primary") -> SelectionSnapshot:
        """Get the current selection snapshot for a layer.
        Returns an empty snapshot if the layer doesn't exist."""
        return self._layers.get(layer, SelectionSnapshot(items=(), layer=layer))

    def subscribe(self, callback: Callable[[SelectionChangedEvent], None]) -> Subscription:
        """Subscribe to selection changes. Uses Subscription from settings.py."""
        self._subscribers.append(callback)
        return Subscription(weakref.ref(self), "change", callback)

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def push_layer(self, name: str) -> None:
        """Push a named selection layer. Initializes it as empty."""
        if name not in self._layers:
            self._layers[name] = SelectionSnapshot(items=(), layer=name)

    def pop_layer(self, name: str) -> None:
        """Pop a named selection layer. Cannot pop 'primary'.
        Raises ValueError if trying to pop 'primary'."""
        if name == "primary":
            raise ValueError("Cannot pop the 'primary' layer")
        self._layers.pop(name, None)

    @staticmethod
    def instance() -> "SelectionBus":
        """Return the application singleton. Creates one if none exists."""
        if SelectionBus._instance is None:
            SelectionBus._instance = SelectionBus()
        return SelectionBus._instance
