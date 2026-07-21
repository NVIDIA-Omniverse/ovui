# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 38 — internal drag-drop within the content browser.

Coverage:

* :meth:`FileBrowserModel.drop` — URL parsing, self-drop / ancestor
  rejection, move vs copy split (``is_copy``), overwrite collision
  handling, cross-parent refresh, ``on_complete`` hook.
* :class:`FileCard` — ``accept_drop_fn`` / ``drop_fn`` delegation,
  folder-only predicate, constructor surface.
* :class:`FileBrowserWidget` — tree drag payload, detail drag payload,
  widget-level drop dispatcher, ``drop_between_items`` wired on both
  TreeViews, Ctrl-state reading via
  :attr:`ovui_widgets.app.application.Application._last_modifier_bits`.

Dialog collision tests monkey-patch :meth:`ConfirmOverwriteDialog.show`
so the test runs headlessly; ``_fire_choice_for_test`` drives the
user-response path without a live button click.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, List

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.content.backends.backend_adapter import BackendResult
from ovui_widgets.content.widget import (
    ConfirmOverwriteDialog,
    FileBrowserModel,
    FileBrowserWidget,
    FileCard,
    FileItem,
    OverwriteChoice,
)
from ovui_widgets.content.widget.file_browser_model import _DropState

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui Window shared across every test in the module."""
    win = ui.Window("_test_content_drag_drop", width=600, height=400)
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
def detail_model(backend):
    """Detail-pane model rooted at ``mock://Home/Documents/Projects``."""
    m = FileBrowserModel(backend, "mock://Home/Documents/Projects")
    yield m
    m.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.drop — parsing + validation
# ──────────────────────────────────────────────────────────────────────────────


class TestDropParsing:

    def test_empty_urls_str_noops(self, backend, detail_model):
        detail_model.drop(target_item=None, urls_str="")
        assert detail_model._drop_state is None

    def test_whitespace_only_urls_noops(self, backend, detail_model):
        # "\n\n" splits to ["", "", ""] — every segment filtered out.
        detail_model.drop(target_item=None, urls_str="\n\n")
        assert detail_model._drop_state is None

    def test_single_url_parses_and_processes(self, backend, detail_model):
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
        )
        r, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        assert r == BackendResult.OK

    def test_multi_url_parses_newlines(self, backend, detail_model):
        payload = "\n".join([
            "mock://Home/Textures/concrete.png",
            "mock://Home/Textures/metal.hdr",
        ])
        detail_model.drop(
            target_item=None, urls_str=payload, is_copy=True,
        )
        r1, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        r2, _ = backend.stat(
            "mock://Home/Documents/Projects/metal.hdr",
        )
        assert r1 == BackendResult.OK
        assert r2 == BackendResult.OK


class TestDropValidation:

    def test_drop_on_self_rejected(self, backend, detail_model):
        # Dragging a folder onto itself must be refused.
        home = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        detail_model.drop(
            target_item=home,
            urls_str="mock://Home",
            is_copy=True,
        )
        # Nothing changed — Home is still there under the root; no
        # self-copy attempted (which would have surfaced as an error).
        assert detail_model._drop_state is None
        # And the sibling Shared was not clobbered.
        r, _ = backend.stat("mock://Home")
        assert r == BackendResult.OK

    def test_drop_of_ancestor_onto_descendant_rejected(
        self, backend, detail_model,
    ):
        # Home is an ancestor of Home/Textures. Dropping Home onto
        # Home/Textures is the classic "parent into child" anti-move.
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home",
            is_copy=False,
        )
        # The drop never ran — Home is still at root and not a child
        # of Textures.
        r, _ = backend.stat("mock://Home/Textures/Home")
        assert r == BackendResult.ERROR_NOT_FOUND
        assert detail_model._drop_state is None

    def test_drop_target_file_rejected(self, backend, detail_model):
        # Files cannot contain children — drop is refused silently.
        demo = FileItem(
            url="mock://Home/Documents/Projects/demo.usda",
            name="demo.usda", is_folder=False,
        )
        detail_model.drop(
            target_item=demo,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
        )
        assert detail_model._drop_state is None

    def test_drop_target_none_uses_root(self, backend, detail_model):
        # None target → drop into the model's current root.
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
        )
        r, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        assert r == BackendResult.OK

    def test_mixed_valid_and_invalid_urls_only_valid_processed(
        self, backend, detail_model,
    ):
        # First URL is an ancestor of the detail root; the second is
        # a valid file. The ancestor is skipped; the file lands.
        payload = "\n".join([
            "mock://Home",                        # ancestor of root
            "mock://Home/Textures/concrete.png",  # valid
        ])
        detail_model.drop(
            target_item=None, urls_str=payload, is_copy=True,
        )
        r, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        assert r == BackendResult.OK

    def test_all_invalid_urls_drop_noops(self, backend, detail_model):
        # Every source is an ancestor of the target — no ops ran.
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home",
            is_copy=True,
        )
        assert detail_model._drop_state is None


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.drop — move vs copy
# ──────────────────────────────────────────────────────────────────────────────


