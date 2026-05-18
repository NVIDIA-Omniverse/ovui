# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 55 — :class:`FileExporterHelper`.

Coverage:

* Public surface — re-export from ``ovwidgets.content``, module
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
* Apply payload — export_handler fires with ``(filename, dirname,
  extension, selections)``; ``last_save_dir`` persisted to Settings;
  dialog hides.
* Extension resolution — ``.usd`` / ``.usda`` / ``.usdc`` picked from
  the combo selection; missing bar returns ``""``.
* Validation — ``validation_mode`` is ``"save"`` so empty filename is
  the rejection criterion (not stat).
* Defensive — export_handler raising does not crash; missing handler is
  a no-op; show-after-destroy rebuilds.

Tests mirror ``tests/test_file_importer.py``'s fixture shape — a
module-scoped ``ephemeral_window`` keeps an ovui window registry live so
each dialog's ``ui.Window`` spawn does not race teardown.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import List, Tuple

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.settings import Settings
from ovwidgets.content import FileExporterHelper as _FileExporterHelper
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend
from ovwidgets.content.file_exporter import (
    DEFAULT_FILE_EXTENSION_TYPES,
    LAST_SAVE_DIR_SETTING,
    FileExporterHelper,
)
from ovwidgets.content.file_picker_dialog import FilePickerDialog

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Module-scoped ovui window — keeps the registry live across tests."""
    win = ui.Window("_test_file_exporter", width=400, height=200)
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
    FileExporterHelper.reset_singleton()
    yield
    FileExporterHelper.reset_singleton()


@pytest.fixture
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def helper(backend: MockBackend, settings: Settings) -> FileExporterHelper:
    """A helper with injected backend + settings (no Application dependency)."""
    return FileExporterHelper(backend=backend, settings=settings)


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestFileExporterHelperSurface:
    def test_reexported_from_content_browser_package(self):
        assert FileExporterHelper is _FileExporterHelper

    def test_last_save_dir_setting_key(self):
        """Matches architecture §36.3 flat content layout."""
        assert LAST_SAVE_DIR_SETTING == "ui.content.last_save_dir"

    def test_default_extension_types_match_architecture(self):
        """Three-entry list per architecture §22.4."""
        assert DEFAULT_FILE_EXTENSION_TYPES == [
            ("*.usd", "USD Binary or Ascii"),
            ("*.usda", "USD Ascii"),
            ("*.usdc", "USD Crate"),
        ]


# ──────────────────────────────────────────────────────────────────────────────
# Singleton lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_instance_returns_same_object(self):
        first = FileExporterHelper.instance()
        second = FileExporterHelper.instance()
        assert first is second

    def test_reset_singleton_clears_cache(self):
        first = FileExporterHelper.instance()
        FileExporterHelper.reset_singleton()
        second = FileExporterHelper.instance()
        assert first is not second

    def test_reset_singleton_when_none_is_safe(self):
        FileExporterHelper.reset_singleton()
        FileExporterHelper.reset_singleton()  # double reset — no raise

    def test_reset_singleton_destroys_live_dialog(
        self, ephemeral_window,
    ):
        helper = FileExporterHelper.instance()
        helper._backend = MockBackend()
        helper._settings_override = Settings()
        with in_window_frame(ephemeral_window):
            helper.show(export_handler=lambda f, d, e, s: None)
        assert helper.dialog is not None
        FileExporterHelper.reset_singleton()
        assert FileExporterHelper._singleton is None


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_backend_is_local_fs(self):
        helper = FileExporterHelper()
        assert isinstance(helper.backend, LocalFSBackend)

    def test_custom_backend_stored(self, backend: MockBackend):
        helper = FileExporterHelper(backend=backend)
        assert helper.backend is backend

    def test_default_has_no_live_dialog(self, helper):
        assert helper.dialog is None

    def test_settings_override_stored(
        self, backend: MockBackend, settings: Settings,
    ):
        helper = FileExporterHelper(backend=backend, settings=settings)
        assert helper._get_settings() is settings


# ──────────────────────────────────────────────────────────────────────────────
# show() — builds the dialog
# ──────────────────────────────────────────────────────────────────────────────


class TestShow:
    def test_show_builds_file_picker_dialog(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog is not None
            assert isinstance(helper.dialog, FilePickerDialog)
            assert helper.dialog.is_open is True
        finally:
            helper.destroy()

    def test_show_passes_title_and_apply_label(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    title="Save Stage As",
                    export_button_label="Save",
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog._title == "Save Stage As"
            assert helper.dialog._apply_label == "Save"
        finally:
            helper.destroy()

    def test_show_uses_default_extensions_when_none(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert (
                helper.dialog._file_extension_types
                == DEFAULT_FILE_EXTENSION_TYPES
            )
        finally:
            helper.destroy()

    def test_show_forwards_caller_extensions(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        custom = [("*.abc", "ABC format")]
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    file_extension_types=custom,
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog._file_extension_types == custom
        finally:
            helper.destroy()

    def test_show_wires_validation_save_mode(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Exporter always uses the save-mode validator (empty-filename check)."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    should_validate=True,
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog._should_validate is True
            assert helper.dialog._validation_mode == "save"
        finally:
            helper.destroy()

    def test_show_honours_should_validate_false(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    should_validate=False,
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog._should_validate is False
        finally:
            helper.destroy()

    def test_show_twice_destroys_previous_dialog(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Each :meth:`show` lands with a fresh dialog — no stale reuse."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    title="Save",
                    export_handler=lambda f, d, e, s: None,
                )
            first = helper.dialog
            with in_window_frame(ephemeral_window):
                helper.show(
                    title="Export",
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog is not first
            assert helper.dialog._title == "Export"
        finally:
            helper.destroy()

    def test_show_passes_backend_to_dialog(
        self, helper: FileExporterHelper, ephemeral_window, backend,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog._backend is backend
        finally:
            helper.destroy()

    def test_show_does_not_allow_multi_selection(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Save As always targets a single destination."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog._allow_multi_selection is False
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Starting directory resolution
# ──────────────────────────────────────────────────────────────────────────────


class TestStartUrlResolution:
    def test_filename_url_parent_wins(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url="mock://Home/Documents/Projects/demo.usda",
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog._start_url == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_filename_url_seeds_initial_filename(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Basename from ``filename_url`` pre-fills the FileBar."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url="mock://Home/Documents/Projects/demo.usda",
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog.get_filename() == "demo.usda"
        finally:
            helper.destroy()

    def test_settings_fallback_used_when_no_filename_url(
        self, helper: FileExporterHelper, ephemeral_window,
        settings: Settings,
    ):
        settings.set(LAST_SAVE_DIR_SETTING, "mock://Home/Textures")
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog._start_url == "mock://Home/Textures"
        finally:
            helper.destroy()

    def test_filename_url_beats_settings_fallback(
        self, helper: FileExporterHelper, ephemeral_window,
        settings: Settings,
    ):
        settings.set(LAST_SAVE_DIR_SETTING, "mock://Home/Textures")
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url="mock://Home/Documents/Projects/demo.usda",
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper.dialog._start_url == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_home_fallback_when_no_filename_and_no_setting(
        self, ephemeral_window,
    ):
        """No filename_url + empty Settings → home dir via LocalFSBackend."""
        helper = FileExporterHelper(settings=Settings())
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog._start_url.startswith("file://")
            home_path = os.path.expanduser("~")
            assert home_path in helper.dialog._start_url
        finally:
            helper.destroy()

    def test_initial_filename_empty_when_no_filename_url(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog.get_filename() == ""
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# export_handler dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestExportHandler:
    def test_apply_fires_export_handler_with_four_args(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        calls: List[Tuple[str, str, str, List[str]]] = []

        def _handler(filename, dirname, extension, selections):
            calls.append((filename, dirname, extension, selections))

        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=_handler,
                )
            # Filename is pre-seeded from filename_url → Apply is valid
            # (save-mode validation passes on non-empty filenames).
            helper.dialog._fire_apply_for_test()
            assert len(calls) == 1
            filename, dirname, extension, selections = calls[0]
            assert filename == "demo.usda"
            assert dirname == "mock://Home/Documents/Projects"
            # First default extension is ``("*.usd", ...)`` → ``.usd``.
            assert extension == ".usd"
            assert isinstance(selections, list)
        finally:
            helper.destroy()

    def test_apply_persists_last_save_dir(
        self, helper: FileExporterHelper, ephemeral_window,
        settings: Settings,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=lambda f, d, e, s: None,
                )
            helper.dialog._fire_apply_for_test()
            assert settings.get(LAST_SAVE_DIR_SETTING) == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_apply_hides_dialog(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=lambda f, d, e, s: None,
                )
            helper.dialog._fire_apply_for_test()
            assert helper.dialog.is_open is False
        finally:
            helper.destroy()

    def test_apply_with_no_export_handler_is_safe(
        self, helper: FileExporterHelper, ephemeral_window,
        settings: Settings,
    ):
        """Missing ``export_handler`` still persists + hides."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=None,
                )
            helper.dialog._fire_apply_for_test()
            assert helper.dialog.is_open is False
            assert settings.get(LAST_SAVE_DIR_SETTING) == (
                "mock://Home/Documents/Projects"
            )
        finally:
            helper.destroy()

    def test_apply_raising_handler_does_not_crash(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        def _handler(filename, dirname, extension, selections):
            raise RuntimeError("boom")

        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=_handler,
                )
            helper.dialog._fire_apply_for_test()  # no raise
        finally:
            helper.destroy()

    def test_cancel_does_not_fire_export_handler(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=lambda f, d, e, s: calls.append(1),
                )
            helper.dialog._fire_cancel_for_test()
            assert calls == []
            assert helper.dialog.is_open is False
        finally:
            helper.destroy()

    def test_escape_does_not_fire_export_handler(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        from ovwidgets.content.file_picker_dialog import _KEY_ESCAPE
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    filename_url=(
                        "mock://Home/Documents/Projects/demo.usda"
                    ),
                    export_handler=lambda f, d, e, s: calls.append(1),
                )
            helper.dialog._fire_key_for_test(_KEY_ESCAPE)
            assert calls == []
            assert helper.dialog.is_open is False
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Extension resolution
# ──────────────────────────────────────────────────────────────────────────────


