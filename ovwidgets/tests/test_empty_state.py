# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 15 — empty-state and error overlays.

The detail pane's overlay (a :class:`ui.VStack` layered over the
scrolling frame via a :class:`ui.ZStack`) surfaces three states the
raw :class:`ui.TreeView` cannot express visually on its own:

* **Empty folder** — ``FileBrowserModel.last_error == OK`` and the
  root has zero children after populate.
* **Access denied** — ``ERROR_ACCESS_DENIED`` + Retry button visible.
* **Not found** — ``ERROR_NOT_FOUND`` + auto-fallback to the parent
  URL via :meth:`FileBrowserWidget._do_parent_fallback`.

These tests focus on the widget's overlay contract and the model's
new :attr:`FileBrowserModel.last_error` property. Generic widget
construction / two-pane layout / selection sync assertions live in
``tests/test_file_browser_widget.py`` and ``tests/test_two_pane_layout.py``
respectively; this module only verifies the Step 15 additions.

See the content browser behavior (edge cases / empty state) and
the content browser implementation step 15.
"""

from __future__ import annotations

from contextlib import contextmanager

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.widget import FileBrowserWidget
from ovwidgets.content.widget.file_browser_model import FileBrowserModel
from ovwidgets.content.widget.file_browser_widget import (
    _ACCESS_DENIED_MESSAGE,
    _EMPTY_FOLDER_MESSAGE,
    _NOT_FOUND_MESSAGE,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One reusable ovui Window for the whole module.

    Same pattern as ``tests/test_two_pane_layout.py`` — building a
    ``ui.Window`` per test is expensive, so tests share one and clear
    the frame between runs.
    """
    win = ui.Window("_test_empty_state", width=800, height=400)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


@pytest.fixture
def mock():
    """Fresh :class:`MockBackend` per test.

    Error injection (``mock._errors[url] = BackendResult.X``) lives on
    the instance, so a module-shared backend would leak injected
    errors between tests. A per-test instance keeps each test
    independent.
    """
    return MockBackend()


@pytest.fixture
def widget(ephemeral_window, mock):
    """Build a widget in the module's window, tear it down after."""
    with in_window_frame(ephemeral_window):
        w = FileBrowserWidget(mock, "mock://Home")
    yield w
    w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Model: last_error property
# ──────────────────────────────────────────────────────────────────────────────


class TestModelLastError:
    """:attr:`FileBrowserModel.last_error` tracks the most recent populate
    result. Reset to :attr:`BackendResult.OK` on construction and on
    :meth:`set_root_url`; updated inside :meth:`get_item_children`."""

    def test_initial_last_error_is_ok(self, mock):
        model = FileBrowserModel(mock, "mock://Home")
        # Before any get_item_children call, the model hasn't attempted
        # a populate — the default state is OK (no error observed yet).
        assert model.last_error is BackendResult.OK

    def test_last_error_ok_after_successful_populate(self, mock):
        model = FileBrowserModel(mock, "mock://Home")
        model.get_item_children(model.root)
        assert model.last_error is BackendResult.OK

    def test_last_error_access_denied_on_injection(self, mock):
        mock._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        model = FileBrowserModel(mock, "mock://Home")
        model.get_item_children(model.root)
        assert model.last_error is BackendResult.ERROR_ACCESS_DENIED

    def test_last_error_not_found_for_missing_url(self, mock):
        model = FileBrowserModel(mock, "mock://does_not_exist")
        model.get_item_children(model.root)
        assert model.last_error is BackendResult.ERROR_NOT_FOUND

    def test_last_error_resets_on_set_root_url(self, mock):
        # Start with a NOT_FOUND, then navigate to a valid root. The
        # model should forget the stale error immediately — before the
        # fresh populate — so the overlay does not flash the old
        # error during the re-root.
        model = FileBrowserModel(mock, "mock://does_not_exist")
        model.get_item_children(model.root)
        assert model.last_error is BackendResult.ERROR_NOT_FOUND
        model.set_root_url("mock://Home")
        assert model.last_error is BackendResult.OK

    def test_last_error_updated_on_reroot_and_populate(self, mock):
        model = FileBrowserModel(mock, "mock://Home")
        model.get_item_children(model.root)
        assert model.last_error is BackendResult.OK
        model.set_root_url("mock://does_not_exist")
        model.get_item_children(model.root)
        assert model.last_error is BackendResult.ERROR_NOT_FOUND

    def test_last_error_is_read_only_via_property(self, mock):
        # Expose as a read-only ``property`` — rewriting via
        # ``model.last_error = X`` must not work (no setter). The
        # invariant is "only the model mutates _last_error, from
        # populate paths".
        model = FileBrowserModel(mock, "mock://Home")
        with pytest.raises(AttributeError):
            model.last_error = BackendResult.ERROR  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Overlay surface
# ──────────────────────────────────────────────────────────────────────────────


