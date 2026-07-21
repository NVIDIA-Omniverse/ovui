# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Abstract ``PropertyWidget`` base class.

property widget stack behavior / the property inspector step 6.1. Base class for every stackable
section that :class:`ovui_widgets.property.window.PropertyWindow` composes inside
its scrollable content area. Concrete subclasses implement
:meth:`on_new_payload` (does this widget want to show for the current
selection?) and :meth:`build_items` (emit the UI).

The sync ``build_items`` path is the default. Widgets that need to fetch
USD data off-thread or throttle expensive layout work may override
:meth:`build_items_async` instead; the window calls the async variant
only when it returns a coroutine. :meth:`request_rebuild` is the
subclass-facing hook that reschedules a deferred rebuild (typically
after a filter or model change); the Step 6.3
:class:`SimplePropertyWidget` will hook this into
``omni.kit.app.next_update_async`` so the rebuild runs one frame later
and sidesteps re-entrancy inside USD notice handlers
(the property inspector behavior).

Step 6.1 ships the ABC only; the concrete subclasses land in Steps
6.2–6.4.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Iterator, Optional

if TYPE_CHECKING:
    from ovui_widgets.property.payload import PropertyPayload


class PropertyWidget(ABC):
    """Base class for every property-panel section.

    Subclasses must implement :meth:`on_new_payload` and
    :meth:`build_items`. The rebuild / async / destroy hooks have safe
    defaults so a minimal subclass only wires the two abstract methods.
    """

    @abstractmethod
    def on_new_payload(self, payload: "PropertyPayload") -> bool:
        """Decide whether this widget shows for ``payload``.

        Called every time the selection changes. Returning ``True``
        makes the window call :meth:`build_items` to draw the section;
        returning ``False`` suppresses it. The payload may be empty
        (no selection) — most widgets return ``False`` in that case.
        """

    @abstractmethod
    def build_items(self) -> None:
        """Emit this widget's UI inside the current ovui build context.

        The host window opens an :class:`omni.ui.VStack` before calling
        :meth:`build_items`, so subclasses just need to drop their
        widgets directly into the ambient ``with`` scope.
        """

    def build_items_async(self) -> Optional[Iterator[Any]]:
        """Async variant of :meth:`build_items` — frame-driven generator.

        Default returns ``None`` — :class:`SimplePropertyWidget` falls
        back to the sync :meth:`build_items` / ``frame.rebuild()`` path.
        Subclasses that want to spread their build across multiple
        frames override this to return a generator; the
        :class:`SimplePropertyWidget` driver advances it one ``next()``
        per frame via chained :meth:`Application.call_later(0.0, ...)`
        calls, so each ``yield`` pauses the build for one frame.

        ovgear has no asyncio event loop today (see the property inspector implementation
        §7.5), so the return type is an :class:`Iterator` rather than
        an ``asyncio.Coroutine``. The driver calls ``.close()`` on the
        generator from :meth:`SimplePropertyWidget.destroy` so any
        ``finally`` cleanup in the body runs on widget teardown.
        """
        return None

    def request_rebuild(self) -> None:
        """Schedule a deferred rebuild of this widget.

        Default is a no-op. :class:`SimplePropertyWidget` (Step 6.3)
        will override this to queue a coroutine via
        ``run_coroutine(_delayed_rebuild())`` so the actual rebuild
        runs one frame after the triggering event, which is the
        standard Kit pattern for avoiding re-entrant UI updates inside
        USD notice handlers.
        """

    def destroy(self) -> None:
        """Release resources held by this widget.

        Default is a no-op. Subclasses that subscribe to models or
        stages must unsubscribe here; the host window calls
        :meth:`destroy` on every registered widget before it tears
        itself down.
        """
