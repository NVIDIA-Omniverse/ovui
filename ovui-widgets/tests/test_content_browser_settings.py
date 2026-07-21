# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for content-browser :class:`Settings` persistence (Step 57).

Coverage:

* Setting keys — constants match the the content browser implementation step 57 spec.
* Construction defaults — with no stored values the widget lands on
  show_hidden=False, show_detail_pane=True, sort_policy=name_asc,
  splitter≈0.3, grid_view_scale=2, show_grid_view=True.
* Construction restoration — stored values override defaults on the
  detail model, tree-pane width, zoom bar, and detail-pane visibility.
* Round-trip persistence — toggling options / dragging the splitter /
  moving the zoom slider / swapping view mode writes to the injected
  :class:`Settings` store.
* Dir persistence — :class:`FileImporterHelper` /
  :class:`FileExporterHelper` both write their last-used directory to
  the right Settings key (verified against the live helpers so the
  tests are resilient to later helper refactors).

Tests use an injected :class:`Settings` store + a :class:`MockBackend`
so they don't depend on a live :class:`Application` singleton or on
the real filesystem.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.settings import Settings
from ovui_widgets.content.file_exporter import (
    LAST_SAVE_DIR_SETTING,
    FileExporterHelper,
)
from ovui_widgets.content.file_importer import (
    LAST_OPEN_DIR_SETTING,
    FileImporterHelper,
)
from ovui_widgets.content.widget import FileBrowserWidget
from ovui_widgets.content.widget.file_browser_model import (
    FileBrowserSortPolicy,
)
from ovui_widgets.content.widget.file_browser_widget import (
    SETTING_GRID_VIEW_SCALE,
    SETTING_SHOW_DETAIL_PANE,
    SETTING_SHOW_GRID_VIEW,
    SETTING_SHOW_HIDDEN,
    SETTING_SORT_POLICY,
    SETTING_SPLITTER,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window(
        "_test_content_browser_settings", width=800, height=400,
    )
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    """Enter ``window.frame`` as a build context and clear it on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


def _make_widget(
    window,
    settings: Settings,
) -> FileBrowserWidget:
    """Build a :class:`FileBrowserWidget` wired to ``settings``."""
    with in_window_frame(window):
        widget = FileBrowserWidget(
            MockBackend(), "mock://Home", settings=settings,
        )
    return widget


# ──────────────────────────────────────────────────────────────────────────────
# Setting-key constants
# ──────────────────────────────────────────────────────────────────────────────


class TestSettingKeys:
    def test_setting_keys_match_content_plan_step_57(self):
        assert SETTING_SHOW_GRID_VIEW == "ui.content.show_grid_view"
        assert SETTING_GRID_VIEW_SCALE == "ui.content.grid_view_scale"
        assert SETTING_SPLITTER == "ui.content.splitter"
        assert SETTING_SHOW_HIDDEN == "ui.content.show_hidden"
        assert SETTING_SORT_POLICY == "ui.content.sort_policy"
        assert SETTING_SHOW_DETAIL_PANE == "ui.content.show_detail_pane"

    def test_last_open_dir_setting_key(self):
        """Already wired by Step 53; kept here as a belt-and-braces guard."""
        assert LAST_OPEN_DIR_SETTING == "ui.content.last_open_dir"

    def test_last_save_dir_setting_key(self):
        """Already wired by Step 55; kept here as a belt-and-braces guard."""
        assert LAST_SAVE_DIR_SETTING == "ui.content.last_save_dir"


# ──────────────────────────────────────────────────────────────────────────────
# Defaults — no stored values
# ──────────────────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_default_show_hidden_false(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._show_hidden is False
            assert widget._detail_model._show_hidden is False
        finally:
            widget.destroy()

    def test_default_sort_policy_name_asc(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._sort_policy == FileBrowserSortPolicy.NAME_ASC
            assert (
                widget._detail_model.sort_policy
                == FileBrowserSortPolicy.NAME_ASC
            )
        finally:
            widget.destroy()

    def test_default_show_detail_pane_true(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._show_detail_pane is True
        finally:
            widget.destroy()

    def test_default_splitter_fraction_maps_to_240_pixels(
        self, ephemeral_window,
    ):
        """0.3 × 800 = 240 — matches the Step-13 pre-persistence default."""
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._tree_pane_width == 240
        finally:
            widget.destroy()

    def test_default_grid_view_scale_index_is_1(self, ephemeral_window):
        """Default 1 = smallest icons."""
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._grid_view_scale_index == 1
        finally:
            widget.destroy()

    def test_default_show_grid_view_true(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._is_grid_view is True
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Restoration — stored values on init
# ──────────────────────────────────────────────────────────────────────────────


class TestRestoration:
    def test_stored_show_hidden_applied_to_model(self, ephemeral_window):
        settings = Settings()
        settings.set(SETTING_SHOW_HIDDEN, True)
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._show_hidden is True
            assert widget._detail_model._show_hidden is True
        finally:
            widget.destroy()

    def test_stored_sort_policy_applied_to_model(self, ephemeral_window):
        settings = Settings()
        settings.set(SETTING_SORT_POLICY, FileBrowserSortPolicy.DATE_ASC)
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._sort_policy == FileBrowserSortPolicy.DATE_ASC
            assert (
                widget._detail_model.sort_policy
                == FileBrowserSortPolicy.DATE_ASC
            )
        finally:
            widget.destroy()

    def test_stored_splitter_fraction_applied_to_tree_pane_width(
        self, ephemeral_window,
    ):
        """0.5 × 800 = 400."""
        settings = Settings()
        settings.set(SETTING_SPLITTER, 0.5)
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._tree_pane_width == 400
        finally:
            widget.destroy()

    def test_hostile_splitter_value_falls_back_to_default(
        self, ephemeral_window,
    ):
        """Out-of-range values snap to the default fraction."""
        settings = Settings()
        settings.set(SETTING_SPLITTER, 1.5)  # out of range
        widget = _make_widget(ephemeral_window, settings)
        try:
            # Default 0.3 × 800 = 240.
            assert widget._tree_pane_width == 240
        finally:
            widget.destroy()

    def test_stored_show_detail_pane_false_hides_detail_frame(
        self, ephemeral_window,
    ):
        settings = Settings()
        settings.set(SETTING_SHOW_DETAIL_PANE, False)
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._show_detail_pane is False
            assert widget._detail_frame is not None
            assert widget._detail_frame.visible is False
            assert widget._splitter is not None
            assert widget._splitter.visible is False
        finally:
            widget.destroy()

    def test_stored_grid_view_scale_applied_to_zoom_bar(
        self, ephemeral_window,
    ):
        settings = Settings()
        settings.set(SETTING_GRID_VIEW_SCALE, 5)
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._zoom_bar is not None
            assert widget._zoom_bar.current_slider_index == 5
        finally:
            widget.destroy()

    def test_stored_grid_view_scale_invalid_falls_back_to_default(
        self, ephemeral_window,
    ):
        """Non-int / out-of-range snaps to 1."""
        settings = Settings()
        settings.set(SETTING_GRID_VIEW_SCALE, "not an int")
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._grid_view_scale_index == 1
        finally:
            widget.destroy()

    def test_stored_show_grid_view_false_applied_to_view_mode(
        self, ephemeral_window,
    ):
        """With scale_index=0 (list slot) the widget boots in list view."""
        settings = Settings()
        settings.set(SETTING_SHOW_GRID_VIEW, False)
        settings.set(SETTING_GRID_VIEW_SCALE, 0)
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._is_grid_view is False
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Round-trip persistence — widget changes → settings
# ──────────────────────────────────────────────────────────────────────────────


class TestPersistence:
    def test_show_hidden_toggle_persists(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            widget._on_show_hidden_changed(True)
            assert settings.get(SETTING_SHOW_HIDDEN) is True
            widget._on_show_hidden_changed(False)
            assert settings.get(SETTING_SHOW_HIDDEN) is False
        finally:
            widget.destroy()

    def test_sort_policy_change_persists(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            widget._on_sort_policy_changed(FileBrowserSortPolicy.SIZE_ASC)
            assert (
                settings.get(SETTING_SORT_POLICY)
                == FileBrowserSortPolicy.SIZE_ASC
            )
        finally:
            widget.destroy()

    def test_show_detail_pane_toggle_persists(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            widget._on_show_detail_pane_changed(False)
            assert settings.get(SETTING_SHOW_DETAIL_PANE) is False
            # And the detail frame is hidden.
            assert widget._detail_frame is not None
            assert widget._detail_frame.visible is False
            widget._on_show_detail_pane_changed(True)
            assert settings.get(SETTING_SHOW_DETAIL_PANE) is True
            assert widget._detail_frame.visible is True
        finally:
            widget.destroy()

    def test_splitter_drag_persists_fraction(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            # Drag +80 pixels on a 240-pixel start → 320 pixels → 0.4.
            widget._on_splitter_dragged(80.0)
            stored = settings.get(SETTING_SPLITTER)
            assert stored == pytest.approx(0.4, rel=1e-3)
        finally:
            widget.destroy()

    def test_splitter_respects_min_pane_width(self, ephemeral_window):
        """A drag that would collapse past the minimum clamps + persists."""
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            # Drag way negative — should clamp at 80 px (=0.1 fraction).
            widget._on_splitter_dragged(-500.0)
            stored = settings.get(SETTING_SPLITTER)
            assert stored == pytest.approx(0.1, rel=1e-3)
        finally:
            widget.destroy()

    def test_zoom_bar_scale_persists(self, ephemeral_window):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._zoom_bar is not None
            # User drags slider to index 5 (scale 2.0).
            widget._zoom_bar.set_slider_index(5)
            # The zoom-bar's on_scale callback fires
            # :meth:`_on_zoom_bar_scale` which writes the index back.
            assert settings.get(SETTING_GRID_VIEW_SCALE) == 5
        finally:
            widget.destroy()

    def test_view_mode_toggle_persists(self, ephemeral_window):
        """Snapping the slider below threshold persists show_grid_view=False."""
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._zoom_bar is not None
            # Drag to the list-mode slot (index 0 → scale 0.5 < 0.75).
            widget._zoom_bar.set_slider_index(0)
            assert settings.get(SETTING_SHOW_GRID_VIEW) is False
            # Snap back above threshold.
            widget._zoom_bar.set_slider_index(3)
            assert settings.get(SETTING_SHOW_GRID_VIEW) is True
        finally:
            widget.destroy()

    def test_settings_none_does_not_raise(self, ephemeral_window):
        """A widget built without a Settings still runs every handler."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home", settings=None,
            )
        try:
            # Each handler should fall through with a None settings ref.
            widget._on_show_hidden_changed(True)
            widget._on_sort_policy_changed(FileBrowserSortPolicy.SIZE_ASC)
            widget._on_show_detail_pane_changed(False)
            widget._on_splitter_dragged(40.0)
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileImporterHelper / FileExporterHelper dir persistence
# ──────────────────────────────────────────────────────────────────────────────


