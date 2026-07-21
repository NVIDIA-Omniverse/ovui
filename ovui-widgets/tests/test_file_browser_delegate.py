# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`FileBrowserDelegate` (the content browser implementation step 8)."""

from __future__ import annotations

from contextlib import contextmanager

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.content.widget.file_browser_delegate import (
    _ARROW_DOWN_PATH,
    _ARROW_UP_PATH,
    _COLUMN_HEADERS,
    _COLUMN_SORT_POLICIES,
    FileBrowserDelegate,
)
from ovui_widgets.content.widget.file_browser_model import (
    FileBrowserModel,
    FileBrowserSortPolicy,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def model() -> FileBrowserModel:
    return FileBrowserModel(MockBackend(), "mock://Home")


@pytest.fixture
def populated_items(model):
    doc_folder = next(
        c for c in model.get_item_children(None)
        if c.is_folder and c.name == "Documents"
    )
    projects = next(
        c for c in model.get_item_children(doc_folder)
        if c.is_folder and c.name == "Projects"
    )
    leaf = next(
        c for c in model.get_item_children(projects)
        if not c.is_folder and c.name == "demo.usda"
    )
    return doc_folder, leaf


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every build_* test in this module.

    Creating one window per test is measurable overhead (docking
    registration, frame allocation). Each call to :func:`in_window_frame`
    rebuilds the frame contents in place — the window itself lives for
    the duration of the test module and is destroyed at teardown.
    """
    win = ui.Window(
        "_test_file_browser_delegate", width=400, height=200,
    )
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


# ──────────────────────────────────────────────────────────────────────────────
# Surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_is_abstract_delegate_subclass(self):
        assert issubclass(FileBrowserDelegate, ui.AbstractItemDelegate)

    def test_instantiable(self):
        assert isinstance(FileBrowserDelegate(), ui.AbstractItemDelegate)

    def test_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import FileBrowserDelegate as FBD
        assert FBD is FileBrowserDelegate

    def test_column_count_matches_model(self):
        # Whatever integer the model's builtins collapse to, the
        # delegate's builtin-range check must agree.
        assert (
            FileBrowserDelegate._is_builtin_column(
                FileBrowserModel.BUILTIN_COLUMN_COUNT - 1,
            )
            is True
        )
        assert (
            FileBrowserDelegate._is_builtin_column(
                FileBrowserModel.BUILTIN_COLUMN_COUNT,
            )
            is False
        )


# ──────────────────────────────────────────────────────────────────────────────
# Column metadata
# ──────────────────────────────────────────────────────────────────────────────


class TestColumnMetadata:
    def test_column_headers_are_name_size_date(self):
        assert _COLUMN_HEADERS == ("Name", "Size", "Date")

    def test_column_sort_policies_cover_all_builtins(self):
        assert set(_COLUMN_SORT_POLICIES.keys()) == {0, 1, 2}

    @pytest.mark.parametrize(
        "column_id,expected",
        [
            (0, (FileBrowserSortPolicy.NAME_ASC,
                 FileBrowserSortPolicy.NAME_DESC)),
            (1, (FileBrowserSortPolicy.SIZE_ASC,
                 FileBrowserSortPolicy.SIZE_DESC)),
            (2, (FileBrowserSortPolicy.DATE_ASC,
                 FileBrowserSortPolicy.DATE_DESC)),
        ],
    )
    def test_column_sort_policy_pair(self, column_id, expected):
        assert _COLUMN_SORT_POLICIES[column_id] == expected


# ──────────────────────────────────────────────────────────────────────────────
# set_model
# ──────────────────────────────────────────────────────────────────────────────


class TestSetModel:
    def test_default_model_is_none(self):
        assert FileBrowserDelegate()._model is None

    def test_set_model_stores_reference(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        assert d._model is model

    def test_set_model_none_detaches(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        d.set_model(None)
        assert d._model is None


# ──────────────────────────────────────────────────────────────────────────────
# Sort policy — click cycle through public model API
# ──────────────────────────────────────────────────────────────────────────────


class TestHeaderClickCycle:
    def test_click_without_model_is_noop(self):
        FileBrowserDelegate()._on_header_clicked(0)  # must not raise

    def test_click_plugin_column_does_not_change_policy(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        before = model.sort_policy
        d._on_header_clicked(99)
        assert model.sort_policy == before

    def test_click_name_from_asc_flips_to_desc(self, model):
        assert model.sort_policy == FileBrowserSortPolicy.NAME_ASC
        d = FileBrowserDelegate()
        d.set_model(model)
        d._on_header_clicked(0)
        assert model.sort_policy == FileBrowserSortPolicy.NAME_DESC

    def test_click_name_twice_cycles_asc_desc_asc(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        d._on_header_clicked(0)
        d._on_header_clicked(0)
        assert model.sort_policy == FileBrowserSortPolicy.NAME_ASC

    def test_click_size_from_name_resets_to_size_asc(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        d._on_header_clicked(1)
        assert model.sort_policy == FileBrowserSortPolicy.SIZE_ASC

    def test_click_size_twice_flips_to_size_desc(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        d._on_header_clicked(1)
        d._on_header_clicked(1)
        assert model.sort_policy == FileBrowserSortPolicy.SIZE_DESC

    def test_click_date_from_name_resets_to_date_asc(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        d._on_header_clicked(2)
        assert model.sort_policy == FileBrowserSortPolicy.DATE_ASC

    def test_click_different_column_after_desc_lands_on_asc(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)
        d._on_header_clicked(0)   # NAME_DESC
        d._on_header_clicked(2)   # DATE_ASC — new column resets to ASC
        assert model.sort_policy == FileBrowserSortPolicy.DATE_ASC


# ──────────────────────────────────────────────────────────────────────────────
# Sort arrow selection
# ──────────────────────────────────────────────────────────────────────────────


class TestSortArrowPath:
    def test_no_arrow_without_model(self):
        assert FileBrowserDelegate()._sort_arrow_path_for(0) is None

    def test_asc_returns_up_arrow_path(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)  # default policy is NAME_ASC
        assert d._sort_arrow_path_for(0) == _ARROW_UP_PATH

    def test_desc_returns_down_arrow_path(self, model):
        model.set_sort_policy(FileBrowserSortPolicy.NAME_DESC)
        d = FileBrowserDelegate()
        d.set_model(model)
        assert d._sort_arrow_path_for(0) == _ARROW_DOWN_PATH

    def test_non_active_column_has_no_arrow(self, model):
        d = FileBrowserDelegate()
        d.set_model(model)  # NAME_ASC — size/date are inactive
        assert d._sort_arrow_path_for(1) is None
        assert d._sort_arrow_path_for(2) is None


# ──────────────────────────────────────────────────────────────────────────────
# build_* must not raise in a real UI context
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildDoesNotCrash:
    def test_build_header_all_three_columns(self, ephemeral_window):
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            for c in (0, 1, 2):
                d.build_header(c)

    def test_build_header_plugin_column_noop(self, ephemeral_window):
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_header(42)

    def test_build_header_with_bound_model_shows_arrow(
        self, ephemeral_window, model,
    ):
        d = FileBrowserDelegate()
        d.set_model(model)
        with in_window_frame(ephemeral_window):
            d.build_header(0)

    def test_build_header_descending_shows_arrow(
        self, ephemeral_window, model,
    ):
        model.set_sort_policy(FileBrowserSortPolicy.NAME_DESC)
        d = FileBrowserDelegate()
        d.set_model(model)
        with in_window_frame(ephemeral_window):
            d.build_header(0)

    def test_build_branch_folder_column_0(
        self, ephemeral_window, model, populated_items,
    ):
        folder, _ = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_branch(model, folder, 0, 0, False)

    def test_build_branch_folder_expanded(
        self, ephemeral_window, model, populated_items,
    ):
        folder, _ = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_branch(model, folder, 0, 0, True)

    def test_build_branch_leaf_column_0(
        self, ephemeral_window, model, populated_items,
    ):
        _, leaf = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_branch(model, leaf, 0, 0, False)

    def test_build_branch_non_zero_column_is_noop(
        self, ephemeral_window, model, populated_items,
    ):
        folder, _ = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            for c in (1, 2):
                d.build_branch(model, folder, c, 0, False)

    def test_build_branch_deep_indent(
        self, ephemeral_window, model, populated_items,
    ):
        folder, _ = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_branch(model, folder, 0, 4, True)

    def test_build_widget_folder_all_columns(
        self, ephemeral_window, model, populated_items,
    ):
        folder, _ = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            for c in (0, 1, 2):
                d.build_widget(model, folder, c, 0, False)

    def test_build_widget_leaf_all_columns(
        self, ephemeral_window, model, populated_items,
    ):
        _, leaf = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            for c in (0, 1, 2):
                d.build_widget(model, leaf, c, 0, False)

    def test_build_widget_none_item_is_noop(self, ephemeral_window, model):
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_widget(model, None, 0, 0, False)

    def test_build_widget_non_fileitem_is_noop(self, ephemeral_window, model):
        d = FileBrowserDelegate()

        class _Bogus:
            pass

        with in_window_frame(ephemeral_window):
            d.build_widget(model, _Bogus(), 0, 0, False)

    def test_build_widget_plugin_column_is_noop(
        self, ephemeral_window, model, populated_items,
    ):
        folder, _ = populated_items
        d = FileBrowserDelegate()
        with in_window_frame(ephemeral_window):
            d.build_widget(model, folder, 99, 0, False)


# ──────────────────────────────────────────────────────────────────────────────
# Readable fade — forward-compatible is_readable handling
# ──────────────────────────────────────────────────────────────────────────────


class TestReadableFade:
    # FileItem does not (yet) carry an ``is_readable`` attribute — that
    # flag lands with the backend-flag plumbing step. The delegate must
    # treat a missing attribute as readable so existing rows don't
    # render faded today, but must honour an explicit value once the
    # flag exists. Monkey-patching here stands in for that future API.

    def test_default_is_readable_true(self, populated_items):
        folder, leaf = populated_items
        assert FileBrowserDelegate._is_readable(folder) is True
        assert FileBrowserDelegate._is_readable(leaf) is True

    def test_explicit_is_readable_false_is_honoured(self, populated_items):
        folder, _ = populated_items
        folder.is_readable = False
        try:
            assert FileBrowserDelegate._is_readable(folder) is False
        finally:
            del folder.is_readable

    def test_explicit_is_readable_true_is_honoured(self, populated_items):
        folder, _ = populated_items
        folder.is_readable = True
        try:
            assert FileBrowserDelegate._is_readable(folder) is True
        finally:
            del folder.is_readable

    def test_build_widget_disabled_leaf_does_not_crash(
        self, ephemeral_window, model, populated_items,
    ):
        _, leaf = populated_items
        leaf.is_readable = False
        d = FileBrowserDelegate()
        try:
            with in_window_frame(ephemeral_window):
                for c in (0, 1, 2):
                    d.build_widget(model, leaf, c, 0, False)
        finally:
            del leaf.is_readable


# ──────────────────────────────────────────────────────────────────────────────
# Provider cache
# ──────────────────────────────────────────────────────────────────────────────


class TestProviderCache:
    def test_provider_for_same_path_is_cached(self):
        from ovui_widgets.content.widget.file_browser_delegate import (
            _provider,
        )
        p1 = _provider(_ARROW_UP_PATH)
        p2 = _provider(_ARROW_UP_PATH)
        assert p1 is p2

    def test_provider_for_different_paths_differs(self):
        from ovui_widgets.content.widget.file_browser_delegate import (
            _provider,
        )
        assert _provider(_ARROW_UP_PATH) is not _provider(_ARROW_DOWN_PATH)


# ──────────────────────────────────────────────────────────────────────────────
# _wire_row_right_click — Bug 4
# ──────────────────────────────────────────────────────────────────────────────


class _FakeWidget:
    """Stand-in widget with the :meth:`set_mouse_pressed_fn` hook.

    Carries an unused ``screen_position_*`` pair so a regression that
    re-adds them to the event coords would silently record them here
    (failing the verbatim-forwarding assertion).
    """

    def __init__(self) -> None:
        self.mouse_pressed_fn = None
        self.screen_position_x = 1000.0
        self.screen_position_y = 2000.0

    def set_mouse_pressed_fn(self, fn):
        self.mouse_pressed_fn = fn


def _file_item():
    from ovui_widgets.content.widget.file_item import FileItem
    return FileItem(url="mock://x", name="x", is_folder=False)


class TestFileBrowserDelegateRightClick:
    """Bug 4: the row right-click handler must forward the event's
    ``(x, y)`` verbatim to the installed callback. The previous code
    added ``widget.screen_position_*`` on top, which double-offset the
    menu from the cursor.
    """

    def test_right_click_forwards_event_coords(self):
        d = FileBrowserDelegate()
        captured = []
        d.set_on_right_click(
            lambda x, y, it: captured.append((x, y, it))
        )
        w = _FakeWidget()
        item = _file_item()
        d._wire_row_right_click(w, item)
        w.mouse_pressed_fn(12.5, 34.5, 1, 0)
        assert captured == [(12.5, 34.5, item)]

    def test_non_right_button_ignored(self):
        d = FileBrowserDelegate()
        captured = []
        d.set_on_right_click(
            lambda x, y, it: captured.append((x, y, it))
        )
        w = _FakeWidget()
        d._wire_row_right_click(w, _file_item())
        w.mouse_pressed_fn(10.0, 20.0, 0, 0)  # left
        w.mouse_pressed_fn(10.0, 20.0, 2, 0)  # middle
        assert captured == []

    def test_no_handler_installed_is_silent(self):
        d = FileBrowserDelegate()
        w = _FakeWidget()
        d._wire_row_right_click(w, _file_item())
        # Must not raise even though no handler was set.
        w.mouse_pressed_fn(5.0, 7.0, 1, 0)


class TestTreeFolderDelegateRightClick:
    """Same invariant as :class:`FileBrowserDelegate` — the tree-pane
    folder delegate's row right-click must forward the event's
    ``(x, y)`` verbatim without adding the widget's
    ``screen_position_*``.
    """

    def test_right_click_forwards_event_coords(self):
        from ovui_widgets.content.widget.file_browser_delegate import (
            TreeFolderDelegate,
        )
        d = TreeFolderDelegate()
        captured = []
        d.set_on_right_click(
            lambda x, y, it: captured.append((x, y, it))
        )
        w = _FakeWidget()
        item = _file_item()
        d._wire_row_right_click(w, item)
        w.mouse_pressed_fn(77.0, 99.0, 1, 0)
        assert captured == [(77.0, 99.0, item)]

    def test_non_right_button_ignored(self):
        from ovui_widgets.content.widget.file_browser_delegate import (
            TreeFolderDelegate,
        )
        d = TreeFolderDelegate()
        captured = []
        d.set_on_right_click(
            lambda x, y, it: captured.append((x, y, it))
        )
        w = _FakeWidget()
        d._wire_row_right_click(w, _file_item())
        w.mouse_pressed_fn(1.0, 2.0, 0, 0)
        assert captured == []
