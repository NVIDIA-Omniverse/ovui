# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 48 — :class:`FileBar` filename bar widget.

Coverage:

* Public surface — re-export from ``ovwidgets.content.widget``
  package, identifier constants, module constants match architecture.
* Construction — no ovui side effects; cached ``initial_filename`` +
  ``file_extension_types`` + labels survive pre-build.
* Build — materialises the HStack inside the caller's frame; field,
  combo, and buttons reachable through private slots.
* Filename accessors — :attr:`filename` round-trips through the live
  field and the cache; ``None`` normalises to ``""``; setter refreshes
  the Apply button's enabled gate.
* Apply-enabled gate — disabled when empty; enabled when non-empty;
  tracks :meth:`set_filename` writes; tracks destroy.
* Extension combo — :attr:`selected_extension` defaults to the first
  entry; updates when the combo index changes; returns the fallback
  ``("*.*", "All files")`` when no extensions configured.
* Callbacks — Apply fires ``on_apply(filename)``; Cancel fires
  ``on_cancel()``; ``None`` callbacks are safe; post-destroy firing is
  a no-op.
* Destroy — nulls every ovui reference; idempotent; snapshots the
  current field value and combo index so :attr:`filename` and
  :attr:`selected_extension` keep working post-destroy.

Tests follow the ``tests/test_file_picker_dialog.py`` pattern:
a module-scoped ``ephemeral_window`` fixture + ``in_window_frame``
context manager so every ovui build happens inside a real ovui frame.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Tuple

import omni.ui as ui
import pytest

