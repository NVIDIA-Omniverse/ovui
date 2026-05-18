# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`FileCard` (the content browser implementation step 21).

Coverage:

* Public surface — package re-export, ``__all__`` inclusion.
* Construction — card builds for folder / file items, stores size,
  wires click + double-click handlers, default thumbnail maps to the
  item's ``icon_key``.
* :meth:`set_selected` toggles the Rectangle's ``selected`` state
  (which drives the ``Content.Card:selected`` selector).
* :meth:`set_thumbnail` reveals the front buffer for a non-empty URL,
  hides it for ``None`` / empty, and is safe post-destroy.
* Label tooltip carries the full item name so clipped truncation
  remains readable.
* Mouse dispatch — :meth:`_dispatch_mouse_pressed` forwards
  ``(button, modifier)`` to ``on_click`` verbatim; double-click fires
  :attr:`on_double_click` for left-button only.
* :meth:`destroy` is idempotent, releases widget refs, drops handler
  references, and later ``set_*`` calls become no-ops.

Structure mirrors ``tests/test_browser_bar.py`` / ``tests/test_path_field.py``
— a single module-scoped ``ephemeral_window`` fixture plus an
``in_window_frame`` context manager wraps widget construction in a
real ovui build context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Tuple

import omni.ui as ui
import pytest

from ovwidgets.common.style.urls import get_icon_path
from ovwidgets.content.widget import FileCard, FileItem
from ovwidgets.content.widget.file_card import FileCard as _FileCard

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_file_card", width=200, height=200)
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


def _file_item(
    url: str = "mock://a.usd", name: str = "a.usd", is_folder: bool = False,
) -> FileItem:
    return FileItem(url=url, name=name, is_folder=is_folder)


