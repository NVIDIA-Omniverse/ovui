# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovui_widgets.app.layout — Step 11 default docking layout."""

import json
import os

import pytest

from ovui_widgets.app.layout import (
    _SPLIT_INI,
    apply_default_layout,
    load_layout,
    save_layout,
    write_split_ini,
)


def test_apply_default_layout_is_callable():
    assert callable(apply_default_layout)


def test_apply_default_layout_no_app_no_crash():
    """apply_default_layout() exits silently when no Application singleton exists."""
    apply_default_layout()


def test_save_layout_creates_file(tmp_path):
    path = str(tmp_path / "layout.json")
    save_layout(path)
    assert os.path.exists(path)


def test_save_layout_valid_json(tmp_path):
    path = str(tmp_path / "layout.json")
    save_layout(path)
    with open(path) as f:
        data = json.load(f)
    assert data.get("version") == 1
    assert "windows" in data


def test_save_layout_windows_is_dict(tmp_path):
    path = str(tmp_path / "layout.json")
    save_layout(path)
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data["windows"], dict)


def test_save_layout_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "sub" / "layout.json")
    save_layout(path)
    assert os.path.exists(path)


def test_load_layout_no_error(tmp_path):
    """load_layout() reads a saved file without raising."""
    path = str(tmp_path / "layout.json")
    save_layout(path)
    load_layout(path)


def test_round_trip_preserves_structure(tmp_path):
    """save → load does not crash; file contents are unchanged by load."""
    path = str(tmp_path / "layout.json")
    save_layout(path)
    with open(path) as f:
        saved = json.load(f)
    load_layout(path)
    with open(path) as f:
        after = json.load(f)
    assert saved == after


def test_load_layout_missing_file_raises(tmp_path):
    path = str(tmp_path / "nonexistent.json")
    with pytest.raises(FileNotFoundError):
        load_layout(path)


def test_load_layout_empty_windows_no_crash(tmp_path):
    """load_layout() handles an empty windows dict gracefully."""
    path = str(tmp_path / "layout.json")
    with open(path, "w") as f:
        json.dump({"version": 1, "windows": {}}, f)
    load_layout(path)


# ---------------------------------------------------------------------------
# Content Browser wiring (Step 11)
# ---------------------------------------------------------------------------


class TestSplitIniIncludesContent:
    """The canonical imgui.ini must pre-dock the Content browser node."""

    def test_content_window_block_present(self):
        assert "[Window][Content]" in _SPLIT_INI

    def test_content_window_has_dock_id(self):
        lines = _SPLIT_INI.splitlines()
        start = lines.index("[Window][Content]")
        # The next five lines (Pos, Size, Collapsed, DockId, blank) describe the block.
        block = "\n".join(lines[start : start + 6])
        assert "DockId=0x00000007" in block

    def test_dock_tree_splits_viewport_column_y(self):
        """Viewport column node 0x00000005 must split Y to fit the content
        browser below the viewport.

        The numeric size reference is computed from the canonical reference
        layout constants rather than hard-coded so future layout tuning does
        not silently invalidate this assertion.
        """
        from ovui_widgets.app import layout

        column_w = layout._REF_WIDTH - layout._REF_LEFT_PANEL - layout._REF_RIGHT_PANEL
        column_h = layout._REF_HEIGHT - layout._REF_MENU_BAR_HEIGHT
        expected = (
            f"ID=0x00000005 Parent=0x00000002 SizeRef={column_w},{column_h} Split=Y"
        )
        assert expected in _SPLIT_INI

    def test_viewport_node_is_central(self):
        """After the Y split, the *new* viewport leaf (0x00000006) owns
        ``CentralNode=1`` — ImGui requires exactly one central node for
        dockable layouts, and it must be the viewport.

        Selected hash 0x995B0CF8 = CRC32("Viewport") — confirms the viewport
        is the window assigned to the central node.
        """
        from ovui_widgets.app import layout

        column_w = layout._REF_WIDTH - layout._REF_LEFT_PANEL - layout._REF_RIGHT_PANEL
        column_h = layout._REF_HEIGHT - layout._REF_MENU_BAR_HEIGHT
        viewport_h = int(column_h * layout._REF_VIEWPORT_HEIGHT_RATIO)
        expected = (
            f"ID=0x00000006 Parent=0x00000005 SizeRef={column_w},{viewport_h} "
            "CentralNode=1 Selected=0x995B0CF8"
        )
        assert expected in _SPLIT_INI

    def test_content_node_uses_content_crc32(self):
        """The content node selector must be CRC32 of the window title
        ``"Content"`` — 0x31780935 — so ImGui routes the Content window
        into that leaf on first boot."""
        assert "ID=0x00000007" in _SPLIT_INI
        assert "Selected=0x31780935" in _SPLIT_INI

    def test_panel_leaf_nodes_keep_functional_dock_tabs(self):
        """Fixed app panels keep real dock tabs while hiding menu/close buttons."""
        panel_node_lines = [
            line for line in _SPLIT_INI.splitlines() if "Selected=0x" in line
        ]

        assert panel_node_lines
        for line in panel_node_lines:
            assert " NoTabBar=1" not in line
            assert " NoWindowMenuButton=1" in line
            assert " NoCloseButton=1" in line

    def test_write_split_ini_emits_content_block(self, tmp_path):
        path = str(tmp_path / "imgui.ini")
        write_split_ini(path)
        with open(path) as f:
            data = f.read()
        assert "[Window][Content]" in data
        assert "0x31780935" in data