from ovwidgets.content.widget import FileBar as _FileBar
from ovwidgets.content.widget.file_bar import (
    _DROPDOWN_POPUP_FLAGS,
    APPLY_BUTTON_IDENTIFIER,
    CANCEL_BUTTON_IDENTIFIER,
    FileBar,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window reused across tests — keeps an ovui root live."""
    win = ui.Window("_test_file_bar", width=800, height=100)
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


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarSurface:
    def test_reexported_from_widget_package(self):
        assert FileBar is _FileBar

    def test_identifier_constants(self):
        """Architecture §15.1 fixes the identifier strings."""
        assert APPLY_BUTTON_IDENTIFIER == "filepicker_apply_button"
        assert CANCEL_BUTTON_IDENTIFIER == "filepicker_cancel_button"

    def test_extension_dropdown_uses_popup_window_flags(self):
        """The extension dropdown must dismiss like an ovui popup."""
        assert _DROPDOWN_POPUP_FLAGS & ui.WINDOW_FLAGS_POPUP


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarConstruction:
    def test_no_ovui_side_effects_at_construction(self):
        """Ctor must not materialise widgets — that's :meth:`build`'s job."""
        bar = FileBar()
        assert bar.is_built is False
        assert bar._field is None
        assert bar._combo is None
        assert bar._apply_button is None
        assert bar._cancel_button is None

    def test_initial_filename_cached(self):
        bar = FileBar(initial_filename="foo.usd")
        assert bar.filename == "foo.usd"

    def test_initial_filename_defaults_to_empty(self):
        bar = FileBar()
        assert bar.filename == ""

    def test_none_initial_filename_normalised_to_empty(self):
        bar = FileBar(initial_filename=None)  # type: ignore[arg-type]
        assert bar.filename == ""

    def test_custom_labels_stored(self):
        bar = FileBar(
            apply_label="Save",
            cancel_label="Dismiss",
            label_text="Destination:",
        )
        assert bar._apply_label == "Save"
        assert bar._cancel_label == "Dismiss"
        assert bar._label_text == "Destination:"

    def test_extension_types_stored(self):
        exts = [("*.usd, *.usda", "USD Files"), ("*.*", "All files")]
        bar = FileBar(file_extension_types=exts)
        assert bar._file_extension_types == exts

    def test_extension_types_none_defaults_to_empty_list(self):
        bar = FileBar(file_extension_types=None)
        assert bar._file_extension_types == []

    def test_extension_types_defensive_copy(self):
        """Ctor copies the caller's list so later mutation doesn't leak."""
        exts = [("*.usd", "USD")]
        bar = FileBar(file_extension_types=exts)
        exts.append(("*.png", "PNG"))
        assert bar._file_extension_types == [("*.usd", "USD")]


# ──────────────────────────────────────────────────────────────────────────────
# Build / destroy lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarBuild:
    def test_build_materialises_widgets(self, ephemeral_window):
        bar = FileBar(initial_filename="foo.usd")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar.is_built is True
            assert bar._field is not None
            assert bar._apply_button is not None
            assert bar._cancel_button is not None
        finally:
            bar.destroy()

    def test_build_no_combo_when_extensions_empty(self, ephemeral_window):
        bar = FileBar()
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar._combo is None
        finally:
            bar.destroy()

    def test_build_combo_when_extensions_provided(self, ephemeral_window):
        exts = [("*.usd", "USD Files"), ("*.*", "All files")]
        bar = FileBar(file_extension_types=exts)
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar._combo is not None
        finally:
            bar.destroy()

    def test_build_seeds_field_with_initial_filename(self, ephemeral_window):
        bar = FileBar(initial_filename="draft.usd")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar._field is not None
            assert bar._field.model.get_value_as_string() == "draft.usd"
        finally:
            bar.destroy()

    def test_build_button_identifiers(self, ephemeral_window):
        bar = FileBar()
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar._apply_button.identifier == APPLY_BUTTON_IDENTIFIER
            assert bar._cancel_button.identifier == CANCEL_BUTTON_IDENTIFIER
        finally:
            bar.destroy()


class TestFileBarDestroy:
    def test_destroy_nulls_references(self, ephemeral_window):
        bar = FileBar(initial_filename="a.usd")
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.destroy()
        assert bar._field is None
        assert bar._combo is None
        assert bar._apply_button is None
        assert bar._cancel_button is None
        assert bar.is_built is False

    def test_destroy_before_build_is_safe(self):
        bar = FileBar()
        bar.destroy()  # no raise

    def test_destroy_twice_is_idempotent(self, ephemeral_window):
        bar = FileBar()
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.destroy()
        bar.destroy()  # no raise

    def test_destroy_snapshots_filename(self, ephemeral_window):
        """Post-destroy :attr:`filename` returns the last typed value."""
        bar = FileBar()
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.filename = "typed.usd"
        bar.destroy()
        assert bar.filename == "typed.usd"

    def test_destroy_snapshots_extension_index(self, ephemeral_window):
        """Post-destroy :attr:`selected_extension` tracks the picked index."""
        exts = [("*.usd", "USD"), ("*.png", "PNG"), ("*.*", "All")]
        bar = FileBar(file_extension_types=exts)
        with in_window_frame(ephemeral_window):
            bar.build()
        bar._set_combo_index_for_test(1)
        bar.destroy()
        assert bar.selected_extension == ("*.png", "PNG")

    def test_destroy_clears_callbacks(self, ephemeral_window):
        """``on_apply`` / ``on_cancel`` are cleared so they do not leak."""
        bar = FileBar(
            initial_filename="a.usd",
            on_apply=lambda fn: None,
            on_cancel=lambda: None,
        )
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.destroy()
        assert bar._on_apply is None
        assert bar._on_cancel is None


# ──────────────────────────────────────────────────────────────────────────────
# Filename property
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarFilename:
    def test_get_filename_reads_cache_pre_build(self):
        bar = FileBar(initial_filename="cached.usd")
        assert bar.filename == "cached.usd"

    def test_get_filename_reads_field_post_build(self, ephemeral_window):
        bar = FileBar(initial_filename="seed.usd")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            # Mutate the live field directly; property reads it back.
            bar._field.model.set_value("mutated.usd")
            assert bar.filename == "mutated.usd"
        finally:
            bar.destroy()

    def test_set_filename_updates_cache_pre_build(self):
        bar = FileBar()
        bar.filename = "later.usd"
        assert bar.filename == "later.usd"

    def test_set_filename_updates_field_post_build(self, ephemeral_window):
        bar = FileBar()
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar.filename = "written.usd"
            assert bar._field.model.get_value_as_string() == "written.usd"
            assert bar.filename == "written.usd"
        finally:
            bar.destroy()

    def test_set_filename_none_normalises_to_empty(self):
        bar = FileBar(initial_filename="a.usd")
        bar.filename = None  # type: ignore[assignment]
        assert bar.filename == ""


# ──────────────────────────────────────────────────────────────────────────────
# Apply-enabled gate
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarApplyEnabled:
    def test_apply_disabled_when_empty_initial(self, ephemeral_window):
        bar = FileBar(initial_filename="")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar.apply_enabled is False
        finally:
            bar.destroy()

    def test_apply_enabled_when_initial_non_empty(self, ephemeral_window):
        bar = FileBar(initial_filename="foo.usd")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar.apply_enabled is True
        finally:
            bar.destroy()

    def test_apply_enables_on_set_filename(self, ephemeral_window):
        bar = FileBar(initial_filename="")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar.apply_enabled is False
            bar.filename = "typed.usd"
            assert bar.apply_enabled is True
        finally:
            bar.destroy()

    def test_apply_disables_when_cleared(self, ephemeral_window):
        bar = FileBar(initial_filename="foo.usd")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar.filename = ""
            assert bar.apply_enabled is False
        finally:
            bar.destroy()

    def test_apply_tracks_direct_field_mutation(self, ephemeral_window):
        """User typing (simulated via direct model mutation) re-enables Apply."""
        bar = FileBar(initial_filename="")
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            assert bar.apply_enabled is False
            bar._field.model.set_value("x")
            assert bar.apply_enabled is True
            bar._field.model.set_value("")
            assert bar.apply_enabled is False
        finally:
            bar.destroy()

    def test_apply_enabled_is_false_pre_build(self):
        bar = FileBar(initial_filename="foo.usd")
        # No button yet — apply_enabled is ``False`` by convention.
        assert bar.apply_enabled is False


# ──────────────────────────────────────────────────────────────────────────────
# Extension combo
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarExtensionCombo:
    def test_selected_extension_default_when_no_extensions(self):
        """No combo → falls back to the module default."""
        bar = FileBar()
        assert bar.selected_extension == ("*.*", "All files")

    def test_selected_extension_first_entry_by_default(self):
        exts = [("*.usd", "USD Files"), ("*.png", "PNG")]
        bar = FileBar(file_extension_types=exts)
        assert bar.selected_extension == ("*.usd", "USD Files")

    def test_selected_extension_tracks_combo_index(self, ephemeral_window):
        exts = [
            ("*.usd", "USD Files"),
            ("*.png", "PNG"),
            ("*.*", "All files"),
        ]
        bar = FileBar(file_extension_types=exts)
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar._set_combo_index_for_test(2)
            assert bar.selected_extension == ("*.*", "All files")
            bar._set_combo_index_for_test(1)
            assert bar.selected_extension == ("*.png", "PNG")
        finally:
            bar.destroy()

    def test_selected_extension_clamps_out_of_range(self):
        """A drifted cached index clamps to the last valid entry.

        Tests the cache-path clamp (pre-build / post-destroy) — when
        the combo is live, the combo's own value model is authoritative
        and ovui itself will not hand the property an out-of-range
        index. The clamp exists for the cache fallback when the combo
        reference is gone (post-destroy) or was never built.
        """
        exts = [("*.usd", "USD"), ("*.*", "All")]
        bar = FileBar(file_extension_types=exts)
        bar._selected_extension_index = 999
        assert bar.selected_extension == ("*.*", "All")
        bar._selected_extension_index = -5
        assert bar.selected_extension == ("*.usd", "USD")

    def test_selected_extension_reads_cache_pre_build(self):
        exts = [("*.usd", "USD"), ("*.png", "PNG")]
        bar = FileBar(file_extension_types=exts)
        bar._selected_extension_index = 1
        assert bar.selected_extension == ("*.png", "PNG")


# ──────────────────────────────────────────────────────────────────────────────
# Callbacks
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarCallbacks:
    def test_apply_fires_with_filename(self, ephemeral_window):
        calls: List[str] = []
        bar = FileBar(
            initial_filename="foo.usd",
            on_apply=lambda fn: calls.append(fn),
        )
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar._fire_apply_for_test()
            assert calls == ["foo.usd"]
        finally:
            bar.destroy()

    def test_apply_reads_latest_typed_value(self, ephemeral_window):
        calls: List[str] = []
        bar = FileBar(
            initial_filename="old.usd",
            on_apply=lambda fn: calls.append(fn),
        )
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar.filename = "new.usd"
            bar._fire_apply_for_test()
            assert calls == ["new.usd"]
        finally:
            bar.destroy()

    def test_cancel_fires_without_args(self, ephemeral_window):
        calls: List[Tuple[()]] = []
        bar = FileBar(on_cancel=lambda: calls.append(()))
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar._fire_cancel_for_test()
            assert calls == [()]
        finally:
            bar.destroy()

    def test_apply_none_callback_is_safe(self, ephemeral_window):
        bar = FileBar(initial_filename="foo.usd", on_apply=None)
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar._fire_apply_for_test()  # no raise
        finally:
            bar.destroy()

    def test_cancel_none_callback_is_safe(self, ephemeral_window):
        bar = FileBar(on_cancel=None)
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar._fire_cancel_for_test()  # no raise
        finally:
            bar.destroy()

    def test_apply_post_destroy_is_noop(self, ephemeral_window):
        calls: List[str] = []
        bar = FileBar(
            initial_filename="foo.usd",
            on_apply=lambda fn: calls.append(fn),
        )
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.destroy()
        bar._fire_apply_for_test()  # short-circuits on ``_apply_button is None``
        assert calls == []

    def test_cancel_post_destroy_is_noop(self, ephemeral_window):
        calls: List[Tuple[()]] = []
        bar = FileBar(on_cancel=lambda: calls.append(()))
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.destroy()
        bar._fire_cancel_for_test()  # short-circuits on ``_cancel_button is None``
        assert calls == []


# ──────────────────────────────────────────────────────────────────────────────
# Extension-changed callback (Step 49)
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarExtensionChangedCallback:
    """Step 49 — ``on_extension_changed`` fires when the combo selection changes."""

    _EXTS = [
        ("*.usd, *.usda", "USD Files"),
        ("*.png", "PNG"),
        ("*.*", "All files"),
    ]

    def test_extension_changed_stored(self):
        calls: List[Tuple[str, str]] = []
        bar = FileBar(
            file_extension_types=self._EXTS,
            on_extension_changed=lambda ext: calls.append(ext),
        )
        assert bar._on_extension_changed is not None

    def test_extension_changed_fires_on_combo_change(
        self, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        bar = FileBar(
            file_extension_types=self._EXTS,
            on_extension_changed=lambda ext: calls.append(ext),
        )
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            # Switch to index 1 — PNG.
            bar._set_combo_index_for_test(1)
            assert ("*.png", "PNG") in calls
        finally:
            bar.destroy()

    def test_extension_changed_fires_with_tuple_shape(
        self, ephemeral_window,
    ):
        """Callback receives the ``(pattern, description)`` tuple."""
        calls: List[Tuple[str, str]] = []
        bar = FileBar(
            file_extension_types=self._EXTS,
            on_extension_changed=lambda ext: calls.append(ext),
        )
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            bar._set_combo_index_for_test(2)
            assert calls[-1] == ("*.*", "All files")
        finally:
            bar.destroy()

    def test_extension_changed_none_callback_is_safe(
        self, ephemeral_window,
    ):
        """A bar with no ``on_extension_changed`` kwarg does not raise."""
        bar = FileBar(
            file_extension_types=self._EXTS,
            on_extension_changed=None,
        )
        try:
            with in_window_frame(ephemeral_window):
                bar.build()
            # Drive the combo; no raise.
            bar._set_combo_index_for_test(1)
        finally:
            bar.destroy()

    def test_extension_changed_cleared_on_destroy(
        self, ephemeral_window,
    ):
        calls: List[Tuple[str, str]] = []
        bar = FileBar(
            file_extension_types=self._EXTS,
            on_extension_changed=lambda ext: calls.append(ext),
        )
        with in_window_frame(ephemeral_window):
            bar.build()
        bar.destroy()
        assert bar._on_extension_changed is None


# ──────────────────────────────────────────────────────────────────────────────
# Label text
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBarLabel:
    def test_default_label_text(self):
        bar = FileBar()
        assert bar._label_text == "File name:"

    def test_folder_label_via_kwarg(self):
        """Callers can pass ``label_text="Folder name:"`` for folder pickers."""
        bar = FileBar(label_text="Folder name:")
        assert bar._label_text == "Folder name:"
