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

from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.common.selection import SelectionBus
from ovwidgets.stage.style import STAGE_STYLES
from ovwidgets.stage.widget.stage_widget import StageWidget


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
        # persisted imgui.ini layout; ovwidgets.app/layout.py + menu_bar.py key on it.
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
        """Replace the backing adapter. Safe to call before the widget is built."""
        self._adapter = adapter
        if self._widget is not None:
            self._widget.set_adapter(adapter)

    def begin_rename_selected(self) -> None:
        """Forward the F2 rename shortcut to the inner widget."""
        if self._widget is not None:
            self._widget.begin_rename_selected()

    def destroy(self) -> None:
        if self._widget is not None:
            self._widget.destroy()
            self._widget = None
        super().destroy()
