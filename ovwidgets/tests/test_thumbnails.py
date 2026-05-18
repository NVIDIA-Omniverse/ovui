# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 25 — thumbnail discovery.

Covers the content browser implementation step 25 / the content browser behavior:

* :meth:`FileItem.set_custom_thumbnail` stores the URL on the item and
  fires the optional ``_on_thumbnail_changed`` callback; the default
  state is ``None`` and a subsequent ``None`` clear works.
* :meth:`FileBrowserModel._populate_thumbnails` reads
  ``<parent>/.thumbs/256x256`` and attaches a custom thumbnail URL to
  image children whose name matches ``<name>.png`` (manual precedence)
  or ``<name>.auto.png`` (fallback). Already-thumbnailed, folder, and
  non-image children are skipped. A missing thumb dir is a silent
  no-op.
* :meth:`FileBrowserModel.get_item_children` schedules the discovery
  pass (via :meth:`ovwidgets.app.application.Application.call_later`, or
  synchronously when no ``Application`` singleton exists) after every
  successful populate — so cards rendered from a fresh folder see the
  custom thumbnail URL before the view asks for it.
* :class:`FileCard` consumes ``item.custom_thumbnail`` on build: the
  front buffer goes visible, the back buffer stays visible as a
  fallback, and the image-progress callback hides the back buffer once
  load completes. ``set_thumbnail(None)`` restores the default-icon
  state.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Optional

import omni.ui as ui
import pytest

from ovwidgets.app.testing import MockBackend
from ovwidgets.app.testing.mock_backend import _MockEntry
from ovwidgets.common.asset_types import AssetCategory
from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.widget import FileBrowserModel, FileCard, FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Tree builders
# ──────────────────────────────────────────────────────────────────────────────

def _build_entry(
    name: str,
    is_folder: bool,
    parent: _MockEntry,
    size: int = 0,
) -> _MockEntry:
    """Attach a child entry under ``parent`` and return it."""
    entry = _MockEntry(
        name=name, is_folder=is_folder, size=size, parent=parent,
    )
    parent.children[name] = entry
    return entry


