# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 32 — Create Folder + Step 37 — Duplicate / Copy URL / Open Native.

Coverage:

* :class:`SimpleInputDialog` — surface, show / destroy lifecycle,
  OK / Cancel button dispatch, Enter / Escape keybindings, test
  hooks for driving the dialog headlessly.
* ``FileContextMenu`` Create-Folder wiring — parent-URL resolution
  for empty-space / folder / file targets, end-to-end create-folder
  flow against :class:`MockBackend`, validation (empty / duplicate /
  illegal-char names), backend-error surfacing through
  :class:`ErrorReporter`, post-create model refresh.
* :meth:`LocalFSBackend.create_folder` — real-filesystem round-trip
  via a :func:`tempfile.TemporaryDirectory`.
* :mod:`file_ops` Step 37 helpers — :func:`_next_copy_name`
  collision math, :func:`duplicate_items` against
  :class:`MockBackend`, :func:`open_in_native_browser` subprocess
  dispatch (mocked), :func:`copy_url_to_clipboard` log + status line.
* :class:`FileContextMenu` Step 37 wiring — Duplicate / Copy URL /
  Open-in-Native menu entries, predicate-driven visibility of the
  native-browser entry, widget / window / application dispatch for
  Ctrl+D.

The dialog tests follow the same pattern as
``tests/test_path_field.py``: a module-scoped ``ephemeral_window``
fixture + an ``in_window_frame`` context manager so every
:class:`ui.Window` open happens inside a real ovui root. The
create-folder integration tests monkey-patch :class:`ErrorReporter`
entries so the warning / error surfaces become assertable without
depending on a live status-bar label.
"""

from __future__ import annotations

import os
import subprocess
import sys
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
    FileBrowserWidget,
    FileContextMenu,
    FileItem,
    SimpleInputDialog,
    file_ops,
)
from ovwidgets.content.widget.context_menu import (
    _ERROR_CREATE_FAILED,
    _ERROR_DUPLICATE_FAILED,
    _ILLEGAL_NAME_CHARS,
    _NEW_FOLDER_DIALOG_DEFAULT,
    _NEW_FOLDER_DIALOG_PROMPT,
    _NEW_FOLDER_DIALOG_TITLE,
    _STATUS_DUPLICATED_MULTI,
    _STATUS_DUPLICATED_SINGLE,
    _WARN_DUPLICATE_NAME,
    _WARN_EMPTY_NAME,
    _WARN_ILLEGAL_CHARS,
    _WARN_NATIVE_BROWSER_UNAVAILABLE,
)
from ovwidgets.content.widget.file_ops import (
    _LOCAL_SCHEME,
    _LOG_COPY_URL_MESSAGE,
    _LOG_COPY_URL_MODULE,
    _STATUS_COPY_URL_SUCCESS,
    _is_local_url,
    _next_copy_name,
)
from ovwidgets.content.widget.simple_input_dialog import (
    _KEY_ENTER,
    _KEY_ESCAPE,
    _KEY_KEYPAD_ENTER,
)
from ovwidgets.content.widget.simple_input_dialog import (
    SimpleInputDialog as _SimpleInputDialog,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window shared across every test — same pattern as the
    other content-browser widget modules."""
    win = ui.Window("_test_file_ops", width=400, height=240)
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
    """Captures every :class:`ErrorReporter` warning / error / success /
    info message so tests can assert against the exact vocabulary.

    The reporter's ``show_warning`` / ``show_error`` / ``show_success``
    and ``log_info`` surfaces are static, so monkey-patching the
    classmethods forwards to per-test lists without needing a running
    :class:`Application`. The log-info capture (Step 37) also records
    the module name so ``copy_url_to_clipboard`` tests can verify the
    ``"FileOps"`` attribution.
    """

    def __init__(self) -> None:
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.successes: List[str] = []
        self.infos: List[Tuple[str, str]] = []

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
        monkeypatch.setattr(
            ErrorReporter, "log_info",
            lambda mod, msg, r=self: r.infos.append((mod, msg)),
        )


@pytest.fixture
def reporter(monkeypatch: pytest.MonkeyPatch) -> _RecordedReport:
    r = _RecordedReport()
    r.install(monkeypatch)
    return r


# ──────────────────────────────────────────────────────────────────────────────
# SimpleInputDialog — public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSimpleInputDialogSurface:
    def test_reexported_from_widget_package(self):
        assert SimpleInputDialog is _SimpleInputDialog

    def test_widget_package_all_contains_simple_input_dialog(self):
        import ovwidgets.content.widget as pkg

        assert "SimpleInputDialog" in pkg.__all__

    def test_constructor_stores_fields(self):
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="V", on_ok=lambda v: None,
        )
        assert dlg._title == "T"
        assert dlg._prompt == "P"
        assert dlg._initial_value == "V"
        assert dlg._on_ok is not None
        assert not dlg.is_open

    def test_none_initial_value_coerces_to_empty_string(self):
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value=None,  # type: ignore[arg-type]
            on_ok=lambda v: None,
        )
        assert dlg._initial_value == ""


# ──────────────────────────────────────────────────────────────────────────────
# SimpleInputDialog — lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestSimpleInputDialogLifecycle:
    def test_show_opens_window(self, ephemeral_window):
        dlg = SimpleInputDialog(
            title="New Folder", prompt="Name:",
            initial_value="x", on_ok=lambda v: None,
        )
        try:
            dlg.show()
            assert dlg.is_open
            assert dlg._window is not None
            assert dlg._field is not None
        finally:
            dlg.destroy()

    def test_show_twice_is_idempotent(self):
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="",
            on_ok=lambda v: None,
        )
        try:
            dlg.show()
            first_window = dlg._window
            dlg.show()  # No raise, no re-materialisation.
            assert dlg._window is first_window
        finally:
            dlg.destroy()

    def test_destroy_without_show_is_safe(self):
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="",
            on_ok=lambda v: None,
        )
        dlg.destroy()  # No raise.
        assert not dlg.is_open

    def test_destroy_idempotent(self):
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="",
            on_ok=lambda v: None,
        )
        dlg.show()
        dlg.destroy()
        dlg.destroy()  # Second call is a no-op.
        assert not dlg.is_open

    def test_destroy_clears_on_ok_handler(self):
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="",
            on_ok=lambda v: None,
        )
        dlg.show()
        dlg.destroy()
        assert dlg._on_ok is None