class TestDropMoveVsCopy:

    def test_default_is_move(self, backend, detail_model):
        # ``is_copy=False`` — source should be gone, destination present.
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
        )
        src, _ = backend.stat("mock://Home/Textures/concrete.png")
        dst, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        assert src == BackendResult.ERROR_NOT_FOUND
        assert dst == BackendResult.OK

    def test_ctrl_is_copy(self, backend, detail_model):
        # ``is_copy=True`` — source preserved, destination created.
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
        )
        src, _ = backend.stat("mock://Home/Textures/concrete.png")
        dst, _ = backend.stat(
            "mock://Home/Documents/Projects/concrete.png",
        )
        assert src == BackendResult.OK
        assert dst == BackendResult.OK

    def test_multi_move_moves_all_sources(self, backend, detail_model):
        payload = "\n".join([
            "mock://Home/Textures/concrete.png",
            "mock://Home/Textures/metal.hdr",
        ])
        detail_model.drop(
            target_item=None, urls_str=payload, is_copy=False,
        )
        for src in (
            "mock://Home/Textures/concrete.png",
            "mock://Home/Textures/metal.hdr",
        ):
            r, _ = backend.stat(src)
            assert r == BackendResult.ERROR_NOT_FOUND
        for dst in (
            "mock://Home/Documents/Projects/concrete.png",
            "mock://Home/Documents/Projects/metal.hdr",
        ):
            r, _ = backend.stat(dst)
            assert r == BackendResult.OK

    def test_target_item_folder_lands_inside_it(
        self, backend, detail_model,
    ):
        # Drop onto Textures — the file lands under Textures even
        # though the model is rooted at Projects.
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usda",
            is_copy=True,
        )
        r, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert r == BackendResult.OK


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.drop — collisions + overwrite dialog
# ──────────────────────────────────────────────────────────────────────────────