class TestApplyDefaultLayoutContentBranch:
    """``apply_default_layout`` must not crash when the app has a content
    window, and must include it in the fallback dock plan.
    """

    def test_apply_default_layout_with_content_app_no_crash(self):
        """Minimal smoke test: apply_default_layout must tolerate an
        application where every panel attribute is None — the current
        ``if not (stage_win and prop_win and vp_win): return`` guard is
        what keeps the test suite from needing a full ovui window stack.
        """
        apply_default_layout()


class TestCollectLayoutIncludesContent:
    """The panel map used by _collect_layout / _restore_layout must list
    the content window alongside the other three panels."""

    def test_collect_layout_panel_map_contains_content(self):
        import inspect

        from ovui_widgets.app.layout import _collect_layout

        src = inspect.getsource(_collect_layout)
        assert '"Content"' in src
        assert "app._content_window" in src

    def test_restore_layout_panel_map_contains_content(self):
        import inspect

        from ovui_widgets.app.layout import _restore_layout

        src = inspect.getsource(_restore_layout)
        assert '"Content"' in src
        assert "app._content_window" in src


class TestSplitIniIsDpiAware:
    """``_build_split_ini`` must scale every dock dimension by the
    runtime DPI. Writing it at DPI 1.0 on a 200% display pins the side
    panels at logical half-width, which is the reported HiDPI bug.
    """

    def _build_at_dpi(self, scale: float) -> str:
        from unittest.mock import patch

        from ovui_widgets.app import layout as layout_module

        with patch.object(layout_module, "_get_dpi_scale", return_value=scale):
            return layout_module._build_split_ini()

    def test_window_and_dock_dimensions_double_at_dpi_2(self):
        from ovui_widgets.app import layout as layout_module

        ini_2x = self._build_at_dpi(2.0)

        expected_w = layout_module._REF_WIDTH * 2
        expected_h = layout_module._REF_HEIGHT * 2
        expected_left = layout_module._REF_LEFT_PANEL * 2
        expected_right = layout_module._REF_RIGHT_PANEL * 2

        assert f"Size={expected_w},{expected_h}" in ini_2x  # DockSpace window
        assert f"Size={expected_left}," in ini_2x  # Stage Browser
        assert f"Size={expected_right}," in ini_2x  # Property Inspector
        assert f"SizeRef={expected_left}," in ini_2x  # Stage Browser dock node
        assert f"SizeRef={expected_right}," in ini_2x  # Property Inspector dock node

    def test_baseline_dpi_one_matches_reference_pixels(self):
        from ovui_widgets.app import layout as layout_module

        ini_1x = self._build_at_dpi(1.0)

        assert f"Size={layout_module._REF_LEFT_PANEL}," in ini_1x
        assert f"Size={layout_module._REF_RIGHT_PANEL}," in ini_1x

    def test_application_run_writes_split_ini_after_ui_init(self):
        """``Application.run`` must call ``write_split_ini`` *after*
        ``ui.init`` so the live monitor DPI is used. Calling it before
        pins the dock tree at DPI=1.0 because no platform window exists
        yet, which made every side panel half-width on 200% displays.
        """
        import inspect

        from ovui_widgets.app.application import Application

        source = inspect.getsource(Application.run)
        init_idx = source.find("ui.init(")
        write_idx = source.find("write_split_ini()")

        assert init_idx != -1, "Application.run must still initialise omni.ui"
        assert write_idx != -1, "Application.run must still write the split ini"
        assert write_idx > init_idx, (
            "write_split_ini() must run AFTER ui.init() so the dock tree "
            "scales with the live monitor DPI."
        )
