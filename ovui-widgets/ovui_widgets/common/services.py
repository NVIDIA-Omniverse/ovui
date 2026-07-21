# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""WidgetServices protocol — three-member dependency surface for widgets.

Widget packages that previously took an ``app: Application`` parameter
take ``services: WidgetServices`` instead. The Protocol is intentionally
narrow -- exactly three members:

* :attr:`selection_bus` -- the live :class:`~ovui_widgets.common.selection.SelectionBus`
  the widget publishes / subscribes through.
* :attr:`undo_manager` -- the active :class:`~ovui_widgets.common.undo.UndoManager`
  the widget pushes commands into.
* :meth:`call_later` -- the deferred-callback scheduler the widget uses
  to defer work to the next frame (debounced filter rebuilds, deferred
  selection rebuilds, etc.). Returns a
  :class:`~ovui_widgets.common.scheduler.CallbackHandle` whose
  ``cancel()`` is called when the widget needs to drop a pending
  scheduled callback.

``open_file`` is **deliberately not** on this Protocol. The two seams
that need an open-file callback (``ContentBrowserWindow`` and
``FileBrowserWidget``) take an explicit
``open_file_fn: Optional[Callable[[str], None]] = None`` keyword
parameter. Keeping ``open_file`` off the universal service surface
preserves a clean separation between the runtime services every widget
needs and the per-widget integration hooks that only some widgets need.

The Protocol is decorated with :func:`typing.runtime_checkable` so
``isinstance(some_obj, WidgetServices)`` works at runtime -- useful
for both ``isinstance(...)`` test assertions and for the explicit
fixture in :mod:`tests.conftest` to assert protocol conformance
without a structural-typing static analysis pass.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ovui_widgets.common.scheduler import CallbackHandle
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.undo import UndoManager


@runtime_checkable
class WidgetServices(Protocol):
    """Three-member service surface widgets read from.

    See module docstring for the design rationale (no ``open_file``).
    """

    @property
    def selection_bus(self) -> SelectionBus: ...

    @property
    def undo_manager(self) -> UndoManager: ...

    def call_later(
        self,
        delay_secs: float,
        callback: Callable,
    ) -> CallbackHandle: ...
