# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.app.style: URL constants, GLOBAL_STYLES dict, and style helpers.

Step 3 tests: urls.py, styles.py, and the apply_global_styles / set_theme
functions in style/__init__.py.
"""

import os

import omni.ui as ui
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLOR_KEYS = frozenset({"background_color", "color", "secondary_color", "border_color"})


@pytest.fixture(autouse=True)
def restore_shade():
    yield
    ui.set_shade("default")


# ---------------------------------------------------------------------------
# Part A: URL constants
# ---------------------------------------------------------------------------

class TestURLConstants:
    def test_urls_module_importable(self):
        from ovwidgets.common.style import urls  # noqa: F401

    @pytest.mark.parametrize("name", [
        "icon_check", "icon_close", "icon_expand", "icon_collapse",
        "icon_eye_open", "icon_eye_closed",
        "icon_lock", "icon_warning", "icon_error", "icon_info",
        "icon_search", "icon_filter", "icon_settings",
        "icon_add", "icon_remove",
        "icon_prim_xform", "icon_prim_mesh", "icon_prim_light",
        "icon_prim_camera", "icon_prim_scope", "icon_prim_generic",
        "viewport_tool_move", "viewport_tool_rotate", "viewport_tool_scale",
    ])
    def test_url_name_registered(self, name):
        from omni.ui import url

        import ovwidgets.app
        import ovwidgets.app.style  # noqa: F401 — ensures urls.py has run
        # Accessing url.<name> returns a _ShadeName string with the name
        val = getattr(url, name)
        assert isinstance(val, str)
        assert val == name

    @pytest.mark.parametrize("icon_name,file_name", [
        ("icon_check", "check.svg"),
        ("icon_close", "close.svg"),
        ("icon_expand", "expand.svg"),
        ("icon_collapse", "collapse.svg"),
        ("icon_eye_open", "eye_open.svg"),
        ("icon_eye_closed", "eye_closed.svg"),
        ("icon_lock", "lock.svg"),
        ("icon_warning", "warning.svg"),
        ("icon_error", "error.svg"),
        ("icon_info", "info.svg"),
        ("icon_search", "search.svg"),
        ("icon_filter", "filter.svg"),
        ("icon_settings", "settings.svg"),
        ("icon_add", "add.svg"),
        ("icon_remove", "remove.svg"),
        ("icon_prim_xform", "prim_xform.svg"),
        ("icon_prim_mesh", "prim_mesh.svg"),
        ("icon_prim_light", "prim_light.svg"),
        ("icon_prim_camera", "prim_camera.svg"),
        ("icon_prim_scope", "prim_scope.svg"),
        ("icon_prim_generic", "prim_generic.svg"),
    ])
    def test_icon_file_exists(self, icon_name, file_name):
        """The placeholder SVG on disk must exist at the expected path."""
        import ovwidgets.app.style  # noqa: F401
        from ovwidgets.common.style import urls as _urls_module
        icons_dir = _urls_module._ICONS_DIR
        path = os.path.join(icons_dir, file_name)
        assert os.path.isfile(path), f"Icon file missing: {path}"

    def test_icon_file_is_valid_svg(self):
        """Spot-check that the placeholder SVG is readable."""
        import ovwidgets.app.style  # noqa: F401
        from ovwidgets.common.style import urls as _urls_module
        path = os.path.join(_urls_module._ICONS_DIR, "check.svg")
        with open(path) as f:
            content = f.read()
        assert "<svg" in content
        assert "rect" in content

    @pytest.mark.parametrize("icon_name,file_name", [
        ("viewport_tool_move", "viewport_tool_move.png"),
        ("viewport_tool_rotate", "viewport_tool_rotate.png"),
        ("viewport_tool_scale", "viewport_tool_scale.png"),
    ])
    def test_viewport_tool_icon_file_exists(self, icon_name, file_name):
        import ovwidgets.app.style  # noqa: F401
        from ovwidgets.common.style.urls import get_icon_path

        path = get_icon_path(icon_name)
        assert path.endswith(file_name)
        assert os.path.isfile(path), f"Icon file missing: {path}"

    def test_legacy_prim_icon_urls_are_monochrome_line_glyphs(self):
        import re

        import ovwidgets.app.style  # noqa: F401
        from ovwidgets.common.style import urls as _urls_module

        expected = "#797A7F"
        for file_name in (
            "prim_xform.svg", "prim_mesh.svg", "prim_light.svg",
            "prim_camera.svg", "prim_scope.svg", "prim_generic.svg",
        ):
            path = os.path.join(_urls_module._ICONS_DIR, file_name)
            with open(path) as f:
                content = f.read()
            colors = set(re.findall(r'(?:stroke|fill)="(#[0-9A-Fa-f]{6})"', content))
            assert colors == {expected}, f"{file_name} colors are {colors}"
            assert 'fill="none"' in content


# ---------------------------------------------------------------------------
# Part B: GLOBAL_STYLES structure
# ---------------------------------------------------------------------------

class TestGlobalStylesStructure:
    def test_global_styles_is_non_empty_dict(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        assert isinstance(GLOBAL_STYLES, dict)
        assert len(GLOBAL_STYLES) > 0

    @pytest.mark.parametrize("key", [
        # Buttons
        "Button",
        "Button:hovered",
        "Button:pressed",
        "Button:disabled",
        "Button:checked",
        "Button.Label",
        "Button.Label:hovered",
        "Button.Label:disabled",
        "Button.Label:checked",
        "Button::ok",
        "Button::ok:hovered",
        "Button.Label::ok",
        "Button::cancel",
        "Button::cancel:hovered",
        "Button.Label::cancel",
        "Button::destructive",
        "Button::destructive:hovered",
        "Button.Label::destructive",
        "OKButton",
        "OKButton:hovered",
        "OKButton:pressed",
        "OKButton.Label",
        "CancelButton",
        "CancelButton:hovered",
        "CancelButton:pressed",
        "CancelButton.Label",
        # Text
        "Label",
        "Label:disabled",
        # Input
        "CheckBox",
        "CheckBox:hovered",
        "CheckBox:checked",
        "CheckBox:disabled",
        "Field",
        "Field:hovered",
        "Field:pressed",
        "Field:focused",
        "Field:disabled",
        "StringField",
        "StringField:hovered",
        "StringField:pressed",
        "StringField:focused",
        "StringField:disabled",
        "FloatField",
        "FloatField:hovered",
        "FloatField:pressed",
        "FloatField:focused",
        "FloatField:disabled",
        "IntField",
        "IntField:hovered",
        "IntField:pressed",
        "IntField:focused",
        "IntField:disabled",
        "FloatDrag",
        "FloatDrag:hovered",
        "FloatDrag:pressed",
        "FloatDrag:focused",
        "IntDrag",
        "IntDrag:hovered",
        "IntDrag:pressed",
        "IntDrag:focused",
        "ComboBox",
        "ComboBox:hovered",
        "ComboBox:pressed",
        "ComboBox:focused",
        "ComboBox:disabled",
        # Containers
        "ScrollingFrame",
        "ScrollingFrame:hovered",
        "ScrollingFrame:pressed",
        "Splitter",
        "Splitter:hovered",
        "CollapsableFrame",
        "CollapsableFrame:hovered",
        "CollapsableFrame:pressed",
        # TreeView
        "TreeView",
        "TreeView:selected",
        "TreeView.Item",
        "TreeView.Item:selected",
        "TreeView.Header",
        # Menu
        "Menu.Window",
        "MenuBar",
        "MenuBar.Item",
        "MenuBar.Item:hovered",
        "MenuBar.ProductLabel",
        "MenuBar.Logo",
        "MenuBar.ProductSeparator",
        "Menu.Item",
        "Menu.Item:hovered",
        "Menu.Item:disabled",
        "Menu.Separator",
        # Misc
        "Tooltip",
        "Separator",
        "ProgressBar",
        "Rectangle",
        # OvGear domain
        "OvGear.StatusBar",
        "Viewport.HUD",
        "Viewport.HUD.Label",
        "Viewport.HUD.Value",
        "Viewport.HUD.Separator",
        "Viewport.Toolbar",
        "Viewport.Toolbar.Button",
        "Viewport.Toolbar.Button:hovered",
        "Viewport.Toolbar.Button:pressed",
        "Viewport.Toolbar.Button:checked",
        "Viewport.Toolbar.Button::active",
        "Viewport.Toolbar.Icon",
        "Menu.Item.CheckMark",
        "Menu.Item.CheckMark:disabled",
        "OvGear.StatusBar::error",
        "OvGear.StatusBar::warning",
        "OvGear.StatusBar::success",
    ])
    def test_required_key_present(self, key):
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        assert key in GLOBAL_STYLES, f"Missing GLOBAL_STYLES key: {key!r}"

    def test_each_entry_is_dict(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        for selector, props in GLOBAL_STYLES.items():
            assert isinstance(props, dict), f"{selector!r}: value must be dict"

    def test_each_entry_non_empty(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        for selector, props in GLOBAL_STYLES.items():
            assert props, f"{selector!r}: style dict is empty"

    def test_scrolling_frame_uses_step19_scrollbar_tokens(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES

        entry = GLOBAL_STYLES["ScrollingFrame"]
        assert entry["background_color"] == "scrollbar_track"
        assert entry["secondary_color"] == "scrollbar_thumb"
        assert entry["scrollbar_size"] == "scrollbar_width"
        assert entry["border_radius"] == "radius_small"

    def test_scrolling_frame_hover_uses_hover_thumb(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES

        assert (
            GLOBAL_STYLES["ScrollingFrame:hovered"]["secondary_color"]
            == "scrollbar_thumb_hovered"
        )
        assert (
            GLOBAL_STYLES["ScrollingFrame:pressed"]["secondary_color"]
            == "scrollbar_thumb_hovered"
        )

    def test_splitter_uses_step20_tokens(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES

        rest = GLOBAL_STYLES["Splitter"]
        hovered = GLOBAL_STYLES["Splitter:hovered"]

        assert rest["background_color"] == "splitter_handle"
        assert rest["color"] == "splitter_handle"
        assert rest["border_width"] == "splitter_visual_width"
        assert rest["padding"] == "splitter_hit_target"
        assert hovered["background_color"] == "splitter_handle_hovered"
        assert hovered["color"] == "splitter_handle_hovered"


class TestStep22UnifiedFieldStyles:
    """Step 22: every editable field type shares fill, border, radius, and focus."""

    @pytest.mark.parametrize(
        "selector",
        ["Field", "StringField", "FloatField", "IntField", "FloatDrag", "IntDrag", "ComboBox"],
    )
    def test_field_base_style_uses_shared_tokens(self, selector):
        from ovwidgets.app.style.styles import GLOBAL_STYLES

        style = GLOBAL_STYLES[selector]
        assert style["background_color"] == "background_field"
        assert style["border_color"] == "border_default"
        assert style["border_width"] == 1
        assert style["border_radius"] == "radius_small"

    @pytest.mark.parametrize(
        "selector",
        [
            "Field:pressed",
            "Field:focused",
            "StringField:pressed",
            "StringField:focused",
            "FloatField:pressed",
            "FloatField:focused",
            "IntField:pressed",
            "IntField:focused",
            "FloatDrag:pressed",
            "FloatDrag:focused",
            "IntDrag:pressed",
            "IntDrag:focused",
            "ComboBox:pressed",
            "ComboBox:focused",
        ],
    )
    def test_field_focus_states_keep_fill_and_use_focused_border(self, selector):
        from ovwidgets.app.style.styles import GLOBAL_STYLES

        style = GLOBAL_STYLES[selector]
        assert style["background_color"] == "background_field"
        assert style["border_color"] == "border_focused"

    @pytest.mark.parametrize(
        "selector",
        ["FloatDrag", "IntDrag", "ComboBox", "FloatDrag:focused", "IntDrag:focused", "ComboBox:focused"],
    )
    def test_field_secondary_fill_matches_background_field(self, selector):
        from ovwidgets.app.style.styles import GLOBAL_STYLES

        assert GLOBAL_STYLES[selector]["secondary_color"] == "background_field"


# ---------------------------------------------------------------------------
# Part C: No raw hex colors
# ---------------------------------------------------------------------------

class TestNoRawHex:
    def test_color_values_are_cl_references(self):
        """All *_color and 'color' values must be cl.xxx string refs, not ints."""
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        violations = []
        for selector, props in GLOBAL_STYLES.items():
            for key, val in props.items():
                if key in _COLOR_KEYS:
                    if not isinstance(val, str):
                        violations.append(
                            f"{selector}/{key}: expected str (cl.xxx), "
                            f"got {type(val).__name__} {val!r}"
                        )
        assert not violations, "Raw color values found:\n" + "\n".join(violations)

    def test_no_raw_argb_integers(self):
        """No value in any style entry should be a large ARGB integer (>= 0x80000000)."""
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        violations = []
        for selector, props in GLOBAL_STYLES.items():
            for key, val in props.items():
                if isinstance(val, int) and val >= 0x80000000:
                    violations.append(f"{selector}/{key}: {hex(val)}")
        assert not violations, "Raw ARGB ints found:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Part D: apply_global_styles and set_theme
# ---------------------------------------------------------------------------

class TestStyleHelpers:
    def test_apply_global_styles_callable(self):
        import ovwidgets.app.style
        assert callable(ovwidgets.app.style.apply_global_styles)

    def test_set_theme_callable(self):
        import ovwidgets.app.style
        assert callable(ovwidgets.app.style.set_theme)

    def test_apply_global_styles_sets_default(self):
        """After apply_global_styles(), ui.style.default is a non-empty dict
        containing the expected top-level selectors."""
        import ovwidgets.app.style
        ovwidgets.app.style.apply_global_styles()
        result = ui.style.default
        assert isinstance(result, dict)
        assert len(result) > 0
        for key in ("Button", "Label", "TreeView", "OvGear.StatusBar"):
            assert key in result, f"ui.style.default missing '{key}' after apply"

    def test_apply_global_styles_resolves_colors(self):
        """Colors in ui.style.default should be resolved integers (not strings)."""
        import ovwidgets.app.style
        ovwidgets.app.style.apply_global_styles()
        result = ui.style.default
        btn = result.get("Button", {})
        assert "background_color" in btn
        assert isinstance(btn["background_color"], int)

    def test_set_theme_light_does_not_crash(self):
        import ovwidgets.app.style
        ovwidgets.app.style.set_theme("light")

    def test_set_theme_dark_does_not_crash(self):
        import ovwidgets.app.style
        ovwidgets.app.style.set_theme("dark")

    def test_set_theme_unknown_falls_back_to_dark(self):
        import ovwidgets.app.style
        ovwidgets.app.style.set_theme("unknown")  # should not raise

    def test_theme_switch_updates_resolved_color(self):
        """After apply + light theme, background_primary resolves to a different int."""
        import ovwidgets.app.style
        ovwidgets.app.style.apply_global_styles()
        dark_val = ui.style.default["Button"]["background_color"]

        ovwidgets.app.style.set_theme("light")
        # Re-apply so style.default reflects the new shade
        ovwidgets.app.style.apply_global_styles()
        light_val = ui.style.default["Button"]["background_color"]

        assert dark_val != light_val, (
            "Dark and light Button background_color should differ"
        )

        # Restore
        ovwidgets.app.style.set_theme("dark")


# ---------------------------------------------------------------------------
# Part E: URL icon file path content
# ---------------------------------------------------------------------------

class TestPlaceholderSVGs:
    @pytest.mark.parametrize("name", [
        "check", "close", "expand", "collapse",
        "eye_open", "eye_closed",
        "lock", "warning", "error", "info",
        "search", "filter", "settings",
        "add", "remove",
        "prim_xform", "prim_mesh", "prim_light",
        "prim_camera", "prim_scope", "prim_generic",
    ])
    def test_svg_placeholder_valid(self, name):
        """Each placeholder SVG must be a parseable 16×16 document."""
        import ovwidgets.app.style  # noqa: F401
        from ovwidgets.common.style import urls as _urls_module
        path = os.path.join(_urls_module._ICONS_DIR, f"{name}.svg")
        assert os.path.isfile(path), f"Missing icon file for '{name}'"
        with open(path) as f:
            content = f.read()
        assert 'xmlns="http://www.w3.org/2000/svg"' in content
        assert 'width="16"' in content
        assert 'height="16"' in content


# ---------------------------------------------------------------------------
# Step 73 — register_urls() and style/icons/ SVG placeholders
# ---------------------------------------------------------------------------

class TestRegisterUrls:
    """Tests for register_urls() and style/icons/ icon files.

    feature/stage-design: app / prim / stage-chrome / badge icons now ship as
    ``.png`` (with ``.svg`` sources committed alongside) because the
    standalone ``omni.ui`` build routes ``ui.Image`` through stb_image,
    which doesn't read SVG. Status and control-state icons remain ``.svg``;
    they are referenced by styling only and never rasterised today.

    Property Step 4.4 added the ``control_state_*`` icons — still SVG
    because they are state-selector glyphs referenced from style dicts
    only, never rasterised today.
    """

    # App + prim + badge + chrome icons — registered as .png with SVG sources alongside.
    # Layers Step 49 added ``prim_def`` + ``prim_over`` to the
    # specifier-icon axis (``prim_class`` was already present for the
    # Stage window's is-a-class flag and is now reused by the Layers
    # tree's ``Sdf.SpecifierClass`` rows).
    PNG_ICON_NAMES = [
        "app_logo",
        "prim_mesh", "prim_light", "prim_camera", "prim_scope",
        "prim_xform",
        "prim_def", "prim_over", "prim_class",
        "prim_generic",
        "stage_search", "stage_close_x", "stage_eye_on", "stage_eye_off",
        "stage_active_off",
        "viewport_tool_move", "viewport_tool_rotate", "viewport_tool_scale",
        "menu_checkmark",
        "badge_reference", "badge_payload", "badge_instance",
        "badge_inherits", "badge_specializes",
    ]
    # Status + control-state icons — registered as .svg.
    SVG_ICON_NAMES = [
        "status_warning", "status_error", "status_info",
        "control_state_mixed", "control_state_locked",
        "control_state_timesample", "control_state_not_default",
    ]
    # Content-browser placeholder PNGs (the content browser implementation step 5). 64x64 raster
    # placeholders with no SVG source — production artwork replaces them
    # in-place, so the SVG-source invariant only applies to PNG_ICON_NAMES.
    CONTENT_BROWSER_PNG_NAMES = [
        "asset_folder", "asset_usd", "asset_image", "asset_material",
        "asset_model", "asset_sound", "asset_script", "asset_volume",
        "asset_text", "asset_archive", "asset_unknown",
        "content_search", "content_filter",
        "content_bookmark", "content_bookmark_filled",
        "content_arrow_left", "content_arrow_right", "content_arrow_up",
        "content_arrow_down",
        "content_grid_view", "content_list_view",
        "content_home", "content_plus", "content_minus",
        # Step 27 — reuses the existing ``close_x.png`` asset (also
        # pointed at by ``stage_close_x``) for the SearchField clear
        # button. The content-domain URL alias keeps callers inside
        # the ``url.content_*`` namespace.
        "content_close",
        # Step 56 — gear icon for the Options toolbar button. 64×64
        # placeholder PNG matching the other ``content_*`` chrome icons.
        "content_gear",
    ]
    STYLE_ICON_NAMES = PNG_ICON_NAMES + SVG_ICON_NAMES + CONTENT_BROWSER_PNG_NAMES

    def test_register_urls_does_not_crash(self):
        from ovwidgets.common.style.urls import register_urls
        register_urls()  # idempotent — must not raise

    def test_style_icon_paths_dict_populated(self):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        assert len(_STYLE_ICON_PATHS) == len(self.STYLE_ICON_NAMES)

    @pytest.mark.parametrize("name", STYLE_ICON_NAMES)
    def test_style_icon_path_key_present(self, name):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        assert name in _STYLE_ICON_PATHS

    @pytest.mark.parametrize("name", STYLE_ICON_NAMES)
    def test_style_icon_file_exists(self, name):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        path = _STYLE_ICON_PATHS[name]
        assert os.path.isfile(path), f"Missing icon file: {path}"

    @pytest.mark.parametrize("name", PNG_ICON_NAMES)
    def test_png_icon_has_svg_source(self, name):
        """Each raster icon keeps its SVG source next to it (editing surface)."""
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        png_path = _STYLE_ICON_PATHS[name]
        svg_path = png_path[:-4] + ".svg"
        assert os.path.isfile(svg_path), f"Missing SVG source: {svg_path}"

    @pytest.mark.parametrize("name", SVG_ICON_NAMES)
    def test_svg_icon_is_valid_svg(self, name):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        path = _STYLE_ICON_PATHS[name]
        with open(path) as f:
            content = f.read()
        assert "<svg" in content, f"{name}.svg missing <svg> tag"
        assert 'xmlns="http://www.w3.org/2000/svg"' in content, f"{name}.svg missing xmlns"

    @pytest.mark.parametrize("name", ["prim_mesh", "prim_light", "prim_camera", "prim_scope", "prim_generic"])
    def test_prim_icon_svg_source_is_16x16(self, name):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        svg_path = _STYLE_ICON_PATHS[name][:-4] + ".svg"
        with open(svg_path) as f:
            content = f.read()
        assert 'width="16"' in content
        assert 'height="16"' in content

    @pytest.mark.parametrize("name", SVG_ICON_NAMES)
    def test_svg_icon_is_16x16(self, name):
        """Status + control-state icons are registered as ``.svg`` directly."""
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        path = _STYLE_ICON_PATHS[name]
        with open(path) as f:
            content = f.read()
        assert 'width="16"' in content
        assert 'height="16"' in content

    @pytest.mark.parametrize("name", SVG_ICON_NAMES)
    def test_svg_icon_parses_as_xml(self, name):
        """SVG is well-formed XML — catches unclosed tags, attribute typos."""
        import xml.etree.ElementTree as ET

        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        path = _STYLE_ICON_PATHS[name]
        root = ET.parse(path).getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert root.get("viewBox") == "0 0 16 16"

    def test_prim_mesh_url_registered_in_url_store(self):
        from omni.ui import url

        import ovwidgets.app.style  # noqa: F401
        val = url.prim_mesh
        assert isinstance(val, str)

    def test_status_warning_url_registered_in_url_store(self):
        from omni.ui import url

        import ovwidgets.app.style  # noqa: F401
        val = url.status_warning
        assert isinstance(val, str)

    def test_style_icons_dir_exists(self):
        from ovwidgets.common.style.urls import _STYLE_ICONS_DIR
        assert _STYLE_ICONS_DIR.is_dir()

    def test_style_icon_paths_are_in_style_icons_dir(self):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS, _STYLE_ICONS_DIR
        for name, path in _STYLE_ICON_PATHS.items():
            assert str(_STYLE_ICONS_DIR) in path, f"{name} path not under style/icons/"

    def test_style_icon_filenames_are_renderable(self):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        for name, path in _STYLE_ICON_PATHS.items():
            assert path.endswith(".png") or path.endswith(".svg"), (
                f"{name} path {path!r} is neither .png nor .svg"
            )

    def test_register_urls_idempotent_no_crash(self):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS, register_urls
        register_urls()
        count_before = len(_STYLE_ICON_PATHS)
        register_urls()
        assert len(_STYLE_ICON_PATHS) == count_before

    def test_prim_icons_are_monochrome_muted_line_glyphs(self):
        """Step 7: prim icons are muted gray line glyphs, not type-colored."""
        import re

        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        expected = "#797A7F"
        for name in (
            "prim_mesh", "prim_light", "prim_camera", "prim_scope",
            "prim_xform", "prim_class", "prim_generic",
        ):
            svg_path = _STYLE_ICON_PATHS[name][:-4] + ".svg"
            with open(svg_path) as f:
                content = f.read()
            colors = set(re.findall(r'(?:stroke|fill)="(#[0-9A-Fa-f]{6})"', content))
            assert colors == {expected}, f"{name} colors are {colors}"
            assert 'fill="none"' in content

    def test_runtime_prim_pngs_are_monochrome_line_glyphs(self):
        """The Stage tree renders PNGs, so stale colored rasters must fail."""
        from PIL import Image

        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS

        for name in (
            "prim_mesh", "prim_light", "prim_camera", "prim_scope",
            "prim_xform", "prim_class", "prim_generic",
        ):
            img = Image.open(_STYLE_ICON_PATHS[name]).convert("RGBA")
            visible = [
                img.getpixel((x, y))
                for y in range(img.height)
                for x in range(img.width)
                if img.getpixel((x, y))[3] > 16
            ]
            assert visible, f"{name} has no visible pixels"
            assert len(visible) < 128, f"{name} looks filled, not line-style"
            for y in range(img.height):
                for x in range(img.width):
                    r, g, b, a = img.getpixel((x, y))
                    if a > 64:
                        assert max(r, g, b) - min(r, g, b) <= 10, (
                            f"{name} contains chromatic pixel {(r, g, b)}"
                        )

    def test_status_icons_have_distinct_colors(self):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        colors = set()
        for name in ("status_warning", "status_error", "status_info"):
            with open(_STYLE_ICON_PATHS[name]) as f:
                content = f.read()
            import re
            match = re.search(r'fill="(#[0-9A-Fa-f]{6})"', content)
            if match:
                colors.add(match.group(1))
        assert len(colors) == 3, "Each status icon should have a distinct fill color"

    def test_menu_checkmark_style_uses_registered_icon(self):
        from ovwidgets.app.style.styles import GLOBAL_STYLES
        from ovwidgets.common.style.urls import get_icon_path

        expected = get_icon_path("menu_checkmark")
        assert GLOBAL_STYLES["Menu.Item.CheckMark"]["image_url"] == expected
        assert GLOBAL_STYLES["Menu.Item.CheckMark:disabled"]["image_url"] == expected


# ---------------------------------------------------------------------------
# Step 4.4 — ControlState icons and get_icon_path() accessor
# ---------------------------------------------------------------------------


class TestControlStateIcons:
    """Step 4.4 — per-state SVG glyphs in ``ovwidgets.app/style/icons/``.

    Distinct from the placeholder prim/status icons: these carry real
    shapes (padlock, diamond, dot, split circle) and a specific
    palette-matching fill colour. The handlers registered by
    :func:`_register_defaults` in ``control_state.py`` reference these
    files; tests pin both the SVGs and the wiring so a rename on one
    side can't silently desync from the other.
    """

    CONTROL_STATE_NAMES = [
        "control_state_mixed",
        "control_state_locked",
        "control_state_timesample",
        "control_state_not_default",
    ]

    @pytest.mark.parametrize("name", CONTROL_STATE_NAMES)
    def test_registered_in_style_icon_paths(self, name):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        assert name in _STYLE_ICON_PATHS

    @pytest.mark.parametrize("name", CONTROL_STATE_NAMES)
    def test_file_exists_under_style_icons_dir(self, name):
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS, _STYLE_ICONS_DIR
        path = _STYLE_ICON_PATHS[name]
        assert os.path.isfile(path)
        assert str(_STYLE_ICONS_DIR) in path

    @pytest.mark.parametrize("name", CONTROL_STATE_NAMES)
    def test_svg_parses_and_is_16x16(self, name):
        import xml.etree.ElementTree as ET

        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        path = _STYLE_ICON_PATHS[name]
        root = ET.parse(path).getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert root.get("width") == "16"
        assert root.get("height") == "16"
        assert root.get("viewBox") == "0 0 16 16"

    @pytest.mark.parametrize("name", CONTROL_STATE_NAMES)
    def test_svg_has_no_external_refs(self, name):
        """No ``<image href=...>``, no ``<use xlink:href=...>`` — SVGs are
        self-contained so the standalone/Kit renderer doesn't need a
        resource base URL.
        """
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
        with open(_STYLE_ICON_PATHS[name]) as f:
            content = f.read()
        assert "xlink:href" not in content
        assert "<image" not in content
        assert "http://" not in content.replace(
            'xmlns="http://www.w3.org/2000/svg"', ""
        )

    def test_not_default_icon_is_rounded_square(self):
        import xml.etree.ElementTree as ET

        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS

        root = ET.parse(_STYLE_ICON_PATHS["control_state_not_default"]).getroot()
        rect = root.find("{http://www.w3.org/2000/svg}rect")
        assert rect is not None
        assert rect.get("x") == "2"
        assert rect.get("y") == "2"
        assert rect.get("width") == "12"
        assert rect.get("height") == "12"
        assert rect.get("rx") == "2"
        assert rect.get("fill") == "currentColor"


class TestGetIconPath:
    """``get_icon_path()`` exposes the filesystem path for a registered URL.

    ``omni.ui.url`` stores shade-name strings (useful as ``source_url``
    for Kit's ``ui.Image``), so a path-aware accessor is necessary for
    consumers that need the real on-disk path — tests that assert the
    file exists, the ``ControlStateManager`` default handler
    registration that stores ``icon_path`` on :class:`ControlStateHandler`,
    and future code that wants to open / hash / copy the icon.
    """

    def test_returns_absolute_path_for_registered_name(self):
        from ovwidgets.common.style.urls import get_icon_path
        path = get_icon_path("control_state_mixed")
        assert os.path.isabs(path)
        assert os.path.isfile(path)
        assert path.endswith("mixed.svg")

    def test_raises_keyerror_for_unregistered_name(self):
        from ovwidgets.common.style.urls import get_icon_path
        with pytest.raises(KeyError):
            get_icon_path("definitely_not_registered_xyz")

    def test_agrees_with_style_icon_paths_dict(self):
        """Public accessor returns the exact same value as the internal dict."""
        from ovwidgets.common.style.urls import _STYLE_ICON_PATHS, get_icon_path
        for name, path in _STYLE_ICON_PATHS.items():
            assert get_icon_path(name) == path


class TestControlStateHandlerIconWiring:
    """Built-in control-state handlers point at the Step 4.4 SVGs.

    The Step 4.3 registrations used placeholder paths in
    ``ovwidgets.app/resources/icons/``. Step 4.4 retargets them at the
    dedicated glyphs under ``ovwidgets.app/style/icons/`` — this test pins
    that the retarget actually happened and stays valid after future
    handler-registration refactors.
    """

    def _fresh_handlers(self):
        from ovwidgets.property.parts import ControlStateManager
        ControlStateManager._reset_for_tests()
        mgr = ControlStateManager.get_instance()
        try:
            return {h.name: h for h in mgr.list_states()}
        finally:
            ControlStateManager._reset_for_tests()

    def test_each_default_handler_points_at_style_icons_dir(self):
        from ovwidgets.common.style.urls import _STYLE_ICONS_DIR
        handlers = self._fresh_handlers()
        for name in ("Mixed", "Locked", "TimeSampled", "NotDefault"):
            assert str(_STYLE_ICONS_DIR) in handlers[name].icon_path, (
                f"{name} handler icon_path not under style/icons/"
            )

    def test_each_default_handler_points_at_existing_file(self):
        handlers = self._fresh_handlers()
        for name in ("Mixed", "Locked", "TimeSampled", "NotDefault"):
            assert os.path.isfile(handlers[name].icon_path), (
                f"{name} handler icon {handlers[name].icon_path} missing"
            )

    def test_handler_icon_paths_match_named_svg_files(self):
        """Handler name ↔ SVG filename mapping is stable: ``Mixed`` →
        ``mixed.svg``, ``Locked`` → ``locked.svg``, ``TimeSampled`` →
        ``timesample.svg``, ``NotDefault`` → ``not_default.svg``.
        """
        handlers = self._fresh_handlers()
        assert handlers["Mixed"].icon_path.endswith("mixed.svg")
        assert handlers["Locked"].icon_path.endswith("locked.svg")
        assert handlers["TimeSampled"].icon_path.endswith("timesample.svg")
        assert handlers["NotDefault"].icon_path.endswith("not_default.svg")


class TestLayersStyles:
    """LAYERS-PLAN Step 11 — LAYERS_STYLES palette tokens + theme re-apply.

    Pins the dict structure (non-empty, required selectors present), the
    new ``cl.layers_*`` shade registrations, and the apply_global_styles
    merge hook. Theme-switch test confirms the shade mechanism actually
    produces different resolved ints for dark vs light.
    """

    REQUIRED_SELECTORS = [
        "Layers.TreeView",
        "Layers.TreeView:hovered",
        "Layers.TreeView:selected",
        "Layers.TreeView.Row",
        "Layers.TreeView.Row:selected",
        "Layers.TreeView.Row:hovered",
        "Layers.NameLabel",
        "Layers.NameLabel::missing",
        "Layers.NameLabel::edit_target",
        "Layers.IconButton",
        "Layers.IconButton::muted",
    ]

    NEW_COLOR_TOKENS = [
        "layers_row_edit_target",
        "layers_row_hover",
        # Group D consolidated the selected-row colour onto the shared
        # ``treeview_selection`` token (audit issue #5); the former
        # ``layers_row_selected`` was removed from the palette.
        "layers_label_missing",
        "layers_label_disabled",
        "layers_icon_edit_target",
        "layers_icon_outdated",
    ]

    def test_layers_styles_is_non_empty_dict(self):
        from ovwidgets.layers.style import LAYERS_STYLES
        assert isinstance(LAYERS_STYLES, dict)
        assert len(LAYERS_STYLES) > 0

    @pytest.mark.parametrize("key", REQUIRED_SELECTORS)
    def test_required_selector_present(self, key):
        from ovwidgets.layers.style import LAYERS_STYLES
        assert key in LAYERS_STYLES, f"Missing LAYERS_STYLES key: {key!r}"

    def test_each_entry_is_dict(self):
        from ovwidgets.layers.style import LAYERS_STYLES
        for selector, props in LAYERS_STYLES.items():
            assert isinstance(props, dict), f"{selector!r}: value must be dict"

    def test_each_entry_non_empty(self):
        from ovwidgets.layers.style import LAYERS_STYLES
        for selector, props in LAYERS_STYLES.items():
            assert props, f"{selector!r}: style dict is empty"

    def test_color_values_are_cl_references(self):
        """All *_color / 'color' values resolve via cl.* shades, not raw ints."""
        from ovwidgets.layers.style import LAYERS_STYLES
        violations = []
        for selector, props in LAYERS_STYLES.items():
            for key, val in props.items():
                if key in _COLOR_KEYS and not isinstance(val, str):
                    violations.append(
                        f"{selector}/{key}: expected cl.xxx str, "
                        f"got {type(val).__name__} {val!r}"
                    )
        assert not violations, "Raw color values found:\n" + "\n".join(violations)

    @pytest.mark.parametrize("name", NEW_COLOR_TOKENS)
    def test_layers_palette_token_registered(self, name):
        from omni.ui import color as cl

        import ovwidgets.app.style  # noqa: F401 — triggers palette registration
        val = getattr(cl, name)
        assert isinstance(val, str)
        assert val == name

    def test_apply_global_styles_includes_layers_selectors(self):
        import ovwidgets.app.style
        ovwidgets.app.style.apply_global_styles()
        resolved = ui.style.default
        for key in self.REQUIRED_SELECTORS:
            assert key in resolved, (
                f"ui.style.default missing Layers selector {key!r} "
                "after apply_global_styles()"
            )

    def test_theme_switch_reresolves_layers_row_hover(self):
        """Dark→light on a Layers-specific shade must change the resolved int.

        Proof the LAYERS_STYLES merge path is shade-aware end-to-end:
        the selector is in ``ui.style.default`` and its colour comes from
        a layers-only shade, so a different integer between dark and
        light could only come from the shade re-resolve happening.
        """
        import ovwidgets.app.style
        ovwidgets.app.style.set_theme("dark")
        ovwidgets.app.style.apply_global_styles()
        dark_val = ui.style.default["Layers.TreeView.Row:hovered"][
            "background_color"
        ]

        ovwidgets.app.style.set_theme("light")
        light_val = ui.style.default["Layers.TreeView.Row:hovered"][
            "background_color"
        ]
        # Restore before leaving the test.
        ovwidgets.app.style.set_theme("dark")

        assert isinstance(dark_val, int) and isinstance(light_val, int)
        assert dark_val != light_val, (
            "layers_row_hover should resolve to a different int under light "
            "shade — theme re-apply hook is broken"
        )


class TestSvgRenderingFlag:
    """The Kit/standalone probe gates the ``ui.Image`` fallback path."""

    def test_flag_matches_in_kit_constant(self):
        import omni.ui as ui

        from ovwidgets.property.parts.control_state import _SVG_RENDERING_AVAILABLE
        assert _SVG_RENDERING_AVAILABLE is bool(getattr(ui, "_IN_KIT", False))

    def test_flag_false_in_standalone_build(self):
        """The dev VM runs standalone omni.ui; the flag must be
        False here so tests pin the Rectangle-fallback path is what
        renders on this build.
        """
        import omni.ui as ui

        from ovwidgets.property.parts.control_state import _SVG_RENDERING_AVAILABLE
        if not getattr(ui, "_IN_KIT", False):
            assert _SVG_RENDERING_AVAILABLE is False


# ---------------------------------------------------------------------------
# Design Step 2 — typographic proportions. Each text role in the UI is
# pinned to a named tier in the fl.font_size_* ladder so the hierarchy is
# enforceable at the style-dict level rather than hidden inside widget code.
# ---------------------------------------------------------------------------

class TestFontSizeTiers:
    """Every role-to-tier binding DESIGN-PLAN Step 2 specifies is pinned
    here. If anyone retunes a tier value, these selectors still resolve to
    the right *relative* tier — the whole point of the named ladder.

    omni.ui resolves ``fl.*`` references to concrete floats when a style
    dict is assigned to ``ui.style.default``, so the assertions here
    compare the resolved ``ui.style.default[selector]["font_size"]``
    value against ``ui.FloatStore.find(<token>)``.
    """

    def _merged_and_tiers(self):
        import ovwidgets.app.style
        ovwidgets.app.style.apply_global_styles()
        tiers = {
            "tiny": ui.FloatStore.find("font_size_tiny"),
            "small": ui.FloatStore.find("font_size_small"),
            "medium": ui.FloatStore.find("font_size_medium"),
            "large": ui.FloatStore.find("font_size_large"),
        }
        return ui.style.default, tiers

    def test_baseline_body_tree_row_name_uses_small_tier(self):
        # Design Step 5 tightens the Stage tree; prim names use the small
        # tier and selected rows must not enlarge that text.
        merged, tiers = self._merged_and_tiers()
        assert merged["Stage.Name"]["font_size"] == tiers["small"]
        assert merged["TreeView.Item"]["font_size"] == tiers["small"]

    def test_tree_row_type_label_smaller_than_name(self):
        # DESIGN-PLAN: "Tree row type labels are slightly smaller than names".
        merged, _ = self._merged_and_tiers()
        name_fs = merged["Stage.Name"]["font_size"]
        type_fs = merged["Stage.TypeLabel"]["font_size"]
        assert type_fs < name_fs
        assert merged["Stage.TypeLabel:selected"]["font_size"] == type_fs
        assert (
            merged["Stage.TypeLabel:selected"]["color"]
            == merged["Stage.TypeLabel"]["color"]
        )

    def test_selected_tree_row_name_keeps_body_size(self):
        merged, tiers = self._merged_and_tiers()
        assert (
            merged["TreeView.Item:selected"]["font_size"]
            == merged["TreeView.Item"]["font_size"]
        )
        assert merged["TreeView.Item:selected"]["font_size"] == tiers["small"]

    def test_stage_column_header_small(self):
        merged, tiers = self._merged_and_tiers()
        assert merged["Stage.ColumnHeader"]["font_size"] == tiers["small"]

    def test_filter_placeholder_small(self):
        merged, tiers = self._merged_and_tiers()
        assert merged["Stage.FilterFieldInput"]["font_size"] == tiers["small"]
        assert merged["Property.SearchFieldInput"]["font_size"] == tiers["small"]

    def test_property_group_header_smaller_than_body(self):
        # Group headers ("ATTRIBUTES", "PRIMVARS", "TRANSFORM") must read as
        # quieter than body text. Before Step 2 they were medium (same as
        # body) — which is the exact hierarchy bug this test guards against.
        merged, tiers = self._merged_and_tiers()
        group_fs = merged["Property.GroupFrame"]["font_size"]
        assert group_fs == tiers["small"]
        assert group_fs < tiers["medium"]

    def test_chevrons_use_secondary_text_tone(self):
        merged, _ = self._merged_and_tiers()
        secondary = ui.ColorStore.find("text_secondary")
        assert merged["Stage.TreeChevron"]["color"] == secondary
        assert merged["Property.GroupFrame.Chevron"]["color"] == secondary
        assert merged["Property.ComboBoxChevron"]["color"] == secondary

    def test_property_attribute_label_small(self):
        merged, tiers = self._merged_and_tiers()
        assert merged["Property.LabelColumn"]["font_size"] == tiers["small"]
        assert merged["Property.AttributeLabel"]["font_size"] == tiers["small"]

    def test_property_channel_labels_small(self):
        # Channel axis labels (X/Y/Z/W) follow the attribute-label tier so the
        # row's left side reads as one cohesive label column.
        merged, tiers = self._merged_and_tiers()
        for axis in ("X", "Y", "Z", "W"):
            selector = f"Property.ChannelLabel.{axis}"
            assert merged[selector]["font_size"] == tiers["tiny"], (
                f"{selector} not at font_size_tiny"
            )

    def test_viewport_hud_small(self):
        # Step 18 pins all corner HUD labels/values to the small tier.
        merged, tiers = self._merged_and_tiers()
        for selector in (
            "Viewport.HUD.Label",
            "Viewport.HUD.Value",
            "Viewport.HUD.Separator",
            "ViewportWidget.HUD.FpsLabel",
            "ViewportWidget.HUD.PrimLabel",
        ):
            assert selector in merged, f"Missing HUD selector: {selector}"
            assert merged[selector]["font_size"] == tiers["small"]

    def test_viewport_hud_label_value_color_hierarchy(self):
        merged, _ = self._merged_and_tiers()
        assert merged["Viewport.HUD.Label"]["color"] == (
            ui.ColorStore.find("text_secondary")
        )
        assert merged["Viewport.HUD.Value"]["color"] == (
            ui.ColorStore.find("text_value")
        )
        assert merged["Viewport.HUD.Separator"]["color"] == (
            ui.ColorStore.find("text_disabled")
        )

    def test_property_selection_header_tiers(self):
        # The header widget is introduced later in the design plan, but Step 2
        # pins its typographic role now so the title lands above inspector body.
        merged, tiers = self._merged_and_tiers()
        assert merged["Property.SelectionHeader"]["font_size"] == tiers["small"]
        assert merged["Property.SelectionHeader.Title"]["font_size"] == tiers["large"]
        assert merged["Property.SelectionHeader.Path"]["font_size"] == tiers["small"]

    def test_status_bar_small(self):
        merged, tiers = self._merged_and_tiers()
        assert merged["OvGear.StatusBar"]["font_size"] == tiers["small"]

    def test_menu_font_sizes_use_fixed_exception_tier(self):
        merged, _ = self._merged_and_tiers()
        menu_size = ui.FloatStore.find("menu_item_font_size")
        product_size = ui.FloatStore.find("menu_bar_product_font_size")

        assert menu_size == 14.0
        assert product_size == 16.0
        assert merged["MenuBar"]["font_size"] == menu_size
        assert merged["MenuBar.Item"]["font_size"] == menu_size
        assert merged["Menu.Item"]["font_size"] == menu_size
        assert merged["MenuBar.ProductLabel"]["font_size"] == product_size

    def test_hierarchy_ordering(self):
        # Step 18 moves viewport HUD labels onto the same small tier as
        # compact UI labels while values use brighter colour for hierarchy.
        merged, _ = self._merged_and_tiers()
        hud = merged["Viewport.HUD.Label"]["font_size"]
        group = merged["Property.GroupFrame"]["font_size"]
        label = merged["Property.LabelColumn"]["font_size"]
        body = merged["Stage.Name"]["font_size"]
        assert hud == label == group == body