def _folder_item(
    url: str = "mock://folder", name: str = "folder",
) -> FileItem:
    return FileItem(url=url, name=name, is_folder=True)


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_reexported_from_widget_package(self):
        from ovwidgets.content.widget import FileCard as FC

        assert FC is _FileCard

    def test_widget_package_all_contains_file_card(self):
        import ovwidgets.content.widget as pkg

        assert "FileCard" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_instantiates_with_file_item(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert isinstance(card, FileCard)
        card.destroy()

    def test_instantiates_with_folder_item(self, ephemeral_window):
        """Folder items carry ``icon_key='asset_folder'`` — no special-casing."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card.item.icon_key == "asset_folder"
        card.destroy()

    def test_default_size_is_96(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card.size == 96
        card.destroy()

    def test_custom_size_is_honoured(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
                size=128,
            )
        assert card.size == 128
        card.destroy()

    def test_item_property_returns_source_item(self, ephemeral_window):
        item = _file_item(name="unique.usd")
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item,
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card.item is item
        card.destroy()

    def test_build_creates_root_zstack(self, ephemeral_window):
        """The card's root widget ref is populated after build."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._root is not None
        assert card._rect is not None
        card.destroy()

    def test_build_creates_label_with_item_name(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(name="filename.usd"),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._label is not None
        assert card._label.text == "filename.usd"
        card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Default thumbnail (default icon)
# ──────────────────────────────────────────────────────────────────────────────


class TestDefaultThumbnail:
    def test_back_buffer_is_built(self, ephemeral_window):
        """Default icon back buffer exists and starts visible."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._back_buffer is not None
        assert card._back_buffer.visible is True
        card.destroy()

    def test_front_buffer_starts_hidden(self, ephemeral_window):
        """Custom-thumbnail front buffer is invisible until set_thumbnail."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._front_buffer is not None
        assert card._front_buffer.visible is False
        card.destroy()

    def test_default_icon_matches_item_icon_key_usd(self, ephemeral_window):
        """A ``.usd`` leaf resolves to ``icon_key='asset_usd'``; the
        module-level ``_PROVIDER_CACHE`` should be keyed by that icon's
        absolute path after the card builds its back buffer.
        """
        from ovwidgets.content.widget.file_card import _PROVIDER_CACHE

        expected_path = get_icon_path("asset_usd")
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert expected_path in _PROVIDER_CACHE
        card.destroy()

    def test_default_icon_matches_item_icon_key_folder(self, ephemeral_window):
        from ovwidgets.content.widget.file_card import _PROVIDER_CACHE

        expected_path = get_icon_path("asset_folder")
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert expected_path in _PROVIDER_CACHE
        card.destroy()

    def test_default_icon_matches_item_icon_key_image(self, ephemeral_window):
        from ovwidgets.content.widget.file_card import _PROVIDER_CACHE

        expected_path = get_icon_path("asset_image")
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(url="mock://pic.png", name="pic.png"),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert expected_path in _PROVIDER_CACHE
        card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Selection
# ──────────────────────────────────────────────────────────────────────────────


class TestSetSelected:
    def test_set_selected_true_flips_state(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_selected(True)
        assert card._rect.selected is True
        card.destroy()

    def test_set_selected_false_flips_state(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_selected(True)
        card.set_selected(False)
        assert card._rect.selected is False
        card.destroy()

    def test_set_selected_defaults_to_unselected(self, ephemeral_window):
        """A fresh card is not selected."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._rect.selected is False
        card.destroy()

    def test_set_selected_coerces_truthy_values(self, ephemeral_window):
        """Non-bool inputs are coerced — ``set_selected(1)`` works."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_selected(1)
        assert card._rect.selected is True
        card.destroy()

    def test_set_selected_post_destroy_is_noop(self, ephemeral_window):
        """Post-destroy call should not raise."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        # Must not raise:
        card.set_selected(True)
        card.set_selected(False)


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnail override
# ──────────────────────────────────────────────────────────────────────────────


class TestSetThumbnail:
    def test_set_thumbnail_reveals_front_buffer(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("mock://thumb.png")
        assert card._front_buffer.visible is True
        card.destroy()

    def test_set_thumbnail_points_source_url(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("mock://thumb.png")
        assert card._front_image.source_url == "mock://thumb.png"
        card.destroy()

    def test_set_thumbnail_none_hides_front_buffer(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("mock://thumb.png")
        card.set_thumbnail(None)
        assert card._front_buffer.visible is False
        card.destroy()

    def test_set_thumbnail_empty_string_hides_front_buffer(
        self, ephemeral_window,
    ):
        """Empty string is treated as clear, per the API contract."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("mock://thumb.png")
        card.set_thumbnail("")
        assert card._front_buffer.visible is False
        card.destroy()

    def test_set_thumbnail_back_buffer_stays_visible(self, ephemeral_window):
        """Back buffer is the fallback — it must remain visible when
        the front buffer is flipped on, per architecture §9.10.
        """
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("mock://thumb.png")
        assert card._back_buffer.visible is True
        card.destroy()

    def test_set_thumbnail_post_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        # Must not raise:
        card.set_thumbnail("mock://thumb.png")
        card.set_thumbnail(None)

    def test_set_thumbnail_local_file_url_uses_provider(
        self, ephemeral_window,
    ):
        """Bug 10: ``file://`` URLs must route through
        :class:`ui.ImageWithProvider` + :class:`ui.RasterImageProvider`
        — this ovui build's :class:`ui.Image` / stb_image path silently
        drops local-file decodes, so custom thumbnails from
        :class:`LocalFSBackend` never paint on the card otherwise. The
        provider-backed widget has no ``source_url`` attribute, so its
        presence is the marker that the local branch actually ran."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("file:///tmp/thumb.png")
        assert card._front_buffer.visible is True
        assert isinstance(card._front_image, ui.ImageWithProvider)
        # Back buffer stays hidden on the provider branch — the
        # RasterImageProvider has already decoded the PNG by the time
        # it attaches to the widget, so there is no load race to
        # shield with a default-icon fallback.
        assert card._back_buffer.visible is False
        card.destroy()

    def test_set_thumbnail_remote_url_keeps_ui_image(
        self, ephemeral_window,
    ):
        """Remote URLs (``mock://`` / ``omniverse://`` / ``http://``)
        stay on the :class:`ui.Image` + :attr:`source_url` path so a
        future Omniverse / HTTP backend's thumbnails still resolve."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.set_thumbnail("mock://thumb.png")
        assert card._front_buffer.visible is True
        assert isinstance(card._front_image, ui.Image)
        assert card._front_image.source_url == "mock://thumb.png"
        # Remote branch keeps the back buffer up as fallback until
        # the front image reports ``progress == 1.0`` (architecture
        # §9.10).
        assert card._back_buffer.visible is True
        card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# file:// URL → local path conversion (Windows drive-letter handling)
# ──────────────────────────────────────────────────────────────────────────────


class TestFileUrlToPath:
    """``_file_url_to_path`` must hand a RasterImageProvider-openable
    path on every platform. POSIX builds want the leading slash
    preserved (``file:///home/x`` → ``/home/x``); Windows builds need
    the leading slash stripped from drive-letter paths
    (``file:///C:/Users/x`` → ``C:/Users/x``) because the
    RasterImageProvider otherwise treats the slash as a UNC share
    prefix and silently fails to open the file.
    """

    def test_non_file_url_returns_none(self):
        from ovwidgets.content.widget.file_card import _file_url_to_path

        assert _file_url_to_path("mock://thumb.png") is None
        assert _file_url_to_path("") is None
        assert _file_url_to_path("http://example.com/a.png") is None

    def test_posix_path_unchanged_on_linux(self, monkeypatch):
        from ovwidgets.content.widget import file_card

        monkeypatch.setattr(file_card.sys, "platform", "linux")
        assert (
            file_card._file_url_to_path("file:///home/user/thumb.png")
            == "/home/user/thumb.png"
        )

    def test_posix_path_unchanged_on_darwin(self, monkeypatch):
        from ovwidgets.content.widget import file_card

        monkeypatch.setattr(file_card.sys, "platform", "darwin")
        assert (
            file_card._file_url_to_path("file:///Users/foo/thumb.png")
            == "/Users/foo/thumb.png"
        )

    def test_windows_drive_path_strips_leading_slash(self, monkeypatch):
        from ovwidgets.content.widget import file_card

        monkeypatch.setattr(file_card.sys, "platform", "win32")
        assert (
            file_card._file_url_to_path("file:///C:/Users/foo/thumb.png")
            == "C:/Users/foo/thumb.png"
        )
        assert (
            file_card._file_url_to_path("file:///D:/assets/a.png")
            == "D:/assets/a.png"
        )

    def test_windows_unc_share_path_preserved(self, monkeypatch):
        """``file:////server/share/x`` loses only the scheme — the UNC
        double-slash must survive so the provider can still resolve
        the share. ``/server/...`` (no drive letter after the slash)
        must not be stripped either.
        """
        from ovwidgets.content.widget import file_card

        monkeypatch.setattr(file_card.sys, "platform", "win32")
        assert (
            file_card._file_url_to_path("file:////server/share/a.png")
            == "//server/share/a.png"
        )
        assert (
            file_card._file_url_to_path("file:///server/share/a.png")
            == "/server/share/a.png"
        )

    def test_uppercase_file_scheme_accepted(self, monkeypatch):
        from ovwidgets.content.widget import file_card

        monkeypatch.setattr(file_card.sys, "platform", "win32")
        assert (
            file_card._file_url_to_path("FILE:///C:/Users/foo.png")
            == "C:/Users/foo.png"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Label tooltip
# ──────────────────────────────────────────────────────────────────────────────


class TestLabelTooltip:
    def test_label_tooltip_matches_item_name(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(name="short.usd"),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._label.tooltip == "short.usd"
        card.destroy()

    def test_label_tooltip_full_name_even_when_long(self, ephemeral_window):
        """Long names clip visually in the label but the tooltip
        retains the full string so hovering still reveals it.
        """
        long_name = "a_very_long_asset_name_that_will_clip_in_a_96px_card.usd"
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(name=long_name),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._label.tooltip == long_name
        assert card._label.text == long_name
        card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Label clipping — Bugs 5 + 6
# ──────────────────────────────────────────────────────────────────────────────


class TestLabelClipping:
    """The bottom label band must be width-clamped and clipped so long
    filenames can neither paint past the card edge nor drag the
    :class:`ui.Rectangle` selection highlight into the adjacent cell.
    """

    def test_label_frame_width_matches_card_size(self, ephemeral_window):
        """Default 96 px card → label frame clamps to 96 px."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._label_frame is not None
        assert card._label_frame.width.value == 96.0
        card.destroy()

    def test_label_frame_width_tracks_custom_size(self, ephemeral_window):
        """Zoom-scaled cards carry a matching label frame width."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
                size=144,
            )
        assert card._label_frame is not None
        assert card._label_frame.width.value == 144.0
        card.destroy()

    def test_label_frame_has_horizontal_clipping(self, ephemeral_window):
        """Bug 5 + 6 fix: the frame must clip overflowing label pixels."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(
                    name=(
                        "this_is_a_very_very_very_long_filename_that_"
                        "will_overflow.usd"
                    ),
                ),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._label_frame is not None
        assert card._label_frame.horizontal_clipping is True
        card.destroy()

    def test_label_has_elided_text_enabled(self, ephemeral_window):
        """Long names render with a ``…`` ellipsis rather than a hard
        mid-glyph clip once the frame truncates them.
        """
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(name="short.usd"),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        assert card._label is not None
        assert card._label.elided_text is True
        card.destroy()

    def test_search_highlight_label_also_clipped(self, ephemeral_window):
        """Bug 5 + 6 also covers the search-highlight label path: the
        wrapping frame must exist and clip for the :class:`HighlightLabel`
        variant too, not just the plain label.
        """
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(name="long_asset_name_with_match.usd"),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
                size=96,
                search_term="match",
            )
        assert card._highlight_label is not None
        assert card._label is None
        assert card._label_frame is not None
        assert card._label_frame.width.value == 96.0
        assert card._label_frame.horizontal_clipping is True
        card.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Mouse dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestMouseDispatch:
    def test_click_handler_receives_button_and_modifier(
        self, ephemeral_window,
    ):
        """`_dispatch_mouse_pressed` drops x/y and forwards (btn, mod)."""
        received: List[Tuple[int, int]] = []

        def on_click(btn: int, mod: int) -> None:
            received.append((btn, mod))

        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=on_click,
                on_double_click=_noop_double_click,
            )
        # Invoke the dispatcher directly — we do not need ovui to
        # simulate a real mouse event to verify the forwarding shape.
        card._dispatch_mouse_pressed(0, 0, 0, 4)
        assert received == [(0, 4)]
        card.destroy()

    def test_click_handler_forwards_right_button(self, ephemeral_window):
        received: List[Tuple[int, int]] = []
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=lambda btn, mod: received.append((btn, mod)),
                on_double_click=_noop_double_click,
            )
        card._dispatch_mouse_pressed(0, 0, 1, 0)
        assert received == [(1, 0)]
        card.destroy()

    def test_right_click_forwards_event_coords_verbatim(
        self, ephemeral_window,
    ):
        """Bug 4: the event's ``(x, y)`` is already in DPI-scaled points
        (the same coord system :meth:`ui.Menu.show_at` expects); the
        dispatcher must pass them through unchanged, not add the hit
        rect's ``screen_position_*`` on top (which would double-offset
        the menu from the cursor).
        """
        received: List[Tuple[float, float]] = []
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
                on_right_click=lambda x, y: received.append((x, y)),
            )
        card._dispatch_mouse_pressed(123.0, 456.0, 1, 0)
        assert received == [(123.0, 456.0)]
        card.destroy()

    def test_left_click_does_not_fire_right_click_handler(
        self, ephemeral_window,
    ):
        received: List[Tuple[float, float]] = []
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
                on_right_click=lambda x, y: received.append((x, y)),
            )
        card._dispatch_mouse_pressed(10.0, 20.0, 0, 0)
        assert received == []
        card.destroy()

    def test_click_dispatcher_tolerates_missing_handler(
        self, ephemeral_window,
    ):
        """After destroy the handler ref is cleared — dispatch must
        not raise if a straggling event arrives."""
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        # Must not raise:
        card._dispatch_mouse_pressed(0, 0, 0, 0)

    def test_double_click_left_button_fires_handler(self, ephemeral_window):
        received: List[int] = []

        def on_double_click() -> None:
            received.append(1)

        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=on_double_click,
            )
        card._dispatch_mouse_double_clicked(0, 0, 0, 0)
        assert received == [1]
        card.destroy()

    def test_double_click_right_button_ignored(self, ephemeral_window):
        received: List[int] = []
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=lambda: received.append(1),
            )
        card._dispatch_mouse_double_clicked(0, 0, 1, 0)
        assert received == []
        card.destroy()

    def test_double_click_middle_button_ignored(self, ephemeral_window):
        received: List[int] = []
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=lambda: received.append(1),
            )
        card._dispatch_mouse_double_clicked(0, 0, 2, 0)
        assert received == []
        card.destroy()

    def test_double_click_dispatcher_tolerates_missing_handler(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        # Must not raise:
        card._dispatch_mouse_double_clicked(0, 0, 0, 0)

    def test_click_callbacks_wired_on_rectangle(self, ephemeral_window):
        """The Rectangle hit target owns the mouse callbacks.

        The ``has_*_fn`` slots read from the omni.ui C++ side, which is
        only alive inside the frame context — same constraint as
        :mod:`tests.test_two_pane_layout`'s
        ``test_build_wires_detail_double_click_callback``. The
        assertion and teardown therefore happen inside the frame.
        """
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
            try:
                assert card._rect.has_mouse_pressed_fn() is True
                assert card._rect.has_mouse_double_clicked_fn() is True
            finally:
                card.destroy()

    def test_destroy_clears_rectangle_mouse_callbacks(self, ephemeral_window):
        """After destroy, the hit rect's mouse callbacks are unbound
        so the ovui C++ side does not keep the :class:`FileCard` alive
        via a dangling slot reference. Same pattern as
        :mod:`tests.test_two_pane_layout`'s
        ``test_destroy_clears_selection_callback``.
        """
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
            rect = card._rect
            assert rect.has_mouse_pressed_fn() is True
            assert rect.has_mouse_double_clicked_fn() is True
            card.destroy()
            assert rect.has_mouse_pressed_fn() is False
            assert rect.has_mouse_double_clicked_fn() is False


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_widget_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        assert card._root is None
        assert card._rect is None
        assert card._back_buffer is None
        assert card._front_buffer is None
        assert card._front_image is None
        assert card._label is None
        assert card._label_frame is None

    def test_destroy_drops_handler_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        assert card._on_click is None
        assert card._on_double_click is None

    def test_destroy_does_not_crash(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        # Must not raise:
        card.destroy()

    def test_destroy_is_idempotent(self, ephemeral_window):
        """Calling destroy twice should not crash — widget refs are
        already None on the second call so the guards short-circuit.
        """
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _file_item(),
                on_click=_noop_click,
                on_double_click=_noop_double_click,
            )
        card.destroy()
        # Must not raise:
        card.destroy()
