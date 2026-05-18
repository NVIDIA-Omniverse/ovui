# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 34 — Delete with confirmation dialog.

Coverage:

* :class:`ConfirmDeleteDialog` — surface, show / destroy lifecycle,
  Yes / No dispatch, Enter / Escape keybindings, test hooks for driving
  the dialog headlessly.
* :class:`FileContextMenu` Delete wiring — single-item dialog open from
  both file and folder menus, end-to-end delete flow against
  :class:`MockBackend`, backend-error surfacing through
  :class:`ErrorReporter`, post-delete model refresh.
* :class:`FileBrowserWidget` integration — :meth:`delete_selected`
  resolves multi-selection across grid / detail-tree / tree panes and
  shows the dialog; confirming removes every selected item.
* :meth:`MockBackend.delete` / :meth:`LocalFSBackend.delete` —
  real-backend round-trip on files and folders (recursive).
* :class:`ContentBrowserWindow.delete_selected` proxy + application-
  level Del key dispatch.

Dialog tests follow the same pattern as ``tests/test_file_ops.py``:
a module-scoped ``ephemeral_window`` fixture + an ``in_window_frame``
context manager so every :class:`ui.Window` open happens inside a real
ovui root. The integration tests monkey-patch :class:`ErrorReporter`
classmethods so the warning / error / success surfaces become assertable
without depending on a live status-bar label.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Any, List, Optional, Tuple

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.error_reporter import ErrorReporter
from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend
from ovwidgets.content.widget import (
    ConfirmDeleteDialog,
    FileBrowserWidget,
    FileContextMenu,
    FileItem,
)
from ovwidgets.content.widget.confirm_delete_dialog import (
    _KEY_ENTER,
    _KEY_ESCAPE,
    _KEY_KEYPAD_ENTER,
    DIALOG_TITLE,
    NO_BUTTON_LABEL,
    WARNING_MESSAGE,
    YES_BUTTON_LABEL,
)
from ovwidgets.content.widget.confirm_delete_dialog import (
    ConfirmDeleteDialog as _ConfirmDeleteDialog,
)
from ovwidgets.content.widget.context_menu import (
    _ERROR_DELETE_FAILED,
    _STATUS_DELETE_DONE_MULTI,
    _STATUS_DELETE_DONE_SINGLE,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window shared across every test — same pattern as the
    other content-browser widget modules."""
    win = ui.Window("_test_delete", width=500, height=320)
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


class _RecordedReport:
    """Captures every :class:`ErrorReporter` warning / error / success.

    The reporter's surfaces are classmethods, so monkey-patching them
    forwards to a per-test list without needing a running
    :class:`Application`.
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
# ConfirmDeleteDialog — public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestConfirmDeleteDialogSurface:
    def test_reexported_from_widget_package(self):
        assert ConfirmDeleteDialog is _ConfirmDeleteDialog

    def test_widget_package_all_contains_confirm_delete_dialog(self):
        import ovwidgets.content.widget as pkg

        assert "ConfirmDeleteDialog" in pkg.__all__

    def test_dialog_strings_are_constants(self):
        assert WARNING_MESSAGE == "This cannot be undone."
        assert DIALOG_TITLE == "Confirm Delete"
        assert YES_BUTTON_LABEL == "Yes"
        assert NO_BUTTON_LABEL == "No"


class TestConfirmDeleteDialogConstruction:
    def test_urls_stored_as_list_copy(self):
        src = ["mock://a", "mock://b"]
        dlg = ConfirmDeleteDialog(urls=src, on_yes=lambda: None)
        # The dialog copies the list so caller mutation does not affect
        # the rendered set.
        src.append("mock://c")
        assert dlg.urls == ["mock://a", "mock://b"]

    def test_urls_returns_fresh_copy(self):
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"], on_yes=lambda: None,
        )
        snapshot = dlg.urls
        snapshot.append("mock://b")
        assert dlg.urls == ["mock://a"]

    def test_not_open_before_show(self):
        dlg = ConfirmDeleteDialog(urls=[], on_yes=lambda: None)
        assert dlg.is_open is False


class TestConfirmDeleteDialogLifecycle:
    def test_show_opens_window(self, ephemeral_window):
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"], on_yes=lambda: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        try:
            assert dlg.is_open is True
        finally:
            dlg.destroy()

    def test_show_twice_is_idempotent(self, ephemeral_window):
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"], on_yes=lambda: None,
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
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"], on_yes=lambda: None,
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg.destroy()
        assert dlg.is_open is False

    def test_destroy_without_show_is_safe(self):
        dlg = ConfirmDeleteDialog(urls=[], on_yes=lambda: None)
        dlg.destroy()  # no raise


