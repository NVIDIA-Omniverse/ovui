# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 53 — :class:`FileImporterHelper`.

Coverage:

* Public surface — re-export from ``ovui_widgets.content``, module
  constants, default file-extension list.
* Singleton lifecycle — :meth:`instance` returns the same object across
  calls; :meth:`reset_singleton` clears it.
* Construction — backend / settings overrides; default backend is
  :class:`LocalFSBackend`.
* :meth:`show` — builds the dialog with the helper's configuration,
  destroys + rebuilds on re-show, honours the extension-types default.
* Starting directory — filename_url's parent wins; Settings fallback
  wins next; home-directory fallback wins last.
* Initial filename — extracted from ``filename_url`` when given.
* Apply payload — import_handler fires with ``(filename, dirname,
  selections)``; ``last_open_dir`` persisted to Settings; dialog hides.
* Cancel / ESC — dialog hides, no handler fired.
* Validation — ``should_validate=True`` routes through the dialog's
  open-mode validator (rejects missing files).
* Defensive — import_handler raising does not crash; missing handler is
  a no-op; show-after-destroy rebuilds.

Tests mirror ``tests/test_file_picker_dialog.py``'s fixture shape — a
module-scoped ``ephemeral_window`` keeps an ovui window registry live so
each dialog's ``ui.Window`` spawn does not race teardown.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import List, Tuple

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.settings import Settings
from ovui_widgets.content import FileImporterHelper as _FileImporterHelper
from ovui_widgets.content.backends.local_fs_backend import (
    LocalFSBackend,
    _url_to_fspath,
)
from ovui_widgets.content.file_importer import (
    DEFAULT_FILE_EXTENSION_TYPES,
    LAST_OPEN_DIR_SETTING,
    FileImporterHelper,
)
from ovui_widgets.content.file_picker_dialog import FilePickerDialog

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Module-scoped ovui window — keeps the registry live across tests."""
    win = ui.Window("_test_file_importer", width=400, height=200)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Clear the cached singleton between tests."""
    FileImporterHelper.reset_singleton()
    yield
    FileImporterHelper.reset_singleton()


@pytest.fixture
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def helper(backend: MockBackend, settings: Settings) -> FileImporterHelper:
    """A helper with injected backend + settings (no Application dependency)."""
    return FileImporterHelper(backend=backend, settings=settings)


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestFileImporterHelperSurface:
    def test_reexported_from_content_browser_package(self):
        assert FileImporterHelper is _FileImporterHelper

    def test_last_open_dir_setting_key(self):
        """Matches architecture §36.3 flat content layout."""
        assert LAST_OPEN_DIR_SETTING == "ui.content.last_open_dir"

    def test_default_extension_types_are_usd_first(self):
        """USD files first, catch-all second — architecture §22.1."""
        assert DEFAULT_FILE_EXTENSION_TYPES[0] == (
            "*.usd, *.usda, *.usdc, *.usdz", "USD Files",
        )
        assert DEFAULT_FILE_EXTENSION_TYPES[-1] == ("*.*", "All files")


# ──────────────────────────────────────────────────────────────────────────────
# Singleton lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_instance_returns_same_object(self):
        first = FileImporterHelper.instance()
        second = FileImporterHelper.instance()
        assert first is second

    def test_reset_singleton_clears_cache(self):
        first = FileImporterHelper.instance()
        FileImporterHelper.reset_singleton()
        second = FileImporterHelper.instance()
        assert first is not second

    def test_reset_singleton_when_none_is_safe(self):
        FileImporterHelper.reset_singleton()
        FileImporterHelper.reset_singleton()  # double reset — no raise

    def test_reset_singleton_destroys_live_dialog(
        self, ephemeral_window,
    ):
        helper = FileImporterHelper.instance()
        helper._backend = MockBackend()
        helper._settings_override = Settings()
        with in_window_frame(ephemeral_window):
            helper.show(import_handler=lambda f, d, s: None)
        assert helper.dialog is not None
        FileImporterHelper.reset_singleton()
        assert FileImporterHelper._singleton is None


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_backend_is_local_fs(self):
        helper = FileImporterHelper()
        assert isinstance(helper.backend, LocalFSBackend)

    def test_custom_backend_stored(self, backend: MockBackend):
        helper = FileImporterHelper(backend=backend)
        assert helper.backend is backend

    def test_default_has_no_live_dialog(self, helper):
        assert helper.dialog is None

    def test_settings_override_stored(
        self, backend: MockBackend, settings: Settings,
    ):
        helper = FileImporterHelper(backend=backend, settings=settings)
        assert helper._get_settings() is settings