class TestDropCollision:

    def test_collision_opens_overwrite_dialog(
        self, backend, detail_model, monkeypatch,
    ):
        # Pre-seed a collision: copy demo.usda into Textures so a
        # subsequent drop targets an existing URL.
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usda",
            is_copy=True,
        )
        dlg = detail_model._drop_confirm_dialog
        assert dlg is not None
        assert dlg.url == "mock://Home/Textures/demo.usda"
        # Single-URL drop → multi flag False.
        assert dlg.multi is False

    def test_yes_overwrites(
        self, backend, detail_model, monkeypatch,
    ):
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usda",
            is_copy=True,
        )
        detail_model._on_drop_overwrite_choice(OverwriteChoice.YES)
        # Overwrite succeeded — destination exists (copy, both sources
        # still present).
        r, _ = backend.stat("mock://Home/Textures/demo.usda")
        assert r == BackendResult.OK
        # State cleared after finalize.
        assert detail_model._drop_state is None

    def test_no_skips(
        self, backend, detail_model, monkeypatch,
    ):
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usda",
            is_copy=True,
        )
        detail_model._on_drop_overwrite_choice(OverwriteChoice.NO)
        assert detail_model._drop_state is None

    def test_yes_to_all_covers_remaining_collisions(
        self, backend, detail_model, monkeypatch,
    ):
        # Two collisions — after YES_TO_ALL the second must not spawn
        # a dialog and must also complete with overwrite.
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )
        backend.copy(
            "mock://Home/Documents/Projects/demo.usdc",
            "mock://Home/Textures/demo.usdc",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        payload = "\n".join([
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Documents/Projects/demo.usdc",
        ])
        detail_model.drop(
            target_item=textures, urls_str=payload, is_copy=True,
        )
        assert detail_model._drop_confirm_dialog is not None
        # ``multi=True`` on a 2-URL batch so Yes-to-All button is live.
        assert detail_model._drop_confirm_dialog.multi is True
        detail_model._on_drop_overwrite_choice(OverwriteChoice.YES_TO_ALL)
        # No second dialog — both URLs completed with overwrite.
        assert detail_model._drop_confirm_dialog is None
        assert detail_model._drop_state is None
        r1, _ = backend.stat("mock://Home/Textures/demo.usda")
        r2, _ = backend.stat("mock://Home/Textures/demo.usdc")
        assert r1 == BackendResult.OK
        assert r2 == BackendResult.OK


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.drop — refresh + on_complete hook
# ──────────────────────────────────────────────────────────────────────────────


class TestDropRefresh:

    def test_successful_drop_triggers_on_complete(
        self, backend, detail_model,
    ):
        calls: List[int] = []
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
            on_complete=lambda: calls.append(1),
        )
        assert calls == [1]

    def test_refresh_touches_both_source_and_destination_parents(
        self, backend, detail_model,
    ):
        # After a move, both the source parent (Textures) and the
        # destination parent (Projects) must get a refresh signal.
        calls: List[str] = []

        orig_refresh = detail_model._refresh_drop_parent

        def tracked_refresh(url: str) -> None:
            calls.append(url)
            orig_refresh(url)

        detail_model._refresh_drop_parent = tracked_refresh  # type: ignore[assignment]
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=False,
        )
        # Both parents were refreshed once each.
        assert sorted(calls) == sorted([
            "mock://Home/Textures",
            "mock://Home/Documents/Projects",
        ])

    def test_drop_state_cleared_after_finalize(
        self, backend, detail_model,
    ):
        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
        )
        assert detail_model._drop_state is None

    def test_on_complete_exception_does_not_crash_finalize(
        self, backend, detail_model,
    ):
        # A crashing on_complete hook must not leave ``_drop_state``
        # populated — :meth:`_drop_finalize` must still null it.
        def bad_complete() -> None:
            raise RuntimeError("boom")

        detail_model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
            on_complete=bad_complete,
        )
        assert detail_model._drop_state is None


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.drop — re-entrancy + lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestDropLifecycle:

    def test_reentrancy_guard_during_dialog(
        self, backend, detail_model, monkeypatch,
    ):
        # A drop with a pending dialog must refuse to start a second.
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        # First drop — stalls on dialog.
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usda",
            is_copy=True,
        )
        state_before = detail_model._drop_state
        assert state_before is not None
        # Second drop — silently no-op, does NOT overwrite state.
        detail_model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usdc",
            is_copy=True,
        )
        assert detail_model._drop_state is state_before

    def test_destroy_dismisses_pending_dialog(
        self, backend, monkeypatch,
    ):
        # Destroy with a live drop dialog must clean up without raising.
        model = FileBrowserModel(
            backend, "mock://Home/Documents/Projects",
        )
        backend.copy(
            "mock://Home/Documents/Projects/demo.usda",
            "mock://Home/Textures/demo.usda",
        )
        monkeypatch.setattr(
            ConfirmOverwriteDialog, "show", lambda self: None,
        )
        textures = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        model.drop(
            target_item=textures,
            urls_str="mock://Home/Documents/Projects/demo.usda",
            is_copy=True,
        )
        assert model._drop_confirm_dialog is not None
        model.destroy()
        assert model._drop_confirm_dialog is None
        assert model._drop_state is None

    def test_drop_after_destroy_is_noop(self, backend):
        model = FileBrowserModel(
            backend, "mock://Home/Documents/Projects",
        )
        model.destroy()
        # No backend reference after destroy — but we still call drop;
        # the method's guards absorb the post-destroy state.
        model._backend = None  # simulate widget's destroy path
        model.drop(
            target_item=None,
            urls_str="mock://Home/Textures/concrete.png",
            is_copy=True,
        )
        # No crash; state is None.
        assert model._drop_state is None


