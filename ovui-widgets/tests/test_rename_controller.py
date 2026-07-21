# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 33 — Inline rename.

Coverage:

* :class:`RenameController` — begin / commit / cancel lifecycle,
  validation (empty / illegal-char / duplicate / same-name),
  :meth:`BackendAdapter.move` dispatch, success-path refresh of both
  models, backend-error surface via :class:`ErrorReporter`,
  post-destroy no-op guards.
* :class:`FileContextMenu` Rename wiring — the "Rename" menu entry on
  file and folder targets routes into :meth:`FileBrowserWidget.begin_rename`.
* :class:`FileBrowserWidget` rename dispatch — ``begin_rename`` /
  ``begin_rename_selected`` forward to the controller; the grid
  selection is preferred over the tree selection in grid mode.
* :class:`ContentBrowserWindow` F2 proxy — ``begin_rename_selected``
  reaches the widget.
* Application F2 dispatch — pressing F2 invokes both the Stage and
  Content windows' ``begin_rename_selected`` hooks.
* Delegate / card render branch — the inline :class:`ui.StringField`
  is emitted when the controller flags an item as the active rename
  target.
* :class:`MockBackend.move` and :class:`LocalFSBackend.move` —
  round-trip renames against the in-memory tree and a real tmpdir.

Same fixture / reporter pattern as ``tests/test_file_ops.py``: module-
scoped ``ephemeral_window``, an ``in_window_frame`` context manager,
and a ``_RecordedReport`` that captures :class:`ErrorReporter` warnings
/ errors without needing a running :class:`Application`.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Any, List, Optional

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.content.backends.backend_adapter import BackendResult
from ovui_widgets.content.backends.local_fs_backend import LocalFSBackend
from ovui_widgets.content.widget import (
    FileBrowserWidget,
    FileContextMenu,
    FileItem,
    RenameController,
)
from ovui_widgets.content.widget.rename_controller import (
    _ERROR_RENAME_FAILED,
    _WARN_DUPLICATE_NAME,
    _WARN_EMPTY_NAME,
    _WARN_ILLEGAL_CHARS,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window shared across every test — same pattern as
    :mod:`tests.test_file_ops`."""
    win = ui.Window("_test_rename_controller", width=400, height=240)
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


class _RecordedReport:
    """Captures every :class:`ErrorReporter` warning / error message."""

    def __init__(self) -> None:
        self.warnings: List[str] = []
        self.errors: List[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda msg, duration_ms=4000, r=self: r.warnings.append(msg),
        )
        monkeypatch.setattr(
            ErrorReporter, "show_error",
            lambda msg, duration_ms=5000, r=self: r.errors.append(msg),
        )


@pytest.fixture
def reporter(monkeypatch: pytest.MonkeyPatch) -> _RecordedReport:
    r = _RecordedReport()
    r.install(monkeypatch)
    return r


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────────


class _FakeModel:
    """Stand-in for :class:`FileBrowserModel`.

    Records ``refresh_item`` / ``refresh_all`` / ``_item_changed`` calls;
    :meth:`resolve` returns a pre-seeded item map.
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
        self.item_changed_calls: List[Any] = []

    def resolve(self, url: str) -> Optional[FileItem]:
        return self._resolved.get(url)

    def refresh_item(self, item: FileItem) -> None:
        self.refresh_item_calls.append(item)

    def refresh_all(self) -> None:
        self.refresh_all_count += 1

    def _item_changed(self, item: Any) -> None:
        self.item_changed_calls.append(item)


class _FakeBackend:
    """Records move calls and returns a configurable result."""

    def __init__(self, result: BackendResult = BackendResult.OK) -> None:
        self.result = result
        self.move_calls: List[tuple] = []

    def parent_url(self, url: str) -> Optional[str]:
        tail = url.replace("mock://", "")
        if "/" not in tail:
            return None
        return url.rsplit("/", 1)[0]

    def join_url(self, base: str, child: str) -> str:
        return f"{base}/{child}"

    def move(
        self, src: str, dst: str, overwrite: bool = False,
    ) -> BackendResult:
        self.move_calls.append((src, dst, overwrite))
        return self.result


class _FakeGrid:
    """Records ``refresh`` / ``get_selection`` calls."""

    def __init__(self, selection: Optional[List[FileItem]] = None) -> None:
        self.refresh_count = 0
        self._selection = selection or []

    def refresh(self) -> None:
        self.refresh_count += 1

    def get_selection(self) -> List[FileItem]:
        return list(self._selection)


class _FakeWidget:
    """Minimal widget surface the :class:`RenameController` reads."""

    def __init__(
        self,
        backend: _FakeBackend,
        detail_model: _FakeModel,
        tree_model: Optional[_FakeModel] = None,
        grid: Optional[_FakeGrid] = None,
    ) -> None:
        self._backend = backend
        self._detail_model = detail_model
        self._tree_model = tree_model
        self._detail_grid_view = grid


def _make_item(
    url: str = "mock://Home/Projects",
    name: str = "Projects",
    is_folder: bool = True,
    parent: Optional[FileItem] = None,
) -> FileItem:
    return FileItem(
        url=url, name=name, is_folder=is_folder, parent=parent,
    )


# ──────────────────────────────────────────────────────────────────────────────
# RenameController — public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestRenameControllerSurface:
    def test_reexported_from_widget_package(self):
        from ovui_widgets.content.widget.rename_controller import (
            RenameController as _RC,
        )
        assert RenameController is _RC

    def test_widget_package_all_contains_rename_controller(self):
        import ovui_widgets.content.widget as pkg
        assert "RenameController" in pkg.__all__

    def test_constructor_starts_idle(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        assert ctrl.active_item is None
        assert not ctrl.is_renaming(_make_item())


# ──────────────────────────────────────────────────────────────────────────────
# RenameController — begin_rename
# ──────────────────────────────────────────────────────────────────────────────


class TestBeginRename:
    def test_begin_sets_active_item(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        item = _make_item()
        ctrl.begin_rename(item)
        assert ctrl.active_item is item
        assert ctrl.is_renaming(item)

    def test_begin_invalidates_both_models(self):
        detail = _FakeModel()
        tree = _FakeModel()
        widget = _FakeWidget(_FakeBackend(), detail, tree)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        item = _make_item()
        ctrl.begin_rename(item)
        assert detail.item_changed_calls == [item]
        assert tree.item_changed_calls == [item]

    def test_begin_refreshes_grid(self):
        grid = _FakeGrid()
        widget = _FakeWidget(_FakeBackend(), _FakeModel(), grid=grid)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item())
        assert grid.refresh_count == 1

    def test_begin_rejects_non_file_item(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename("not an item")  # type: ignore[arg-type]
        assert ctrl.active_item is None

    def test_begin_rejects_none(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(None)  # type: ignore[arg-type]
        assert ctrl.active_item is None

    def test_second_begin_cancels_first(self):
        detail = _FakeModel()
        widget = _FakeWidget(_FakeBackend(), detail)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        a = _make_item(url="mock://Home/A", name="A")
        b = _make_item(url="mock://Home/B", name="B")
        ctrl.begin_rename(a)
        ctrl.begin_rename(b)
        assert ctrl.active_item is b
        # ``a`` was invalidated on begin(a) and on cancel-before-b;
        # ``b`` was invalidated on begin(b).
        assert detail.item_changed_calls.count(a) == 2
        assert detail.item_changed_calls.count(b) == 1

    def test_begin_after_destroy_noop(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.destroy()
        ctrl.begin_rename(_make_item())
        assert ctrl.active_item is None


# ──────────────────────────────────────────────────────────────────────────────
# RenameController — cancel_rename
# ──────────────────────────────────────────────────────────────────────────────


class TestCancelRename:
    def test_cancel_clears_active(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item())
        ctrl.cancel_rename()
        assert ctrl.active_item is None

    def test_cancel_does_not_call_backend(self):
        backend = _FakeBackend()
        widget = _FakeWidget(backend, _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item())
        ctrl.cancel_rename()
        assert backend.move_calls == []

    def test_cancel_while_idle_is_noop(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.cancel_rename()  # No raise.
        assert ctrl.active_item is None

    def test_cancel_invalidates_item_once(self):
        detail = _FakeModel()
        widget = _FakeWidget(_FakeBackend(), detail)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        item = _make_item()
        ctrl.begin_rename(item)
        detail.item_changed_calls.clear()
        ctrl.cancel_rename()
        assert detail.item_changed_calls == [item]


# ──────────────────────────────────────────────────────────────────────────────
# RenameController — commit_rename validation
# ──────────────────────────────────────────────────────────────────────────────


class TestCommitValidation:
    def _setup(self, reporter):
        backend = _FakeBackend()
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        return backend, detail, ctrl

    def test_commit_without_active_is_noop(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        ctrl.commit_rename("anything")
        assert backend.move_calls == []
        assert reporter.warnings == []
        assert reporter.errors == []

    def test_empty_name_rejected_with_warning(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        ctrl.begin_rename(_make_item())
        ctrl.commit_rename("   ")
        assert backend.move_calls == []
        assert reporter.warnings == [_WARN_EMPTY_NAME]
        assert ctrl.active_item is None

    def test_forward_slash_rejected(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        ctrl.begin_rename(_make_item())
        ctrl.commit_rename("a/b")
        assert backend.move_calls == []
        assert reporter.warnings == [_WARN_ILLEGAL_CHARS]

    def test_backslash_rejected(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        ctrl.begin_rename(_make_item())
        ctrl.commit_rename("a\\b")
        assert backend.move_calls == []
        assert reporter.warnings == [_WARN_ILLEGAL_CHARS]

    def test_name_trimmed_before_validation(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("   NewName   ")
        assert backend.move_calls == [
            ("mock://Home/Old", "mock://Home/NewName", False),
        ]

    def test_same_name_no_op(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        item = _make_item(url="mock://Home/Same", name="Same")
        ctrl.begin_rename(item)
        ctrl.commit_rename("Same")
        assert backend.move_calls == []
        assert reporter.warnings == []
        assert reporter.errors == []
        assert ctrl.active_item is None

    def test_duplicate_sibling_rejected(self, reporter):
        backend, _, ctrl = self._setup(reporter)
        parent = _make_item(url="mock://Home", name="Home")
        sib_a = _make_item(
            url="mock://Home/A", name="A", parent=parent,
        )
        sib_b = _make_item(
            url="mock://Home/B", name="B", parent=parent,
        )
        parent.add_child(sib_a)
        parent.add_child(sib_b)
        ctrl.begin_rename(sib_a)
        ctrl.commit_rename("B")
        assert backend.move_calls == []
        assert reporter.warnings == [_WARN_DUPLICATE_NAME]

    def test_rename_same_name_on_parented_item_skips_dup_check(
        self, reporter,
    ):
        """Self-name is excluded from the duplicate check."""
        backend, _, ctrl = self._setup(reporter)
        parent = _make_item(url="mock://Home", name="Home")
        child = _make_item(
            url="mock://Home/X", name="X", parent=parent,
        )
        parent.add_child(child)
        ctrl.begin_rename(child)
        ctrl.commit_rename("X")
        assert backend.move_calls == []
        assert reporter.warnings == []


# ──────────────────────────────────────────────────────────────────────────────
# RenameController — commit_rename backend + refresh
# ──────────────────────────────────────────────────────────────────────────────


class TestCommitBackendRefresh:
    def test_success_calls_backend_with_joined_url(self, reporter):
        backend = _FakeBackend(result=BackendResult.OK)
        detail = _FakeModel()
        widget = _FakeWidget(backend, detail)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/OldName", name="OldName",
        ))
        ctrl.commit_rename("NewName")
        assert backend.move_calls == [
            ("mock://Home/OldName", "mock://Home/NewName", False),
        ]
        assert reporter.errors == []

    def test_success_clears_active_item(self, reporter):
        backend = _FakeBackend()
        widget = _FakeWidget(backend, _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("New")
        assert ctrl.active_item is None

    def test_success_refreshes_resolved_detail_parent(self, reporter):
        parent = _make_item(url="mock://Home", name="Home")
        detail = _FakeModel(resolved={"mock://Home": parent})
        backend = _FakeBackend()
        widget = _FakeWidget(backend, detail)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("New")
        assert detail.refresh_item_calls == [parent]
        assert detail.refresh_all_count == 0

    def test_success_falls_back_to_refresh_all(self, reporter):
        # Parent unresolved in detail model → refresh_all.
        detail = _FakeModel()
        backend = _FakeBackend()
        widget = _FakeWidget(backend, detail)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("New")
        assert detail.refresh_all_count == 1
        assert detail.refresh_item_calls == []

    def test_success_refreshes_tree_parent_if_resolved(self, reporter):
        parent_d = _make_item(url="mock://Home", name="Home")
        parent_t = _make_item(url="mock://Home", name="Home")
        detail = _FakeModel(resolved={"mock://Home": parent_d})
        tree = _FakeModel(resolved={"mock://Home": parent_t})
        backend = _FakeBackend()
        widget = _FakeWidget(backend, detail, tree)
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("New")
        assert detail.refresh_item_calls == [parent_d]
        assert tree.refresh_item_calls == [parent_t]

    def test_backend_error_surfaces_via_error_reporter(self, reporter):
        backend = _FakeBackend(result=BackendResult.ERROR_ACCESS_DENIED)
        widget = _FakeWidget(backend, _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("New")
        assert backend.move_calls == [
            ("mock://Home/Old", "mock://Home/New", False),
        ]
        assert reporter.warnings == []
        assert reporter.errors == [
            _ERROR_RENAME_FAILED.format(reason="ERROR_ACCESS_DENIED"),
        ]
        assert ctrl.active_item is None

    def test_backend_already_exists_surfaces_error(self, reporter):
        backend = _FakeBackend(result=BackendResult.ERROR_ALREADY_EXISTS)
        widget = _FakeWidget(backend, _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item(
            url="mock://Home/Old", name="Old",
        ))
        ctrl.commit_rename("New")
        assert reporter.errors == [
            _ERROR_RENAME_FAILED.format(reason="ERROR_ALREADY_EXISTS"),
        ]

    def test_post_destroy_commit_is_noop(self, reporter):
        backend = _FakeBackend()
        widget = _FakeWidget(backend, _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item())
        ctrl.destroy()
        ctrl.commit_rename("Whatever")
        assert backend.move_calls == []


# ──────────────────────────────────────────────────────────────────────────────
# RenameController — destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_is_idempotent(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.destroy()
        ctrl.destroy()  # no raise

    def test_destroy_clears_active(self):
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        ctrl.begin_rename(_make_item())
        ctrl.destroy()
        assert ctrl.active_item is None


# ──────────────────────────────────────────────────────────────────────────────
# FileContextMenu — Rename entry wiring
# ──────────────────────────────────────────────────────────────────────────────


class _BeginRenameWidget:
    """Widget double that records ``begin_rename`` calls."""

    def __init__(self) -> None:
        self._backend = _FakeBackend()
        self._detail_model = _FakeModel()
        self._tree_model = _FakeModel()
        self._detail_grid_view: Optional[_FakeGrid] = None
        self.begin_rename_calls: List[FileItem] = []

    def begin_rename(self, item: FileItem) -> None:
        self.begin_rename_calls.append(item)


class TestContextMenuRenameEntry:
    def test_file_spec_has_rename_entry(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        entries = [s.name for s in menu._file_specs()]
        assert "Rename" in entries

    def test_folder_spec_has_rename_entry(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        entries = [s.name for s in menu._folder_specs()]
        assert "Rename" in entries

    def test_empty_spec_does_not_have_rename(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        entries = [s.name for s in menu._empty_specs()]
        assert "Rename" not in entries

    def test_file_rename_routes_to_widget_begin_rename(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        f = _make_item(
            url="mock://f.usd", name="f.usd", is_folder=False,
        )
        rename_spec = next(
            s for s in menu._file_specs() if s.name == "Rename"
        )
        rename_spec.click_fn(f)
        assert w.begin_rename_calls == [f]

    def test_folder_rename_routes_to_widget_begin_rename(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        folder = _make_item()
        rename_spec = next(
            s for s in menu._folder_specs() if s.name == "Rename"
        )
        rename_spec.click_fn(folder)
        assert w.begin_rename_calls == [folder]

    def test_rename_with_none_item_falls_through_to_stub(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        menu._begin_rename(None)
        assert w.begin_rename_calls == []

    def test_rename_post_destroy_is_noop(self):
        w = _BeginRenameWidget()
        menu = FileContextMenu(w)  # type: ignore[arg-type]
        menu.destroy()
        menu._begin_rename(_make_item())
        assert w.begin_rename_calls == []


# ──────────────────────────────────────────────────────────────────────────────
# MockBackend.move — round-trip
# ──────────────────────────────────────────────────────────────────────────────


class TestMockBackendMove:
    def test_rename_folder_updates_url(self):
        backend = MockBackend()
        assert backend.move(
            "mock://Home/Documents",
            "mock://Home/Docs",
        ) == BackendResult.OK
        r1, _ = backend.stat("mock://Home/Docs")
        assert r1 == BackendResult.OK
        r2, _ = backend.stat("mock://Home/Documents")
        assert r2 == BackendResult.ERROR_NOT_FOUND

    def test_rename_file_updates_url(self):
        backend = MockBackend()
        assert backend.move(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Documents/Projects/demo2.usda",
        ) == BackendResult.OK
        r1, _ = backend.stat(
            "mock://Home/Documents/Projects/demo2.usda",
        )
        assert r1 == BackendResult.OK

    def test_duplicate_target_rejected(self):
        backend = MockBackend()
        # ``Textures`` is an existing sibling of ``Documents`` under
        # ``Home`` in the default mock tree — renaming onto it must
        # report the collision without clobbering.
        result = backend.move(
            "mock://Home/Documents",
            "mock://Home/Textures",
        )
        assert result == BackendResult.ERROR_ALREADY_EXISTS

    def test_missing_source_not_found(self):
        backend = MockBackend()
        result = backend.move(
            "mock://Home/Bogus",
            "mock://Home/Other",
        )
        assert result == BackendResult.ERROR_NOT_FOUND


# ──────────────────────────────────────────────────────────────────────────────
# LocalFSBackend.move — round-trip against a real tmpdir
# ──────────────────────────────────────────────────────────────────────────────


class TestLocalFsBackendMove:
    def test_renames_file_on_disk(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = os.path.join(tmpdir, "old.txt")
            with open(src_path, "w", encoding="utf-8") as f:
                f.write("content")
            src_url = backend.join_url(tmpdir, "old.txt")
            dst_url = backend.join_url(tmpdir, "new.txt")
            assert backend.move(src_url, dst_url) == BackendResult.OK
            assert not os.path.exists(src_path)
            assert os.path.exists(os.path.join(tmpdir, "new.txt"))

    def test_renames_folder_on_disk(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = os.path.join(tmpdir, "OldFolder")
            os.mkdir(src_path)
            src_url = backend.join_url(tmpdir, "OldFolder")
            dst_url = backend.join_url(tmpdir, "NewFolder")
            assert backend.move(src_url, dst_url) == BackendResult.OK
            assert not os.path.isdir(src_path)
            assert os.path.isdir(os.path.join(tmpdir, "NewFolder"))

    def test_duplicate_returns_already_exists(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(
                os.path.join(tmpdir, "a.txt"), "w", encoding="utf-8",
            ) as f:
                f.write("a")
            with open(
                os.path.join(tmpdir, "b.txt"), "w", encoding="utf-8",
            ) as f:
                f.write("b")
            src = backend.join_url(tmpdir, "a.txt")
            dst = backend.join_url(tmpdir, "b.txt")
            assert (
                backend.move(src, dst)
                == BackendResult.ERROR_ALREADY_EXISTS
            )

    def test_missing_source_returns_not_found(self):
        backend = LocalFSBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            src = backend.join_url(tmpdir, "nope.txt")
            dst = backend.join_url(tmpdir, "never.txt")
            assert (
                backend.move(src, dst) == BackendResult.ERROR_NOT_FOUND
            )


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserWidget — end-to-end rename via RenameController
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetRenameIntegration:
    def test_rename_renames_in_mock_backend(
        self, ephemeral_window, reporter,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            documents = widget._detail_model.resolve(
                "mock://Home/Documents",
            )
            assert documents is not None
            widget.begin_rename(documents)
            assert widget._rename_controller.active_item is documents
            widget._rename_controller.commit_rename("Docs")
            result, entries = backend.list_dir("mock://Home")
            names = [e.name for e in entries]
            assert "Docs" in names
            assert "Documents" not in names
            assert reporter.errors == []
        finally:
            widget.destroy()

    def test_begin_rename_selected_uses_grid_selection(
        self, ephemeral_window, reporter,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            documents = widget._detail_model.resolve(
                "mock://Home/Documents",
            )
            assert documents is not None
            widget._detail_grid_view.set_selection([documents])
            widget.begin_rename_selected()
            assert widget._rename_controller.active_item is documents
        finally:
            widget.destroy()

    def test_begin_rename_selected_no_selection_noop(
        self, ephemeral_window, reporter,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget.begin_rename_selected()
            assert widget._rename_controller.active_item is None
        finally:
            widget.destroy()

    def test_destroy_tears_down_rename_controller(
        self, ephemeral_window, reporter,
    ):
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        widget.destroy()
        assert widget._rename_controller is None

    def test_duplicate_name_caught_before_backend(
        self, ephemeral_window, reporter,
    ):
        """Renaming to an existing sibling's name is rejected client-side."""
        backend = MockBackend()
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Home")
        try:
            widget._detail_model.get_item_children(None)
            documents = widget._detail_model.resolve(
                "mock://Home/Documents",
            )
            assert documents is not None
            # ``Textures`` is an existing sibling of ``Documents`` under
            # ``Home``; renaming onto it must be rejected client-side
            # before the backend is touched.
            widget.begin_rename(documents)
            widget._rename_controller.commit_rename("Textures")
            assert reporter.warnings == [_WARN_DUPLICATE_NAME]
            _, entries = backend.list_dir("mock://Home")
            names = [e.name for e in entries]
            assert "Documents" in names
            assert "Textures" in names
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# ContentBrowserWindow.begin_rename_selected — proxy forwards to widget
# ──────────────────────────────────────────────────────────────────────────────


class TestContentBrowserWindowProxy:
    def test_forwards_to_widget(self):
        from ovui_widgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )

        calls: List[str] = []

        class _FakeInnerWidget:
            def begin_rename_selected(self) -> None:
                calls.append("called")

        # Sidestep :meth:`ManagedWindow.__init__` — we only want the
        # method wrapper under test.
        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = _FakeInnerWidget()  # type: ignore[assignment]
        win.begin_rename_selected()
        assert calls == ["called"]

    def test_no_widget_is_noop(self):
        from ovui_widgets.content.window.content_browser_window import (
            ContentBrowserWindow,
        )
        win = ContentBrowserWindow.__new__(ContentBrowserWindow)
        win._widget = None
        win.begin_rename_selected()  # no raise


# ──────────────────────────────────────────────────────────────────────────────
# Delegate / card render branch
# ──────────────────────────────────────────────────────────────────────────────


class TestDelegateAndCardRenameBranch:
    """Verify the rename-mode branch is reachable from delegate + card."""

    def test_file_browser_delegate_set_rename_controller(self):
        from ovui_widgets.content.widget.file_browser_delegate import (
            FileBrowserDelegate,
        )
        delegate = FileBrowserDelegate()
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        delegate.set_rename_controller(ctrl)
        assert delegate._rename_controller is ctrl

    def test_tree_folder_delegate_set_rename_controller(self):
        from ovui_widgets.content.widget.file_browser_delegate import (
            TreeFolderDelegate,
        )
        delegate = TreeFolderDelegate()
        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        delegate.set_rename_controller(ctrl)
        assert delegate._rename_controller is ctrl

    def test_card_without_controller_renders_label(
        self, ephemeral_window,
    ):
        from ovui_widgets.content.widget.file_card import FileCard

        item = FileItem(
            url="mock://Home/X", name="X", is_folder=False,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        assert card._rename_field is None
        assert card._label is not None
        card.destroy()

    def test_card_with_active_rename_renders_stringfield(
        self, ephemeral_window,
    ):
        from ovui_widgets.content.widget.file_card import FileCard

        widget = _FakeWidget(_FakeBackend(), _FakeModel())
        ctrl = RenameController(widget)  # type: ignore[arg-type]
        item = FileItem(
            url="mock://Home/X", name="X", is_folder=False,
        )
        ctrl.begin_rename(item)
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                rename_controller=ctrl,
            )
        assert card._rename_field is not None
        assert card._label is None
        card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Application F2 dispatch — forwards to both Stage and Content windows
# ──────────────────────────────────────────────────────────────────────────────


class TestApplicationF2Dispatch:
    def test_f2_dispatches_to_content_window(self):
        """Simulates the F2 branch of :meth:`Application._on_key_pressed`.

        Instead of spinning up a full Application (heavy), assemble the
        minimal attribute surface the handler reads and call the method
        directly with a stubbed key code.
        """
        from ovui_widgets.app import application as app_module
        from ovui_widgets.app.application import Application

        app = Application.__new__(Application)
        app._viewport_window = None
        app._undo_manager = None
        app._main_win = None
        app._property_window = None

        stage_calls: List[str] = []
        content_calls: List[str] = []

        class _Stage:
            def begin_rename_selected(self) -> None:
                stage_calls.append("stage")

        class _Content:
            def begin_rename_selected(self) -> None:
                content_calls.append("content")

        app._stage_window = _Stage()
        app._content_window = _Content()

        app._on_key_pressed(app_module._KEY_F2, 0, True)
        assert stage_calls == ["stage"]
        assert content_calls == ["content"]