class TestOverlaySurface:
    """Static structure of the overlay — created on build, hidden by
    default, and wired to the model's ``item_changed`` dispatch."""

    def test_overlay_container_exists_after_build(self, widget):
        assert widget._empty_state_container is not None
        assert isinstance(widget._empty_state_container, ui.VStack)

    def test_overlay_label_exists_after_build(self, widget):
        assert widget._empty_state_label is not None
        assert isinstance(widget._empty_state_label, ui.Label)

    def test_overlay_retry_button_exists_after_build(self, widget):
        assert widget._empty_state_retry_button is not None
        assert isinstance(widget._empty_state_retry_button, ui.Button)

    def test_detail_model_subscription_is_held(self, widget):
        # The subscription handle is held so the model keeps firing
        # ``item_changed`` callbacks for the overlay. Losing the ref
        # would silently de-wire the overlay updates (no tests would
        # fail unless they observed staleness — so pin it explicitly).
        assert widget._detail_model_change_sub is not None


# ──────────────────────────────────────────────────────────────────────────────
# Empty folder
# ──────────────────────────────────────────────────────────────────────────────


class TestEmptyFolderOverlay:
    """``OK`` + zero children → the "This folder is empty" label."""

    def test_navigate_to_empty_folder_shows_overlay(self, widget):
        # "Shared" is the designated empty folder in the default mock
        # tree (see _build_default_tree in ovwidgets.app/testing/mock_backend.py).
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert widget._empty_state_container.visible is True

    def test_empty_folder_label_text(self, widget):
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert widget._empty_state_label.text == _EMPTY_FOLDER_MESSAGE

    def test_empty_folder_hides_retry_button(self, widget):
        # Retry is pointless for an empty-folder state — the folder
        # genuinely has no contents, and refreshing won't populate
        # anything new.
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert widget._empty_state_retry_button.visible is False

    def test_navigate_to_populated_folder_hides_overlay(self, widget):
        # Home has Documents / Textures / Scripts — non-empty.
        widget.navigate_to("mock://Home")
        widget._update_empty_state()
        assert widget._empty_state_container.visible is False

    def test_initial_home_root_is_populated_so_overlay_hidden(self, widget):
        # The widget ran _update_empty_state() once at the end of its
        # constructor; Home has children, so the overlay is hidden.
        assert widget._empty_state_container.visible is False

    def test_overlay_shown_hides_scrolling_frame(self, widget):
        # The overlay must also hide the sibling ScrollingFrame — the
        # TreeView's self-drawn header row otherwise paints on top of
        # the overlay even with the overlay as a later ZStack child
        # (omni.ui z-order quirk). Confirmed visually in the QA
        # screenshot; pinned here so a future refactor that tries to
        # rely on the ZStack's z-order alone fails fast.
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert widget._detail_scrolling_frame.visible is False

    def test_overlay_hidden_shows_scrolling_frame(self, widget):
        # Step 24: overlay-hide restores whichever view is currently
        # active. After toggling to list view, Home (populated) must
        # re-surface the TreeView's ScrollingFrame.
        widget._on_zoom_bar_toggle_grid(False)
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert widget._detail_scrolling_frame.visible is False
        widget.navigate_to("mock://Home")
        widget._update_empty_state()
        assert widget._detail_scrolling_frame.visible is True

    def test_overlay_hidden_shows_grid_frame_in_grid_mode(self, widget):
        # Step 24: overlay-hide with default grid view restores the
        # grid frame — not the TreeView's ScrollingFrame.
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert widget._detail_grid_frame.visible is False
        widget.navigate_to("mock://Home")
        widget._update_empty_state()
        assert widget._detail_grid_frame.visible is True
        assert widget._detail_scrolling_frame.visible is False


# ──────────────────────────────────────────────────────────────────────────────
# Access denied
# ──────────────────────────────────────────────────────────────────────────────


