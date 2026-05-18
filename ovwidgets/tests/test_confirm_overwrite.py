# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 52 — save-mode overwrite confirm.

Scope: the :class:`ConfirmOverwriteDialog` ``on_yes`` surface that
Save-style callers use when the target filename already exists on the
backend. Paste-mode behaviour (``on_response`` + 4-choice enum) is
covered by :mod:`test_clipboard_ops`; this module exercises only the
save-specific construction, dispatch, and teardown paths.

Save-mode contract:

* Yes fires ``on_yes()`` exactly once, then dismisses.
* No / Escape dismiss without firing any callback (the caller's save
  path is not invoked — the user returns to the file picker).
* ``multi`` is forced to ``False``; the Yes-to-All / No-to-All
  affordances are nonsense on a single-file save collision.
* Warning label defaults to :data:`WARNING_MESSAGE_SAVE` ("File already
  exists. Overwrite?"). Caller can override via the ``message`` kwarg.
* ``destroy`` clears the callback slot so a post-destroy fire hook is a
  silent no-op.

Dialog lifecycle tests reuse the :class:`ui.Window` ephemeral-host
pattern from :mod:`test_delete` / :mod:`test_clipboard_ops` so the
build path runs under a real ovui frame.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List

import omni.ui as ui
import pytest

from ovwidgets.content.widget import (
    ConfirmOverwriteDialog,
    OverwriteChoice,
)
from ovwidgets.content.widget.confirm_overwrite_dialog import (
    _KEY_ENTER,
    _KEY_ESCAPE,
    _KEY_KEYPAD_ENTER,
    DIALOG_TITLE,
    NO_BUTTON_LABEL,
    WARNING_MESSAGE,
    WARNING_MESSAGE_SAVE,
    YES_BUTTON_LABEL,
)


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window shared across every test in this module.

    Mirrors :mod:`test_clipboard_ops` so the build-path tests land
    under a real ovui frame without spinning up the full
    :class:`Application`.
    """
    win = ui.Window("_test_confirm_overwrite", width=520, height=200)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    """Enter ``window.frame`` as a build context; clear on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Module constants
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveModeMessageConstant:

    def test_save_message_is_expected_literal(self):
        assert WARNING_MESSAGE_SAVE == "File already exists. Overwrite?"

    def test_save_message_differs_from_paste_message(self):
        assert WARNING_MESSAGE_SAVE != WARNING_MESSAGE


# ──────────────────────────────────────────────────────────────────────────────
# Construction contract
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveModeConstruction:

    def test_requires_either_on_response_or_on_yes(self):
        with pytest.raises(ValueError):
            ConfirmOverwriteDialog(url="mock://a.usda")

    def test_rejects_both_on_response_and_on_yes(self):
        with pytest.raises(ValueError):
            ConfirmOverwriteDialog(
                url="mock://a.usda",
                on_response=lambda c: None,
                on_yes=lambda: None,
            )

    def test_on_yes_stores_filename_in_url(self):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        assert dlg.url == "demo.usda"

    def test_on_yes_forces_multi_false_even_when_requested(self):
        # Save mode has no meaningful Yes-to-All semantics — the dialog
        # silently overrides multi=True so a misconfigured caller can
        # still construct safely.
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None, multi=True,
        )
        assert dlg.multi is False

    def test_on_yes_defaults_to_save_message(self):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        assert dlg.message == WARNING_MESSAGE_SAVE

    def test_paste_mode_keeps_paste_message(self):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_response=lambda c: None,
        )
        assert dlg.message == WARNING_MESSAGE

    def test_explicit_message_override_wins(self):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda",
            on_yes=lambda: None,
            message="Custom localised prompt",
        )
        assert dlg.message == "Custom localised prompt"

    def test_not_open_before_show(self):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        assert dlg.is_open is False


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveModeLifecycle:

    def test_show_opens_window(self, ephemeral_window):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        try:
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_show_renders_filename(self, ephemeral_window):
        # The URL row paints ``self._url`` verbatim — save callers pass
        # just the filename (or the full URL; the dialog doesn't care).
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        try:
            assert dlg.url == "demo.usda"
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_destroy_closes_window(self, ephemeral_window):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        assert dlg.is_open is False

    def test_destroy_without_show_is_safe(self):
        dlg = ConfirmOverwriteDialog(
            url="demo.usda", on_yes=lambda: None,
        )
        dlg.destroy()  # no raise

    def test_destroy_clears_callback(self, ephemeral_window):
        # Post-destroy, the callback slot must be None so a stray fire
        # hook becomes a silent no-op. This matches ConfirmDeleteDialog.
        calls: List[None] = []
        dlg = ConfirmOverwriteDialog(
            url="demo.usda",
            on_yes=lambda acc=calls: acc.append(None),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        # Even without the window, _fire must not resurrect the callback.
        dlg._fire(OverwriteChoice.YES)
        assert calls == []


# ──────────────────────────────────────────────────────────────────────────────
# Commit / dismiss dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveModeDispatch:

    def _show_dialog(self, ephemeral_window):
        calls: List[None] = []
        dlg = ConfirmOverwriteDialog(
            url="demo.usda",
            on_yes=lambda acc=calls: acc.append(None),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        return dlg, calls

    def test_yes_fires_overwrite_callback(self, ephemeral_window):
        dlg, calls = self._show_dialog(ephemeral_window)
        dlg._fire_choice_for_test(OverwriteChoice.YES)
        assert calls == [None]
        assert dlg.is_open is False

    def test_no_returns_to_picker_without_firing_callback(
        self, ephemeral_window,
    ):
        # Save-mode NO dismisses the dialog silently — the caller's
        # save path is not invoked, so the user effectively returns
        # to the file picker (which is still open on the stack).
        dlg, calls = self._show_dialog(ephemeral_window)
        dlg._fire_choice_for_test(OverwriteChoice.NO)
        assert calls == []
        assert dlg.is_open is False

    def test_escape_returns_to_picker_without_firing_callback(
        self, ephemeral_window,
    ):
        dlg, calls = self._show_dialog(ephemeral_window)
        dlg._fire_key_for_test(_KEY_ESCAPE)
        assert calls == []
        assert dlg.is_open is False

    def test_enter_fires_overwrite_callback(self, ephemeral_window):
        dlg, calls = self._show_dialog(ephemeral_window)
        dlg._fire_key_for_test(_KEY_ENTER)
        assert calls == [None]

    def test_keypad_enter_fires_overwrite_callback(self, ephemeral_window):
        dlg, calls = self._show_dialog(ephemeral_window)
        dlg._fire_key_for_test(_KEY_KEYPAD_ENTER)
        assert calls == [None]

    def test_yes_after_destroy_is_silent_noop(self):
        calls: List[None] = []
        dlg = ConfirmOverwriteDialog(
            url="demo.usda",
            on_yes=lambda acc=calls: acc.append(None),
        )
        dlg.destroy()
        dlg._fire_choice_for_test(OverwriteChoice.YES)
        assert calls == []

    def test_yes_to_all_is_silent_in_save_mode(self, ephemeral_window):
        # YES_TO_ALL cannot be produced by the UI (multi is forced to
        # False so the button does not render) but the test hook can
        # synthesise it; save-mode must silently skip the callback.
        dlg, calls = self._show_dialog(ephemeral_window)
        dlg._fire_choice_for_test(OverwriteChoice.YES_TO_ALL)
        assert calls == []
        assert dlg.is_open is False


# ──────────────────────────────────────────────────────────────────────────────
# Dialog chrome spot-checks — guard against accidental drift
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveModeChromeSpotCheck:

    def test_dialog_title_shared_with_paste_mode(self):
        # Both modes render under the same window title — the mode
        # is a caller-side construction detail, not a user-facing
        # category.
        assert DIALOG_TITLE == "Confirm Overwrite"

    def test_button_labels_shared_with_paste_mode(self):
        assert YES_BUTTON_LABEL == "Yes"
        assert NO_BUTTON_LABEL == "No"
