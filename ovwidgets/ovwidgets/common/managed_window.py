# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Base class for all OvGear dockable panel windows.

See property inspector style behavior (Window Management and Docking).
"""

from typing import Any

import omni.ui as ui

# Managed windows use real ImGui dock tabs for their title/chrome. Keep this
# legacy constant at zero so older callers do not reserve a fake title row.
TAB_TITLE_RESERVE_PX = 0


class ManagedWindow:
    """
    Base class for all OvGear dockable windows.

    From property inspector style behavior: All panel windows (Stage Browser, Property Inspector, Viewport)
    inherit from ManagedWindow. Provides window lifecycle, visibility toggling,
    styling, and destruction.

    Subclasses override _build_ui() and optionally _get_module_styles().
    """

    def __init__(self, title: str, width: int = 400, height: int = 300, **window_kwargs: Any) -> None:
        # DockPreference.MAIN prevents ovui from calling SetNextWindowPos(center, Once)
        # which would set PosUndock=true and cause ImGui's BeginDocked() to undock the
        # window even when DockId is loaded from imgui.ini.
        self._window = ui.Window(
            title, dockPreference=ui.DockPreference.MAIN, width=width, height=height, **window_kwargs
        )
        # The dark-panel background is painted via an inner ``ui.Rectangle``
        # inside :meth:`_build_frame_wrapper` so it covers the docked panel
        # content area while the dock-node tab chrome stays hidden by layout.
        self._window.frame.set_build_fn(self._build_frame_wrapper)

    def _get_module_styles(self) -> dict:
        """Override to return module-specific style overrides applied on top of ui.style.default."""
        return {}

    def _build_frame_wrapper(self) -> None:
        """Build the window content with a painted dark-panel background."""
        from omni.ui import color as cl
        with ui.VStack(spacing=0):
            with ui.ZStack():
                ui.Rectangle(style={"background_color": cl.background_primary, "border_width": 0})
                self._build_ui()

    def _build_ui(self) -> None:
        """Override to build the window content."""
        ui.Label("(empty)", alignment=ui.Alignment.CENTER)

    def on_theme_changed(self) -> None:
        """Re-apply the panel background after a shade switch.

        After ``ui.set_shade()`` + ``apply_global_styles()``, triggering a
        frame rebuild re-runs :meth:`_build_frame_wrapper`, which resolves
        ``cl.background_primary`` against the new shade and re-paints the
        background rectangle.
        """
        if self._window is not None:
            self._window.frame.rebuild()

    @property
    def is_focused(self) -> bool:
        """``True`` when ImGui reports this window as focused.

        Used by :class:`~ovwidgets.app.application.Application` hotkey
        dispatchers to scope keys to the panel that owns focus — e.g.
        Del on the Layers window deletes selected prim specs (Step 50)
        rather than falling through to the Stage window's prim delete.
        Returns ``False`` after :meth:`destroy` releases ``_window``.
        """
        if self._window is None:
            return False
        return bool(self._window.focused)

    @property
    def visible(self) -> bool:
        return self._window.visible if self._window else False

    @visible.setter
    def visible(self, v: bool) -> None:
        if self._window:
            self._window.visible = v

    @property
    def title(self) -> str:
        return self._window.title if self._window else ""

    @property
    def window(self) -> "ui.Window":
        """Access the underlying ui.Window."""
        return self._window

    def destroy(self) -> None:
        """Destroy the window and release resources."""
        if self._window:
            self._window.destroy()
            self._window = None