class TestConfirmDeleteDialogCommit:
    def test_yes_fires_on_yes_and_dismisses(self, ephemeral_window):
        calls: List[str] = []
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"],
            on_yes=lambda: calls.append("yes"),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg._fire_yes_for_test()
        assert calls == ["yes"]
        assert dlg.is_open is False

    def test_no_does_not_fire_on_yes(self, ephemeral_window):
        calls: List[str] = []
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"],
            on_yes=lambda: calls.append("yes"),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg._fire_no_for_test()
        assert calls == []
        assert dlg.is_open is False

    def test_enter_fires_on_yes(self, ephemeral_window):
        calls: List[str] = []
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"],
            on_yes=lambda: calls.append("yes"),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg._fire_key_for_test(_KEY_ENTER)
        assert calls == ["yes"]

    def test_keypad_enter_fires_on_yes(self, ephemeral_window):
        calls: List[str] = []
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"],
            on_yes=lambda: calls.append("yes"),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg._fire_key_for_test(_KEY_KEYPAD_ENTER)
        assert calls == ["yes"]

    def test_escape_dismisses_without_firing(self, ephemeral_window):
        calls: List[str] = []
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"],
            on_yes=lambda: calls.append("yes"),
        )
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg._fire_key_for_test(_KEY_ESCAPE)
        assert calls == []
        assert dlg.is_open is False

    def test_yes_after_destroy_is_noop(self):
        calls: List[str] = []
        dlg = ConfirmDeleteDialog(
            urls=["mock://a"],
            on_yes=lambda: calls.append("yes"),
        )
        dlg.destroy()
        dlg._fire_yes_for_test()  # window is None — short-circuits.
        assert calls == []

    def test_yes_dismisses_before_firing_handler(self, ephemeral_window):
        """Dismiss ordering: the handler sees ``is_open == False``.

        Matches the :class:`SimpleInputDialog` dispatch contract.
        """
        seen_states: List[bool] = []

        def _on_yes() -> None:
            seen_states.append(dlg.is_open)

        dlg = ConfirmDeleteDialog(urls=["mock://a"], on_yes=_on_yes)
        with in_window_frame(ephemeral_window):
            dlg.show()
        dlg._fire_yes_for_test()
        assert seen_states == [False]


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — Delete wiring
# ──────────────────────────────────────────────────────────────────────────────