def _build_tree_with_thumbnails(
    images: List[str],
    thumb_files: Optional[List[str]] = None,
    extra_files: Optional[List[str]] = None,
    include_thumb_dir: bool = True,
) -> _MockEntry:
    """Build a ``mock://Home`` tree with explicit children + thumbs.

    Shape::

        mock://
          Home/
            <each entry in ``images``>   (image file)
            <each entry in ``extra_files``, if any>
            .thumbs/
              256x256/
                <each entry in ``thumb_files``>

    ``thumb_files`` names the entries inside ``.thumbs/256x256/`` —
    callers pass e.g. ``["foo.png.png", "bar.png.auto.png"]``.
    ``include_thumb_dir=False`` omits the ``.thumbs`` folder entirely,
    simulating a folder that has never been thumbnailed.
    """
    root = _MockEntry(name="", is_folder=True)
    home = _build_entry("Home", is_folder=True, parent=root)

    for name in images:
        _build_entry(name, is_folder=False, parent=home, size=100)
    for name in extra_files or ():
        _build_entry(name, is_folder=False, parent=home, size=100)

    if include_thumb_dir:
        thumbs = _build_entry(".thumbs", is_folder=True, parent=home)
        size256 = _build_entry("256x256", is_folder=True, parent=thumbs)
        for name in thumb_files or ():
            _build_entry(name, is_folder=False, parent=size256, size=100)

    return root


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every FileCard-build test."""
    win = ui.Window("_test_thumbnails", width=200, height=200)
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


def _noop_click(_btn: int, _mod: int) -> None:
    pass


def _noop_double_click() -> None:
    pass


# ──────────────────────────────────────────────────────────────────────────────
# FileItem.set_custom_thumbnail
# ──────────────────────────────────────────────────────────────────────────────

class TestFileItemCustomThumbnail:
    def test_custom_thumbnail_defaults_to_none(self):
        item = FileItem("mock://Home/foo.png", "foo.png", is_folder=False)
        assert item.custom_thumbnail is None

    def test_set_custom_thumbnail_stores_url(self):
        item = FileItem("mock://Home/foo.png", "foo.png", is_folder=False)
        url = "mock://Home/.thumbs/256x256/foo.png.png"
        item.set_custom_thumbnail(url)
        assert item.custom_thumbnail == url

    def test_set_custom_thumbnail_accepts_none_to_clear(self):
        item = FileItem("mock://Home/foo.png", "foo.png", is_folder=False)
        item.set_custom_thumbnail("mock://x")
        item.set_custom_thumbnail(None)
        assert item.custom_thumbnail is None

    def test_set_custom_thumbnail_fires_changed_callback(self):
        item = FileItem("mock://Home/foo.png", "foo.png", is_folder=False)
        fired: List[bool] = []
        item._on_thumbnail_changed = lambda: fired.append(True)
        item.set_custom_thumbnail("mock://Home/.thumbs/256x256/foo.png.png")
        assert fired == [True]

    def test_set_custom_thumbnail_without_callback_is_safe(self):
        """The callback slot is ``None`` by default — the setter
        must not crash when nothing has subscribed to thumbnail
        changes."""
        item = FileItem("mock://Home/foo.png", "foo.png", is_folder=False)
        # Should not raise.
        item.set_custom_thumbnail("mock://x")
        assert item.custom_thumbnail == "mock://x"

    def test_callback_fires_on_every_set(self):
        """Even repeat sets fire the callback — the subscriber may want
        to know the discovery pass ran regardless of whether the value
        actually changed."""
        item = FileItem("mock://Home/foo.png", "foo.png", is_folder=False)
        count = [0]
        item._on_thumbnail_changed = lambda: count.__setitem__(0, count[0] + 1)
        item.set_custom_thumbnail("mock://x")
        item.set_custom_thumbnail("mock://x")
        item.set_custom_thumbnail(None)
        assert count[0] == 3


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel._populate_thumbnails
# ──────────────────────────────────────────────────────────────────────────────

class TestPopulateThumbnails:
    def test_manual_match_sets_custom_thumbnail(self):
        root = _build_tree_with_thumbnails(
            images=["concrete.png"],
            thumb_files=["concrete.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        # Populate so children materialise. The thumbnail pass runs
        # synchronously because no Application singleton is available.
        children = model.get_item_children(model.root)
        concrete = next(c for c in children if c.name == "concrete.png")
        assert concrete.custom_thumbnail == (
            "mock://Home/.thumbs/256x256/concrete.png.png"
        )

    def test_auto_fallback_when_manual_missing(self):
        root = _build_tree_with_thumbnails(
            images=["metal.png"],
            thumb_files=["metal.png.auto.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        metal = next(c for c in children if c.name == "metal.png")
        assert metal.custom_thumbnail == (
            "mock://Home/.thumbs/256x256/metal.png.auto.png"
        )

    def test_manual_wins_over_auto_when_both_present(self):
        """the content browser behavior: manual > auto."""
        root = _build_tree_with_thumbnails(
            images=["both.png"],
            thumb_files=["both.png.png", "both.png.auto.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        both = next(c for c in children if c.name == "both.png")
        assert both.custom_thumbnail == (
            "mock://Home/.thumbs/256x256/both.png.png"
        )

    def test_no_thumbnail_dir_is_noop(self):
        """A folder with no ``.thumbs`` dir → every child stays on its
        default icon. ``list_dir`` returns ``ERROR_NOT_FOUND``; the
        populate pass must absorb that silently without raising."""
        root = _build_tree_with_thumbnails(
            images=["alone.png"],
            include_thumb_dir=False,
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        alone = next(c for c in children if c.name == "alone.png")
        assert alone.custom_thumbnail is None

    def test_non_image_children_receive_thumbnails(self):
        """Bug 10: every leaf category may carry a custom thumbnail when
        a matching entry exists in ``.thumbs/``. Real-world
        ``.thumbs/256x256`` folders (Kit / Nucleus convention) host
        previews of USDs / materials / scripts — restricting discovery
        to :class:`AssetCategory.IMAGE` masked the exact assets users
        most want a preview for."""
        root = _build_tree_with_thumbnails(
            images=[],
            extra_files=["notes.txt", "script.py", "scene.usda"],
            thumb_files=[
                "notes.txt.png",
                "script.py.png",
                "scene.usda.png",
            ],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        by_name = {c.name: c for c in children}
        assert by_name["notes.txt"].custom_thumbnail == (
            "mock://Home/.thumbs/256x256/notes.txt.png"
        )
        assert by_name["script.py"].custom_thumbnail == (
            "mock://Home/.thumbs/256x256/script.py.png"
        )
        assert by_name["scene.usda"].custom_thumbnail == (
            "mock://Home/.thumbs/256x256/scene.usda.png"
        )

    def test_folders_are_skipped(self):
        """Sub-folders never get a custom thumbnail — they render the
        folder icon. A ``Subdir.png`` entry in ``.thumbs/`` for a
        ``Subdir`` folder should not hijack the folder's icon."""
        root = _build_tree_with_thumbnails(
            images=[],
            thumb_files=["Subdir.png"],
        )
        # Append a sub-folder to the home tree.
        home = root.children["Home"]
        _build_entry("Subdir", is_folder=True, parent=home)

        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        subdir = next(c for c in children if c.name == "Subdir")
        assert subdir.is_folder is True
        assert subdir.custom_thumbnail is None

    def test_already_thumbnailed_items_not_overwritten(self):
        """A child that already carries a ``custom_thumbnail`` stays
        on it — the populate pass is additive, not authoritative."""
        root = _build_tree_with_thumbnails(
            images=["foo.png"],
            thumb_files=["foo.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        # Pre-populate and pre-assign a sentinel URL on the cached
        # child so the next populate call finds the item with a
        # non-``None`` thumbnail.
        model.get_item_children(model.root)
        foo = next(
            c for c in model.root.children if c.name == "foo.png"
        )
        foo.set_custom_thumbnail("mock://sentinel/url.png")

        # Re-run the populate pass (bypasses the ``populated`` guard
        # by calling the helper directly).
        model._populate_thumbnails(model.root)
        assert foo.custom_thumbnail == "mock://sentinel/url.png"

    def test_populate_fires_item_changed_when_thumbnail_set(self):
        """Discovery pass schedules a refresh via
        :meth:`_schedule_item_changed` only when something actually
        changed — otherwise an empty folder burns a dispatch per
        navigation, which §5.7 throttling is supposed to absorb but
        still wastes a frame."""
        root = _build_tree_with_thumbnails(
            images=["foo.png"],
            thumb_files=["foo.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        dispatched: List[object] = []
        sub = model.subscribe_item_changed_fn(  # noqa: F841
            lambda m, item: dispatched.append(item)
        )

        # Populate — triggers the thumbnail pass which fires
        # ``_schedule_item_changed(model.root)``.
        model.get_item_children(model.root)

        assert model.root in dispatched

    def test_populate_skips_item_changed_when_no_match(self):
        """Empty thumb dir → no thumbnail set → no dispatch burn."""
        root = _build_tree_with_thumbnails(
            images=["foo.png"],
            thumb_files=[],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        dispatched: List[object] = []
        sub = model.subscribe_item_changed_fn(  # noqa: F841
            lambda m, item: dispatched.append(item)
        )

        # Pre-populate so ``_populate_thumbnails`` isn't co-triggered by
        # the backend-change subscription path.
        model.get_item_children(model.root)
        dispatched.clear()

        model._populate_thumbnails(model.root)
        assert dispatched == []

    def test_populate_thumbnails_url_construction_uses_backend_join(self):
        """The thumbnail URL must be built via ``backend.join_url`` so
        a future backend with non-slash separators still composes a
        valid URL rather than a raw string concatenation."""
        root = _build_tree_with_thumbnails(
            images=["foo.png"],
            thumb_files=["foo.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        foo = next(c for c in children if c.name == "foo.png")
        # Mirrors what ``backend.join_url`` would have produced.
        expected = backend.join_url(
            backend.join_url("mock://Home", ".thumbs/256x256"),
            "foo.png.png",
        )
        assert foo.custom_thumbnail == expected


# ──────────────────────────────────────────────────────────────────────────────
# Scheduling: populate via get_item_children triggers discovery
# ──────────────────────────────────────────────────────────────────────────────

class TestScheduledDiscovery:
    def test_get_item_children_triggers_thumbnail_pass(self):
        """Without explicit intervention, the discovery pass must run
        after the initial populate — no caller is supposed to have to
        poke the model for thumbnails to appear."""
        root = _build_tree_with_thumbnails(
            images=["foo.png"],
            thumb_files=["foo.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        foo = next(c for c in children if c.name == "foo.png")
        # Without Application, the schedule call falls through to
        # synchronous dispatch — so the thumbnail is present even in
        # the very first read of ``children``.
        assert foo.custom_thumbnail is not None

    def test_thumbnail_pass_defers_via_call_later_when_application_exists(
        self, headless_app,
    ):
        """With a live :class:`Application`, the pass is scheduled via
        :meth:`Application.call_later` — the first call returns before
        thumbnails are assigned; the next frame tick applies them."""
        root = _build_tree_with_thumbnails(
            images=["foo.png"],
            thumb_files=["foo.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        foo = next(c for c in children if c.name == "foo.png")
        # Deferred — not yet applied.
        assert foo.custom_thumbnail is None

        headless_app._on_frame_update(0.0)
        assert foo.custom_thumbnail == (
            "mock://Home/.thumbs/256x256/foo.png.png"
        )

    def test_access_denied_populate_skips_thumbnail_pass(self):
        """If the backend refuses to list the folder, there is nothing
        to match against — the discovery pass must not run."""
        backend = MockBackend()
        backend._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        model = FileBrowserModel(backend, "mock://Home")

        # Should not raise — and no ``list_dir`` call lands against
        # ``mock://Home/.thumbs/256x256`` since the populate itself
        # failed.
        result = model.get_item_children(model.root)
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# FileCard consumption of item.custom_thumbnail
# ──────────────────────────────────────────────────────────────────────────────

class TestFileCardConsumesCustomThumbnail:
    def test_builds_without_custom_thumbnail_keeps_front_hidden(
        self, ephemeral_window,
    ):
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._front_buffer is not None
        assert card._front_buffer.visible is False
        card.destroy()

    def test_pre_set_custom_thumbnail_reveals_front_buffer(
        self, ephemeral_window,
    ):
        """A custom thumbnail already on the item at build time wires
        the front buffer during construction — no one has to call
        ``set_thumbnail`` after the fact."""
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        item.set_custom_thumbnail(
            "mock://Home/.thumbs/256x256/foo.png.png",
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._front_buffer is not None
        assert card._front_buffer.visible is True
        assert card._front_image is not None
        assert card._front_image.source_url == (
            "mock://Home/.thumbs/256x256/foo.png.png"
        )
        card.destroy()

    def test_back_buffer_starts_visible_under_front(self, ephemeral_window):
        """Front paints on top, back stays visible as fallback until
        progress reports complete. Matches architecture §9.10."""
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        item.set_custom_thumbnail(
            "mock://Home/.thumbs/256x256/foo.png.png",
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._back_buffer is not None
        assert card._back_buffer.visible is True
        card.destroy()

    def test_progress_complete_hides_back_buffer(self, ephemeral_window):
        """The progress callback hides the back buffer once the front
        image reports ``1.0`` — no double-paint after load."""
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        item.set_custom_thumbnail(
            "mock://Home/.thumbs/256x256/foo.png.png",
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        # Drive the progress callback directly.
        card._on_front_image_progress(1.0)
        assert card._back_buffer is not None
        assert card._back_buffer.visible is False
        card.destroy()

    def test_progress_partial_keeps_back_buffer_visible(
        self, ephemeral_window,
    ):
        """Any progress less than ``1.0`` leaves the back buffer
        showing — we only flip once the front image is fully loaded."""
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        item.set_custom_thumbnail(
            "mock://Home/.thumbs/256x256/foo.png.png",
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card._on_front_image_progress(0.5)
        assert card._back_buffer is not None
        assert card._back_buffer.visible is True
        card.destroy()

    def test_set_thumbnail_none_restores_back_buffer(self, ephemeral_window):
        """Clearing the thumbnail after a completed load must re-show
        the back buffer, otherwise a cleared card would be blank."""
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        item.set_custom_thumbnail(
            "mock://Home/.thumbs/256x256/foo.png.png",
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card._on_front_image_progress(1.0)
        assert card._back_buffer.visible is False

        card.set_thumbnail(None)
        assert card._back_buffer.visible is True
        assert card._front_buffer.visible is False
        card.destroy()

    def test_destroy_after_custom_thumbnail_is_idempotent(
        self, ephemeral_window,
    ):
        item = FileItem(
            url="mock://Home/foo.png",
            name="foo.png",
            is_folder=False,
        )
        item.set_custom_thumbnail(
            "mock://Home/.thumbs/256x256/foo.png.png",
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        # A second destroy must not raise.
        card.destroy()
        assert card._front_image is None
        assert card._back_buffer is None


# ──────────────────────────────────────────────────────────────────────────────
# Integration: full flow (populate → thumbnail → card consumes)
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegrationFullFlow:
    def test_populate_then_card_build_shows_custom_thumbnail(
        self, ephemeral_window,
    ):
        """End-to-end: populate discovers the manual thumbnail, and a
        card built afterwards renders its front buffer pointed at the
        discovered URL."""
        root = _build_tree_with_thumbnails(
            images=["concrete.png"],
            thumb_files=["concrete.png.png"],
        )
        backend = MockBackend(root=root)
        model = FileBrowserModel(backend, "mock://Home")

        children = model.get_item_children(model.root)
        concrete = next(c for c in children if c.name == "concrete.png")
        assert concrete.category is AssetCategory.IMAGE

        with in_window_frame(ephemeral_window):
            card = FileCard(
                concrete,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._front_buffer.visible is True
        assert card._front_image.source_url == (
            "mock://Home/.thumbs/256x256/concrete.png.png"
        )
        card.destroy()