# ──────────────────────────────────────────────────────────────────────────────
# show() — builds the dialog
# ──────────────────────────────────────────────────────────────────────────────


class TestShow:
    def test_show_builds_file_picker_dialog(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert helper.dialog is not None
            assert isinstance(helper.dialog, FilePickerDialog)
            assert helper.dialog.is_open is True
        finally:
            helper.destroy()

    def test_show_passes_title_and_apply_label(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    title="Open USD File",
                    import_button_label="Open",
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog._title == "Open USD File"
            assert helper.dialog._apply_label == "Open"
        finally:
            helper.destroy()

    def test_show_uses_default_extensions_when_none(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert (
                helper.dialog._file_extension_types
                == DEFAULT_FILE_EXTENSION_TYPES
            )
        finally:
            helper.destroy()

    def test_show_forwards_caller_extensions(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        custom = [("*.png", "PNG"), ("*.*", "All files")]
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    file_extension_types=custom,
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog._file_extension_types == custom
        finally:
            helper.destroy()

    def test_show_wires_validation_open_mode(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    should_validate=True,
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog._should_validate is True
            assert helper.dialog._validation_mode == "open"
        finally:
            helper.destroy()

    def test_show_allows_multi_files_selection(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    allow_multi_files_selection=True,
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog._allow_multi_selection is True
        finally:
            helper.destroy()

    def test_show_twice_destroys_previous_dialog(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        """Each :meth:`show` lands with a fresh dialog — no stale reuse."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    title="Open",
                    import_handler=lambda f, d, s: None,
                )
            first = helper.dialog
            with in_window_frame(ephemeral_window):
                helper.show(
                    title="Import USD",
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog is not first
            assert helper.dialog._title == "Import USD"
        finally:
            helper.destroy()

    def test_show_passes_backend_to_dialog(
        self, helper: FileImporterHelper, ephemeral_window, backend,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert helper.dialog._backend is backend
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Starting directory resolution
# ──────────────────────────────────────────────────────────────────────────────


class TestStartUrlResolution:
    def test_filename_url_parent_wins(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url="mock://Home/Documents/Projects/demo.usda",
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog._start_url == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_filename_url_seeds_initial_filename(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        """Basename from ``filename_url`` pre-fills the FileBar."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url="mock://Home/Documents/Projects/demo.usda",
                    import_handler=lambda f, d, s: None,
                )
            assert helper.dialog.get_filename() == "demo.usda"
        finally:
            helper.destroy()

    def test_settings_fallback_used_when_no_filename_url(
        self, helper: FileImporterHelper, ephemeral_window,
        settings: Settings,
    ):
        settings.set(LAST_OPEN_DIR_SETTING, "mock://Home/Textures")
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert helper.dialog._start_url == "mock://Home/Textures"
        finally:
            helper.destroy()

    def test_filename_url_beats_settings_fallback(
        self, helper: FileImporterHelper, ephemeral_window,
        settings: Settings,
    ):
        settings.set(LAST_OPEN_DIR_SETTING, "mock://Home/Textures")
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url="mock://Home/Documents/Projects/demo.usda",
                    import_handler=lambda f, d, s: None,
                )
            # filename_url's parent wins over the Settings fallback.
            assert helper.dialog._start_url == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_home_fallback_when_no_filename_and_no_setting(
        self, ephemeral_window,
    ):
        """No filename_url + empty Settings → home dir via LocalFSBackend."""
        helper = FileImporterHelper(settings=Settings())
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert helper.dialog._start_url.startswith("file://")
            home_path = os.path.expanduser("~")
            assert Path(_url_to_fspath(helper.dialog._start_url)) == Path(home_path)
        finally:
            helper.destroy()

    def test_initial_filename_empty_when_no_filename_url(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert helper.dialog.get_filename() == ""
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# import_handler dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestImportHandler:
    def test_apply_fires_import_handler_with_three_args(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        calls: List[Tuple[str, str, List[str]]] = []

        def _handler(filename, dirname, selections):
            calls.append((filename, dirname, selections))

        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=_handler,
                )
            # Filename is pre-seeded from filename_url → Apply is valid.
            helper.dialog._fire_apply_for_test()
            assert len(calls) == 1
            filename, dirname, selections = calls[0]
            assert filename == "demo.usda"
            assert dirname == "mock://Home/Documents/Projects"
            assert isinstance(selections, list)
        finally:
            helper.destroy()

    def test_apply_persists_last_open_dir(
        self, helper: FileImporterHelper, ephemeral_window,
        settings: Settings,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=lambda f, d, s: None,
                )
            helper.dialog._fire_apply_for_test()
            assert settings.get(LAST_OPEN_DIR_SETTING) == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_apply_hides_dialog(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=lambda f, d, s: None,
                )
            helper.dialog._fire_apply_for_test()
            assert helper.dialog.is_open is False
        finally:
            helper.destroy()

    def test_apply_with_no_import_handler_is_safe(
        self, helper: FileImporterHelper, ephemeral_window,
        settings: Settings,
    ):
        """Missing ``import_handler`` still persists + hides."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=None,
                )
            helper.dialog._fire_apply_for_test()
            assert helper.dialog.is_open is False
            assert settings.get(LAST_OPEN_DIR_SETTING) == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_apply_raising_handler_does_not_crash(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        def _handler(filename, dirname, selections):
            raise RuntimeError("boom")

        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=_handler,
                )
            helper.dialog._fire_apply_for_test()  # no raise
        finally:
            helper.destroy()

    def test_cancel_does_not_fire_import_handler(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=lambda f, d, s: calls.append(1),
                )
            helper.dialog._fire_cancel_for_test()
            assert calls == []
            assert helper.dialog.is_open is False
        finally:
            helper.destroy()

    def test_escape_does_not_fire_import_handler(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        from ovui_widgets.content.file_picker_dialog import _KEY_ESCAPE
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    import_handler=lambda f, d, s: calls.append(1),
                )
            helper.dialog._fire_key_for_test(_KEY_ESCAPE)
            assert calls == []
            assert helper.dialog.is_open is False
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Validation pass-through
# ──────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_validation_rejects_missing_file(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        """``should_validate=True`` + missing file → handler not fired."""
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    import_handler=lambda f, d, s: calls.append(1),
                    should_validate=True,
                )
            # Type a filename that does not exist under the start URL.
            helper.dialog.navigate_to("mock://Home/Documents/Projects")
            helper.dialog.set_filename("nonexistent.usd")
            helper.dialog._fire_apply_for_test()
            assert calls == []
            # Dialog stays open so the user can correct their input.
            assert helper.dialog.is_open is True
        finally:
            helper.destroy()

    def test_validation_passes_for_existing_file(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    import_handler=lambda f, d, s: calls.append(
                        (f, d, s),
                    ),
                    should_validate=True,
                )
            helper.dialog.navigate_to("mock://Home/Documents/Projects")
            helper.dialog.set_filename("demo.usda")
            helper.dialog._fire_apply_for_test()
            assert len(calls) == 1
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# destroy()
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_dialog_reference(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            helper.show(import_handler=lambda f, d, s: None)
        assert helper.dialog is not None
        helper.destroy()
        assert helper.dialog is None

    def test_destroy_without_show_is_safe(
        self, helper: FileImporterHelper,
    ):
        helper.destroy()  # no raise

    def test_show_after_destroy_rebuilds(
        self, helper: FileImporterHelper, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            helper.show(import_handler=lambda f, d, s: None)
        helper.destroy()
        try:
            with in_window_frame(ephemeral_window):
                helper.show(import_handler=lambda f, d, s: None)
            assert helper.dialog is not None
            assert helper.dialog.is_open is True
        finally:
            helper.destroy()
