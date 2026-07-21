# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Dockable window shell hosting :class:`StageWidget` (widget-window split).

The window owns docking, title, module styles, and lifecycle; the widget
owns tree model, delegate, filter, and rename. See the stage hierarchy behavior
for the widget/window split rationale.
"""

from typing import Any, Optional

import omni.ui as ui

from ovui_widgets.common.managed_window import ManagedWindow
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.stage.style import STAGE_STYLES
from ovui_widgets.stage.widget.stage_widget import StageWidget


class StageWindow(ManagedWindow):
    """Dockable window hosting a :class:`StageWidget`.

    ``adapter`` and ``selection_bus`` are late-bound: the widget is not
    built until :meth:`_build_ui` fires on the first rendered frame, so
    :meth:`set_adapter` called before that stores the adapter and applies
    it when the widget is constructed.
    """

    def __init__(
        self,
        adapter: Any = None,
        selection_bus: Optional[SelectionBus] = None,
    ) -> None:
        self._adapter = adapter
        self._selection_bus = selection_bus
        self._widget: Optional[StageWidget] = None
        # Title is "Stage Browser" to preserve the dock CRC32 used by the
        # persisted imgui.ini layout; ovui_widgets.app/layout.py + menu_bar.py key on it.
        # NO_SCROLLBAR suppresses the parent ui.Window's built-in scrollbar;
        # the inner ui.ScrollingFrame in StageWidget owns all tree scrolling.
        super().__init__(
            "Stage Browser",
            width=320,
            height=600,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR,
        )

    def _get_module_styles(self) -> dict:
        return STAGE_STYLES

    def _build_ui(self) -> None:
        self._widget = StageWidget(
            adapter=self._adapter,
            selection_bus=self._selection_bus,
        )

    def set_adapter(self, adapter: Any) -> None:
        """Replace the backing adapter. Safe to call before the widget is built.

        Atomic across the wrapper: on a transactional widget failure the
        window keeps the old adapter; on a completed-swap throwable the
        window follows the widget to the new document before re-raising.
        """
        pending_throwable = None
        if self._widget is not None:
            try:
                self._widget.set_adapter(adapter)
            except BaseException as exc:
                if getattr(self._widget, "_adapter", None) is not adapter:
                    raise
                pending_throwable = exc
        self._adapter = adapter
        if pending_throwable is not None:
            raise pending_throwable

    def detach_document(self) -> None:
        """Converge to the explicit no-document state (widget included).

        Safe to call before the widget is built; afterwards the inner
        widget revokes its subscriptions and resolves no stale row.
        """
        self._adapter = None
        if self._widget is not None:
            self._widget.detach_document()

    def begin_rename_selected(self) -> None:
        """Forward the F2 rename shortcut to the inner widget."""
        if self._widget is not None:
            self._widget.begin_rename_selected()

    def is_filter_editing(self) -> bool:
        """Forward the filter-edit ownership query to the inner widget.

        Returns ``False`` before the widget is built or after :meth:`destroy`.
        """
        if self._widget is not None:
            return self._widget.is_filter_editing()
        return False

    def destroy(self) -> None:
        if self._widget is not None:
            self._widget.destroy()
            self._widget = None
        super().destroy()
