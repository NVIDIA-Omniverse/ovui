# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Useful runtime information for Help > About USD Viewer."""

from __future__ import annotations

import os
import platform
from importlib import metadata
from typing import Any, Iterable, Optional

import omni.ui as ui
from ovui_data_adapters.common.ovrtx_import import OVRTX_ROOT_ENV, ovrtx_root_version


_COMPONENT_DISTRIBUTIONS = (
    ("USD Viewer", "ovui-widgets-app"),
    ("ovui", "ovui"),
    ("ovui-widgets", "ovui-widgets-app"),
    ("ovui-data-adapters", "ovui-data-adapters-common"),
    ("ovrtx", "ovrtx"),
    ("ovstage", "ovstage"),
)


def installed_component_versions(
    runtime_component_versions: Iterable[tuple[str, str]] = (),
) -> tuple[tuple[str, str], ...]:
    """Return truthful installed versions without importing native runtimes."""
    runtime_versions = dict(runtime_component_versions)
    rows = []
    for label, distribution in _COMPONENT_DISTRIBUTIONS:
        # The active adapter reports the ovrtx and ovstage it loaded.
        version = runtime_versions.get(label, "")
        if not version and distribution == "ovrtx" and os.environ.get(OVRTX_ROOT_ENV, "").strip():
            version = ovrtx_root_version()
        elif not version:
            try:
                version = metadata.version(distribution)
            except Exception:
                version = ""
        rows.append((label, version or "Unavailable"))
    openusd = runtime_versions.get("OpenUSD") or "Unavailable"
    rows.extend((
        ("OpenUSD", openusd),
        ("Python", platform.python_version()),
    ))
    return tuple(rows)


class AboutDialog:
    """Small, app-owned, dismissible About window."""

    def __init__(self) -> None:
        self._window: Optional[Any] = None

    def show(
        self,
        runtime_component_versions: Iterable[tuple[str, str]] = (),
    ) -> None:
        if self._window is not None:
            self._window.visible = True
            return
        self._window = ui.Window(
            "About USD Viewer",
            width=500,
            height=450,
            flags=ui.WINDOW_FLAGS_MODAL,
            style_type_name_override="Dialog",
        )
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                with ui.HStack():
                    ui.Spacer(width=16)
                    with ui.VStack(spacing=8):
                        ui.Label(
                            "USD Viewer",
                            height=30,
                            style_type_name_override="Dialog.SectionTitle",
                        )
                        ui.Label(
                            "Standalone OpenUSD scene inspection and rendering",
                            height=22,
                        )
                        ui.Separator(height=2)
                        for label, version in installed_component_versions(
                            runtime_component_versions
                        ):
                            with ui.HStack(height=24):
                                ui.Label(label, width=190)
                                ui.Label(version)
                        ui.Spacer()
                        with ui.HStack(height=30):
                            ui.Spacer()
                            ui.Button("Close", width=100, clicked_fn=self.close)
                            ui.Spacer()
                        ui.Spacer(height=8)
                    ui.Spacer(width=16)

    def close(self) -> None:
        if self._window is not None:
            self._window.visible = False

    def destroy(self) -> None:
        window = self._window
        self._window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass


__all__ = ["AboutDialog", "installed_component_versions"]
