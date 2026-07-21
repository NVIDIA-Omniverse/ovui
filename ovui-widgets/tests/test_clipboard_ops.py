# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 36 — Copy / Cut / Paste menu actions.

Coverage:

* :class:`ConfirmOverwriteDialog` — public surface, show / destroy
  lifecycle, Yes / No / Yes-to-All / No-to-All dispatch, keyboard
  shortcuts, multi-button visibility.
* :class:`FileContextMenu` — :meth:`_copy_items` / :meth:`_cut_items`
  / :meth:`_begin_paste_into` against a :class:`MockBackend` (both
  collision-free and collision flows).
* :class:`FileBrowserWidget` clipboard dispatch — :meth:`copy_selected`
  / :meth:`cut_selected` / :meth:`paste_into_current` resolve the
  current multi-selection and route through the context menu.
* Cut style variant — :class:`FileCard` and the tree-row delegates
  apply the ``cut`` name when the card's URL is in a Cut clipboard.
* :class:`ContentBrowserWindow` proxies + application-level
  Ctrl+C / X / V dispatch.

Dialog tests follow the same ``ephemeral_window`` + ``in_window_frame``
pattern as :mod:`test_delete`. The integration tests monkey-patch
:class:`ErrorReporter` so the warning / error / success surfaces become
assertable without a live :class:`Application`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, List, Optional

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.content.backends.backend_adapter import BackendResult
from ovui_widgets.content.widget import (
    ConfirmOverwriteDialog,
    FileBrowserWidget,
    FileContextMenu,
    FileItem,
    OverwriteChoice,
    clipboard,
)
from ovui_widgets.content.widget.confirm_overwrite_dialog import (
    _KEY_ENTER,
    _KEY_ESCAPE,
    _KEY_KEYPAD_ENTER,
    DIALOG_TITLE,
    NO_ALL_BUTTON_LABEL,
    NO_BUTTON_LABEL,
    WARNING_MESSAGE,
    YES_ALL_BUTTON_LABEL,
    YES_BUTTON_LABEL,
)
from ovui_widgets.content.widget.confirm_overwrite_dialog import (
    ConfirmOverwriteDialog as _ConfirmOverwriteDialog,
)
from ovui_widgets.content.widget.context_menu import (
    _ERROR_COPY_FAILED,
    _ERROR_MOVE_FAILED,
    _STATUS_CLIPBOARD_COPIED_MULTI,
    _STATUS_CLIPBOARD_COPIED_SINGLE,
    _STATUS_COPIED_MULTI,
    _STATUS_COPIED_SINGLE,
    _STATUS_CUT_MULTI,
    _STATUS_CUT_SINGLE,
    _STATUS_MOVED_MULTI,
    _STATUS_MOVED_SINGLE,
    _WARN_NOTHING_TO_PASTE,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window shared across every test — same pattern as
    ``test_delete.py`` and the other content-browser widget modules."""
    win = ui.Window("_test_clipboard_ops", width=500, height=320)
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


@pytest.fixture(autouse=True)
def _reset_clipboard():
    """Every test starts with an empty clipboard.

    Clipboard state is process-global; without this fixture one test's
    leftover Cut state leaks into the next. Matches the
    :mod:`test_clipboard` module's same-named fixture.
    """
    clipboard.clear_clipboard()
    yield
    clipboard.clear_clipboard()


class _RecordedReport:
    """Captures every :class:`ErrorReporter` warning / error / success.

    Same shape as :class:`test_delete._RecordedReport` — kept as a
    separate copy rather than imported so the two modules stay
    independently runnable.
    """

    def __init__(self) -> None:
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.successes: List[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda msg, duration_ms=4000, r=self: r.warnings.append(msg),
        )
        monkeypatch.setattr(
            ErrorReporter, "show_error",
            lambda msg, duration_ms=5000, r=self: r.errors.append(msg),
        )
        monkeypatch.setattr(
            ErrorReporter, "show_success",
            lambda msg, duration_ms=3000, r=self: r.successes.append(msg),
        )


@pytest.fixture
def reporter(monkeypatch: pytest.MonkeyPatch) -> _RecordedReport:
    r = _RecordedReport()
    r.install(monkeypatch)
    return r


# ──────────────────────────────────────────────────────────────────────────────
# ConfirmOverwriteDialog — public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestConfirmOverwriteDialogSurface:

    def test_reexported_from_widget_package(self):
        assert ConfirmOverwriteDialog is _ConfirmOverwriteDialog

    def test_widget_package_all_contains_dialog(self):
        import ovui_widgets.content.widget as pkg

        assert "ConfirmOverwriteDialog" in pkg.__all__
        assert "OverwriteChoice" in pkg.__all__

    def test_dialog_strings_are_constants(self):
        assert DIALOG_TITLE == "Confirm Overwrite"
        assert WARNING_MESSAGE == "An item with that name already exists:"
        assert YES_BUTTON_LABEL == "Yes"
        assert NO_BUTTON_LABEL == "No"
        assert YES_ALL_BUTTON_LABEL == "Yes to All"
        assert NO_ALL_BUTTON_LABEL == "No to All"

    def test_overwrite_choice_has_four_members(self):
        assert set(c.name for c in OverwriteChoice) == {
            "YES", "NO", "YES_TO_ALL", "NO_TO_ALL",
        }


class TestConfirmOverwriteDialogConstruction:

    def test_url_stored(self):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        assert dlg.url == "mock://a.usda"

    def test_multi_defaults_to_false(self):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        assert dlg.multi is False

    def test_multi_true_when_requested(self):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda",
            on_response=lambda c: None,
            multi=True,
        )
        assert dlg.multi is True

    def test_not_open_before_show(self):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        assert dlg.is_open is False


class TestConfirmOverwriteDialogLifecycle:

    def test_show_opens_window(self, ephemeral_window):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        try:
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_show_twice_is_idempotent(self, ephemeral_window):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        try:
            window_ref = dlg._window
            with in_window_frame(ephemeral_window):
                dlg.show()
            assert dlg._window is window_ref
        finally:
            dlg.destroy()

    def test_destroy_closes_window(self, ephemeral_window):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        assert dlg.is_open is False

    def test_destroy_without_show_is_safe(self):
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda", on_response=lambda c: None,
        )
        dlg.destroy()  # no raise


class TestConfirmOverwriteDialogCommit:

    def _show_dialog(
        self, ephemeral_window, multi: bool = False,
    ):
        """Build a dialog and track the user's choice."""
        choices: List[OverwriteChoice] = []
        dlg = ConfirmOverwriteDialog(
            url="mock://collide.usda",
            on_response=lambda c, acc=choices: acc.append(c),
            multi=multi,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        return dlg, choices

    def test_yes_fires_yes_choice(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window)
        dlg._fire_choice_for_test(OverwriteChoice.YES)
        assert choices == [OverwriteChoice.YES]
        assert dlg.is_open is False

    def test_no_fires_no_choice(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window)
        dlg._fire_choice_for_test(OverwriteChoice.NO)
        assert choices == [OverwriteChoice.NO]

    def test_yes_to_all_fires_yes_to_all_choice(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window, multi=True)
        dlg._fire_choice_for_test(OverwriteChoice.YES_TO_ALL)
        assert choices == [OverwriteChoice.YES_TO_ALL]

    def test_no_to_all_fires_no_to_all_choice(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window, multi=True)
        dlg._fire_choice_for_test(OverwriteChoice.NO_TO_ALL)
        assert choices == [OverwriteChoice.NO_TO_ALL]

    def test_enter_fires_yes(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window)
        dlg._fire_key_for_test(_KEY_ENTER)
        assert choices == [OverwriteChoice.YES]

    def test_keypad_enter_fires_yes(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window)
        dlg._fire_key_for_test(_KEY_KEYPAD_ENTER)
        assert choices == [OverwriteChoice.YES]

    def test_escape_fires_no(self, ephemeral_window):
        dlg, choices = self._show_dialog(ephemeral_window)
        dlg._fire_key_for_test(_KEY_ESCAPE)
        assert choices == [OverwriteChoice.NO]

    def test_choice_after_destroy_is_noop(self):
        choices: List[OverwriteChoice] = []
        dlg = ConfirmOverwriteDialog(
            url="mock://a.usda",
            on_response=lambda c, acc=choices: acc.append(c),
        )
        dlg.destroy()
        dlg._fire_choice_for_test(OverwriteChoice.YES)
        assert choices == []


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — Copy / Cut on the clipboard
# ──────────────────────────────────────────────────────────────────────────────


class _FakeWidget:
    """Minimal widget surface the clipboard menu helpers read."""

    def __init__(
        self,
        backend: Any = None,
        detail_model: Any = None,
        tree_model: Any = None,
    ) -> None:
        self._backend = backend
        self._detail_model = detail_model
        self._tree_model = tree_model
        self.refresh_cut_style_calls = 0

    def refresh_cut_style(self) -> None:
        self.refresh_cut_style_calls += 1


class _FakeModel:
    def __init__(
        self,
        root_url: str = "mock://Home/Documents/Projects",
        resolved: Optional[dict] = None,
    ) -> None:
        self.root_url = root_url
        self._resolved = resolved or {}
        self.refresh_item_calls: List[FileItem] = []
        self.refresh_all_count = 0

    def resolve(self, url: str) -> Optional[FileItem]:
        return self._resolved.get(url)

    def refresh_item(self, item: FileItem) -> None:
        self.refresh_item_calls.append(item)

    def refresh_all(self) -> None:
        self.refresh_all_count += 1


class TestCopyItems:

    def test_single_item_populates_clipboard_as_copy(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(
            url="mock://Home/a.usda", name="a.usda", is_folder=False,
        )
        menu._copy_items([item])
        assert clipboard.get_clipboard_urls() == ["mock://Home/a.usda"]
        assert clipboard.is_clipboard_cut() is False

    def test_multi_item_preserves_order(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        items = [
            FileItem(url="mock://a", name="a", is_folder=False),
            FileItem(url="mock://b", name="b", is_folder=False),
            FileItem(url="mock://c", name="c", is_folder=False),
        ]
        menu._copy_items(items)
        assert clipboard.get_clipboard_urls() == [
            "mock://a", "mock://b", "mock://c",
        ]

    def test_triggers_cut_style_refresh(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(
            url="mock://Home/a.usda", name="a.usda", is_folder=False,
        )
        menu._copy_items([item])
        assert widget.refresh_cut_style_calls == 1

    def test_single_reports_status(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(url="mock://a", name="a", is_folder=False)
        menu._copy_items([item])
        assert reporter.successes == [_STATUS_CLIPBOARD_COPIED_SINGLE]

    def test_multi_reports_status_with_count(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        items = [
            FileItem(url="mock://a", name="a", is_folder=False),
            FileItem(url="mock://b", name="b", is_folder=False),
        ]
        menu._copy_items(items)
        assert reporter.successes == [
            _STATUS_CLIPBOARD_COPIED_MULTI.format(count=2),
        ]

    def test_empty_list_is_noop(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        menu._copy_items([])
        assert clipboard.get_clipboard_urls() == []
        assert reporter.successes == []
        assert widget.refresh_cut_style_calls == 0

    def test_post_destroy_is_noop(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        menu.destroy()
        item = FileItem(url="mock://a", name="a", is_folder=False)
        menu._copy_items([item])
        assert clipboard.get_clipboard_urls() == []


class TestCutItems:

    def test_single_item_populates_clipboard_as_cut(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(
            url="mock://Home/a.usda", name="a.usda", is_folder=False,
        )
        menu._cut_items([item])
        assert clipboard.get_clipboard_urls() == ["mock://Home/a.usda"]
        assert clipboard.is_clipboard_cut() is True
        assert clipboard.is_path_cut("mock://Home/a.usda") is True

    def test_triggers_cut_style_refresh(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(url="mock://a", name="a", is_folder=False)
        menu._cut_items([item])
        assert widget.refresh_cut_style_calls == 1

    def test_single_reports_status(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(url="mock://a", name="a", is_folder=False)
        menu._cut_items([item])
        assert reporter.successes == [_STATUS_CUT_SINGLE]

    def test_multi_reports_status_with_count(self, reporter):
        widget = _FakeWidget()
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        items = [
            FileItem(url="mock://a", name="a", is_folder=False),
            FileItem(url="mock://b", name="b", is_folder=False),
            FileItem(url="mock://c", name="c", is_folder=False),
        ]
        menu._cut_items(items)
        assert reporter.successes == [
            _STATUS_CUT_MULTI.format(count=3),
        ]


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — Paste against MockBackend
# ──────────────────────────────────────────────────────────────────────────────


def _make_menu_with_backend(
    backend: MockBackend,
    root_url: str = "mock://Home/Documents/Projects",
) -> tuple:
    """Build a context menu + fake widget wrapping ``backend``.

    Returns ``(menu, widget, detail_model)`` so tests can reach
    refresh state and detail-model.resolve assertions without rebuilding
    the fakes.
    """
    # Pre-resolve a parent FileItem for the detail model so refreshes
    # land on it; :meth:`_refresh_parent_after_create` walks
    # ``detail_model.resolve(parent)``.
    resolved_item = FileItem(url=root_url, name="Projects", is_folder=True)
    detail = _FakeModel(root_url=root_url, resolved={root_url: resolved_item})
    widget = _FakeWidget(
        backend=backend, detail_model=detail,
    )
    menu = FileContextMenu(widget)  # type: ignore[arg-type]
    return menu, widget, detail


class TestPasteCopy:
    """Copy + Paste duplicates files into the destination folder."""

    def test_copy_paste_single_file_into_same_folder_as_sibling(
        self, reporter,
    ):
        # Paste into a different folder so the source and destination
        # do not collide on URL.
        backend = MockBackend()
        menu, widget, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"],
            is_cut=False,
        )
        menu._begin_paste_into(None)  # paste into root_url folder
        # Source still there, destination created.
        src_result, _ = backend.stat(
            "mock://Home/Documents/Projects/demo.usda",
        )
        dst_result, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert src_result == BackendResult.OK
        assert dst_result == BackendResult.OK
        assert reporter.successes == [_STATUS_COPIED_SINGLE]

    def test_copy_paste_multiple_files(self, reporter):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            [
                "mock://Home/Documents/Projects/demo.usda",
                "mock://Home/Documents/Projects/demo.usdc",
            ],
            is_cut=False,
        )
        menu._begin_paste_into(None)
        r1, _ = backend.stat("mock://Home/Textures/demo.usda")
        r2, _ = backend.stat("mock://Home/Textures/demo.usdc")
        assert r1 == BackendResult.OK
        assert r2 == BackendResult.OK
        assert reporter.successes == [
            _STATUS_COPIED_MULTI.format(count=2),
        ]

    def test_copy_paste_does_not_clear_clipboard(self, reporter):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"], is_cut=False,
        )
        menu._begin_paste_into(None)
        # Clipboard still holds the URLs — repeat-paste of a Copy is
        # standard behaviour.
        assert clipboard.get_clipboard_urls() == [
            "mock://Home/Documents/Projects/demo.usda",
        ]
        assert clipboard.is_clipboard_cut() is False


class TestPasteCut:
    """Cut + Paste moves files from the source to the destination."""

    def test_cut_paste_moves_file(self, reporter):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"], is_cut=True,
        )
        menu._begin_paste_into(None)
        # Source gone, destination present.
        src_result, _ = backend.stat(
            "mock://Home/Documents/Projects/demo.usda",
        )
        dst_result, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert src_result == BackendResult.ERROR_NOT_FOUND
        assert dst_result == BackendResult.OK
        assert reporter.successes == [_STATUS_MOVED_SINGLE]

    def test_cut_paste_clears_clipboard(self, reporter):
        backend = MockBackend()
        menu, widget, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"], is_cut=True,
        )
        menu._begin_paste_into(None)
        assert clipboard.get_clipboard_urls() == []
        assert clipboard.is_clipboard_cut() is False
        # refresh_cut_style fires after the clipboard clear so the
        # ``::Cut`` variant repaints off the (now relocated) source.
        assert widget.refresh_cut_style_calls == 1

    def test_cut_paste_multi_moves_all(self, reporter):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            [
                "mock://Home/Documents/Projects/demo.usda",
                "mock://Home/Documents/Projects/demo.usdc",
            ],
            is_cut=True,
        )
        menu._begin_paste_into(None)
        r1, _ = backend.stat(
            "mock://Home/Documents/Projects/demo.usda",
        )
        r2, _ = backend.stat(
            "mock://Home/Documents/Projects/demo.usdc",
        )
        assert r1 == BackendResult.ERROR_NOT_FOUND
        assert r2 == BackendResult.ERROR_NOT_FOUND
        d1, _ = backend.stat("mock://Home/Textures/demo.usda")
        d2, _ = backend.stat("mock://Home/Textures/demo.usdc")
        assert d1 == BackendResult.OK
        assert d2 == BackendResult.OK
        assert reporter.successes == [
            _STATUS_MOVED_MULTI.format(count=2),
        ]


class TestPasteGuards:

    def test_empty_clipboard_warns_and_noops(self, reporter):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(backend)
        menu._begin_paste_into(None)
        assert reporter.warnings == [_WARN_NOTHING_TO_PASTE]
        assert menu._paste_state is None

    def test_paste_onto_file_target_refuses(self, reporter):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(backend)
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"],
        )
        file_item = FileItem(
            url="mock://Home/Textures/concrete.png",
            name="concrete.png", is_folder=False,
        )
        menu._begin_paste_into(file_item)
        # Warning fired about missing destination.
        assert len(reporter.warnings) == 1
        # Paste never ran.
        assert menu._paste_state is None

    def test_paste_into_folder_target_uses_folder_url(
        self, reporter,
    ):
        backend = MockBackend()
        menu, _, _ = _make_menu_with_backend(backend)
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"],
        )
        folder_item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        menu._begin_paste_into(folder_item)
        r, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert r == BackendResult.OK


class TestPasteCollision:
    """Collision flow: the overwrite dialog drives per-item decisions."""

    def _seed_existing(self, backend: MockBackend) -> None:
        # Create a collision target: copy demo.usda into Textures so a
        # subsequent paste lands on the same URL.
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )

    def test_collision_pops_overwrite_dialog(
        self, reporter, monkeypatch,
    ):
        backend = MockBackend()
        self._seed_existing(backend)
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        # Patch the dialog's show so tests run headlessly.
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"], is_cut=False,
        )
        menu._begin_paste_into(None)
        # Dialog should be live, with the colliding dst URL.
        assert menu._confirm_overwrite_dialog is not None
        assert menu._confirm_overwrite_dialog.url == (
            "mock://Home/Textures/demo.usda"
        )
        # Single-item paste → multi flag is False.
        assert menu._confirm_overwrite_dialog.multi is False

    def test_yes_overwrites(self, reporter, monkeypatch):
        backend = MockBackend()
        self._seed_existing(backend)
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"], is_cut=False,
        )
        menu._begin_paste_into(None)
        menu._on_overwrite_choice(OverwriteChoice.YES)
        # Copy succeeded with overwrite — destination exists, source
        # also exists (copy, not cut).
        r, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert r == BackendResult.OK
        assert reporter.successes == [_STATUS_COPIED_SINGLE]

    def test_no_skips(self, reporter, monkeypatch):
        backend = MockBackend()
        self._seed_existing(backend)
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        clipboard.save_to_clipboard(
            ["mock://Home/Documents/Projects/demo.usda"], is_cut=False,
        )
        menu._begin_paste_into(None)
        menu._on_overwrite_choice(OverwriteChoice.NO)
        # No success message — the one item was skipped.
        assert reporter.successes == []
        # Destination file still present (was there before the skip).
        r, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert r == BackendResult.OK

    def test_yes_to_all_applies_to_remaining(
        self, reporter, monkeypatch,
    ):
        # Two collisions — after Yes-to-All, the second should not
        # spawn a dialog.
        backend = MockBackend()
        self._seed_existing(backend)
        # Add a second collision target.
        backend.copy(
            "mock://Home/Documents/Projects/demo.usdc",
            "mock://Home/Textures/demo.usdc",
        )
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        clipboard.save_to_clipboard(
            [
                "mock://Home/Documents/Projects/demo.usda",
                "mock://Home/Documents/Projects/demo.usdc",
            ],
            is_cut=False,
        )
        menu._begin_paste_into(None)
        assert menu._confirm_overwrite_dialog is not None
        assert menu._confirm_overwrite_dialog.multi is True
        menu._on_overwrite_choice(OverwriteChoice.YES_TO_ALL)
        # Both URLs got through without a second dialog.
        assert menu._confirm_overwrite_dialog is None
        assert reporter.successes == [
            _STATUS_COPIED_MULTI.format(count=2),
        ]

    def test_no_to_all_skips_remaining(
        self, reporter, monkeypatch,
    ):
        backend = MockBackend()
        self._seed_existing(backend)
        backend.copy(
            "mock://Home/Documents/Projects/demo.usdc",
            "mock://Home/Textures/demo.usdc",
        )
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        clipboard.save_to_clipboard(
            [
                "mock://Home/Documents/Projects/demo.usda",
                "mock://Home/Documents/Projects/demo.usdc",
            ],
            is_cut=False,
        )
        menu._begin_paste_into(None)
        menu._on_overwrite_choice(OverwriteChoice.NO_TO_ALL)
        assert menu._confirm_overwrite_dialog is None
        # No successful copies — every item skipped.
        assert reporter.successes == []


class TestPasteErrorReporting:

    def test_non_collision_error_surfaces_and_continues(
        self, reporter,
    ):
        backend = MockBackend()
        # Inject an error on one source URL.
        bad = "mock://Home/Documents/Projects/demo.usda"
        backend._errors[bad] = BackendResult.ERROR_ACCESS_DENIED
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard(
            [bad, "mock://Home/Documents/Projects/demo.usdc"],
            is_cut=False,
        )
        menu._begin_paste_into(None)
        # Error for the bad URL, success for the other.
        assert reporter.errors == [
            _ERROR_COPY_FAILED.format(url=bad, reason="ERROR_ACCESS_DENIED"),
        ]
        assert reporter.successes == [_STATUS_COPIED_SINGLE]
        r, _ = backend.stat("mock://Home/Textures/demo.usdc")
        assert r == BackendResult.OK

    def test_cut_error_uses_move_message(self, reporter):
        backend = MockBackend()
        bad = "mock://Home/Documents/Projects/demo.usda"
        backend._errors[bad] = BackendResult.ERROR_ACCESS_DENIED
        menu, _, _ = _make_menu_with_backend(
            backend, root_url="mock://Home/Textures",
        )
        clipboard.save_to_clipboard([bad], is_cut=True)
        menu._begin_paste_into(None)
        assert reporter.errors == [
            _ERROR_MOVE_FAILED.format(
                url=bad, reason="ERROR_ACCESS_DENIED",
            ),
        ]


# ──────────────────────────────────────────────────────────────────────────────
# Widget + window integration
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetClipboardDispatch:

    def test_copy_selected_reads_grid_selection(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            widget._detail_model.get_item_children(None)
            demo = widget._detail_model.resolve(
                "mock://Home/Documents/Projects/demo.usda",
            )
            assert demo is not None
            # Force grid view so get_selection is consulted.
            widget._is_grid_view = True

            class _FakeGrid:
                def __init__(self, items):
                    self._items = items

                def get_selection(self):
                    return list(self._items)

                def set_rename_controller(self, ctrl):
                    pass

                def destroy(self):
                    pass

                def refresh(self):
                    pass

            widget._detail_grid_view = _FakeGrid([demo])  # type: ignore[assignment]
            widget.copy_selected()
            assert clipboard.get_clipboard_urls() == [
                "mock://Home/Documents/Projects/demo.usda",
            ]
            assert clipboard.is_clipboard_cut() is False
        finally:
            widget.destroy()

    def test_cut_selected_reads_detail_tree_selection(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            widget._detail_model.get_item_children(None)
            demo = widget._detail_model.resolve(
                "mock://Home/Documents/Projects/demo.usda",
            )
            democ = widget._detail_model.resolve(
                "mock://Home/Documents/Projects/demo.usdc",
            )
            assert demo is not None and democ is not None
            widget._is_grid_view = False

            class _FakeTreeView:
                def __init__(self, items):
                    self.selection = items

                def set_mouse_double_clicked_fn(self, fn):
                    pass

            widget._detail_tree_view = _FakeTreeView(  # type: ignore[assignment]
                [demo, democ],
            )
            widget.cut_selected()
            assert clipboard.get_clipboard_urls() == [
                "mock://Home/Documents/Projects/demo.usda",
                "mock://Home/Documents/Projects/demo.usdc",
            ]
            assert clipboard.is_clipboard_cut() is True
        finally:
            widget.destroy()

    def test_paste_into_current_fires_into_detail_root(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home/Textures")
        try:
            clipboard.save_to_clipboard(
                ["mock://Home/Documents/Projects/demo.usda"],
                is_cut=False,
            )
            widget.paste_into_current()
            r, _ = backend.stat("mock://Home/Textures/demo.usda")
            assert r == BackendResult.OK
        finally:
            widget.destroy()

    def test_copy_with_empty_selection_is_noop(
        self, ephemeral_window, reporter,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            widget.copy_selected()
            assert clipboard.get_clipboard_urls() == []
            assert reporter.successes == []
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileCard / TreeFolderDelegate — cut style application
# ──────────────────────────────────────────────────────────────────────────────


class TestFileCardCutStyle:

    def test_label_name_empty_when_not_cut(self, ephemeral_window):
        from ovui_widgets.content.widget.file_card import FileCard

        item = FileItem(url="mock://a.usda", name="a.usda", is_folder=False)
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        try:
            # Label exists and has no variant name applied.
            assert card._label is not None
            assert card._label.name == ""
        finally:
            card.destroy()

    def test_label_name_is_cut_when_cut(self, ephemeral_window):
        from ovui_widgets.content.widget.file_card import FileCard

        item = FileItem(url="mock://a.usda", name="a.usda", is_folder=False)
        clipboard.save_to_clipboard([item.url], is_cut=True)
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        try:
            assert card._label is not None
            assert card._label.name == "cut"
        finally:
            card.destroy()

    def test_label_name_empty_when_copy_mode(self, ephemeral_window):
        from ovui_widgets.content.widget.file_card import FileCard

        item = FileItem(url="mock://a.usda", name="a.usda", is_folder=False)
        # Copy mode — the card should NOT render as cut.
        clipboard.save_to_clipboard([item.url], is_cut=False)
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        try:
            assert card._label is not None
            assert card._label.name == ""
        finally:
            card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Application-level Ctrl+C / Ctrl+X / Ctrl+V dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestApplicationClipboardKeyDispatch:
    """Covers :meth:`Application._on_key_pressed` Ctrl+C / Ctrl+X / Ctrl+V.

    Mirrors :class:`TestApplicationDeleteKeyDispatch` in ``test_delete.py``
    — builds the app via :meth:`Application.__new__` (bypass singleton
    + init requirements) so every dependency can be stubbed cleanly.
    """

    def _app(self):
        """Build a bare :class:`Application` with the fields
        :meth:`_on_key_pressed` reads stubbed to no-op values."""
        from ovui_widgets.app.application import Application

        class _SelBus:
            def get_snapshot(self):
                return None

        app = Application.__new__(Application)
        app._viewport_window = None
        app._undo_manager = None
        app._main_win = None
        app._property_window = None
        app._selection_bus = _SelBus()
        app._stage_adapter = None
        app._stage_window = None
        app._content_window = None
        return app

    def test_ctrl_c_calls_content_window_copy(self):
        from ovui_widgets.app import application as app_mod

        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def copy_selected(self_inner) -> None:
                calls.append("copy")

            def cut_selected(self_inner) -> None:
                calls.append("cut")

            def paste_into_current(self_inner) -> None:
                calls.append("paste")

        app._content_window = _FakeWin()  # type: ignore[assignment]
        # Dispatch Ctrl+C / Ctrl+X / Ctrl+V.
        app._on_key_pressed(ord("C"), app_mod._MOD_CTRL, True)
        app._on_key_pressed(ord("X"), app_mod._MOD_CTRL, True)
        app._on_key_pressed(ord("V"), app_mod._MOD_CTRL, True)
        assert calls == ["copy", "cut", "paste"]

    def test_ctrl_c_lowercase_also_dispatches(self):
        from ovui_widgets.app import application as app_mod

        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def copy_selected(self_inner) -> None:
                calls.append("copy")

            def cut_selected(self_inner) -> None:
                pass

            def paste_into_current(self_inner) -> None:
                pass

        app._content_window = _FakeWin()  # type: ignore[assignment]
        # Lowercase 'c' with ctrl modifier should also route to copy —
        # ovui reports the raw key code regardless of Shift state.
        app._on_key_pressed(ord("c"), app_mod._MOD_CTRL, True)
        assert calls == ["copy"]

    def test_ctrl_c_without_content_window_is_noop(self):
        from ovui_widgets.app import application as app_mod

        app = self._app()
        # No _content_window wired — must not raise.
        app._on_key_pressed(ord("C"), app_mod._MOD_CTRL, True)

    def test_plain_c_without_ctrl_is_noop(self):
        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def copy_selected(self_inner) -> None:
                calls.append("copy")

            def cut_selected(self_inner) -> None:
                calls.append("cut")

            def paste_into_current(self_inner) -> None:
                calls.append("paste")

        app._content_window = _FakeWin()  # type: ignore[assignment]
        # Plain c (no modifier) must not trigger copy.
        app._on_key_pressed(ord("c"), 0, True)
        assert calls == []

    def test_ctrl_shift_c_does_not_fire(self):
        from ovui_widgets.app import application as app_mod

        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def copy_selected(self_inner) -> None:
                calls.append("copy")

            def cut_selected(self_inner) -> None:
                pass

            def paste_into_current(self_inner) -> None:
                pass

        app._content_window = _FakeWin()  # type: ignore[assignment]
        # Ctrl+Shift+C — the shortcut guard requires ``not shift``.
        app._on_key_pressed(
            ord("C"),
            app_mod._MOD_CTRL | app_mod._MOD_SHIFT,
            True,
        )
        assert calls == []


# ──────────────────────────────────────────────────────────────────────────────
# ContentBrowserWindow proxies
# ──────────────────────────────────────────────────────────────────────────────


class TestContentBrowserWindowClipboardProxies:

    def test_copy_selected_forwards_to_widget(self):
        from ovui_widgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        # The constructor calls super().__init__ which builds a real
        # window — but by not invoking _build_ui we leave the widget
        # None and just verify the proxy short-circuits safely.
        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = None
        # No-op with widget=None — must not raise.
        win.copy_selected()
        win.cut_selected()
        win.paste_into_current()

    def test_proxy_calls_widget_method_when_present(self):
        from ovui_widgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        calls: List[str] = []

        class _FakeWidget:
            def copy_selected(self_inner) -> None:
                calls.append("copy")

            def cut_selected(self_inner) -> None:
                calls.append("cut")

            def paste_into_current(self_inner) -> None:
                calls.append("paste")

        win._widget = _FakeWidget()  # type: ignore[assignment]
        win.copy_selected()
        win.cut_selected()
        win.paste_into_current()
        assert calls == ["copy", "cut", "paste"]


# ──────────────────────────────────────────────────────────────────────────────
# Menu spec entry presence (regression guard)
# ──────────────────────────────────────────────────────────────────────────────


class TestMenuSpecEntries:

    def _menu(self) -> FileContextMenu:
        return FileContextMenu(_FakeWidget())  # type: ignore[arg-type]

    def test_file_menu_has_copy_and_cut(self):
        names = [s.name for s in self._menu()._file_specs()]
        assert "Copy" in names
        assert "Cut" in names
        # Paste is intentionally absent on a file target.
        assert "Paste" not in names

    def test_folder_menu_has_copy_cut_paste(self):
        names = [s.name for s in self._menu()._folder_specs()]
        assert "Copy" in names
        assert "Cut" in names
        assert "Paste" in names

    def test_empty_menu_has_paste_not_cut_or_copy(self):
        names = [s.name for s in self._menu()._empty_specs()]
        assert "Paste" in names
        assert "Cut" not in names
        assert "Copy" not in names