# ──────────────────────────────────────────────────────────────────────────────
# SimpleInputDialog — OK / Cancel / key flows
# ──────────────────────────────────────────────────────────────────────────────


class TestSimpleInputDialogCommit:
    def test_ok_fires_on_ok_with_value_and_dismisses(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="MyFolder",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg._fire_ok_for_test()
        assert captured == ["MyFolder"]
        assert not dlg.is_open

    def test_ok_passes_typed_value(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="Original",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg._set_value_for_test("Typed")
        dlg._fire_ok_for_test()
        assert captured == ["Typed"]

    def test_cancel_dismisses_without_firing(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="X",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg._fire_cancel_for_test()
        assert captured == []
        assert not dlg.is_open

    def test_enter_key_fires_ok(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="Z",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg._fire_key_for_test(_KEY_ENTER)
        assert captured == ["Z"]
        assert not dlg.is_open

    def test_keypad_enter_fires_ok(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="Y",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg._fire_key_for_test(_KEY_KEYPAD_ENTER)
        assert captured == ["Y"]

    def test_escape_key_cancels(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="X",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg._fire_key_for_test(_KEY_ESCAPE)
        assert captured == []
        assert not dlg.is_open

    def test_ok_after_destroy_is_noop(self):
        captured: List[str] = []
        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="X",
            on_ok=lambda v, out=captured: out.append(v),
        )
        dlg.show()
        dlg.destroy()
        dlg._fire_ok_for_test()  # Short-circuits on closed window.
        assert captured == []

    def test_ok_dismisses_before_invoking_handler(self):
        """``_on_ok`` reads the current ``is_open`` — must be False."""
        seen_states: List[bool] = []

        def _on_ok(v: str) -> None:
            seen_states.append(dlg.is_open)

        dlg = SimpleInputDialog(
            title="T", prompt="P", initial_value="X",
            on_ok=_on_ok,
        )
        dlg.show()
        dlg._fire_ok_for_test()
        assert seen_states == [False]


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — Create Folder wiring
# ──────────────────────────────────────────────────────────────────────────────


class _FakeModel:
    """Stand-in for :class:`FileBrowserModel` used by parent-URL tests.

    Records ``refresh_item`` / ``refresh_all`` calls; :meth:`resolve`
    returns a pre-seeded item map. The context menu's Create-Folder
    helpers read ``root_url`` and call ``resolve`` / ``refresh_item``,
    so this minimal surface is sufficient.
    """

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
    """Records create_folder calls and returns a configurable result."""

    def __init__(self, result: BackendResult = BackendResult.OK) -> None:
        self.result = result
        self.calls: List[str] = []

    def join_url(self, base: str, child: str) -> str:
        return f"{base}/{child}"

    def create_folder(self, url: str) -> BackendResult:
        self.calls.append(url)
        return self.result


class _FakeWidget:
    """Minimal widget surface the context menu's Create-Folder path reads."""

    def __init__(
        self,
        backend: _FakeBackend,
        detail_model: _FakeModel,
        tree_model: Optional[_FakeModel] = None,
    ) -> None:
        self._backend = backend
        self._detail_model = detail_model
        self._tree_model = tree_model


class TestParentUrlResolution:
    def test_none_item_returns_detail_root_url(self):
        model = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(_FakeBackend(), model)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        assert menu._parent_url_for_create(None) == "mock://Home"

    def test_folder_item_returns_folder_url(self):
        model = _FakeModel()
        widget = _FakeWidget(_FakeBackend(), model)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        folder = FileItem(url="mock://X", name="X", is_folder=True)
        assert menu._parent_url_for_create(folder) == "mock://X"

    def test_file_item_returns_none_and_warns(
        self, reporter, capsys,
    ):
        model = _FakeModel()
        widget = _FakeWidget(_FakeBackend(), model)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        f = FileItem(url="mock://f.usd", name="f.usd", is_folder=False)
        assert menu._parent_url_for_create(f) is None

    def test_missing_widget_returns_none(self):
        model = _FakeModel()
        widget = _FakeWidget(_FakeBackend(), model)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        menu._widget = None
        assert menu._parent_url_for_create(None) is None


class TestCreateFolderDo:
    """End-to-end ``_create_folder_do`` flow with a recording reporter."""

    def _build(
        self,
        result: BackendResult = BackendResult.OK,
        root_url: str = "mock://Home",
        resolved: Optional[dict] = None,
        tree_resolved: Optional[dict] = None,
    ) -> Tuple[FileContextMenu, _FakeBackend, _FakeModel, _FakeModel]:
        backend = _FakeBackend(result=result)
        detail = _FakeModel(root_url=root_url, resolved=resolved)
        tree = _FakeModel(
            root_url=root_url, resolved=tree_resolved,
        )
        widget = _FakeWidget(backend, detail, tree)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        return menu, backend, detail, tree

    def test_success_calls_backend_with_joined_url(self, reporter):
        menu, backend, _, _ = self._build()
        menu._create_folder_do("mock://Home", "NewFolder")
        assert backend.calls == ["mock://Home/NewFolder"]
        assert reporter.warnings == []
        assert reporter.errors == []

    def test_success_refreshes_resolved_detail_parent(self, reporter):
        parent = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        menu, _, detail, _ = self._build(
            resolved={"mock://Home": parent},
        )
        menu._create_folder_do("mock://Home", "New")
        assert detail.refresh_item_calls == [parent]
        assert detail.refresh_all_count == 0

    def test_success_falls_back_to_refresh_all(self, reporter):
        # Parent not resolved → fall back to refresh_all on the detail
        # model. Tree model miss also falls through.
        menu, _, detail, tree = self._build()
        menu._create_folder_do("mock://Home", "New")
        assert detail.refresh_all_count == 1
        assert tree.refresh_item_calls == []

    def test_success_also_refreshes_tree_parent_if_resolved(
        self, reporter,
    ):
        parent = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        tree_parent = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        menu, _, detail, tree = self._build(
            resolved={"mock://Home": parent},
            tree_resolved={"mock://Home": tree_parent},
        )
        menu._create_folder_do("mock://Home", "New")
        assert detail.refresh_item_calls == [parent]
        assert tree.refresh_item_calls == [tree_parent]

    def test_empty_name_rejected_with_warning(self, reporter):
        menu, backend, _, _ = self._build()
        menu._create_folder_do("mock://Home", "   ")
        assert backend.calls == []
        assert reporter.warnings == [_WARN_EMPTY_NAME]

    def test_name_with_forward_slash_rejected(self, reporter):
        menu, backend, _, _ = self._build()
        menu._create_folder_do("mock://Home", "a/b")
        assert backend.calls == []
        assert reporter.warnings == [_WARN_ILLEGAL_CHARS]

    def test_name_with_backslash_rejected(self, reporter):
        menu, backend, _, _ = self._build()
        menu._create_folder_do("mock://Home", "a\\b")
        assert backend.calls == []
        assert reporter.warnings == [_WARN_ILLEGAL_CHARS]

    def test_name_trimmed_before_validation(self, reporter):
        menu, backend, _, _ = self._build()
        menu._create_folder_do("mock://Home", "  Trimmed  ")
        assert backend.calls == ["mock://Home/Trimmed"]

    def test_duplicate_name_rejected(self, reporter):
        existing = FileItem(
            url="mock://Home/Docs", name="Docs", is_folder=True,
            parent=None,
        )
        parent = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        parent.add_child(existing)
        menu, backend, _, _ = self._build(
            resolved={"mock://Home": parent},
        )
        menu._create_folder_do("mock://Home", "Docs")
        assert backend.calls == []
        assert reporter.warnings == [_WARN_DUPLICATE_NAME]

    def test_backend_error_surfaces_via_error_reporter(self, reporter):
        menu, backend, _, _ = self._build(
            result=BackendResult.ERROR_ACCESS_DENIED,
        )
        menu._create_folder_do("mock://Home", "Foo")
        assert backend.calls == ["mock://Home/Foo"]
        assert reporter.warnings == []
        assert reporter.errors == [
            _ERROR_CREATE_FAILED.format(reason="ERROR_ACCESS_DENIED"),
        ]

    def test_backend_already_exists_surfaces_error(self, reporter):
        menu, backend, _, _ = self._build(
            result=BackendResult.ERROR_ALREADY_EXISTS,
        )
        menu._create_folder_do("mock://Home", "Foo")
        assert reporter.errors == [
            _ERROR_CREATE_FAILED.format(reason="ERROR_ALREADY_EXISTS"),
        ]

    def test_post_destroy_is_noop(self, reporter):
        menu, backend, _, _ = self._build()
        menu.destroy()
        menu._create_folder_do("mock://Home", "Foo")
        assert backend.calls == []


class TestOpenCreateFolderDialog:
    """Covers :meth:`FileContextMenu._open_create_folder_dialog`."""

    def test_empty_target_builds_dialog_with_root_parent(
        self, ephemeral_window, monkeypatch,
    ):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        captured_dialogs: List[SimpleInputDialog] = []

        _orig_show = SimpleInputDialog.show

        def _record_show(self):
            captured_dialogs.append(self)
            # Avoid building the live window — we only care about the
            # construction contract here. The widget stays un-opened.

        monkeypatch.setattr(SimpleInputDialog, "show", _record_show)

        menu._open_create_folder_dialog(None)
        assert len(captured_dialogs) == 1
        dlg = captured_dialogs[0]
        assert dlg._title == _NEW_FOLDER_DIALOG_TITLE
        assert dlg._prompt == _NEW_FOLDER_DIALOG_PROMPT
        assert dlg._initial_value == _NEW_FOLDER_DIALOG_DEFAULT
        # Invoke the dialog's on_ok with a typed name — the menu's
        # ``_create_folder_do`` fires against the resolved parent URL.
        assert dlg._on_ok is not None
        dlg._on_ok("Foo")
        assert backend.calls == ["mock://Home/Foo"]

        SimpleInputDialog.show = _orig_show  # type: ignore[method-assign]

    def test_folder_target_uses_folder_url(
        self, monkeypatch,
    ):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        monkeypatch.setattr(
            SimpleInputDialog, "show", lambda self: None,
        )

        folder = FileItem(
            url="mock://Home/Docs", name="Docs", is_folder=True,
        )
        menu._open_create_folder_dialog(folder)
        assert menu._input_dialog is not None
        menu._input_dialog._on_ok("Sub")  # type: ignore[misc]
        assert backend.calls == ["mock://Home/Docs/Sub"]

    def test_file_target_does_not_open_dialog(
        self, reporter, monkeypatch,
    ):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        called = {"show": 0}

        def _record_show(self):
            called["show"] += 1

        monkeypatch.setattr(SimpleInputDialog, "show", _record_show)

        f = FileItem(url="mock://f.usd", name="f.usd", is_folder=False)
        menu._open_create_folder_dialog(f)
        assert called["show"] == 0
        assert menu._input_dialog is None

    def test_post_destroy_open_is_noop(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        called = {"show": 0}

        def _record_show(self):
            called["show"] += 1

        monkeypatch.setattr(SimpleInputDialog, "show", _record_show)
        menu.destroy()
        menu._open_create_folder_dialog(None)
        assert called["show"] == 0

    def test_rapid_double_invoke_dismisses_prior_dialog(
        self, monkeypatch,
    ):
        """Second Create-Folder click replaces the first dialog."""
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]

        monkeypatch.setattr(
            SimpleInputDialog, "show", lambda self: None,
        )

        destroyed: List[SimpleInputDialog] = []
        _orig_destroy = SimpleInputDialog.destroy

        def _record_destroy(self):
            destroyed.append(self)
            _orig_destroy(self)

        monkeypatch.setattr(
            SimpleInputDialog, "destroy", _record_destroy,
        )

        menu._open_create_folder_dialog(None)
        first = menu._input_dialog
        menu._open_create_folder_dialog(None)
        second = menu._input_dialog
        assert first is not None
        assert second is not None
        assert first is not second
        assert first in destroyed


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — folder-menu spec wiring (Create Folder is live, not stub)
# ──────────────────────────────────────────────────────────────────────────────


class TestFolderSpecCreateFolderIsLive:
    def test_folder_spec_click_opens_dialog(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        monkeypatch.setattr(
            SimpleInputDialog, "show", lambda self: None,
        )

        create_spec = next(
            s for s in menu._folder_specs() if s.name == "Create Folder"
        )
        folder = FileItem(
            url="mock://Home/Docs", name="Docs", is_folder=True,
        )
        create_spec.click_fn(folder)
        assert menu._input_dialog is not None

    def test_empty_spec_click_opens_dialog(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        monkeypatch.setattr(
            SimpleInputDialog, "show", lambda self: None,
        )

        create_spec = next(
            s for s in menu._empty_specs() if s.name == "Create Folder"
        )
        create_spec.click_fn(None)
        assert menu._input_dialog is not None


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — teardown dismisses dialog
# ──────────────────────────────────────────────────────────────────────────────


class TestMenuDestroyTearsDownDialog:
    def test_destroy_dismisses_live_dialog(self, monkeypatch):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        monkeypatch.setattr(
            SimpleInputDialog, "show", lambda self: None,
        )

        menu._open_create_folder_dialog(None)
        assert menu._input_dialog is not None
        menu.destroy()
        assert menu._input_dialog is None


# ──────────────────────────────────────────────────────────────────────────────
# LocalFSBackend.create_folder round-trip against a real tmpdir
# ──────────────────────────────────────────────────────────────────────────────


class TestLocalFsBackendCreateFolder:
    def test_creates_folder_on_disk(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            url = backend.join_url(tmpdir, "NewFolder")
            assert backend.create_folder(url) == BackendResult.OK
            assert os.path.isdir(os.path.join(tmpdir, "NewFolder"))

    def test_duplicate_returns_already_exists(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.mkdir(os.path.join(tmpdir, "Dup"))
            url = backend.join_url(tmpdir, "Dup")
            assert (
                backend.create_folder(url)
                == BackendResult.ERROR_ALREADY_EXISTS
            )

    def test_missing_parent_returns_not_found(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            deep = backend.join_url(
                tmpdir, "does_not_exist/Nested",
            )
            assert (
                backend.create_folder(deep)
                == BackendResult.ERROR_NOT_FOUND
            )


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end — FileBrowserWidget + MockBackend create-folder round-trip
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetCreateFolderIntegration:
    """FileBrowserWidget + MockBackend — new folder appears in the model."""

    def test_create_folder_appears_in_detail_model(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            # Populate the detail model's root so duplicate check has
            # a cached child list to consult.
            widget._detail_model.get_item_children(None)

            monkeypatch.setattr(
                SimpleInputDialog, "show", lambda self: None,
            )
            # Empty-space Create Folder → creates under detail root.
            widget._context_menu._open_create_folder_dialog(None)
            widget._context_menu._input_dialog._on_ok("Brand New")

            # MockBackend tree now contains the new folder.
            result, entries = backend.list_dir("mock://Home")
            assert result == BackendResult.OK
            names = [e.name for e in entries]
            assert "Brand New" in names
            assert reporter.errors == []
        finally:
            widget.destroy()

    def test_duplicate_name_caught_before_backend(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            monkeypatch.setattr(
                SimpleInputDialog, "show", lambda self: None,
            )
            # "Documents" already exists under Home.
            widget._context_menu._open_create_folder_dialog(None)
            widget._context_menu._input_dialog._on_ok("Documents")
            assert _WARN_DUPLICATE_NAME in reporter.warnings
            # Backend was not touched — tree size unchanged.
            result, entries = backend.list_dir("mock://Home")
            assert [e.name for e in entries].count("Documents") == 1
        finally:
            widget.destroy()

    def test_illegal_chars_caught_before_backend(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            monkeypatch.setattr(
                SimpleInputDialog, "show", lambda self: None,
            )
            widget._context_menu._open_create_folder_dialog(None)
            widget._context_menu._input_dialog._on_ok("a/b")
            assert _WARN_ILLEGAL_CHARS in reporter.warnings
            # No new entry.
            result, entries = backend.list_dir("mock://Home")
            assert "a" not in [e.name for e in entries]
        finally:
            widget.destroy()

    def test_empty_name_caught_before_backend(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            monkeypatch.setattr(
                SimpleInputDialog, "show", lambda self: None,
            )
            widget._context_menu._open_create_folder_dialog(None)
            widget._context_menu._input_dialog._on_ok("   ")
            assert _WARN_EMPTY_NAME in reporter.warnings
        finally:
            widget.destroy()

    def test_backend_error_surfaces_message(
        self, ephemeral_window, reporter, monkeypatch,
    ):
        backend = MockBackend()
        backend._errors["mock://Home/Denied"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            monkeypatch.setattr(
                SimpleInputDialog, "show", lambda self: None,
            )
            widget._context_menu._open_create_folder_dialog(None)
            widget._context_menu._input_dialog._on_ok("Denied")
            assert any(
                "ERROR_ACCESS_DENIED" in m for m in reporter.errors
            )
        finally:
            widget.destroy()

    def test_module_constants_expose_illegal_chars(self):
        """Both common separators are rejected — Windows + POSIX."""
        assert "/" in _ILLEGAL_NAME_CHARS
        assert "\\" in _ILLEGAL_NAME_CHARS


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — Copy-name generation (pure helper, no backend)
# ──────────────────────────────────────────────────────────────────────────────


class TestNextCopyName:
    """Covers :func:`file_ops._next_copy_name`.

    The helper is pure: inputs are ``(name, is_folder, existing_names)``
    and the output is a fresh name that does not collide. Tests stay
    entirely in-memory — no backend, no widget, no ovui.
    """

    def test_file_with_no_prior_copy_gets_base_suffix(self):
        assert _next_copy_name("foo.txt", False, set()) == "foo Copy.txt"

    def test_folder_with_no_prior_copy_gets_base_suffix(self):
        assert _next_copy_name("Docs", True, set()) == "Docs Copy"

    def test_folder_with_dot_in_name_is_not_split(self):
        # Folder names are never split on the final dot — "My.Backup"
        # is a folder identity, not name+ext.
        assert (
            _next_copy_name("My.Backup", True, set())
            == "My.Backup Copy"
        )

    def test_file_with_existing_copy_increments_to_two(self):
        # "foo Copy.txt" exists — duplicating "foo.txt" bumps to Copy 2.
        existing = {"foo Copy.txt"}
        assert (
            _next_copy_name("foo.txt", False, existing)
            == "foo Copy 2.txt"
        )

    def test_duplicate_of_copy_name_increments(self):
        # Duplicating "foo Copy.txt" itself — suffix says Copy 2.
        assert (
            _next_copy_name("foo Copy.txt", False, set())
            == "foo Copy 2.txt"
        )

    def test_duplicate_of_copy_n_increments(self):
        assert (
            _next_copy_name("foo Copy 2.txt", False, set())
            == "foo Copy 3.txt"
        )

    def test_duplicate_of_copy_9_increments_to_10(self):
        assert (
            _next_copy_name("foo Copy 9.txt", False, set())
            == "foo Copy 10.txt"
        )

    def test_duplicate_of_copy_folder_increments(self):
        assert (
            _next_copy_name("Docs Copy", True, set())
            == "Docs Copy 2"
        )

    def test_sequential_increments_skip_taken_names(self):
        # "foo Copy.txt" + "foo Copy 2.txt" exist — next free is 3.
        existing = {"foo Copy.txt", "foo Copy 2.txt"}
        assert (
            _next_copy_name("foo.txt", False, existing)
            == "foo Copy 3.txt"
        )

    def test_duplicate_of_copy_respects_existing_siblings(self):
        # Duplicating "foo Copy.txt" when "foo Copy 2.txt" already
        # exists → lands on "foo Copy 3.txt".
        existing = {"foo Copy.txt", "foo Copy 2.txt"}
        assert (
            _next_copy_name("foo Copy.txt", False, existing)
            == "foo Copy 3.txt"
        )

    def test_name_containing_mid_string_copy_is_not_suffixed(self):
        # "My Copy Files.txt" has "Copy" mid-stem. The regex anchors
        # to end-of-stem so this is treated as a novel name.
        assert (
            _next_copy_name("My Copy Files.txt", False, set())
            == "My Copy Files Copy.txt"
        )

    def test_bare_copy_stem_cycles_into_copy_2(self):
        # The stem is literally " Copy" (empty stem root) — the
        # helper still produces a valid increment.
        assert _next_copy_name(" Copy", True, set()) == " Copy 2"


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — duplicate_items end-to-end against MockBackend
# ──────────────────────────────────────────────────────────────────────────────


class TestDuplicateItemsAgainstMockBackend:
    """Covers :func:`file_ops.duplicate_items` with a real backend.

    :class:`MockBackend` ships a deterministic tree
    (``mock://Home/Documents/Projects/demo.usda`` etc.) — duplicating
    into that tree verifies the backend.copy call and the in-tree
    state afterwards without any real filesystem I/O.
    """

    def _item(self, url: str, name: str, is_folder: bool = False) -> FileItem:
        return FileItem(url=url, name=name, is_folder=is_folder)

    def test_duplicate_single_file_creates_copy_sibling(self):
        backend = MockBackend()
        src_url = "mock://Home/Documents/Projects/demo.usda"
        item = self._item(src_url, "demo.usda")
        success, errors = file_ops.duplicate_items(backend, [item])
        assert success == 1
        assert errors == []
        # The new sibling appears in the parent listing.
        result, entries = backend.list_dir(
            "mock://Home/Documents/Projects",
        )
        assert result == BackendResult.OK
        names = {e.name for e in entries}
        assert "demo Copy.usda" in names
        # Original still present.
        assert "demo.usda" in names

    def test_duplicate_single_folder_creates_copy_sibling(self):
        backend = MockBackend()
        src_url = "mock://Home/Documents/Projects"
        item = self._item(src_url, "Projects", is_folder=True)
        success, errors = file_ops.duplicate_items(backend, [item])
        assert success == 1
        assert errors == []
        _, entries = backend.list_dir("mock://Home/Documents")
        names = {e.name for e in entries}
        assert "Projects Copy" in names

    def test_duplicate_twice_increments_suffix(self):
        backend = MockBackend()
        src_url = "mock://Home/Documents/Projects/demo.usda"
        item = self._item(src_url, "demo.usda")
        file_ops.duplicate_items(backend, [item])
        file_ops.duplicate_items(backend, [item])
        _, entries = backend.list_dir(
            "mock://Home/Documents/Projects",
        )
        names = {e.name for e in entries}
        assert "demo Copy.usda" in names
        assert "demo Copy 2.usda" in names

    def test_duplicate_of_copy_lands_on_copy_2(self):
        backend = MockBackend()
        # First duplicate demo.usda → demo Copy.usda exists.
        demo = self._item(
            "mock://Home/Documents/Projects/demo.usda", "demo.usda",
        )
        file_ops.duplicate_items(backend, [demo])
        # Now duplicate demo Copy.usda — expected demo Copy 2.usda.
        copy_item = self._item(
            "mock://Home/Documents/Projects/demo Copy.usda",
            "demo Copy.usda",
        )
        success, errors = file_ops.duplicate_items(backend, [copy_item])
        assert success == 1
        assert errors == []
        _, entries = backend.list_dir(
            "mock://Home/Documents/Projects",
        )
        names = {e.name for e in entries}
        assert "demo Copy 2.usda" in names

    def test_duplicate_multi_item_batch_fires_refresh_per_parent(self):
        backend = MockBackend()
        refreshed: List[str] = []
        items = [
            self._item(
                "mock://Home/Documents/Projects/demo.usda", "demo.usda",
            ),
            self._item(
                "mock://Home/Documents/Projects/readme.md", "readme.md",
            ),
        ]
        success, errors = file_ops.duplicate_items(
            backend, items, refresh_parent_fn=refreshed.append,
        )
        assert success == 2
        assert errors == []
        # Both items live under the same parent — refresh fires once.
        assert refreshed == ["mock://Home/Documents/Projects"]

    def test_duplicate_empty_list_is_noop(self):
        backend = MockBackend()
        success, errors = file_ops.duplicate_items(backend, [])
        assert success == 0
        assert errors == []

    def test_duplicate_backend_copy_failure_reports_error(self):
        backend = MockBackend()
        # Inject an error on the destination URL so the first copy fails.
        backend._errors[
            "mock://Home/Documents/Projects/demo Copy.usda"
        ] = BackendResult.ERROR_ACCESS_DENIED
        item = self._item(
            "mock://Home/Documents/Projects/demo.usda", "demo.usda",
        )
        success, errors = file_ops.duplicate_items(backend, [item])
        assert success == 0
        assert errors == [
            (
                "mock://Home/Documents/Projects/demo.usda",
                "ERROR_ACCESS_DENIED",
            ),
        ]

    def test_duplicate_refresh_callback_not_fired_on_all_failures(self):
        backend = MockBackend()
        # Inject errors for *both* expected destinations.
        backend._errors[
            "mock://Home/Documents/Projects/demo Copy.usda"
        ] = BackendResult.ERROR_ACCESS_DENIED
        backend._errors[
            "mock://Home/Documents/Projects/readme Copy.md"
        ] = BackendResult.ERROR_ACCESS_DENIED
        refreshed: List[str] = []
        items = [
            self._item(
                "mock://Home/Documents/Projects/demo.usda", "demo.usda",
            ),
            self._item(
                "mock://Home/Documents/Projects/readme.md", "readme.md",
            ),
        ]
        file_ops.duplicate_items(
            backend, items, refresh_parent_fn=refreshed.append,
        )
        # No successful duplicate → refresh never fires.
        assert refreshed == []

    def test_duplicate_root_item_reports_not_supported(self):
        backend = MockBackend()
        # Root mock:// has no parent — duplicate must refuse.
        item = self._item("mock://", "", is_folder=True)
        success, errors = file_ops.duplicate_items(backend, [item])
        assert success == 0
        assert errors == [("mock://", "ERROR_NOT_SUPPORTED")]

    def test_duplicate_failed_parent_list_reports_error(self):
        backend = MockBackend()
        # Inject list_dir error on parent.
        backend._errors["mock://Home/Documents/Projects"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
        item = self._item(
            "mock://Home/Documents/Projects/demo.usda", "demo.usda",
        )
        success, errors = file_ops.duplicate_items(backend, [item])
        assert success == 0
        assert errors == [
            (
                "mock://Home/Documents/Projects/demo.usda",
                "ERROR_ACCESS_DENIED",
            ),
        ]


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — LocalFSBackend duplicate round-trip on a real tmpdir
# ──────────────────────────────────────────────────────────────────────────────


class TestDuplicateItemsAgainstLocalFS:
    def test_duplicate_file_creates_copy_on_disk(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "hello.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write("hi")
            src_url = backend.normalize_url(src)
            item = FileItem(url=src_url, name="hello.txt", is_folder=False)
            success, errors = file_ops.duplicate_items(backend, [item])
            assert success == 1
            assert errors == []
            assert os.path.isfile(
                os.path.join(tmpdir, "hello Copy.txt"),
            )


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — open_in_native_browser platform dispatch (mocked)
# ──────────────────────────────────────────────────────────────────────────────


class TestOpenInNativeBrowser:
    """Covers :func:`file_ops.open_in_native_browser`.

    The OS launcher is not invoked for real — tests monkey-patch
    :mod:`subprocess.run` / :func:`os.startfile` / :data:`sys.platform`
    so the dispatch is fully introspectable and never spawns a
    window.
    """

    def test_non_local_url_refused(self):
        assert file_ops.open_in_native_browser("mock://Home") is False

    def test_empty_url_refused(self):
        assert file_ops.open_in_native_browser("") is False

    def test_http_url_refused(self):
        assert (
            file_ops.open_in_native_browser("https://example.com")
            is False
        )

    def test_linux_dispatches_xdg_open(self, monkeypatch):
        calls: List[List[str]] = []
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            subprocess, "run",
            lambda args, check=False, c=calls: (
                c.append(list(args)), None
            )[1],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"file://{tmpdir}"
            assert file_ops.open_in_native_browser(url) is True
            assert calls == [["xdg-open", tmpdir]]

    def test_darwin_dispatches_open(self, monkeypatch):
        calls: List[List[str]] = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(
            subprocess, "run",
            lambda args, check=False, c=calls: (
                c.append(list(args)), None
            )[1],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"file://{tmpdir}"
            assert file_ops.open_in_native_browser(url) is True
            assert calls == [["open", tmpdir]]

    def test_windows_dispatches_startfile(self, monkeypatch):
        calls: List[str] = []
        monkeypatch.setattr(sys, "platform", "win32")
        # os.startfile only exists on Windows; add a stub so the test
        # runs on POSIX CI without AttributeError.
        monkeypatch.setattr(
            os, "startfile",
            lambda p, c=calls: c.append(p), raising=False,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"file://{tmpdir}"
            assert file_ops.open_in_native_browser(url) is True
            assert calls == [tmpdir]

    def test_missing_path_refused(self, monkeypatch):
        # Even with a local URL, a non-existent path returns False.
        calls: List[Any] = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda args, check=False, c=calls: (
                c.append(list(args)), None
            )[1],
        )
        monkeypatch.setattr(sys, "platform", "linux")
        bogus = "/tmp/_ovgear_step37_does_not_exist_xyz12345"
        assert (
            file_ops.open_in_native_browser(f"file://{bogus}") is False
        )
        assert calls == []

    def test_subprocess_error_returns_false(self, monkeypatch):
        def _raise(args, check=False):
            raise FileNotFoundError("xdg-open not installed")

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(subprocess, "run", _raise)
        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"file://{tmpdir}"
            assert file_ops.open_in_native_browser(url) is False

    def test_raw_local_path_without_scheme_accepted(self, monkeypatch):
        calls: List[List[str]] = []
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            subprocess, "run",
            lambda args, check=False, c=calls: (
                c.append(list(args)), None
            )[1],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            assert file_ops.open_in_native_browser(tmpdir) is True
            assert calls == [["xdg-open", tmpdir]]

    def test_is_local_url_predicate(self):
        assert _is_local_url("file:///tmp") is True
        assert _is_local_url("/tmp") is True
        assert _is_local_url("mock://Home") is False
        assert _is_local_url("omniverse://server/path") is False
        assert _is_local_url("") is False
        assert _is_local_url(_LOCAL_SCHEME + "foo") is True


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — copy_url_to_clipboard (v1: log + status line)
# ──────────────────────────────────────────────────────────────────────────────


class TestCopyUrlToClipboard:
    def test_logs_via_error_reporter(self, reporter):
        file_ops.copy_url_to_clipboard("mock://Home/Documents/demo.usda")
        assert reporter.infos == [
            (
                _LOG_COPY_URL_MODULE,
                _LOG_COPY_URL_MESSAGE.format(
                    url="mock://Home/Documents/demo.usda",
                ),
            ),
        ]

    def test_shows_success_status_line(self, reporter):
        file_ops.copy_url_to_clipboard("file:///tmp/foo.txt")
        assert reporter.successes == [
            _STATUS_COPY_URL_SUCCESS.format(url="file:///tmp/foo.txt"),
        ]

    def test_empty_url_is_silent_noop(self, reporter):
        file_ops.copy_url_to_clipboard("")
        assert reporter.infos == []
        assert reporter.successes == []


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — FileContextMenu wiring: Duplicate, Copy URL, Open in Native
# ──────────────────────────────────────────────────────────────────────────────


class TestMenuSpecsStep37:
    """Menu specs carry the new Step 37 entries in the expected places."""

    def _menu(self) -> FileContextMenu:
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        return FileContextMenu(widget)  # type: ignore[arg-type]

    def test_file_menu_has_duplicate_and_copy_url(self):
        menu = self._menu()
        names = [s.name for s in menu._file_specs()]
        assert "Duplicate" in names
        assert "Copy URL" in names

    def test_folder_menu_has_duplicate_copy_url_and_open_native(self):
        menu = self._menu()
        names = [s.name for s in menu._folder_specs()]
        assert "Duplicate" in names
        assert "Copy URL" in names
        assert "Open in Native File Browser" in names

    def test_open_native_visible_only_for_local_urls(self):
        menu = self._menu()
        local = FileItem(
            url="file:///tmp/foo", name="foo", is_folder=True,
        )
        remote = FileItem(
            url="mock://Home/Docs", name="Docs", is_folder=True,
        )
        specs_local = menu._specs_for("folder", local)
        specs_remote = menu._specs_for("folder", remote)
        local_names = [s.name for s in specs_local]
        remote_names = [s.name for s in specs_remote]
        assert "Open in Native File Browser" in local_names
        assert "Open in Native File Browser" not in remote_names


class TestMenuDuplicateItems:
    """``FileContextMenu._duplicate_items`` dispatch + reporter output."""

    def _build(self) -> Tuple[FileContextMenu, MockBackend]:
        backend = MockBackend()
        detail = _FakeModel(root_url="mock://Home/Documents/Projects")
        widget = _FakeWidget(backend, detail)  # type: ignore[arg-type]
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        return menu, backend

    def test_single_duplicate_emits_success_line(self, reporter):
        menu, backend = self._build()
        item = FileItem(
            url="mock://Home/Documents/Projects/demo.usda",
            name="demo.usda", is_folder=False,
        )
        menu._duplicate_items([item])
        assert reporter.successes == [_STATUS_DUPLICATED_SINGLE]
        assert reporter.errors == []
        _, entries = backend.list_dir(
            "mock://Home/Documents/Projects",
        )
        assert "demo Copy.usda" in {e.name for e in entries}

    def test_multi_duplicate_emits_count_line(self, reporter):
        menu, backend = self._build()
        items = [
            FileItem(
                url="mock://Home/Documents/Projects/demo.usda",
                name="demo.usda", is_folder=False,
            ),
            FileItem(
                url="mock://Home/Documents/Projects/readme.md",
                name="readme.md", is_folder=False,
            ),
        ]
        menu._duplicate_items(items)
        assert reporter.successes == [
            _STATUS_DUPLICATED_MULTI.format(count=2),
        ]

    def test_backend_failure_surfaces_error_line(self, reporter):
        menu, backend = self._build()
        backend._errors[
            "mock://Home/Documents/Projects/demo Copy.usda"
        ] = BackendResult.ERROR_ACCESS_DENIED
        item = FileItem(
            url="mock://Home/Documents/Projects/demo.usda",
            name="demo.usda", is_folder=False,
        )
        menu._duplicate_items([item])
        assert reporter.successes == []
        assert reporter.errors == [
            _ERROR_DUPLICATE_FAILED.format(
                url="mock://Home/Documents/Projects/demo.usda",
                reason="ERROR_ACCESS_DENIED",
            ),
        ]

    def test_empty_list_is_noop(self, reporter):
        menu, _ = self._build()
        menu._duplicate_items([])
        assert reporter.successes == []
        assert reporter.errors == []

    def test_post_destroy_is_noop(self, reporter):
        menu, _ = self._build()
        menu.destroy()
        item = FileItem(
            url="mock://Home/Documents/Projects/demo.usda",
            name="demo.usda", is_folder=False,
        )
        menu._duplicate_items([item])
        assert reporter.successes == []


class TestMenuCopyUrl:
    """``FileContextMenu._copy_url`` dispatch."""

    def test_copy_url_fires_helper(self, reporter):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        item = FileItem(
            url="mock://Home/Docs/demo.usda", name="demo.usda",
            is_folder=False,
        )
        menu._copy_url(item)
        assert reporter.successes == [
            _STATUS_COPY_URL_SUCCESS.format(
                url="mock://Home/Docs/demo.usda",
            ),
        ]

    def test_copy_url_none_item_is_noop(self, reporter):
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        menu = FileContextMenu(widget)  # type: ignore[arg-type]
        menu._copy_url(None)
        assert reporter.successes == []


class TestMenuOpenInNative:
    """``FileContextMenu._open_in_native`` dispatch + predicate."""

    def _menu(self) -> FileContextMenu:
        backend = _FakeBackend()
        detail = _FakeModel(root_url="mock://Home")
        widget = _FakeWidget(backend, detail)
        return FileContextMenu(widget)  # type: ignore[arg-type]

    def test_can_open_predicate_for_local_item(self):
        menu = self._menu()
        local = FileItem(
            url="file:///tmp/foo", name="foo", is_folder=True,
        )
        assert menu._can_open_in_native(local) is True

    def test_can_open_predicate_refuses_remote(self):
        menu = self._menu()
        remote = FileItem(
            url="mock://Home/Docs", name="Docs", is_folder=True,
        )
        assert menu._can_open_in_native(remote) is False

    def test_can_open_predicate_refuses_none(self):
        menu = self._menu()
        assert menu._can_open_in_native(None) is False

    def test_open_in_native_dispatches_helper(self, monkeypatch):
        menu = self._menu()
        calls: List[str] = []
        monkeypatch.setattr(
            file_ops, "open_in_native_browser",
            lambda url, c=calls: (c.append(url), True)[1],
        )
        item = FileItem(
            url="file:///tmp/foo", name="foo", is_folder=True,
        )
        menu._open_in_native(item)
        assert calls == ["file:///tmp/foo"]

    def test_open_in_native_failure_warns(self, reporter, monkeypatch):
        menu = self._menu()
        monkeypatch.setattr(
            file_ops, "open_in_native_browser", lambda url: False,
        )
        item = FileItem(
            url="file:///tmp/foo", name="foo", is_folder=True,
        )
        menu._open_in_native(item)
        assert reporter.warnings == [_WARN_NATIVE_BROWSER_UNAVAILABLE]

    def test_open_in_native_none_item_is_noop(self, monkeypatch):
        menu = self._menu()
        calls: List[str] = []
        monkeypatch.setattr(
            file_ops, "open_in_native_browser",
            lambda url, c=calls: (c.append(url), True)[1],
        )
        menu._open_in_native(None)
        assert calls == []


# ──────────────────────────────────────────────────────────────────────────────
# Step 37 — FileBrowserWidget / ContentBrowserWindow / Application dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetDuplicateDispatch:
    """:meth:`FileBrowserWidget.duplicate_selected` resolves the current
    multi-selection across grid / detail-tree / tree panes and fires
    :meth:`FileContextMenu._duplicate_items`.

    Same stub-menu pattern as :class:`TestWidgetClipboardDispatch` in
    ``test_clipboard_ops.py``.
    """

    def _widget_with_stub_menu(self):
        widget = FileBrowserWidget.__new__(FileBrowserWidget)
        widget._is_grid_view = False
        widget._detail_grid_view = None
        widget._detail_tree_view = None
        widget._tree_tree_view = None

        class _StubMenu:
            def __init__(self):
                self.calls: List[List[FileItem]] = []

            def _duplicate_items(self, items):
                self.calls.append(list(items))

        widget._context_menu = _StubMenu()
        return widget

    def test_no_selection_is_noop(self):
        widget = self._widget_with_stub_menu()
        widget.duplicate_selected()
        assert widget._context_menu.calls == []

    def test_grid_selection_fires_duplicate(self):
        widget = self._widget_with_stub_menu()
        item = FileItem(url="mock://x", name="x", is_folder=False)

        class _GridView:
            def get_selection(self):
                return [item]

        widget._is_grid_view = True
        widget._detail_grid_view = _GridView()
        widget.duplicate_selected()
        assert widget._context_menu.calls == [[item]]

    def test_detail_tree_selection_fires_duplicate(self):
        widget = self._widget_with_stub_menu()
        item = FileItem(url="mock://y", name="y", is_folder=False)

        class _TreeView:
            selection = [item]

        widget._detail_tree_view = _TreeView()
        widget.duplicate_selected()
        assert widget._context_menu.calls == [[item]]

    def test_missing_menu_is_noop(self):
        widget = FileBrowserWidget.__new__(FileBrowserWidget)
        widget._context_menu = None
        widget.duplicate_selected()  # Must not raise.


class TestContentBrowserWindowDuplicateProxy:
    def test_proxy_without_widget_is_noop(self):
        from ovwidgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = None
        win.duplicate_selected()  # Must not raise.

    def test_proxy_forwards_to_widget(self):
        from ovwidgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        calls: List[str] = []

        class _FakeWidget:
            def duplicate_selected(self_inner) -> None:
                calls.append("dup")

        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = _FakeWidget()  # type: ignore[assignment]
        win.duplicate_selected()
        assert calls == ["dup"]


class TestApplicationDuplicateKeyDispatch:
    """Covers :meth:`Application._on_key_pressed` Ctrl+D dispatch."""

    def _app(self):
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
        app._stage_window = None
        app._content_window = None
        return app

    def test_ctrl_d_calls_duplicate(self):
        from ovwidgets.app import application as app_mod

        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def duplicate_selected(self_inner) -> None:
                calls.append("dup")

            def copy_selected(self_inner) -> None:
                pass

            def cut_selected(self_inner) -> None:
                pass

            def paste_into_current(self_inner) -> None:
                pass

        app._content_window = _FakeWin()  # type: ignore[assignment]
        app._on_key_pressed(ord("D"), app_mod._MOD_CTRL, True)
        assert calls == ["dup"]

    def test_ctrl_d_lowercase_also_dispatches(self):
        from ovwidgets.app import application as app_mod

        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def duplicate_selected(self_inner) -> None:
                calls.append("dup")

            def copy_selected(self_inner) -> None:
                pass

            def cut_selected(self_inner) -> None:
                pass

            def paste_into_current(self_inner) -> None:
                pass

        app._content_window = _FakeWin()  # type: ignore[assignment]
        app._on_key_pressed(ord("d"), app_mod._MOD_CTRL, True)
        assert calls == ["dup"]

    def test_plain_d_is_noop(self):
        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def duplicate_selected(self_inner) -> None:
                calls.append("dup")

        app._content_window = _FakeWin()  # type: ignore[assignment]
        app._on_key_pressed(ord("d"), 0, True)
        assert calls == []

    def test_ctrl_shift_d_does_not_fire(self):
        from ovwidgets.app import application as app_mod

        app = self._app()
        calls: List[str] = []

        class _FakeWin:
            def duplicate_selected(self_inner) -> None:
                calls.append("dup")

            def copy_selected(self_inner) -> None:
                pass

            def cut_selected(self_inner) -> None:
                pass

            def paste_into_current(self_inner) -> None:
                pass

        app._content_window = _FakeWin()  # type: ignore[assignment]
        app._on_key_pressed(
            ord("D"),
            app_mod._MOD_CTRL | app_mod._MOD_SHIFT,
            True,
        )
        assert calls == []

    def test_ctrl_d_without_content_window_is_noop(self):
        from ovwidgets.app import application as app_mod

        app = self._app()
        # No _content_window — must not raise.
        app._on_key_pressed(ord("D"), app_mod._MOD_CTRL, True)
