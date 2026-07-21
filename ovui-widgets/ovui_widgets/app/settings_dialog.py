# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Settings dialog for OvGear (settings-dialog step).

Modal window with snap and theme controls wired through Application.settings.
Changes take effect immediately — no OK/Apply needed.
"""

from typing import TYPE_CHECKING, Any, Optional

import omni.ui as ui

if TYPE_CHECKING:
    from ovui_widgets.app.application import Application


class SettingsDialog:
    """Modal Settings dialog with snap and theme controls."""

    def __init__(self, app: "Application") -> None:
        self._app = app
        self._window: Optional[Any] = None
        self._snap_checkbox: Optional[Any] = None
        self._grid_size_drag: Optional[Any] = None
        self._close_button: Optional[Any] = None

    def destroy(self) -> None:
        """Tear down the modal Settings window if present.

        Idempotent — safe to call from :meth:`Application.shutdown`
        regardless of whether :meth:`show` was ever invoked. Issue
        #35 Step 4b.
        """
        window = self._window
        self._window = None
        self._snap_checkbox = None
        self._grid_size_drag = None
        self._close_button = None
        if window is None:
            return
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            # ovui may raise if the window was already torn down — the
            # attribute null above already dropped our reference.
            pass

    def show(self) -> None:
        """Create (or reveal) the modal Settings window with current settings values."""
        if self._window is not None and self._window.visible:
            return

        self._window = ui.Window(
            "Settings",
            width=400,
            height=300,
            flags=ui.WINDOW_FLAGS_MODAL,
            style_type_name_override="Dialog",
        )
        with self._window.frame:
            with ui.VStack(spacing=8):
                with ui.HStack():
                    ui.Spacer(width=8)
                    with ui.VStack(spacing=8):
                        ui.Spacer(height=4)
                        ui.Label(
                            "Snap",
                            style_type_name_override="Dialog.SectionTitle",
                            height=20,
                        )

                        with ui.HStack(height=24):
                            ui.Label("Enable snap", width=120)
                            self._snap_checkbox = ui.CheckBox()
                            self._snap_checkbox.model.set_value(
                                bool(self._app.settings.get("snap.enabled", False))
                            )
                            self._snap_checkbox.model.add_value_changed_fn(
                                lambda m: self._app.settings.set(
                                    "snap.enabled", m.get_value_as_bool()
                                )
                            )

                        with ui.HStack(height=24):
                            ui.Label("Grid size", width=120)
                            self._grid_size_drag = ui.FloatDrag(min=0.001, max=100.0)
                            self._grid_size_drag.model.set_value(
                                float(self._app.settings.get("snap.grid_size", 1.0))
                            )
                            self._grid_size_drag.model.add_end_edit_fn(
                                lambda m: self._app.settings.set(
                                    "snap.grid_size", m.get_value_as_float()
                                )
                            )

                        ui.Separator(height=2)
                        ui.Label(
                            "Appearance",
                            style_type_name_override="Dialog.SectionTitle",
                            height=20,
                        )

                        with ui.HStack(height=24):
                            ui.Label("Theme", width=120)
                            combo = ui.ComboBox(
                                0 if self._app.settings.get("ui.theme", "dark") == "dark"
                                else 1,
                                "Dark",
                                "Light",
                            )
                            combo.model.add_item_changed_fn(
                                lambda m, _: self._app.settings.set(
                                    "ui.theme",
                                    "dark"
                                    if m.get_item_value_model().get_value_as_int() == 0
                                    else "light",
                                )
                            )

                        ui.Spacer()
                        with ui.HStack(height=28):
                            ui.Spacer()
                            self._close_button = ui.Button(
                                "Close",
                                width=100,
                                clicked_fn=self._close,
                            )
                            ui.Spacer()
                        ui.Spacer(height=8)
                    ui.Spacer(width=8)

    def _close(self) -> None:
        """Hide the dialog without destroying it."""
        if self._window is not None:
            self._window.visible = False
