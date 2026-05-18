# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 39 — external OS drag-drop INTO content browser.

Coverage:

* :meth:`ContentBrowserWindow._on_external_drop` — parses
  ``event.mime_data`` (``\\n``-joined URLs), guards the empty / None
  / whitespace payloads, short-circuits when the widget is not yet
  built, and surfaces an aggregate "Imported N items" status line.
* :meth:`ContentBrowserWindow._build_ui` — wires
  :meth:`ui.Window.set_drop_fn` exactly once.
* :meth:`FileBrowserWidget.accept_external_drop` — URL filtering,
  copy-into-current-folder semantics, refresh cascade (detail pane
  + tree pane + grid view), destroyed-widget no-op, empty-name skip,
  and batch partial-failure behaviour.
* :attr:`FileBrowserWidget.detail_root_url` — live / post-destroy
  values.

Tests build the widget in a throwaway :class:`ui.Window` frame (the
standard pattern from :file:`tests/test_content_drag_drop.py`); the
window under test is a full :class:`ContentBrowserWindow` so the
drop-handler wiring path is exercised end-to-end. Status-bar asserts
patch :meth:`ErrorReporter.show_status` so the stderr fallback does
not print during the suite.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Optional
from unittest.mock import MagicMock, patch

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.widget import (
    FileBrowserWidget,
)
from ovwidgets.content.window.content_browser_window import (
    ContentBrowserWindow,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


class _FakeDropEvent:
    """Minimal stand-in for ovui's :class:`WidgetMouseDropEvent`.

    ovui's event carries ``mime_data`` (newline-joined URLs), ``x``,
    ``y`` — the production drop handler only reads ``mime_data``, so
    this stub mirrors that surface. A ``None`` sentinel pins the
    "missing attribute" case.
    """

    def __init__(self, mime_data: Optional[str]) -> None:
        self.mime_data = mime_data


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window shared across every test in the module."""
    win = ui.Window("_test_external_drop", width=600, height=400)
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


@pytest.fixture
def backend():
    """Fresh :class:`MockBackend` with the default tree. Reset per test."""
    b = MockBackend()
    yield b
    b.reset()


@pytest.fixture
def widget(backend, ephemeral_window):
    """:class:`FileBrowserWidget` rooted at ``mock://Home/Documents/Projects``."""
    with in_window_frame(ephemeral_window):
        w = FileBrowserWidget(backend, "mock://Home/Documents/Projects")
    yield w
    w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserWidget.detail_root_url
# ──────────────────────────────────────────────────────────────────────────────


class TestDetailRootUrl:
    """The widget-level accessor the window reads at drop time."""

    def test_returns_current_detail_root(self, backend, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(backend, "mock://Home/Documents/Projects")
        try:
            assert w.detail_root_url == "mock://Home/Documents/Projects"
        finally:
            w.destroy()

    def test_tracks_navigation(self, backend, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(backend, "mock://Home/Documents/Projects")
        try:
            w._detail_model.set_root_url("mock://Home/Textures")
            assert w.detail_root_url == "mock://Home/Textures"
        finally:
            w.destroy()

    def test_none_after_destroy(self, backend, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(backend, "mock://Home/Documents/Projects")
        w.destroy()
        assert w.detail_root_url is None


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserWidget.accept_external_drop
# ──────────────────────────────────────────────────────────────────────────────


class TestAcceptExternalDrop:
    """Core copy flow on the widget — exercised without the window."""

    def test_single_url_copies_into_current_folder(self, backend, widget):
        result = widget.accept_external_drop([
            "mock://Home/Textures/concrete.png",
        ])
        assert result == 1
        # Destination materialised.
        r, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        assert r == BackendResult.OK
        # Source preserved (copy, not move — architecture §30.3).
        r_src, _ = backend.stat("mock://Home/Textures/concrete.png")
        assert r_src == BackendResult.OK

    def test_multiple_urls_all_copied(self, backend, widget):
        result = widget.accept_external_drop([
            "mock://Home/Textures/concrete.png",
            "mock://Home/Textures/metal.hdr",
        ])
        assert result == 2
        for dst in (
            "mock://Home/Documents/Projects/concrete.png",
            "mock://Home/Documents/Projects/metal.hdr",
        ):
            r, _ = backend.stat(dst)
            assert r == BackendResult.OK

    def test_empty_list_is_noop(self, backend, widget):
        result = widget.accept_external_drop([])
        assert result == 0

    def test_whitespace_only_urls_filtered(self, backend, widget):
        # Empty + whitespace entries must not be forwarded to the backend.
        with patch.object(widget._backend, "copy") as mock_copy:
            result = widget.accept_external_drop(["", "   ", "\t"])
        assert result == 0
        mock_copy.assert_not_called()

    def test_post_destroy_is_noop(self, backend, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        w.destroy()
        # After destroy the backend + detail model are cleared — the
        # method must silently return without touching anything.
        result = w.accept_external_drop([
            "mock://Home/Textures/concrete.png",
        ])
        assert result == 0

    def test_drop_into_empty_folder_materialises_rows(
        self, backend, ephemeral_window,
    ):
        # Create an empty destination folder and root the widget there.
        assert backend.create_folder(
            "mock://Home/Documents/Empty",
        ) == BackendResult.OK
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(backend, "mock://Home/Documents/Empty")
        try:
            # Pre-drop: no children.
            pre_res, pre_entries = backend.list_dir(
                "mock://Home/Documents/Empty",
            )
            assert pre_res == BackendResult.OK
            assert pre_entries == []

            result = w.accept_external_drop([
                "mock://Home/Textures/concrete.png",
            ])
            assert result == 1
            # Row present after drop.
            post_res, post_entries = backend.list_dir(
                "mock://Home/Documents/Empty",
            )
            assert post_res == BackendResult.OK
            assert any(e.name == "concrete.png" for e in post_entries)
        finally:
            w.destroy()

    def test_refresh_cascades_after_drop(self, backend, widget):
        # refresh_all on the detail model + _on_drop_complete on the
        # widget should both fire exactly once per batch (regardless of
        # how many URLs landed).
        detail_refresh_calls: List[int] = []
        widget._detail_model.refresh_all = (  # type: ignore[assignment]
            lambda: detail_refresh_calls.append(1)
        )
        complete_calls: List[int] = []
        widget._on_drop_complete = (  # type: ignore[assignment]
            lambda: complete_calls.append(1)
        )
        result = widget.accept_external_drop([
            "mock://Home/Textures/concrete.png",
            "mock://Home/Textures/metal.hdr",
        ])
        assert result == 2
        assert detail_refresh_calls == [1]
        assert complete_calls == [1]

    def test_no_refresh_when_zero_successes(self, backend, widget):
        # A batch where every URL is a failure (nonexistent source)
        # must NOT fire refresh_all / on_drop_complete — saves the
        # pane from a no-op rebuild.
        detail_refresh_calls: List[int] = []
        widget._detail_model.refresh_all = (  # type: ignore[assignment]
            lambda: detail_refresh_calls.append(1)
        )
        complete_calls: List[int] = []
        widget._on_drop_complete = (  # type: ignore[assignment]
            lambda: complete_calls.append(1)
        )
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_warning"):
            result = widget.accept_external_drop([
                "mock://NonExistent/ghost.usda",
            ])
        assert result == 0
        assert detail_refresh_calls == []
        assert complete_calls == []

    def test_collision_logged_but_does_not_abort_batch(
        self, backend, widget,
    ):
        # Pre-seed a collision — the first URL already exists at the
        # destination, the second is a clean copy. The first must fail
        # (ERROR_ALREADY_EXISTS), the second must succeed, and the
        # batch return count is 1 (only the clean copy counted).
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )  # seed the collision

        # Clobber the detail root to Textures so demo.usda collides there.
        widget._detail_model.set_root_url("mock://Home/Textures")

        with patch(
            "ovwidgets.common.error_reporter.ErrorReporter.show_warning"
        ) as warn:
            result = widget.accept_external_drop([
                "mock://Home/Documents/Projects/demo.usda",   # collides
                "mock://Home/Documents/Projects/readme.md",   # clean
            ])
        assert result == 1
        # The collision surfaced a warning.
        assert warn.called
        # Clean copy landed.
        r, _ = backend.stat("mock://Home/Textures/readme.md")
        assert r == BackendResult.OK

    def test_empty_basename_source_skipped(self, backend, widget):
        # Degenerate URL — basename comes back empty. MockBackend.basename
        # returns "" for "mock://" alone; the loop skips without calling
        # copy.
        with patch.object(widget._backend, "copy") as mock_copy:
            result = widget.accept_external_drop(["mock://"])
        assert result == 0
        mock_copy.assert_not_called()

    def test_copies_use_overwrite_false(self, backend, widget):
        # Per the content browser implementation step 39 the copies are unconditional non-
        # overwriting — a collision is a failure, not a prompt.
        calls: List[tuple] = []
        orig_copy = backend.copy

        def tracked(src, dst, overwrite=False):
            calls.append((src, dst, overwrite))
            return orig_copy(src, dst, overwrite=overwrite)

        widget._backend.copy = tracked  # type: ignore[assignment]
        widget.accept_external_drop([
            "mock://Home/Textures/concrete.png",
        ])
        assert len(calls) == 1
        assert calls[0][2] is False


# ──────────────────────────────────────────────────────────────────────────────
# ContentBrowserWindow._on_external_drop + set_drop_fn wiring
# ──────────────────────────────────────────────────────────────────────────────


class TestContentBrowserWindowDropWiring:
    """The window-level drop handler + its ``set_drop_fn`` registration."""

    def test_build_ui_calls_set_drop_fn(self):
        # ``_build_ui`` must call ``self._window.set_drop_fn`` exactly
        # once with the window's ``_on_external_drop`` as the callback
        # (when ovui exposes the method — the ``hasattr`` guard keeps
        # headless / older builds functional). ovui's C++ Window type
        # rejects arbitrary attribute assignment, so the test swaps
        # the whole window for a :class:`MagicMock` that carries the
        # method. The swap happens after the real window is destroyed
        # to avoid leaking a registered drop handler onto a live
        # window.
        cw = ContentBrowserWindow(backend=MockBackend())
        cw._window.destroy()
        cw._window = MagicMock()
        try:
            cw._build_ui()
            cw._window.set_drop_fn.assert_called_once_with(
                cw._on_external_drop,
            )
        finally:
            # Destroy the widget; the mock window has no real resources.
            if cw._widget is not None:
                cw._widget.destroy()
                cw._widget = None

    def test_build_ui_no_set_drop_fn_method_is_noop(self):
        # If ovui's window does not expose set_drop_fn, _build_ui must
        # not crash. Remove the attribute to trigger the hasattr
        # fallback branch.
        cw = ContentBrowserWindow(backend=MockBackend())
        try:
            # Patch the window to report no set_drop_fn support.
            with patch(
                "ovwidgets.content.window."
                "content_browser_window.hasattr",
                return_value=False,
            ):
                cw._build_ui()  # must not raise
        finally:
            cw.destroy()

    def test_drop_before_widget_built_is_noop(self):
        # A drop that fires between __init__ and _build_ui must not
        # crash — in practice ovui never fires a drop on an invisible
        # window, but the guard keeps the method robust.
        cw = ContentBrowserWindow(backend=MockBackend())
        try:
            assert cw._widget is None
            cw._on_external_drop(_FakeDropEvent(
                "mock://Home/Textures/concrete.png",
            ))
            # No crash, no-op — widget still None.
            assert cw._widget is None
        finally:
            cw.destroy()

    def test_drop_with_no_mime_data_is_noop(self):
        cw = ContentBrowserWindow(backend=MockBackend())
        try:
            cw._build_ui()
            # Event with mime_data=None.
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status:
                cw._on_external_drop(_FakeDropEvent(None))
            status.assert_not_called()
        finally:
            cw.destroy()

    def test_drop_with_empty_mime_data_is_noop(self):
        cw = ContentBrowserWindow(backend=MockBackend())
        try:
            cw._build_ui()
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status:
                cw._on_external_drop(_FakeDropEvent(""))
            status.assert_not_called()
        finally:
            cw.destroy()

    def test_drop_with_whitespace_only_mime_is_noop(self):
        cw = ContentBrowserWindow(backend=MockBackend())
        try:
            cw._build_ui()
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status:
                cw._on_external_drop(_FakeDropEvent("\n\n \n"))
            status.assert_not_called()
        finally:
            cw.destroy()

    def test_drop_event_without_mime_data_attr_is_noop(self):
        cw = ContentBrowserWindow(backend=MockBackend())
        try:
            cw._build_ui()
            # Raw object() has no mime_data attribute at all.
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status:
                cw._on_external_drop(object())
            status.assert_not_called()
        finally:
            cw.destroy()

    def test_single_url_drop_copies_and_posts_status(self):
        # Full window → widget → model path. Status text for a single
        # file is "Imported 1 item via drop" (singular).
        be = MockBackend()
        cw = ContentBrowserWindow(
            backend=be, start_url="mock://Home/Documents/Projects",
        )
        try:
            cw._build_ui()
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status:
                cw._on_external_drop(_FakeDropEvent(
                    "mock://Home/Textures/concrete.png",
                ))
            # Destination exists in backend.
            r, _ = be.stat(
                "mock://Home/Documents/Projects/concrete.png",
            )
            assert r == BackendResult.OK
            # Status line posted with "success" level.
            status.assert_called_once()
            msg = status.call_args[0][0]
            assert "1 item" in msg
            assert status.call_args[1].get("level") == "success"
        finally:
            cw.destroy()

    def test_multi_url_drop_uses_plural_status(self):
        be = MockBackend()
        cw = ContentBrowserWindow(
            backend=be, start_url="mock://Home/Documents/Projects",
        )
        try:
            cw._build_ui()
            payload = "\n".join([
                "mock://Home/Textures/concrete.png",
                "mock://Home/Textures/metal.hdr",
            ])
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status:
                cw._on_external_drop(_FakeDropEvent(payload))
            status.assert_called_once()
            msg = status.call_args[0][0]
            assert "2 items" in msg
        finally:
            cw.destroy()

    def test_all_urls_fail_no_status_posted(self):
        # A batch where every copy fails should post no success status.
        be = MockBackend()
        cw = ContentBrowserWindow(
            backend=be, start_url="mock://Home/Documents/Projects",
        )
        try:
            cw._build_ui()
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ) as status, patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_warning",
            ):
                cw._on_external_drop(_FakeDropEvent(
                    "mock://NonExistent/ghost.usda",
                ))
            status.assert_not_called()
        finally:
            cw.destroy()

    def test_refresh_fires_after_drop(self):
        # The detail model should repopulate after a successful drop so
        # the new row is visible without a manual refresh.
        be = MockBackend()
        cw = ContentBrowserWindow(
            backend=be, start_url="mock://Home/Documents/Projects",
        )
        try:
            cw._build_ui()
            detail_refresh_calls: List[int] = []
            cw._widget._detail_model.refresh_all = (  # type: ignore[assignment]
                lambda: detail_refresh_calls.append(1)
            )
            with patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ):
                cw._on_external_drop(_FakeDropEvent(
                    "mock://Home/Textures/concrete.png",
                ))
            assert detail_refresh_calls == [1]
        finally:
            cw.destroy()

    def test_newline_joined_payload_parses_to_multiple_copies(self):
        # Belt-and-braces: the OS-joined payload shape matches the
        # internal-drag format exactly.
        be = MockBackend()
        cw = ContentBrowserWindow(
            backend=be, start_url="mock://Home/Documents/Projects",
        )
        try:
            cw._build_ui()
            with patch.object(
                cw._widget, "accept_external_drop",
                return_value=2,
            ) as mock_accept, patch(
                "ovwidgets.common.error_reporter.ErrorReporter.show_status",
            ):
                cw._on_external_drop(_FakeDropEvent(
                    "mock://a\nmock://b",
                ))
            mock_accept.assert_called_once()
            urls_arg = mock_accept.call_args[0][0]
            assert urls_arg == ["mock://a", "mock://b"]
        finally:
            cw.destroy()