class _FakeModel:
    """Stand-in for :class:`FileBrowserModel` used by the menu tests."""

    def __init__(
        self,
        root_url: str = "mock://Home",
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


class _FakeBackend:
    """Records delete / parent_url calls with a configurable result."""

    def __init__(
        self,
        result_map: Optional[dict] = None,
        default_result: BackendResult = BackendResult.OK,
    ) -> None:
        self.result_map = result_map or {}
        self.default_result = default_result
        self.delete_calls: List[str] = []

    def parent_url(self, url: str) -> Optional[str]:
        if "/" not in url.removeprefix("mock://"):
            return None
        parent, _, _ = url.rpartition("/")
        return parent

    def delete(self, url: str) -> BackendResult:
        self.delete_calls.append(url)
        return self.result_map.get(url, self.default_result)


class _FakeWidget:
    """Minimal widget surface the context menu's Delete helper reads."""

    def __init__(
        self,
        backend: _FakeBackend,
        detail_model: _FakeModel,
        tree_model: Optional[_FakeModel] = None,
    ) -> None:
        self._backend = backend
        self._detail_model = detail_model
        self._tree_model = tree_model


class TestDeleteDo:
    """End-to-end ``_delete_do`` flow with a recording reporter."""

    def _build(
        self,
        result_map: Optional[dict] = None,
        default_result: BackendResult = BackendResult.OK,
        resolved: Optional[dict] = None,
        tree_resolved: Optional[dict] = None,
    ) -> Tuple[FileContextMenu, _FakeBackend, _FakeModel, _FakeModel]:
        backend = _FakeBackend(
            result_map=result_map,
            default_result=default_result,
        )
        detail = _FakeModel(resolved=resolved)
        tree = _FakeModel(resolved=tree_resolved)
        widget = _FakeWidget(backend, detail, tree)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        return menu, backend, detail, tree

    def test_single_delete_calls_backend(self, reporter):
        menu, backend, _, _ = self._build()
        menu._delete_do(["mock://Home/file.txt"])
        assert backend.delete_calls == ["mock://Home/file.txt"]
        assert reporter.errors == []

    def test_success_reports_status_message_single(self, reporter):
        menu, _, _, _ = self._build()
        menu._delete_do(["mock://Home/file.txt"])
        assert reporter.successes == [_STATUS_DELETE_DONE_SINGLE]

    def test_success_reports_status_message_multi(self, reporter):
        menu, _, _, _ = self._build()
        menu._delete_do([
            "mock://Home/a.txt",
            "mock://Home/b.txt",
            "mock://Home/c.txt",
        ])
        assert reporter.successes == [
            _STATUS_DELETE_DONE_MULTI.format(count=3),
        ]

    def test_multi_delete_calls_backend_for_each(self, reporter):
        menu, backend, _, _ = self._build()
        menu._delete_do([
            "mock://Home/a.txt",
            "mock://Home/b.txt",
        ])
        assert backend.delete_calls == [
            "mock://Home/a.txt",
            "mock://Home/b.txt",
        ]

    def test_success_refreshes_resolved_detail_parent_once(
        self, reporter,
    ):
        parent = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        menu, _, detail, _ = self._build(
            resolved={"mock://Home": parent},
        )
        # Two deletes under the same parent — only one refresh call.
        menu._delete_do([
            "mock://Home/a.txt",
            "mock://Home/b.txt",
        ])
        assert detail.refresh_item_calls == [parent]
        assert detail.refresh_all_count == 0

    def test_success_refreshes_each_distinct_parent(self, reporter):
        home = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        other = FileItem(
            url="mock://Other", name="Other", is_folder=True,
        )
        menu, _, detail, _ = self._build(
            resolved={
                "mock://Home": home,
                "mock://Other": other,
            },
        )
        menu._delete_do([
            "mock://Home/a.txt",
            "mock://Other/b.txt",
        ])
        assert detail.refresh_item_calls == [home, other]

    def test_success_falls_back_to_refresh_all(self, reporter):
        # Parent not resolved → fall back to refresh_all on the detail
        # model.
        menu, _, detail, _ = self._build()
        menu._delete_do(["mock://Home/a.txt"])
        assert detail.refresh_all_count == 1

    def test_success_also_refreshes_tree_parent_if_resolved(
        self, reporter,
    ):
        home = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        tree_home = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        menu, _, detail, tree = self._build(
            resolved={"mock://Home": home},
            tree_resolved={"mock://Home": tree_home},
        )
        menu._delete_do(["mock://Home/a.txt"])
        assert tree.refresh_item_calls == [tree_home]

    def test_backend_error_surfaces_via_error_reporter(self, reporter):
        url = "mock://Home/denied.txt"
        menu, _, _, _ = self._build(
            result_map={url: BackendResult.ERROR_ACCESS_DENIED},
        )
        menu._delete_do([url])
        assert reporter.errors == [
            _ERROR_DELETE_FAILED.format(
                url=url, reason="ERROR_ACCESS_DENIED",
            ),
        ]
        # No success message when every URL failed.
        assert reporter.successes == []

    def test_partial_failure_continues_and_reports_success(
        self, reporter,
    ):
        menu, backend, _, _ = self._build(
            result_map={
                "mock://Home/bad.txt": BackendResult.ERROR_NOT_FOUND,
            },
        )
        menu._delete_do([
            "mock://Home/bad.txt",
            "mock://Home/good.txt",
        ])
        # Both URLs reached the backend (no short-circuit on failure).
        assert backend.delete_calls == [
            "mock://Home/bad.txt",
            "mock://Home/good.txt",
        ]
        assert reporter.errors == [
            _ERROR_DELETE_FAILED.format(
                url="mock://Home/bad.txt", reason="ERROR_NOT_FOUND",
            ),
        ]
        assert reporter.successes == [_STATUS_DELETE_DONE_SINGLE]

    def test_post_destroy_is_noop(self, reporter):
        menu, backend, _, _ = self._build()
        menu.destroy()
        menu._delete_do(["mock://Home/a.txt"])
        assert backend.delete_calls == []

    def test_empty_url_list_is_noop(self, reporter):
        menu, backend, _, _ = self._build()
        menu._delete_do([])
        assert backend.delete_calls == []
        assert reporter.successes == []


class TestOpenConfirmDeleteDialog:
    """Covers :meth:`FileContextMenu._open_confirm_delete_dialog`."""

    def test_builds_dialog_with_item_urls(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        monkeypatch.setattr(
            ConfirmDeleteDialog, "show", lambda self: None,
        )

        items = [
            FileItem(
                url="mock://Home/a.txt", name="a.txt", is_folder=False,
            ),
            FileItem(
                url="mock://Home/b.txt", name="b.txt", is_folder=False,
            ),
        ]
        menu._open_confirm_delete_dialog(items)
        assert menu._confirm_delete_dialog is not None
        assert menu._confirm_delete_dialog.urls == [
            "mock://Home/a.txt",
            "mock://Home/b.txt",
        ]

    def test_yes_handler_invokes_delete_do(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        monkeypatch.setattr(
            ConfirmDeleteDialog, "show", lambda self: None,
        )

        item = FileItem(
            url="mock://Home/a.txt", name="a.txt", is_folder=False,
        )
        menu._open_confirm_delete_dialog([item])
        dlg = menu._confirm_delete_dialog
        assert dlg is not None
        dlg._on_yes()  # drive directly — ``show`` was patched out.
        assert backend.delete_calls == ["mock://Home/a.txt"]

    def test_empty_items_list_does_not_open_dialog(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        called = {"show": 0}

        def _record_show(self):
            called["show"] += 1

        monkeypatch.setattr(
            ConfirmDeleteDialog, "show", _record_show,
        )
        menu._open_confirm_delete_dialog([])
        assert called["show"] == 0
        assert menu._confirm_delete_dialog is None

    def test_second_open_dismisses_prior_dialog(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        destroys: List[int] = []

        def _record_destroy(self):
            destroys.append(id(self))

        monkeypatch.setattr(
            ConfirmDeleteDialog, "show", lambda self: None,
        )
        monkeypatch.setattr(
            ConfirmDeleteDialog, "destroy", _record_destroy,
        )

        item_a = FileItem(
            url="mock://Home/a.txt", name="a.txt", is_folder=False,
        )
        item_b = FileItem(
            url="mock://Home/b.txt", name="b.txt", is_folder=False,
        )
        menu._open_confirm_delete_dialog([item_a])
        first = menu._confirm_delete_dialog
        assert first is not None
        menu._open_confirm_delete_dialog([item_b])
        assert destroys == [id(first)]
        assert menu._confirm_delete_dialog is not first


class TestBeginDelete:
    """Covers :meth:`FileContextMenu._begin_delete`."""

    def test_item_opens_dialog(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        monkeypatch.setattr(
            ConfirmDeleteDialog, "show", lambda self: None,
        )
        item = FileItem(
            url="mock://Home/a.txt", name="a.txt", is_folder=False,
        )
        menu._begin_delete(item)
        dlg = menu._confirm_delete_dialog
        assert dlg is not None
        assert dlg.urls == ["mock://Home/a.txt"]

    def test_none_item_falls_through_to_log_stub(
        self, reporter, capsys,
    ):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        menu._begin_delete(None)
        # Stub routes through logger, not the dialog.
        assert menu._confirm_delete_dialog is None
        assert backend.delete_calls == []


class TestContextMenuDeleteEntries:
    """Delete appears in file and folder specs, is absent from empty."""

    def _menu(self) -> FileContextMenu:
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        return FileContextMenu(widget)  # type: ignore[arg-type]

    def test_file_menu_has_delete(self):
        menu = self._menu()
        names = [s.name for s in menu._file_specs()]
        assert "Delete" in names

    def test_folder_menu_has_delete(self):
        menu = self._menu()
        names = [s.name for s in menu._folder_specs()]
        assert "Delete" in names

    def test_empty_menu_does_not_have_delete(self):
        menu = self._menu()
        names = [s.name for s in menu._empty_specs()]
        assert "Delete" not in names


# ──────────────────────────────────────────────────────────────────────────────
# MockBackend.delete — round-trip
# ──────────────────────────────────────────────────────────────────────────────


class TestMockBackendDelete:
    def test_delete_file_removes_from_tree(self):
        backend = MockBackend()
        url = "mock://Home/Documents/Projects/demo.usda"
        assert backend.delete(url) == BackendResult.OK
        result, _ = backend.stat(url)
        assert result == BackendResult.ERROR_NOT_FOUND

    def test_delete_folder_removes_subtree(self):
        backend = MockBackend()
        # ``Projects`` has three children in the default tree.
        folder_url = "mock://Home/Documents/Projects"
        demo_url = f"{folder_url}/demo.usda"
        assert backend.delete(folder_url) == BackendResult.OK
        # Folder gone.
        fr, _ = backend.stat(folder_url)
        assert fr == BackendResult.ERROR_NOT_FOUND
        # Children gone too (recursive delete).
        dr, _ = backend.stat(demo_url)
        assert dr == BackendResult.ERROR_NOT_FOUND

    def test_delete_missing_returns_not_found(self):
        backend = MockBackend()
        assert backend.delete(
            "mock://Home/missing.txt",
        ) == BackendResult.ERROR_NOT_FOUND

    def test_delete_root_refused(self):
        backend = MockBackend()
        assert backend.delete("mock://") == BackendResult.ERROR


# ──────────────────────────────────────────────────────────────────────────────
# LocalFSBackend.delete — round-trip against a real tmpdir
# ──────────────────────────────────────────────────────────────────────────────


class TestLocalFsBackendDelete:
    def test_deletes_file_on_disk(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "target.txt")
            with open(path, "w") as f:
                f.write("contents")
            url = backend.join_url(tmpdir, "target.txt")
            assert backend.delete(url) == BackendResult.OK
            assert not os.path.exists(path)

    def test_deletes_folder_recursively(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = os.path.join(tmpdir, "victim")
            os.mkdir(folder)
            # Nested file + subdir so rmtree must recurse.
            with open(os.path.join(folder, "inner.txt"), "w") as f:
                f.write("x")
            nested = os.path.join(folder, "inner_folder")
            os.mkdir(nested)
            with open(os.path.join(nested, "leaf.txt"), "w") as f:
                f.write("y")
            url = backend.join_url(tmpdir, "victim")
            assert backend.delete(url) == BackendResult.OK
            assert not os.path.exists(folder)

    def test_missing_path_returns_not_found(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            url = backend.join_url(tmpdir, "does_not_exist")
            assert (
                backend.delete(url)
                == BackendResult.ERROR_NOT_FOUND
            )


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end — FileBrowserWidget + MockBackend delete round-trip
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetDeleteIntegration:
    """FileBrowserWidget + MockBackend — deleted items vanish from the model."""

    def test_delete_removes_file_from_backend(
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

            monkeypatch.setattr(
                ConfirmDeleteDialog, "show", lambda self: None,
            )
            widget._context_menu._begin_delete(demo)
            dlg = widget._context_menu._confirm_delete_dialog
            assert dlg is not None
            dlg._on_yes_clicked()  # confirm

            # Backend no longer has the file.
            result, _ = backend.stat(
                "mock://Home/Documents/Projects/demo.usda",
            )
            assert result == BackendResult.ERROR_NOT_FOUND
            assert reporter.errors == []
            assert reporter.successes == [_STATUS_DELETE_DONE_SINGLE]
        finally:
            widget.destroy()

    def test_delete_folder_removes_subtree(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home/Documents")
        try:
            widget._detail_model.get_item_children(None)
            projects = widget._detail_model.resolve(
                "mock://Home/Documents/Projects",
            )
            assert projects is not None

            monkeypatch.setattr(
                ConfirmDeleteDialog, "show", lambda self: None,
            )
            widget._context_menu._begin_delete(projects)
            dlg = widget._context_menu._confirm_delete_dialog
            assert dlg is not None
            dlg._on_yes_clicked()

            # Folder and its children both gone.
            fr, _ = backend.stat("mock://Home/Documents/Projects")
            assert fr == BackendResult.ERROR_NOT_FOUND
            dr, _ = backend.stat(
                "mock://Home/Documents/Projects/demo.usda",
            )
            assert dr == BackendResult.ERROR_NOT_FOUND
        finally:
            widget.destroy()

    def test_cancel_leaves_backend_untouched(
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

            monkeypatch.setattr(
                ConfirmDeleteDialog, "show", lambda self: None,
            )
            widget._context_menu._begin_delete(demo)
            dlg = widget._context_menu._confirm_delete_dialog
            assert dlg is not None
            dlg._on_no_clicked()  # cancel

            # File still there — backend was never touched.
            result, _ = backend.stat(
                "mock://Home/Documents/Projects/demo.usda",
            )
            assert result == BackendResult.OK
            assert reporter.successes == []
        finally:
            widget.destroy()

    def test_backend_error_surfaces_for_user(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        # Inject access-denied error at a specific URL.
        backend._errors["mock://Home/Documents/Projects/demo.usda"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
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

            monkeypatch.setattr(
                ConfirmDeleteDialog, "show", lambda self: None,
            )
            widget._context_menu._begin_delete(demo)
            dlg = widget._context_menu._confirm_delete_dialog
            assert dlg is not None
            dlg._on_yes_clicked()

            # Error surfaced.
            assert any(
                "ERROR_ACCESS_DENIED" in msg
                for msg in reporter.errors
            )
            assert reporter.successes == []
            # Remove the injection so stat can see the live tree, then
            # confirm the file survived the refused delete.
            backend._errors.pop(
                "mock://Home/Documents/Projects/demo.usda",
            )
            result, _ = backend.stat(
                "mock://Home/Documents/Projects/demo.usda",
            )
            assert result == BackendResult.OK
        finally:
            widget.destroy()

    def test_delete_selected_uses_detail_tree_selection(
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
            # Force list-view mode so the detail TreeView selection is
            # the path the widget reads.
            widget._is_grid_view = False

            class _FakeSelection:
                def __init__(self, items: List[FileItem]) -> None:
                    self.selection = items

                def set_mouse_double_clicked_fn(
                    self, fn: Optional[Any],
                ) -> None:
                    # ``FileBrowserWidget.destroy`` calls this to release
                    # its double-click callback — no-op in the fake.
                    pass

            widget._detail_tree_view = _FakeSelection([demo, democ])  # type: ignore[assignment]

            monkeypatch.setattr(
                ConfirmDeleteDialog, "show", lambda self: None,
            )
            widget.delete_selected()
            dlg = widget._context_menu._confirm_delete_dialog
            assert dlg is not None
            assert dlg.urls == [
                "mock://Home/Documents/Projects/demo.usda",
                "mock://Home/Documents/Projects/demo.usdc",
            ]
            dlg._on_yes_clicked()
            # Both deleted.
            for url in dlg.urls:
                r, _ = backend.stat(url)
                assert r == BackendResult.ERROR_NOT_FOUND
            assert reporter.successes == [
                _STATUS_DELETE_DONE_MULTI.format(count=2),
            ]
        finally:
            widget.destroy()

    def test_delete_selected_no_selection_is_noop(
        self, ephemeral_window, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            called = {"show": 0}

            def _record_show(self):
                called["show"] += 1

            monkeypatch.setattr(
                ConfirmDeleteDialog, "show", _record_show,
            )
            widget.delete_selected()
            assert called["show"] == 0
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# ContentBrowserWindow proxy
# ──────────────────────────────────────────────────────────────────────────────


class TestContentBrowserWindowDeleteProxy:
    def test_forwards_to_widget(self):
        from ovwidgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        calls: List[str] = []

        class _FakeInnerWidget:
            def delete_selected(self) -> None:
                calls.append("called")

        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = _FakeInnerWidget()  # type: ignore[assignment]
        win.delete_selected()
        assert calls == ["called"]

    def test_no_widget_is_noop(self):
        from ovwidgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = None
        win.delete_selected()  # no raise


# ──────────────────────────────────────────────────────────────────────────────
# Application Del-key dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestApplicationDeleteKeyDispatch:
    def test_delete_dispatches_to_content_window(self):
        """Simulates the Del branch of :meth:`Application._on_key_pressed`.

        Mirrors the F2 dispatch test in test_rename_controller.py. The
        app's :meth:`_delete_selected` (stage prim path) needs a
        ``_selection_bus`` with a ``get_snapshot`` that returns ``None``
        so the path short-circuits without reaching the undo manager —
        the point of this test is the content-window fan-out, not the
        stage path.
        """
        from ovwidgets.app import application as app_module
        from ovwidgets.app.application import Application

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

        content_calls: List[str] = []

        class _Content:
            def delete_selected(self) -> None:
                content_calls.append("content")

            def begin_rename_selected(self) -> None:
                pass

            def go_back(self) -> None:
                pass

            def go_forward(self) -> None:
                pass

        app._stage_window = None
        app._content_window = _Content()
        # Layers panel must be present (None) for the prim-spec branch
        # to short-circuit before we hit the content-window fan-out.
        app._layer_window = None

        app._on_key_pressed(app_module._KEY_DELETE, 0, True)
        assert content_calls == ["content"]