class TestExtensionResolution:
    def test_extension_is_first_default_when_combo_untouched(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Default combo index is 0 → ``.usd`` (the first default)."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper._resolve_extension() == ".usd"
        finally:
            helper.destroy()

    def test_extension_follows_combo_selection(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Manual combo-index change flips the resolved extension."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            # Select ".usda" (index 1 in the default list).
            helper.dialog._file_bar._selected_extension_index = 1
            # Force the bar to rebuild its cached value by swapping the
            # combo's underlying int model.
            if helper.dialog._file_bar._combo is not None:
                try:
                    (
                        helper.dialog._file_bar._combo
                        .model.get_item_value_model()
                        .set_value(1)
                    )
                except Exception:  # noqa: BLE001
                    pass
            assert helper._resolve_extension() == ".usda"
        finally:
            helper.destroy()

    def test_extension_empty_when_no_dialog(
        self, helper: FileExporterHelper,
    ):
        """Pre-show / post-destroy resolution returns an empty string."""
        assert helper._resolve_extension() == ""

    def test_extension_strips_leading_star(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """A single-glob pattern ``"*.foo"`` resolves to ``".foo"``."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    file_extension_types=[("*.foo", "FOO")],
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper._resolve_extension() == ".foo"
        finally:
            helper.destroy()

    def test_extension_handles_multi_glob_entry(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """A ``"*.usd, *.usda"`` entry resolves to the first pattern."""
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    file_extension_types=[
                        ("*.usd, *.usda", "Either"),
                    ],
                    export_handler=lambda f, d, e, s: None,
                )
            assert helper._resolve_extension() == ".usd"
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Validation pass-through (save-mode)
# ──────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_validation_rejects_empty_filename(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """``should_validate=True`` + empty filename → handler not fired."""
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    export_handler=lambda f, d, e, s: calls.append(1),
                    should_validate=True,
                )
            helper.dialog.set_filename("")
            helper.dialog._fire_apply_for_test()
            assert calls == []
            # Dialog stays open so the user can type a filename.
            assert helper.dialog.is_open is True
        finally:
            helper.destroy()

    def test_validation_passes_for_non_empty_filename(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        """Non-empty filename → save-mode validator lets Apply proceed.

        Unlike the open-mode validator this does NOT stat — an outgoing
        save target is allowed to not exist yet.
        """
        calls: List = []
        try:
            with in_window_frame(ephemeral_window):
                helper.show(
                    export_handler=lambda f, d, e, s: calls.append(
                        (f, d, e, s),
                    ),
                    should_validate=True,
                )
            helper.dialog.navigate_to("mock://Home/Documents/Projects")
            helper.dialog.set_filename("brand-new.usd")
            helper.dialog._fire_apply_for_test()
            assert len(calls) == 1
        finally:
            helper.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# destroy()
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_dialog_reference(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            helper.show(export_handler=lambda f, d, e, s: None)
        assert helper.dialog is not None
        helper.destroy()
        assert helper.dialog is None

    def test_destroy_without_show_is_safe(
        self, helper: FileExporterHelper,
    ):
        helper.destroy()  # no raise

    def test_show_after_destroy_rebuilds(
        self, helper: FileExporterHelper, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            helper.show(export_handler=lambda f, d, e, s: None)
        helper.destroy()
        try:
            with in_window_frame(ephemeral_window):
                helper.show(export_handler=lambda f, d, e, s: None)
            assert helper.dialog is not None
            assert helper.dialog.is_open is True
        finally:
            helper.destroy()