class TestImporterExporterDirPersistence:
    def test_file_importer_persists_last_open_dir(self):
        """After :meth:`_persist_last_open_dir`, Settings contains the dir."""
        settings = Settings()
        helper = FileImporterHelper(
            backend=MockBackend(), settings=settings,
        )
        helper._persist_last_open_dir("mock://Home/Documents/Projects")
        assert (
            settings.get(LAST_OPEN_DIR_SETTING)
            == "mock://Home/Documents/Projects"
        )

    def test_file_importer_empty_dirname_does_not_write(self):
        settings = Settings()
        helper = FileImporterHelper(
            backend=MockBackend(), settings=settings,
        )
        helper._persist_last_open_dir("")
        assert settings.get(LAST_OPEN_DIR_SETTING) is None

    def test_file_exporter_persists_last_save_dir(self):
        settings = Settings()
        helper = FileExporterHelper(
            backend=MockBackend(), settings=settings,
        )
        helper._persist_last_save_dir("mock://Home/Out")
        assert settings.get(LAST_SAVE_DIR_SETTING) == "mock://Home/Out"

    def test_file_exporter_empty_dirname_does_not_write(self):
        settings = Settings()
        helper = FileExporterHelper(
            backend=MockBackend(), settings=settings,
        )
        helper._persist_last_save_dir("")
        assert settings.get(LAST_SAVE_DIR_SETTING) is None

    def test_file_importer_start_url_prefers_stored_dir(self):
        """If no filename_url is passed, start URL comes from settings."""
        settings = Settings()
        settings.set(LAST_OPEN_DIR_SETTING, "mock://Home/Last/Session")
        helper = FileImporterHelper(
            backend=MockBackend(), settings=settings,
        )
        assert (
            helper._resolve_start_url(None)
            == "mock://Home/Last/Session"
        )

    def test_file_exporter_start_url_prefers_stored_dir(self):
        settings = Settings()
        settings.set(LAST_SAVE_DIR_SETTING, "mock://Home/Prev/Save")
        helper = FileExporterHelper(
            backend=MockBackend(), settings=settings,
        )
        assert (
            helper._resolve_start_url(None)
            == "mock://Home/Prev/Save"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Cross-cutting — settings persistence across simulated restart
# ──────────────────────────────────────────────────────────────────────────────


class TestSimulatedRestart:
    def test_toggle_then_restart_restores_state(self, ephemeral_window):
        """Toggle options, destroy widget, rebuild — state survives."""
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            widget._on_show_hidden_changed(True)
            widget._on_sort_policy_changed(
                FileBrowserSortPolicy.DATE_ASC,
            )
            widget._on_show_detail_pane_changed(False)
        finally:
            widget.destroy()

        # Settings survive the widget.
        assert settings.get(SETTING_SHOW_HIDDEN) is True
        assert (
            settings.get(SETTING_SORT_POLICY)
            == FileBrowserSortPolicy.DATE_ASC
        )
        assert settings.get(SETTING_SHOW_DETAIL_PANE) is False

        # Rebuild — the new widget should pick up the stored values.
        widget2 = _make_widget(ephemeral_window, settings)
        try:
            assert widget2._show_hidden is True
            assert widget2._sort_policy == FileBrowserSortPolicy.DATE_ASC
            assert widget2._show_detail_pane is False
            assert widget2._detail_frame is not None
            assert widget2._detail_frame.visible is False
        finally:
            widget2.destroy()

    def test_splitter_drag_then_restart_restores_width(
        self, ephemeral_window,
    ):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            # Drag splitter to ~400 px.
            widget._on_splitter_dragged(160.0)
            assert widget._tree_pane_width == 400
        finally:
            widget.destroy()

        widget2 = _make_widget(ephemeral_window, settings)
        try:
            # 400/800 = 0.5 round-trips back to 400.
            assert widget2._tree_pane_width == 400
        finally:
            widget2.destroy()

    def test_zoom_change_then_restart_restores_scale(
        self, ephemeral_window,
    ):
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            assert widget._zoom_bar is not None
            widget._zoom_bar.set_slider_index(4)  # scale 1.5
            assert settings.get(SETTING_GRID_VIEW_SCALE) == 4
        finally:
            widget.destroy()

        widget2 = _make_widget(ephemeral_window, settings)
        try:
            assert widget2._grid_view_scale_index == 4
            assert widget2._zoom_bar is not None
            assert widget2._zoom_bar.current_slider_index == 4
        finally:
            widget2.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Tolerant-reader contract: malformed settings fall through
# ──────────────────────────────────────────────────────────────────────────────


class TestTolerantReader:
    """Cover the internal ``_read_setting`` / ``_write_setting`` guards.

    The widget's full construction depends on a :class:`Settings`
    surface richer than what a raising / bare stub can supply — the
    :class:`NavigationModel`'s :class:`RecentFilesCollection` calls
    :meth:`Settings.subscribe` during init. So we swap the widget's
    ``_settings`` attribute after construction and exercise the
    tolerant helpers directly. Mirrors how the helpers run at
    widget-change time (options-menu toggle, splitter drag).
    """

    def test_settings_none_read_returns_default(self, ephemeral_window):
        widget = _make_widget(ephemeral_window, Settings())
        try:
            widget._settings = None
            assert widget._read_setting("any.key", "fallback") == "fallback"
        finally:
            widget.destroy()

    def test_missing_reader_method_falls_through(self, ephemeral_window):
        widget = _make_widget(ephemeral_window, Settings())
        try:
            class _BareSettings:
                pass

            widget._settings = _BareSettings()
            assert widget._read_setting("any.key", 42) == 42
        finally:
            widget.destroy()

    def test_raising_get_swallowed(self, ephemeral_window):
        widget = _make_widget(ephemeral_window, Settings())
        try:
            class _RaisingSettings:
                def get(self, key: str, default: Any) -> Any:
                    raise RuntimeError("simulated failure")

            widget._settings = _RaisingSettings()
            assert widget._read_setting("any.key", "fallback") == "fallback"
        finally:
            widget.destroy()

    def test_raising_set_swallowed(self, ephemeral_window):
        widget = _make_widget(ephemeral_window, Settings())
        try:
            class _RaisingSetSettings:
                def get(self, key: str, default: Any) -> Any:
                    return default

                def set(self, key: str, value: Any) -> None:
                    raise RuntimeError("simulated failure")

            widget._settings = _RaisingSetSettings()
            # _write_setting must swallow and not raise.
            widget._write_setting("any.key", "anything")
        finally:
            widget.destroy()

    def test_settings_none_write_is_noop(self, ephemeral_window):
        widget = _make_widget(ephemeral_window, Settings())
        try:
            widget._settings = None
            widget._write_setting("any.key", "anything")
        finally:
            widget.destroy()

    def test_suppress_persist_blocks_write(self, ephemeral_window):
        """Writes during :meth:`_apply_restored_view_state` are suppressed."""
        settings = Settings()
        widget = _make_widget(ephemeral_window, settings)
        try:
            # Start fresh: no value written.
            settings._data.pop("test.key", None)
            widget._suppress_persist = True
            widget._write_setting("test.key", "should_not_store")
            assert settings.get("test.key") is None
            widget._suppress_persist = False
        finally:
            widget.destroy()