# ──────────────────────────────────────────────────────────────────────────────
# _DropState container
# ──────────────────────────────────────────────────────────────────────────────


class TestDropStateContainer:

    def test_defaults(self):
        st = _DropState(
            remaining=["a", "b"],
            dst_parent_url="mock://dst",
            is_copy=True,
        )
        assert st.remaining == ["a", "b"]
        assert st.dst_parent_url == "mock://dst"
        assert st.is_copy is True
        assert st.overwrite_all is None
        assert st.success_count == 0
        assert st.errors == []
        assert st.affected_parents == set()
        assert st.on_complete is None

    def test_on_complete_stored(self):
        fn = lambda: None  # noqa: E731
        st = _DropState(
            remaining=[],
            dst_parent_url="mock://dst",
            is_copy=False,
            on_complete=fn,
        )
        assert st.on_complete is fn

    def test_remaining_list_is_copied(self):
        # Defensive-copy in __init__ so mutating the input list after
        # construction does not reach into the state.
        src = ["a", "b"]
        st = _DropState(
            remaining=src,
            dst_parent_url="mock://dst",
            is_copy=False,
        )
        src.append("c")
        assert st.remaining == ["a", "b"]


# ──────────────────────────────────────────────────────────────────────────────
# FileCard drag-drop surface
# ──────────────────────────────────────────────────────────────────────────────


class TestFileCardAcceptDropPredicate:

    def _make_card(
        self, window, item: FileItem, **kwargs,
    ) -> FileCard:
        """Build a card inside the test window and return it."""
        with in_window_frame(window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                **kwargs,
            )
        return card

    def test_folder_card_accepts_non_empty_mime(self, ephemeral_window):
        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        card = self._make_card(
            ephemeral_window, item,
            on_drag=lambda: "",
            on_drop=lambda it, m: None,
        )
        try:
            assert card._accept_drop("mock://Home/x") is True
            assert card._accept_drop(
                "mock://Home/x\nmock://Home/y",
            ) is True
        finally:
            card.destroy()

    def test_folder_card_refuses_empty_mime(self, ephemeral_window):
        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        card = self._make_card(
            ephemeral_window, item,
            on_drag=lambda: "",
            on_drop=lambda it, m: None,
        )
        try:
            assert card._accept_drop("") is False
            # Whitespace-only MIME filters to no segments.
            assert card._accept_drop("\n\n") is False
        finally:
            card.destroy()

    def test_file_card_refuses_drop(self, ephemeral_window):
        item = FileItem(
            url="mock://Home/file.usda", name="file.usda", is_folder=False,
        )
        card = self._make_card(
            ephemeral_window, item,
            on_drag=lambda: "",
            on_drop=lambda it, m: None,
        )
        try:
            # Even a well-formed MIME is refused on a file target.
            assert card._accept_drop("mock://Home/x") is False
        finally:
            card.destroy()


