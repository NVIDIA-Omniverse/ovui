# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ZoomBar` (the content browser implementation step 23).

Coverage:

* Public surface — package re-export, ``__all__`` inclusion,
  ``SCALE_MAP`` contents.
* Construction — default state (``_is_grid=True``, slider index 2,
  percent label reads "100%"), builds every widget ref, no initial
  callback fire.
* Slider dispatch — every slider index fires ``on_scale`` with the
  expected float, percent label follows, threshold crossings fire
  ``on_toggle_grid`` exactly once.
* Toggle button — flips ``_is_grid``, fires ``on_toggle_grid``, snaps
  slider to 0 on grid → list, restores last grid index on list →
  grid, no spurious double-fire of ``on_toggle_grid`` from the
  slider's value-changed path.
* Destroy — idempotent, releases widget refs, drops handler refs,
  later slider callbacks fall through safely.

Structure mirrors ``tests/test_browser_bar.py`` / ``tests/test_file_card.py``
— a module-scoped ``ephemeral_window`` fixture plus an
``in_window_frame`` context manager wraps widget construction in a
real ovui build context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List

import omni.ui as ui
import pytest

from ovui_widgets.content.widget import SCALE_MAP, ZoomBar
from ovui_widgets.content.widget.zoom_bar import (
    SCALE_MAP as _SCALE_MAP,
)
from ovui_widgets.content.widget.zoom_bar import (
    ZoomBar as _ZoomBar,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_zoom_bar", width=300, height=40)
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


def _noop_scale(_s: float) -> None:
    pass


def _noop_toggle(_is_grid: bool) -> None:
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_zoom_bar_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import ZoomBar as ZB

        assert ZB is _ZoomBar

    def test_scale_map_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import SCALE_MAP as SM

        assert SM is _SCALE_MAP

    def test_widget_package_all_contains_zoom_bar(self):
        import ovui_widgets.content.widget as pkg

        assert "ZoomBar" in pkg.__all__
        assert "SCALE_MAP" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# SCALE_MAP — pure data, no ovui fixture needed
# ──────────────────────────────────────────────────────────────────────────────


class TestScaleMap:
    def test_has_six_entries(self):
        """Architecture §25.4 — six-step ladder, values 0..5."""
        assert set(SCALE_MAP.keys()) == {0, 1, 2, 3, 4, 5}

    def test_index_0_is_half(self):
        assert SCALE_MAP[0] == 0.5

    def test_index_1_is_three_quarters(self):
        """Threshold position — anything at or above 0.75 is grid."""
        assert SCALE_MAP[1] == 0.75

    def test_index_2_is_identity(self):
        """Default slider position maps to scale 1.0 (card size 96)."""
        assert SCALE_MAP[2] == 1.0

    def test_index_3_is_1_25(self):
        assert SCALE_MAP[3] == 1.25

    def test_index_4_is_1_5(self):
        assert SCALE_MAP[4] == 1.5

    def test_index_5_is_2_0(self):
        assert SCALE_MAP[5] == 2.0

    def test_values_monotonic(self):
        """Slider drag right == larger thumbnails."""
        values = [SCALE_MAP[i] for i in range(6)]
        assert values == sorted(values)

    def test_only_index_0_is_below_threshold(self):
        """Grid-vs-list threshold invariant: exactly one list-mode step."""
        below = [i for i in range(6) if SCALE_MAP[i] < 0.75]
        assert below == [0]


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_builds_with_no_initial_scale_callback(self, ephemeral_window):
        """Subscription must be wired AFTER the initial ``set_value``.

        Otherwise Step 24's caller would receive a spurious
        ``on_scale(1.0)`` at widget-build time, before the grid view
        is plumbed.
        """
        scales: List[float] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=scales.append,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert scales == []
        finally:
            bar.destroy()

    def test_builds_with_no_initial_toggle_callback(self, ephemeral_window):
        """No spurious ``on_toggle_grid`` fire at build time."""
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            assert toggles == []
        finally:
            bar.destroy()

    def test_default_is_grid(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._is_grid is True
        finally:
            bar.destroy()

    def test_default_slider_index_is_2(self, ephemeral_window):
        """Scale 1.0 = identity; card size stays at Step 21 default 96."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            assert bar._slider.model.get_value_as_int() == 2
        finally:
            bar.destroy()

    def test_default_percent_label_reads_100(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._percent_label is not None
            assert bar._percent_label.text == "100%"
        finally:
            bar.destroy()

    def test_builds_all_widget_refs(self, ephemeral_window):
        """Every public widget handle populated — no ``None`` slots."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._hstack is not None
            assert bar._toggle_button is not None
            assert bar._grid_icon_image is not None
            assert bar._list_icon_image is not None
            assert bar._slider is not None
            assert bar._percent_label is not None
            assert bar._slider_value_changed_sub is not None
        finally:
            bar.destroy()

    def test_initial_icon_visibility_matches_grid_mode(
        self, ephemeral_window,
    ):
        """Is-grid=True → list icon visible (click takes user to list)."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._list_icon_image is not None
            assert bar._grid_icon_image is not None
            assert bar._list_icon_image.visible is True
            assert bar._grid_icon_image.visible is False
        finally:
            bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Slider value-changed dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestSliderDispatch:
    def test_slider_change_fires_on_scale(self, ephemeral_window):
        scales: List[float] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=scales.append,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(3)
            assert scales == [1.25]
        finally:
            bar.destroy()

    def test_slider_change_each_index_produces_map_value(
        self, ephemeral_window,
    ):
        """All six indices round-trip through ``on_scale``."""
        scales: List[float] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=scales.append,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            # Start at default 2. Walk 3 → 4 → 5 → 4 → 3 → 1 → 0.
            sequence = [3, 4, 5, 4, 3, 1, 0]
            for idx in sequence:
                bar._slider.model.set_value(idx)
            expected = [SCALE_MAP[i] for i in sequence]
            assert scales == expected
        finally:
            bar.destroy()

    def test_slider_change_updates_percent_label(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            assert bar._percent_label is not None
            bar._slider.model.set_value(4)
            assert bar._percent_label.text == "150%"
            bar._slider.model.set_value(0)
            assert bar._percent_label.text == "50%"
            bar._slider.model.set_value(5)
            assert bar._percent_label.text == "200%"
        finally:
            bar.destroy()

    def test_slider_change_within_grid_does_not_fire_toggle(
        self, ephemeral_window,
    ):
        """Grid → grid slider drag never re-fires ``on_toggle_grid``."""
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(3)
            bar._slider.model.set_value(4)
            bar._slider.model.set_value(5)
            assert toggles == []
        finally:
            bar.destroy()

    def test_slider_to_zero_fires_toggle_to_list(self, ephemeral_window):
        """Scale < 0.75 signals list mode — crosses threshold once."""
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(0)
            assert toggles == [False]
            assert bar._is_grid is False
        finally:
            bar.destroy()

    def test_slider_back_to_grid_fires_toggle_to_grid(
        self, ephemeral_window,
    ):
        """Going back up crosses the threshold the other way exactly once."""
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(0)  # → list
            bar._slider.model.set_value(3)  # → grid
            assert toggles == [False, True]
            assert bar._is_grid is True
        finally:
            bar.destroy()

    def test_slider_to_one_stays_grid(self, ephemeral_window):
        """Scale 0.75 is the threshold — inclusive lower bound of grid."""
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(1)
            assert toggles == []
            assert bar._is_grid is True
        finally:
            bar.destroy()

    def test_slider_threshold_crossing_updates_icon(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            assert bar._list_icon_image is not None
            assert bar._grid_icon_image is not None
            bar._slider.model.set_value(0)  # → list
            assert bar._list_icon_image.visible is False
            assert bar._grid_icon_image.visible is True
            bar._slider.model.set_value(4)  # → grid
            assert bar._list_icon_image.visible is True
            assert bar._grid_icon_image.visible is False
        finally:
            bar.destroy()

    def test_slider_grid_moves_track_last_grid_index(
        self, ephemeral_window,
    ):
        """``_last_grid_slider_index`` updates on every in-grid slider move."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(4)
            assert bar._last_grid_slider_index == 4
            bar._slider.model.set_value(5)
            assert bar._last_grid_slider_index == 5
            # List-side move does not update the memo.
            bar._slider.model.set_value(0)
            assert bar._last_grid_slider_index == 5
        finally:
            bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Toggle button
# ──────────────────────────────────────────────────────────────────────────────


class TestToggleButton:
    def test_toggle_flips_mode_to_list(self, ephemeral_window):
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            bar._on_toggle_click()
            assert bar._is_grid is False
            assert toggles == [False]
        finally:
            bar.destroy()

    def test_toggle_snaps_slider_to_zero_on_grid_to_list(
        self, ephemeral_window,
    ):
        """§25.4: explicit toggle to list forces slider = 0."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            bar._on_toggle_click()
            assert bar._slider.model.get_value_as_int() == 0
        finally:
            bar.destroy()

    def test_toggle_restores_last_grid_index_on_list_to_grid(
        self, ephemeral_window,
    ):
        """§25.4 round-trip: list → grid restores last grid slider index."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            bar._slider.model.set_value(4)  # grid at index 4
            bar._on_toggle_click()  # → list, slider → 0
            assert bar._slider.model.get_value_as_int() == 0
            bar._on_toggle_click()  # → grid, slider → 4
            assert bar._slider.model.get_value_as_int() == 4
        finally:
            bar.destroy()

    def test_toggle_fires_on_toggle_grid_exactly_once(
        self, ephemeral_window,
    ):
        """The slider-driven path must NOT re-fire on_toggle_grid."""
        toggles: List[bool] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=toggles.append,
            )
        try:
            bar._on_toggle_click()  # grid → list
            bar._on_toggle_click()  # list → grid
            assert toggles == [False, True]
        finally:
            bar.destroy()

    def test_toggle_fires_on_scale_from_slider_snap(self, ephemeral_window):
        """The slider's post-toggle set_value emits on_scale for the new scale."""
        scales: List[float] = []
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=scales.append,
                on_toggle_grid=_noop_toggle,
            )
        try:
            bar._on_toggle_click()  # grid → list: slider 2→0, scale 0.5
            assert scales == [0.5]
            bar._on_toggle_click()  # list → grid: slider 0→2, scale 1.0
            assert scales == [0.5, 1.0]
        finally:
            bar.destroy()

    def test_toggle_updates_icon_visibility(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._list_icon_image is not None
            assert bar._grid_icon_image is not None
            bar._on_toggle_click()  # → list
            assert bar._list_icon_image.visible is False
            assert bar._grid_icon_image.visible is True
            bar._on_toggle_click()  # → grid
            assert bar._list_icon_image.visible is True
            assert bar._grid_icon_image.visible is False
        finally:
            bar.destroy()

    def test_first_toggle_to_grid_without_prior_grid_slider_lands_at_default(
        self, ephemeral_window,
    ):
        """list → grid with no prior grid move uses the default index."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        try:
            assert bar._slider is not None
            bar._on_toggle_click()  # grid → list (slider now 0)
            bar._on_toggle_click()  # list → grid (restore default 2)
            assert bar._slider.model.get_value_as_int() == 2
        finally:
            bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_widget_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        bar.destroy()
        assert bar._hstack is None
        assert bar._toggle_button is None
        assert bar._grid_icon_image is None
        assert bar._list_icon_image is None
        assert bar._slider is None
        assert bar._percent_label is None
        assert bar._slider_value_changed_sub is None

    def test_destroy_clears_handler_refs(self, ephemeral_window):
        """Handlers nulled so callback re-entry post-destroy is safe."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        bar.destroy()
        assert bar._on_scale is None
        assert bar._on_toggle_grid is None

    def test_destroy_is_idempotent(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        bar.destroy()
        # A second call must not raise — widget refs are already None.
        bar.destroy()

    def test_toggle_click_after_destroy_does_not_raise(
        self, ephemeral_window,
    ):
        """Post-destroy click from a live-in-UI callback falls through."""
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        bar.destroy()
        bar._on_toggle_click()

    def test_update_toggle_icon_after_destroy_does_not_raise(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        bar.destroy()
        bar._update_toggle_icon()

    def test_update_percent_label_after_destroy_does_not_raise(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            bar = ZoomBar(
                on_scale=_noop_scale,
                on_toggle_grid=_noop_toggle,
            )
        bar.destroy()
        bar._update_percent_label(1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Format percent (static helper)
# ──────────────────────────────────────────────────────────────────────────────


class TestFormatPercent:
    def test_identity(self):
        assert ZoomBar._format_percent(1.0) == "100%"

    def test_half(self):
        assert ZoomBar._format_percent(0.5) == "50%"

    def test_three_quarters(self):
        assert ZoomBar._format_percent(0.75) == "75%"

    def test_double(self):
        assert ZoomBar._format_percent(2.0) == "200%"

    def test_rounds_rather_than_truncates(self):
        """Cover the ``int(round(...))`` rather than ``int(...)`` choice."""
        # 0.125 * 100 = 12.5 — round-half-to-even → 12.
        assert ZoomBar._format_percent(0.125) == "12%"
        # 0.129 * 100 = 12.9 — round up to 13.
        assert ZoomBar._format_percent(0.129) == "13%"
