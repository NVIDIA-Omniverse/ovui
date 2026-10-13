# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Window-menu row oracle the wheel e2e tests click through.

The e2e golden test closes the Content browser with two real mouse clicks, so
it needs the row "Content Browser" is drawn on. Hard-coding that row does not
fail when the menu grows — it clicks whatever entry moved into its place. The
row now comes from the live menu, which these tests pin down on both sides:
the inspector reports the entries, and the driver turns a label into a row.

The fixtures below are deliberately synthetic. The oracle must hold for any
Window menu, so these tests name no real entry beyond the one the e2e flow
clicks.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ovui_widgets.app.inspector_state import _menu_item_labels


def _load_e2e_driver():
    path = Path(__file__).resolve().parent / "e2e" / "driver.py"
    spec = importlib.util.spec_from_file_location("ovui_e2e_driver_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# An entry that sits above "Content Browser" and pushes its row down.
ADDED_ENTRY = "Some Added Panel"

WINDOW_MENU = [
    "Stage Browser",
    "Property Inspector",
    "Viewport",
    ADDED_ENTRY,
    "Content Browser",
    "Layers",
    "Reset Layout",
]


class TestMenuItemLabels:
    def test_reports_entries_in_order_and_drops_separators(self, monkeypatch):
        ui = pytest.importorskip("omni.ui")
        menu = object()
        # ui.Separator is a text-less MenuItem; it draws no row of its own.
        children = [SimpleNamespace(text=label) for label in WINDOW_MENU]
        children.insert(6, SimpleNamespace(text=""))
        monkeypatch.setattr(
            ui,
            "Inspector",
            SimpleNamespace(get_children=lambda widget: children),
        )
        assert _menu_item_labels(menu) == WINDOW_MENU

    def test_unreadable_menu_reports_no_entries(self, monkeypatch):
        ui = pytest.importorskip("omni.ui")

        def _raise(widget):
            raise RuntimeError("no widget tree")

        monkeypatch.setattr(ui, "Inspector", SimpleNamespace(get_children=_raise))
        assert _menu_item_labels(object()) == []


class TestDriverMenuRow:
    def test_row_follows_the_live_menu(self):
        driver = _load_e2e_driver()
        menu = {"label": "Window", "items": WINDOW_MENU}
        assert driver.menu_row(menu, "Content Browser") == 4
        # Drop the entry above it and the same label is one row higher.
        menu_without = {"label": "Window", "items": [
            label for label in WINDOW_MENU if label != ADDED_ENTRY
        ]}
        assert driver.menu_row(menu_without, "Content Browser") == 3

    def test_missing_entry_fails_with_the_menu(self):
        driver = _load_e2e_driver()
        menu = {"label": "Window", "items": WINDOW_MENU}
        with pytest.raises(AssertionError, match=ADDED_ENTRY):
            driver.menu_row(menu, "Content Browsers")

    def test_unreported_menu_fails_instead_of_guessing_row_zero(self):
        driver = _load_e2e_driver()
        with pytest.raises(AssertionError, match="no entries"):
            driver.menu_row({"label": "Window", "items": []}, "Content Browser")