class TestFileCardDragDispatch:

    def test_drag_returns_payload_from_handler(self, ephemeral_window):
        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "mock://Home/x\nmock://Home/y",
                on_drop=lambda it, m: None,
            )
        try:
            assert card._dispatch_drag() == "mock://Home/x\nmock://Home/y"
        finally:
            card.destroy()

    def test_drag_with_no_handler_returns_empty(self, ephemeral_window):
        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        try:
            assert card._dispatch_drag() == ""
        finally:
            card.destroy()

    def test_drag_handler_exception_returns_empty(self, ephemeral_window):
        # A crashing drag provider must not propagate into ovui.
        def bad_drag() -> str:
            raise RuntimeError("boom")

        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=bad_drag,
                on_drop=lambda it, m: None,
            )
        try:
            assert card._dispatch_drag() == ""
        finally:
            card.destroy()


class TestFileCardDropDispatch:

    def test_drop_forwards_item_and_mime(self, ephemeral_window):
        calls: List[tuple] = []
        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )

        class FakeEvent:
            mime_data = "mock://Home/x"

        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "",
                on_drop=lambda it, m: calls.append((it, m)),
            )
        try:
            card._dispatch_drop(FakeEvent())
            assert calls == [(item, "mock://Home/x")]
        finally:
            card.destroy()

    def test_drop_with_no_handler_is_silent_noop(self, ephemeral_window):
        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )

        class FakeEvent:
            mime_data = "mock://Home/x"

        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        try:
            # Does not raise.
            card._dispatch_drop(FakeEvent())
        finally:
            card.destroy()

    def test_drop_handler_exception_is_swallowed(self, ephemeral_window):
        def bad_drop(it: FileItem, m: str) -> None:
            raise RuntimeError("boom")

        item = FileItem(
            url="mock://Home/Textures", name="Textures", is_folder=True,
        )

        class FakeEvent:
            mime_data = "mock://Home/x"

        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "",
                on_drop=bad_drop,
            )
        try:
            # Handler crashes — card does not propagate.
            card._dispatch_drop(FakeEvent())
        finally:
            card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserWidget drag-drop integration
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetDragDropWiring:

    def test_detail_tree_view_has_drop_between_items(
        self, backend, ephemeral_window,
    ):
        # Step 42: the nav pane no longer participates in drag-drop —
        # drops always target the detail pane / its cards. Only the
        # detail TreeView still sets ``drop_between_items`` so ovui's
        # drop cursor lands between rows (future feature: reorder per
        # §30.1).
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            assert widget._detail_tree_view is not None
            assert widget._detail_tree_view.drop_between_items is True
        finally:
            widget.destroy()

    def test_detail_drag_payload_joins_urls(
        self, backend, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            # Force grid view + fake grid selection.
            widget._is_grid_view = True

            class _FakeGrid:
                def __init__(self, items):
                    self._items = items

                def get_selection(self):
                    return list(self._items)

                def set_rename_controller(self, c):
                    pass

                def destroy(self):
                    pass

                def refresh(self):
                    pass

            a = FileItem(
                url="mock://a.usda", name="a.usda", is_folder=False,
            )
            b = FileItem(
                url="mock://b.usda", name="b.usda", is_folder=False,
            )
            widget._detail_grid_view = _FakeGrid([a, b])  # type: ignore[assignment]
            payload = widget._detail_drag_payload()
            assert payload == "mock://a.usda\nmock://b.usda"
        finally:
            widget.destroy()

    def test_accept_drop_mime_predicate(self):
        assert FileBrowserWidget._accept_drop_mime("mock://a") is True
        assert FileBrowserWidget._accept_drop_mime("a\nb") is True
        assert FileBrowserWidget._accept_drop_mime("") is False
        assert FileBrowserWidget._accept_drop_mime("\n\n") is False

    def test_is_ctrl_drop_without_app_returns_false(self):
        # No Application singleton — predicate falls through to False.
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        Application._instance = None
        SelectionBus._instance = None
        try:
            # Build a widget without an active Application.
            win = ui.Window(
                "_test_no_app_ctrl", width=300, height=200,
            )
            try:
                with win.frame:
                    widget = FileBrowserWidget(
                        MockBackend(),
                        "mock://Home/Documents/Projects",
                    )
                try:
                    assert widget._is_ctrl_drop() is False
                finally:
                    widget.destroy()
            finally:
                win.destroy()
        finally:
            Application._instance = None
            SelectionBus._instance = None


class TestWidgetDropDispatch:
    """Widget-level drop dispatcher routes through the detail model."""

    def test_dispatch_drop_routes_to_detail_model(
        self, backend, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            captured: List[tuple] = []
            orig_drop = widget._detail_model.drop

            def tracked(
                target_item, urls_str, is_copy=False, on_complete=None,
            ):
                captured.append((target_item, urls_str, is_copy))
                return orig_drop(
                    target_item=target_item,
                    urls_str=urls_str,
                    is_copy=is_copy,
                    on_complete=on_complete,
                )

            widget._detail_model.drop = tracked  # type: ignore[assignment]
            widget._dispatch_drop(
                target_item=None,
                mime="mock://Home/Textures/concrete.png",
            )
            assert len(captured) == 1
            assert captured[0][0] is None
            assert captured[0][1] == "mock://Home/Textures/concrete.png"
            assert captured[0][2] is False
        finally:
            widget.destroy()

    def test_dispatch_drop_empty_mime_noop(
        self, backend, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            calls: List[Any] = []
            widget._detail_model.drop = (  # type: ignore[assignment]
                lambda **kw: calls.append(kw)
            )
            widget._dispatch_drop(target_item=None, mime="")
            assert calls == []
        finally:
            widget.destroy()

    def test_on_drop_complete_refreshes_grid(
        self, backend, ephemeral_window,
    ):
        # Step 42: pre-Step-42 the on-drop-complete path also refreshed
        # a sibling tree-pane :class:`FileBrowserModel`. The Step 42
        # nav model is a fixed collection list with no populated folder
        # cache, so only the grid view refreshes now.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            class _FakeGrid:
                def __init__(self):
                    self.refresh_calls = 0

                def get_selection(self):
                    return []

                def set_rename_controller(self, c):
                    pass

                def destroy(self):
                    pass

                def refresh(self):
                    self.refresh_calls += 1

            fake_grid = _FakeGrid()
            widget._detail_grid_view = fake_grid  # type: ignore[assignment]
            widget._on_drop_complete()
            assert fake_grid.refresh_calls == 1
        finally:
            widget.destroy()

    def test_on_card_drop_refuses_file_target(
        self, backend, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            calls: List[Any] = []
            widget._detail_model.drop = (  # type: ignore[assignment]
                lambda **kw: calls.append(kw)
            )
            file_item = FileItem(
                url="mock://file.usda", name="file.usda", is_folder=False,
            )
            widget._on_card_drop(file_item, "mock://other")
            assert calls == []
        finally:
            widget.destroy()

    def test_on_card_drop_folder_target_dispatches(
        self, backend, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                backend, "mock://Home/Documents/Projects",
            )
        try:
            textures = FileItem(
                url="mock://Home/Textures",
                name="Textures", is_folder=True,
            )
            widget._on_card_drop(
                textures, "mock://Home/Documents/Projects/demo.usda",
            )
            r, _ = backend.stat("mock://Home/Textures/demo.usda")
            assert r == BackendResult.OK
        finally:
            widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Application._last_modifier_bits tracker
# ──────────────────────────────────────────────────────────────────────────────


class TestApplicationModifierTracking:

    def test_initial_value_is_zero(self, headless_app):
        assert headless_app._last_modifier_bits == 0

    def test_ctrl_press_updates_tracker(self, headless_app):
        # Simulate a Ctrl-held key press. ``_MOD_CTRL`` is bit 2.
        headless_app._on_key_pressed(ord("A"), 2, True)
        assert headless_app._last_modifier_bits & 2 == 2

    def test_plain_key_clears_ctrl_bit(self, headless_app):
        # Press with Ctrl.
        headless_app._on_key_pressed(ord("A"), 2, True)
        assert headless_app._last_modifier_bits & 2 == 2
        # Press without Ctrl — tracker reads current modifier state.
        headless_app._on_key_pressed(ord("B"), 0, True)
        assert headless_app._last_modifier_bits & 2 == 0