class TestAccessDeniedOverlay:
    """``ERROR_ACCESS_DENIED`` → overlay with access-denied label + Retry."""

    def test_access_denied_shows_overlay(self, widget, mock):
        mock._errors["mock://Home/Documents"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
        widget.navigate_to("mock://Home/Documents")
        widget._update_empty_state()
        assert widget._empty_state_container.visible is True

    def test_access_denied_label_text(self, widget, mock):
        mock._errors["mock://Home/Documents"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
        widget.navigate_to("mock://Home/Documents")
        widget._update_empty_state()
        assert widget._empty_state_label.text == _ACCESS_DENIED_MESSAGE

    def test_access_denied_shows_retry_button(self, widget, mock):
        # ACCESS_DENIED is the only state where retry is meaningful —
        # the permission fix is out-of-band and a retry is the
        # user's handshake that they've resolved it.
        mock._errors["mock://Home/Documents"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
        widget.navigate_to("mock://Home/Documents")
        widget._update_empty_state()
        assert widget._empty_state_retry_button.visible is True


# ──────────────────────────────────────────────────────────────────────────────
# Not found
# ──────────────────────────────────────────────────────────────────────────────


class TestNotFoundOverlay:
    """``ERROR_NOT_FOUND`` → overlay + auto-fallback to the parent URL."""

    def test_not_found_shows_overlay(self, widget):
        widget.navigate_to("mock://Home/does_not_exist")
        widget._update_empty_state()
        assert widget._empty_state_container.visible is True

    def test_not_found_label_text(self, widget):
        widget.navigate_to("mock://Home/does_not_exist")
        widget._update_empty_state()
        assert widget._empty_state_label.text == _NOT_FOUND_MESSAGE

    def test_not_found_hides_retry_button(self, widget):
        # Retry is not offered for NOT_FOUND — the folder is gone, not
        # permission-restricted. The auto-fallback to the parent URL
        # is the automatic recovery action.
        widget.navigate_to("mock://Home/does_not_exist")
        widget._update_empty_state()
        assert widget._empty_state_retry_button.visible is False

    def test_not_found_do_parent_fallback_re_roots_to_parent(self, widget):
        # Drive the fallback directly (the scheduled path needs an
        # Application singleton; the direct method does not).
        widget.navigate_to("mock://Home/does_not_exist")
        widget._update_empty_state()
        widget._do_parent_fallback()
        # After the fallback, the detail model is back at the parent.
        assert widget._detail_model.root_url == "mock://Home"

    def test_do_parent_fallback_noop_at_root(self, widget):
        # At the top of the URL space there is no parent — the
        # fallback must not raise or infinite-loop on its own guard.
        widget.navigate_to("mock://")
        widget._update_empty_state()
        widget._do_parent_fallback()  # must not raise
        # Still at the same (empty) root.
        assert widget._detail_model.root_url == "mock://"


# ──────────────────────────────────────────────────────────────────────────────
# Retry button
# ──────────────────────────────────────────────────────────────────────────────


class TestRetry:
    """Retry click re-attempts the root's populate via ``refresh_all``."""

    def test_retry_clears_error_when_underlying_injection_removed(
        self, widget, mock,
    ):
        # Inject ACCESS_DENIED on a real folder ("Shared" — empty but
        # it exists in the tree), navigate, see access-denied, clear
        # the injection, fire retry, re-evaluate, see empty-folder.
        mock._errors["mock://Shared"] = BackendResult.ERROR_ACCESS_DENIED
        widget.navigate_to("mock://Shared")
        widget._update_empty_state()
        assert (
            widget._empty_state_label.text == _ACCESS_DENIED_MESSAGE
        )
        # Clear the injection — Shared is an empty folder in the
        # default tree, so the retry should surface the empty-folder
        # state instead of the access-denied state.
        del mock._errors["mock://Shared"]
        widget._on_retry_clicked()
        widget._update_empty_state()
        assert widget._empty_state_label.text == _EMPTY_FOLDER_MESSAGE
        assert widget._empty_state_container.visible is True

    def test_retry_calls_model_refresh_all(self, widget, mock):
        # Without a mocked refresh_all we verify by effect: after a
        # retry the model's root must be re-populated (it was dirtied
        # by refresh_all, and the next get_item_children in
        # _update_empty_state runs a fresh populate). We navigate
        # to a *new* folder so the fresh populate actually consults
        # the injected error — navigating to the same URL the widget
        # was constructed at is a no-op and leaves the cached populate
        # result in place.
        mock._errors["mock://Home/Documents"] = (
            BackendResult.ERROR_ACCESS_DENIED
        )
        widget.navigate_to("mock://Home/Documents")
        widget._update_empty_state()
        assert widget._detail_model.last_error is (
            BackendResult.ERROR_ACCESS_DENIED
        )
        del mock._errors["mock://Home/Documents"]
        widget._on_retry_clicked()
        widget._update_empty_state()
        assert widget._detail_model.last_error is BackendResult.OK

    def test_retry_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
        w.destroy()
        # Must not raise — ``_detail_model`` is None post-destroy and
        # the retry handler short-circuits.
        w._on_retry_clicked()


# ──────────────────────────────────────────────────────────────────────────────
# Subscription + lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestOverlayLifecycle:
    """Overlay + subscription cleared on destroy; update short-circuits."""

    def test_destroy_clears_overlay_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
        w.destroy()
        assert w._empty_state_container is None
        assert w._empty_state_label is None
        assert w._empty_state_retry_button is None

    def test_destroy_clears_subscription(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
        w.destroy()
        assert w._detail_model_change_sub is None

    def test_update_empty_state_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
        w.destroy()
        # Must not raise — every overlay ref is None and the early
        # returns in _update_empty_state short-circuit.
        w._update_empty_state()

    def test_navigate_updates_overlay_via_subscription(
        self, widget, mock,
    ):
        # Confirm the subscription path wires a re-root to an overlay
        # update without a manual _update_empty_state call. The
        # model's ``_schedule_item_changed`` falls through to
        # synchronous dispatch when no Application is running, so the
        # callback fires inside navigate_to.
        assert widget._empty_state_container.visible is False
        widget.navigate_to("mock://Shared")
        # The subscription callback runs during set_root_url via the
        # model's synchronous fallback path; the overlay should now
        # reflect the empty-folder state of "Shared".
        assert widget._empty_state_container.visible is True
        assert widget._empty_state_label.text == _EMPTY_FOLDER_MESSAGE
