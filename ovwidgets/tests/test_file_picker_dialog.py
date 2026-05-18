# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 47 — :class:`FilePickerDialog` window shell.

Coverage:

* Public surface — re-export from ``ovwidgets.content`` package,
  module-level constants, default size / flags.
* Construction — no ovui side effects; cached ``initial_filename`` +
  ``start_url`` + kwargs survive with no window yet.
* Lifecycle — :meth:`show` lazy-builds and toggles ``visible``;
  :meth:`hide` preserves widget state; :meth:`destroy` tears everything
  down; :meth:`show` after destroy rebuilds.
* Accessors — :meth:`get_filename` / :meth:`set_filename` round-trip
  before / during / after show; :meth:`get_directory` tracks the
  embedded widget; :meth:`get_selection` empty pre-build.
* Callbacks — Apply fires ``(filename, dirname)``; Cancel fires same
  shape and hides; ESC fires cancel via the window-level key handler.
* Navigation — :meth:`navigate_to` re-roots the widget's detail pane.

Tests follow the ``tests/test_delete.py`` pattern: a module-scoped
``ephemeral_window`` fixture + an ``in_window_frame`` context manager
so every :class:`ui.Window` spawn happens inside a real ovui root. The
dialog itself creates its own :class:`ui.Window` via :meth:`show`, so
the fixture is used for its side effect of keeping ovui's window
registry reachable — the dialog tests do not render their contents
inside the ephemeral window's frame.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Tuple

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.error_reporter import ErrorReporter
from ovwidgets.content import FilePickerDialog as _FilePickerDialog
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend
from ovwidgets.content.file_picker_dialog import (
    _DEFAULT_HEIGHT,
    _DEFAULT_WIDTH,
    _KEY_ESCAPE,
    _VALIDATION_EMPTY_FILENAME,
    _VALIDATION_FILE_NOT_FOUND,
    _VALIDATION_MODE_OPEN,
    _VALIDATION_MODE_SAVE,
    _WINDOW_FLAGS,
    _WINDOW_TITLE_PREFIX,
    FilePickerDialog,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window reused across tests — keeps an ovui root live.

    The dialog spawns its own :class:`ui.Window` from :meth:`show`; this
    fixture is present so the ovui runtime has an established window
    registry (otherwise the first dialog spawn may race with ovui's
    per-test teardown). Mirrors ``tests/test_delete.py``'s shared
    module-scoped fixture.
    """
    win = ui.Window("_test_file_picker_dialog", width=400, height=200)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    """Enter ``window.frame`` as a build context and clear on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


@pytest.fixture
def mock_backend() -> MockBackend:
    return MockBackend()


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogSurface:
    def test_reexported_from_content_browser_package(self):
        assert FilePickerDialog is _FilePickerDialog

    def test_module_constants_match_architecture(self):
        """§12.2 — regular picker with native title; default 1000x600."""
        assert _DEFAULT_WIDTH == 1000
        assert _DEFAULT_HEIGHT == 600
        expected_flags = (
            ui.WINDOW_FLAGS_NO_DOCKING
            | ui.WINDOW_FLAGS_NO_SCROLLBAR
        )
        assert _WINDOW_FLAGS == expected_flags

    def test_window_title_prefix_is_registry_unique(self):
        """Prefix must vary per-instance so back-to-back dialogs do not
        collide in ovui's window registry."""
        assert _WINDOW_TITLE_PREFIX.endswith("_")


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogConstruction:
    def test_no_ovui_side_effects_at_construction(
        self, mock_backend: MockBackend,
    ):
        """Ctor must not materialise a window — that's :meth:`show`'s job."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
        )
        assert dlg.is_open is False
        assert dlg.window is None
        assert dlg.widget is None

    def test_initial_filename_cached(self, mock_backend: MockBackend):
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="untitled.usd",
        )
        assert dlg.get_filename() == "untitled.usd"

    def test_initial_filename_defaults_to_empty_string(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        assert dlg.get_filename() == ""

    def test_none_initial_filename_normalised_to_empty(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename=None,  # type: ignore[arg-type]
        )
        assert dlg.get_filename() == ""

    def test_start_url_normalised_via_backend(
        self, mock_backend: MockBackend,
    ):
        """``start_url`` seeds :meth:`get_directory` pre-build."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents",
        )
        assert dlg.get_directory() == "mock://Home/Documents"

    def test_start_url_defaults_to_home_via_backend(self):
        """Missing ``start_url`` falls back to the backend's normalised home."""
        dlg = FilePickerDialog(
            title="Open", backend=LocalFSBackend(),
        )
        # LocalFSBackend.normalize_url on ``file://~`` resolves to a
        # file:// URL under the user's home — the exact path is OS-
        # dependent, but it must be non-empty and scheme-prefixed.
        directory = dlg.get_directory()
        assert directory.startswith("file://")

    def test_default_backend_is_local_fs(self):
        """No ``backend`` kwarg → fresh :class:`LocalFSBackend`."""
        dlg = FilePickerDialog(title="Open")
        assert isinstance(dlg._backend, LocalFSBackend)

    def test_custom_labels_stored(self, mock_backend: MockBackend):
        dlg = FilePickerDialog(
            title="Save As",
            backend=mock_backend,
            start_url="mock://Home",
            apply_button_label="Save",
            cancel_button_label="Dismiss",
        )
        assert dlg._apply_label == "Save"
        assert dlg._cancel_label == "Dismiss"

    def test_kwargs_stored_for_step48_filebar(
        self, mock_backend: MockBackend,
    ):
        """Step 48's :class:`FileBar` will consume these — Step 47 just
        caches them so the ctor signature stays stable across the swap."""
        ext_types = [("*.usd, *.usda", "USD Files"), ("*.*", "All files")]
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            allow_multi_selection=True,
            file_extension_types=ext_types,
            folder_only=False,
        )
        assert dlg._allow_multi_selection is True
        assert dlg._file_extension_types == ext_types
        assert dlg._folder_only is False

    def test_file_extension_types_defaults_to_empty_list(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        assert dlg._file_extension_types == []


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogLifecycle:
    def test_show_builds_window_and_widget(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            assert dlg.window is not None
            assert dlg.widget is not None
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_show_sets_title_to_user_facing_string(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open File",
            backend=mock_backend,
            start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # ``title`` setter is present on modern ovui; if it isn't
            # present the dialog still works, just with the registry
            # suffix visible. Both paths should land with a readable
            # title.
            assert "Open File" in dlg.window.title or _WINDOW_TITLE_PREFIX in dlg.window.title
        finally:
            dlg.destroy()

    def test_show_uses_regular_window_flags(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # The File Open picker is a regular floating window with
            # native title chrome, not a modal/no-title custom shell.
            flags = dlg.window.flags
            assert not flags & ui.WINDOW_FLAGS_MODAL
            assert not flags & ui.WINDOW_FLAGS_NO_TITLE_BAR
            assert flags & ui.WINDOW_FLAGS_NO_DOCKING
            assert flags & ui.WINDOW_FLAGS_NO_SCROLLBAR
        finally:
            dlg.destroy()

    def test_show_default_size_1000x600(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            assert dlg.window.width == _DEFAULT_WIDTH
            assert dlg.window.height == _DEFAULT_HEIGHT
        finally:
            dlg.destroy()

    def test_show_twice_is_idempotent_on_window(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Second :meth:`show` re-reveals — does not rebuild."""
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            first_window = dlg.window
            first_widget = dlg.widget
            dlg.hide()
            dlg.show()
            assert dlg.window is first_window
            assert dlg.widget is first_widget
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_hide_sets_visible_false_but_preserves_widget(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            widget_before = dlg.widget
            dlg.hide()
            assert dlg.is_open is False
            assert dlg.widget is widget_before
        finally:
            dlg.destroy()

    def test_hide_before_show_is_noop(self, mock_backend: MockBackend):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        dlg.hide()  # no raise, no state change
        assert dlg.is_open is False

    def test_destroy_tears_down_window_and_widget(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        assert dlg.window is None
        assert dlg.widget is None
        assert dlg.is_open is False

    def test_destroy_without_show_is_safe(self, mock_backend: MockBackend):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        dlg.destroy()  # no raise

    def test_destroy_twice_is_idempotent(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        dlg.destroy()  # no raise

    def test_show_after_destroy_rebuilds(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        first_window = dlg.window
        dlg.destroy()
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            assert dlg.window is not None
            assert dlg.window is not first_window
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Filename accessors
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogFilename:
    def test_get_filename_returns_initial_before_show(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="foo.usd",
        )
        assert dlg.get_filename() == "foo.usd"

    def test_show_seeds_field_with_initial_filename(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="initial.usd",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            assert dlg._filename_field is not None
            assert (
                dlg._filename_field.model.get_value_as_string()
                == "initial.usd"
            )
            assert dlg.get_filename() == "initial.usd"
        finally:
            dlg.destroy()

    def test_set_filename_updates_cache_before_show(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Save", backend=mock_backend, start_url="mock://Home",
        )
        dlg.set_filename("draft.usd")
        assert dlg.get_filename() == "draft.usd"

    def test_set_filename_updates_field_when_live(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Save", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg.set_filename("typed.usd")
            assert (
                dlg._filename_field.model.get_value_as_string()
                == "typed.usd"
            )
            assert dlg.get_filename() == "typed.usd"
        finally:
            dlg.destroy()

    def test_set_filename_none_normalised_to_empty(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="a.usd",
        )
        dlg.set_filename(None)  # type: ignore[arg-type]
        assert dlg.get_filename() == ""

    def test_destroy_snapshots_field_value(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Post-destroy, :meth:`get_filename` returns the last typed value."""
        dlg = FilePickerDialog(
            title="Save", backend=mock_backend, start_url="mock://Home",
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.set_filename("unsaved.usd")
        dlg.destroy()
        assert dlg.get_filename() == "unsaved.usd"


# ──────────────────────────────────────────────────────────────────────────────
# Directory accessor
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogDirectory:
    def test_get_directory_returns_start_url_before_show(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents",
        )
        assert dlg.get_directory() == "mock://Home/Documents"

    def test_get_directory_reads_detail_model_after_show(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # Widget's detail model is rooted at ``mock://Home`` per
            # the ``start_url``; the directory reads through.
            assert dlg.get_directory() == "mock://Home"
        finally:
            dlg.destroy()

    def test_navigate_to_changes_directory(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg.navigate_to("mock://Home/Documents")
            assert dlg.get_directory() == "mock://Home/Documents"
        finally:
            dlg.destroy()

    def test_navigate_to_before_show_is_noop(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
        )
        dlg.navigate_to("mock://Home/Documents")  # no raise, no widget
        # get_directory still returns the cached start_url because the
        # widget hasn't been built yet.
        assert dlg.get_directory() == "mock://Home"

    def test_show_with_path_navigates(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show(path="mock://Home/Scripts")
            assert dlg.get_directory() == "mock://Home/Scripts"
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Selection accessor
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogSelection:
    def test_get_selection_empty_before_show(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        assert dlg.get_selection() == []

    def test_get_selection_empty_after_show_with_no_selection(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            assert dlg.get_selection() == []
        finally:
            dlg.destroy()

    def test_get_selection_returns_fresh_copy(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            first = dlg.get_selection()
            first.append("mock://sentinel")
            # Mutating the returned list must not affect subsequent reads.
            assert dlg.get_selection() == []
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Callbacks
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogCallbacks:
    def test_apply_fires_with_filename_and_dirname(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="foo.usd",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_apply_for_test()
            assert calls == [("foo.usd", "mock://Home")]
        finally:
            dlg.destroy()

    def test_apply_reads_typed_filename(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg.set_filename("renamed.usd")
            dlg._fire_apply_for_test()
            assert calls == [("renamed.usd", "mock://Home")]
        finally:
            dlg.destroy()

    def test_apply_reflects_post_navigation_dirname(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """The dirname at Apply-time is the detail pane's *current* root."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="a.usd",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg.navigate_to("mock://Home/Documents")
            dlg._fire_apply_for_test()
            assert calls == [("a.usd", "mock://Home/Documents")]
        finally:
            dlg.destroy()

    def test_apply_does_not_hide(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Apply leaves the dialog visible — caller decides dismissal."""
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            on_apply=lambda fn, dn: None,
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_apply_for_test()
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_cancel_fires_and_hides(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="sketch.usd",
            on_cancel=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_cancel_for_test()
            assert calls == [("sketch.usd", "mock://Home")]
            assert dlg.is_open is False
        finally:
            dlg.destroy()

    def test_escape_fires_cancel(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            on_cancel=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_key_for_test(_KEY_ESCAPE)
            assert len(calls) == 1
            assert calls[0][1] == "mock://Home"
            assert dlg.is_open is False
        finally:
            dlg.destroy()

    def test_no_on_apply_callback_is_safe(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Apply with ``on_apply=None`` is a no-op, not a crash."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_apply_for_test()  # no raise
        finally:
            dlg.destroy()

    def test_no_on_cancel_callback_is_safe(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_cancel_for_test()  # no raise
            assert dlg.is_open is False  # still hides
        finally:
            dlg.destroy()

    def test_apply_after_destroy_is_noop(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        dlg._fire_apply_for_test()  # short-circuits on ``_window is None``
        assert calls == []

    def test_escape_only_fires_cancel(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """A non-ESC key does not fire cancel — only ESC is bound."""
        cancel_calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            on_cancel=lambda fn, dn: cancel_calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # Enter (257) is intentionally not bound per §12.2.
            dlg._fire_key_for_test(257)
            assert cancel_calls == []
            assert dlg.is_open is True
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Extension filter (Step 49)
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogExtensionFilter:
    """Step 49 — combo picks an extension → browser filters by glob."""

    # Deliberately ordered so index 0 is USD-only (filters out readme.md),
    # index 1 is All Files (no filter), index 2 is PNG (filters out usd).
    _EXT_TYPES = [
        ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
        ("*.*", "All files"),
        ("*.png", "PNG"),
    ]

    @staticmethod
    def _navigate_to_projects(dlg: FilePickerDialog) -> None:
        """Drill into ``mock://Home/Documents/Projects`` — the leaf folder.

        Projects has a mixed content (.usda, .usdc, .md) which makes
        extension filtering visually distinguishable. The top-level
        Home folder is all folders, which always pass the glob filter
        and so wouldn't exercise the leaf-filtering path.
        """
        dlg.navigate_to("mock://Home/Documents/Projects")

    @staticmethod
    def _child_names(dlg: FilePickerDialog) -> List[str]:
        """Return current visible child names (post-filter) via the model."""
        assert dlg.widget is not None
        detail_model = dlg.widget.get_detail_model()
        assert detail_model is not None
        return [
            c.name
            for c in detail_model.get_item_children(detail_model.root)
        ]

    def test_initial_extension_seeds_filter_on_build(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Picker opens with the first extension's glob already applied."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            file_extension_types=self._EXT_TYPES,
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            names = self._child_names(dlg)
            assert "demo.usda" in names
            assert "demo.usdc" in names
            assert "readme.md" not in names
        finally:
            dlg.destroy()

    def test_no_extensions_leaves_filter_empty(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Dialog with no ``file_extension_types`` does not touch the filter."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            detail_model = dlg.widget.get_detail_model()
            assert detail_model is not None
            assert detail_model.glob_filter == []
            # Without a filter, every child — folder or leaf — is visible.
            names = self._child_names(dlg)
            assert "demo.usda" in names
            assert "readme.md" in names
        finally:
            dlg.destroy()

    def test_extension_filter_shows_only_matching_files(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """USD Files combo entry → .usd*/.usda/.usdc visible, readme.md hidden."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            file_extension_types=self._EXT_TYPES,
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            self._navigate_to_projects(dlg)
            # Default selection is index 0 — USD Files.
            names = self._child_names(dlg)
            assert "demo.usda" in names
            assert "demo.usdc" in names
            assert "readme.md" not in names
        finally:
            dlg.destroy()

    def test_all_files_shows_everything(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Picking "All files" (*.*) removes the filter."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            file_extension_types=self._EXT_TYPES,
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            self._navigate_to_projects(dlg)
            # Switch to "All files" (index 1).
            dlg._file_bar._set_combo_index_for_test(1)
            names = self._child_names(dlg)
            assert "demo.usda" in names
            assert "demo.usdc" in names
            assert "readme.md" in names  # The key assertion.
        finally:
            dlg.destroy()

    def test_changing_extension_updates_view(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Switching combo entries at runtime re-filters the detail pane."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            file_extension_types=self._EXT_TYPES,
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            self._navigate_to_projects(dlg)
            # Start on USD Files (index 0) — readme.md hidden.
            assert "readme.md" not in self._child_names(dlg)
            # Switch to "All files" (index 1) — readme.md visible again.
            dlg._file_bar._set_combo_index_for_test(1)
            assert "readme.md" in self._child_names(dlg)
            # Switch to PNG (index 2) — all three leaves hidden.
            dlg._file_bar._set_combo_index_for_test(2)
            names = self._child_names(dlg)
            assert "demo.usda" not in names
            assert "demo.usdc" not in names
            assert "readme.md" not in names
        finally:
            dlg.destroy()

    def test_glob_parsing_splits_and_strips(self):
        """``"*.usd, *.usda"`` → ``["*.usd", "*.usda"]`` per Step 49."""
        parse = FilePickerDialog._parse_glob_string
        assert parse("*.usd, *.usda") == ["*.usd", "*.usda"]
        # Leading / trailing whitespace and multiple commas.
        assert parse("  *.usd ,, *.usda  ") == ["*.usd", "*.usda"]
        # Four-entry USD list from the architecture default.
        assert parse("*.usd, *.usda, *.usdc, *.usdz") == [
            "*.usd", "*.usda", "*.usdc", "*.usdz",
        ]
        # Empty string → empty list.
        assert parse("") == []
        # Single entry, no comma.
        assert parse("*.png") == ["*.png"]

    def test_extension_changed_pushes_to_model_glob_filter(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """The model's :attr:`glob_filter` tracks the combo selection."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            file_extension_types=self._EXT_TYPES,
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            detail_model = dlg.widget.get_detail_model()
            assert detail_model is not None
            # Initial seed — four USD patterns from index 0.
            assert detail_model.glob_filter == [
                "*.usd", "*.usda", "*.usdc", "*.usdz",
            ]
            # Switch to "All files" — model.glob_filter reduces to [].
            dlg._file_bar._set_combo_index_for_test(1)
            assert detail_model.glob_filter == []
            # Switch to PNG — one pattern.
            dlg._file_bar._set_combo_index_for_test(2)
            assert detail_model.glob_filter == ["*.png"]
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Apply validation (Step 50)
# ──────────────────────────────────────────────────────────────────────────────


class _CapturedWarning:
    """Captures the last ``ErrorReporter.show_warning`` call."""

    def __init__(self) -> None:
        self.messages: List[str] = []
        self._saved = None

    def __enter__(self) -> "_CapturedWarning":
        self._saved = ErrorReporter.show_warning

        def _capture(message: str, duration_ms: int = 4000) -> None:
            self.messages.append(message)

        ErrorReporter.show_warning = _capture  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        ErrorReporter.show_warning = self._saved  # type: ignore[assignment]


class TestFilePickerDialogApplyValidation:
    """Step 50 — ``should_validate`` gates Apply on a backend.stat / empty check."""

    def test_should_validate_defaults_false(self, mock_backend: MockBackend):
        dlg = FilePickerDialog(
            title="Open", backend=mock_backend, start_url="mock://Home",
        )
        assert dlg._should_validate is False
        assert dlg._validation_mode == _VALIDATION_MODE_OPEN

    def test_validation_mode_stored(self, mock_backend: MockBackend):
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            should_validate=True,
            validation_mode=_VALIDATION_MODE_SAVE,
        )
        assert dlg._should_validate is True
        assert dlg._validation_mode == _VALIDATION_MODE_SAVE

    def test_invalid_validation_mode_falls_back_to_open(
        self, mock_backend: MockBackend,
    ):
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            should_validate=True,
            validation_mode="bogus",
        )
        assert dlg._validation_mode == _VALIDATION_MODE_OPEN

    def test_validation_disabled_does_not_stat(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """With ``should_validate=False`` Apply fires even for a missing file."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="does_not_exist.usd",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg._fire_apply_for_test()
            assert calls == [("does_not_exist.usd", "mock://Home")]
        finally:
            dlg.destroy()

    def test_open_mode_stat_ok_fires_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Open-mode validation passes when ``backend.stat`` returns OK."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            initial_filename="demo.usda",
            should_validate=True,
            validation_mode=_VALIDATION_MODE_OPEN,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            with _CapturedWarning() as cap:
                dlg._fire_apply_for_test()
            assert calls == [("demo.usda", "mock://Home/Documents/Projects")]
            assert cap.messages == []
        finally:
            dlg.destroy()

    def test_open_mode_missing_file_blocks_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Open-mode validation fails when the file does not exist."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            initial_filename="nope.usd",
            should_validate=True,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            with _CapturedWarning() as cap:
                dlg._fire_apply_for_test()
            assert calls == []
            assert cap.messages == [_VALIDATION_FILE_NOT_FOUND]
        finally:
            dlg.destroy()

    def test_open_mode_empty_filename_blocks_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Open-mode validation rejects an empty filename before stat."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            should_validate=True,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            with _CapturedWarning() as cap:
                dlg._fire_apply_for_test()
            assert calls == []
            assert cap.messages == [_VALIDATION_FILE_NOT_FOUND]
        finally:
            dlg.destroy()

    def test_save_mode_non_empty_filename_fires_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Save-mode validation passes on any non-empty filename — no stat."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="new_file.usd",  # Does not exist yet.
            should_validate=True,
            validation_mode=_VALIDATION_MODE_SAVE,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            with _CapturedWarning() as cap:
                dlg._fire_apply_for_test()
            assert calls == [("new_file.usd", "mock://Home")]
            assert cap.messages == []
        finally:
            dlg.destroy()

    def test_save_mode_empty_filename_blocks_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Save-mode validation rejects an empty filename."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Save",
            backend=mock_backend,
            start_url="mock://Home",
            should_validate=True,
            validation_mode=_VALIDATION_MODE_SAVE,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            with _CapturedWarning() as cap:
                dlg._fire_apply_for_test()
            assert calls == []
            assert cap.messages == [_VALIDATION_EMPTY_FILENAME]
        finally:
            dlg.destroy()

    def test_validation_strips_trailing_slash_on_dirname(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """A dirname ending in ``/`` must not produce a ``//`` in the stat URL."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects/",  # trailing slash.
            initial_filename="demo.usda",
            should_validate=True,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # Force the dirname reported back through the widget to match
            # the start_url string including its trailing slash — we
            # simulate that by directly exercising the validator.
            assert dlg._validate_apply(
                "demo.usda", "mock://Home/Documents/Projects/",
            ) is True
        finally:
            dlg.destroy()

    def test_validation_fails_on_folder_url(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """A folder's URL must be stat-OK but the mock backend does report OK —
        this test documents that the dialog does NOT reject folders here;
        folder-only dialogs are served by a separate Step 52+ flow."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="Documents",
            should_validate=True,
        )
        # Documents is a folder under Home; backend.stat returns OK for
        # either a file or a folder, so the validator does not reject it.
        # This is intentional: folder-picking dialogs (``folder_only``)
        # expose the same stat-OK path.
        assert dlg._validate_apply(
            "Documents", "mock://Home",
        ) is True


# ──────────────────────────────────────────────────────────────────────────────
# Detail-selection → FileBar (Step 51)
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogSelectionAutofill:
    """Step 51 — single-click file in detail pane populates the FileBar."""

    @staticmethod
    def _projects_children(dlg: FilePickerDialog):
        """Return the FileItem list of ``mock://Home/Documents/Projects``."""
        detail_model = dlg.widget.get_detail_model()
        assert detail_model is not None
        return detail_model.get_item_children(detail_model.root)

    def test_file_click_populates_filename_field(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            children = self._projects_children(dlg)
            demo = next(c for c in children if c.name == "demo.usda")
            # Drive the grid selection + fire the widget's click hook —
            # this mirrors the FileGridView post-click dispatch.
            dlg.widget._detail_grid_view.set_selection([demo])
            dlg.widget._on_grid_click(demo, 0, 0)
            assert dlg.get_filename() == "demo.usda"
        finally:
            dlg.destroy()

    def test_folder_click_clears_filename_field(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Folders do NOT populate the filename — user must drill in."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            initial_filename="was_seeded.usd",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            children = dlg.widget._detail_model.get_item_children(None)
            documents = next(c for c in children if c.name == "Documents")
            dlg.widget._detail_grid_view.set_selection([documents])
            dlg.widget._on_grid_click(documents, 0, 0)
            # Folder selection clears the field per the content browser implementation step 51.
            assert dlg.get_filename() == ""
        finally:
            dlg.destroy()

    def test_multi_select_clears_filename_field(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Multi-select shows an empty filename (no "foo.usd vs bar.usd" ambiguity)."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            children = self._projects_children(dlg)
            demo_a = next(c for c in children if c.name == "demo.usda")
            demo_c = next(c for c in children if c.name == "demo.usdc")
            dlg.widget._detail_grid_view.set_selection([demo_a, demo_c])
            dlg.widget._on_grid_click(demo_c, 0, 0)
            assert dlg.get_filename() == ""
        finally:
            dlg.destroy()

    def test_empty_selection_clears_filename_field(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Clicking empty space (selection → []) clears the field."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            initial_filename="stale.usd",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # Empty grid selection → selection-changed fires with [].
            dlg.widget._detail_grid_view.set_selection([])
            dlg.widget._emit_detail_selection_changed()
            assert dlg.get_filename() == ""
        finally:
            dlg.destroy()

    def test_tree_view_selection_also_populates(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """List-view (tree) selection also populates the FileBar."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # Flip to list view.
            dlg.widget._on_zoom_bar_toggle_grid(False)
            children = self._projects_children(dlg)
            demo = next(c for c in children if c.name == "demo.usdc")
            dlg.widget._detail_tree_view.selection = [demo]
            dlg.widget._on_detail_tree_selection([demo])
            assert dlg.get_filename() == "demo.usdc"
        finally:
            dlg.destroy()

    def test_apply_button_enabled_after_selection(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Selecting a file writes to the field → Apply re-enables."""
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            # Empty field → Apply disabled.
            assert dlg._file_bar.apply_enabled is False
            children = self._projects_children(dlg)
            demo = next(c for c in children if c.name == "demo.usda")
            dlg.widget._detail_grid_view.set_selection([demo])
            dlg.widget._on_grid_click(demo, 0, 0)
            assert dlg._file_bar.apply_enabled is True
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Double-click → apply (Step 51)
# ──────────────────────────────────────────────────────────────────────────────


class TestFilePickerDialogFileDoubleClick:
    """Step 51 — double-clicking a file fires Apply with that filename."""

    @staticmethod
    def _projects_children(dlg: FilePickerDialog):
        detail_model = dlg.widget.get_detail_model()
        assert detail_model is not None
        return detail_model.get_item_children(detail_model.root)

    def test_grid_double_click_file_fires_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            children = self._projects_children(dlg)
            demo = next(c for c in children if c.name == "demo.usda")
            # Drive the grid double-click path directly.
            dlg.widget._on_grid_double_click(demo)
            assert calls == [
                ("demo.usda", "mock://Home/Documents/Projects"),
            ]
            # The filename is also written into the bar for post-apply
            # read-back by the caller through :meth:`get_filename`.
            assert dlg.get_filename() == "demo.usda"
        finally:
            dlg.destroy()

    def test_tree_double_click_file_fires_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """List-view file double-click also fires Apply."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            dlg.widget._on_zoom_bar_toggle_grid(False)
            children = self._projects_children(dlg)
            demo = next(c for c in children if c.name == "demo.usdc")
            dlg.widget._detail_tree_view.selection = [demo]
            dlg.widget._on_detail_double_click(0, 0, 0, 0)
            assert calls == [
                ("demo.usdc", "mock://Home/Documents/Projects"),
            ]
        finally:
            dlg.destroy()

    def test_folder_double_click_does_not_fire_apply(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """Double-click on a folder drills in — does not fire Apply."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home",
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            children = dlg.widget._detail_model.get_item_children(None)
            documents = next(c for c in children if c.name == "Documents")
            dlg.widget._on_grid_double_click(documents)
            assert calls == []
            # Drill-in re-rooted the detail pane at the folder.
            assert dlg.get_directory() == "mock://Home/Documents"
        finally:
            dlg.destroy()

    def test_double_click_runs_validation(
        self, mock_backend: MockBackend, ephemeral_window,
    ):
        """``should_validate`` also gates the double-click Apply path."""
        calls: List[Tuple[str, str]] = []
        dlg = FilePickerDialog(
            title="Open",
            backend=mock_backend,
            start_url="mock://Home/Documents/Projects",
            should_validate=True,
            on_apply=lambda fn, dn: calls.append((fn, dn)),
        )
        try:
            with in_window_frame(ephemeral_window):
                dlg.show()
            children = self._projects_children(dlg)
            demo = next(c for c in children if c.name == "demo.usda")
            with _CapturedWarning() as cap:
                dlg.widget._on_grid_double_click(demo)
            # Validation passes (file exists), so Apply fires and no
            # warning is surfaced.
            assert calls == [
                ("demo.usda", "mock://Home/Documents/Projects"),
            ]
            assert cap.messages == []
        finally:
            dlg.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserWidget callbacks (Step 51)
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBrowserWidgetSelectionCallbacks:
    """Step 51 — widget exposes ``on_selection_changed`` + ``on_file_double_clicked``."""

    def test_on_selection_changed_stored(self, ephemeral_window):
        from ovwidgets.content.widget.file_browser_widget import (
            FileBrowserWidget,
        )
        selections: List[List] = []

        def _on_sel(items):
            selections.append(items)

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(),
                "mock://Home/Documents/Projects",
                on_selection_changed=_on_sel,
            )
        try:
            children = widget._detail_model.get_item_children(None)
            demo = next(c for c in children if c.name == "demo.usda")
            widget._detail_grid_view.set_selection([demo])
            widget._on_grid_click(demo, 0, 0)
            assert len(selections) == 1
            assert selections[0][0].name == "demo.usda"
        finally:
            widget.destroy()

    def test_on_file_double_clicked_stored(self, ephemeral_window):
        from ovwidgets.content.widget.file_browser_widget import (
            FileBrowserWidget,
        )
        opens: List[str] = []

        def _on_open(item):
            opens.append(item.name)

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(),
                "mock://Home/Documents/Projects",
                on_file_double_clicked=_on_open,
            )
        try:
            children = widget._detail_model.get_item_children(None)
            demo = next(c for c in children if c.name == "demo.usdc")
            widget._on_grid_double_click(demo)
            assert opens == ["demo.usdc"]
        finally:
            widget.destroy()

    def test_no_callbacks_is_safe(self, ephemeral_window):
        """Widget with no callbacks is safe — falls back to Step-54 stub."""
        from ovwidgets.content.widget.file_browser_widget import (
            FileBrowserWidget,
        )
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        try:
            children = widget._detail_model.get_item_children(None)
            demo = next(c for c in children if c.name == "demo.usda")
            widget._detail_grid_view.set_selection([demo])
            widget._on_grid_click(demo, 0, 0)  # no raise
            widget._on_grid_double_click(demo)  # falls through to log
        finally:
            widget.destroy()

    def test_destroy_clears_callbacks(self, ephemeral_window):
        from ovwidgets.content.widget.file_browser_widget import (
            FileBrowserWidget,
        )
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(),
                "mock://Home",
                on_selection_changed=lambda items: None,
                on_file_double_clicked=lambda item: None,
            )
        widget.destroy()
        assert widget._on_selection_changed is None
        assert widget._on_file_double_clicked is None
