# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ``ovwidgets.content.style`` — the content browser implementation step 12.

Verify that the Content Browser domain styles:
- populate a non-empty dict with every selector required by the plan;
- obey style naming rules "no hex literals" — every colour value is a
  :class:`_ShadeName` string routed through ``cl.*`` (or the shared
  ``transparent`` shade), never a raw int;
- route through :func:`apply_global_styles` so theme switching
  propagates the updated palette to ``ui.style.default``.
"""

from __future__ import annotations

import omni.ui as ui
import pytest

from ovwidgets.content.style import CONTENT_STYLES

# ── Helpers ───────────────────────────────────────────────────────────────

# Style keys whose values are colours in the omni.ui style dict. Any
# entry appearing under one of these keys must reference ``cl.*`` (a
# ``_ShadeName`` str), never a raw int.
_COLOR_KEYS = frozenset(
    {"background_color", "color", "secondary_color", "border_color"}
)


@pytest.fixture(autouse=True)
def restore_shade():
    """Every theme-switching test leaves dark as the active shade."""
    yield
    ui.set_shade("default")


# ── Shape ─────────────────────────────────────────────────────────────────


class TestContentStylesShape:
    def test_content_styles_is_dict(self):
        assert isinstance(CONTENT_STYLES, dict)

    def test_content_styles_non_empty(self):
        assert len(CONTENT_STYLES) > 0

    def test_content_styles_has_expected_minimum_count(self):
        # Plan §12 defines 22 tokens; Step 8 added 11 row/header tokens;
        # the Step 12 discretionary additions (Image sub-elements,
        # PathBar.Field, Splitter:hovered/pressed) bring the total
        # above 30. Any regression below 30 signals an accidental drop.
        assert len(CONTENT_STYLES) >= 30, (
            f"CONTENT_STYLES has {len(CONTENT_STYLES)} entries; expected >= 30"
        )

    def test_every_entry_is_dict(self):
        for selector, props in CONTENT_STYLES.items():
            assert isinstance(props, dict), (
                f"{selector!r}: value must be dict, got {type(props).__name__}"
            )


# ── Required keys per plan + existing row tokens ─────────────────────────


class TestRequiredKeys:
    @pytest.mark.parametrize(
        "key",
        [
            # Step 8 row renderer tokens (must not regress)
            "Content.Row.Name",
            "Content.Row.Name::disabled",
            "Content.Row.Size",
            "Content.Row.Size::disabled",
            "Content.Row.Date",
            "Content.Row.Date::disabled",
            "Content.FileIcon",
            "Content.BranchGlyph",
            "Content.ColumnHeader",
            "Content.ColumnHeader.ClickArea",
            "Content.ColumnHeader.ClickArea:hovered",
            "Content.SortArrow",
            # Toolbar
            "Content.ToolBar",
            "Content.ToolBar.Button",
            "Content.ToolBar.Button:hovered",
            "Content.ToolBar.Button:pressed",
            "Content.ToolBar.Button:disabled",
            "Content.ToolBar.Separator",
            # Path bar
            "Content.PathBar",
            "Content.Breadcrumb",
            "Content.Breadcrumb:hovered",
            "Content.Breadcrumb.Separator",
            # Tree view
            "Content.TreeView",
            "Content.TreeView.Header",
            "Content.TreeView.Item",
            "Content.TreeView.Item:selected",
            "Content.TreeView.Item::disabled",
            "Content.TreeView:selected",
            "Content.TreeView.Icon",
            # Card
            "Content.Card",
            "Content.Card:hovered",
            "Content.Card:selected",
            "Content.Card.Label",
            "Content.Card.Label:selected",
            "Content.Card.Label::cut",
            # Status / empty
            "Content.EmptyState",
            "Content.LoadingSpinner",
            # Scroll
            "Content.ScrollingFrame",
            # Splitter
            "Content.Splitter",
            # File picker bar
            "Content.FileBar",
            "Content.FileBar.Field",
        ],
    )
    def test_required_key_present(self, key):
        assert key in CONTENT_STYLES, f"Missing CONTENT_STYLES key: {key!r}"


# ── Selector-naming discipline (style naming rules) ───────────────────


class TestSelectorNaming:
    def test_every_selector_is_content_namespaced(self):
        violations = [k for k in CONTENT_STYLES if not k.startswith("Content.")]
        assert not violations, (
            "All Content Browser selectors must live under the Content.* "
            "namespace per style naming rules Violations: " + repr(violations)
        )

    def test_selectors_are_not_empty(self):
        for key in CONTENT_STYLES:
            assert key.strip() == key, f"Selector has whitespace: {key!r}"
            assert key, "Empty selector found"


# ── No hex literals (style naming rules) ───────────────────────────────────


class TestNoHexLiterals:
    def test_color_values_are_cl_references(self):
        """Every *_color / color value must be a cl.* _ShadeName str."""
        violations = []
        for selector, props in CONTENT_STYLES.items():
            for key, val in props.items():
                if key in _COLOR_KEYS:
                    if not isinstance(val, str):
                        violations.append(
                            f"{selector!r}/{key}: expected cl.* str, "
                            f"got {type(val).__name__} {val!r}"
                        )
        assert not violations, (
            "Raw (non-cl.*) colour values found:\n"
            + "\n".join(violations)
        )

    def test_no_raw_argb_integers(self):
        """No style value should be a packed ARGB int (>= 0x80000000)."""
        violations = []
        for selector, props in CONTENT_STYLES.items():
            for key, val in props.items():
                if isinstance(val, int) and val >= 0x80000000:
                    violations.append(
                        f"{selector!r}/{key}: {hex(val)}"
                    )
        assert not violations, (
            "Raw ARGB ints found (must use cl.* shade):\n"
            + "\n".join(violations)
        )

    def test_no_hex_literal_strings(self):
        """No value should be a raw '#RRGGBB' / '#AARRGGBB' string.

        These would bypass the shade store entirely — colour would
        freeze at whichever theme was active when the dict was built.
        """
        violations = []
        for selector, props in CONTENT_STYLES.items():
            for key, val in props.items():
                if isinstance(val, str) and val.startswith("#"):
                    violations.append(f"{selector!r}/{key}: {val!r}")
        assert not violations, (
            "Raw hex-literal strings found:\n" + "\n".join(violations)
        )


# ── apply_global_styles merge ─────────────────────────────────────────────


class TestApplyGlobalStylesMerge:
    def test_apply_global_styles_includes_content_styles(self):
        """Merged ui.style.default contains Content.* selectors."""
        import ovwidgets.app
        import ovwidgets.app.style

        ovwidgets.app.style.apply_global_styles()
        result = ui.style.default
        assert isinstance(result, dict)

        for key in (
            "Content.TreeView",
            "Content.Card",
            "Content.ToolBar",
            "Content.PathBar",
            "Content.Row.Name",
        ):
            assert key in result, (
                f"ui.style.default missing {key!r} after "
                "apply_global_styles() — CONTENT_STYLES not merged in"
            )

    def test_apply_global_styles_resolves_content_colors(self):
        """A Content.* colour resolves to a concrete int (not the raw
        cl.* string) once merged into ui.style.default."""
        import ovwidgets.app.style

        ovwidgets.app.style.apply_global_styles()
        result = ui.style.default
        tree = result.get("Content.TreeView", {})
        assert "background_color" in tree, (
            "Content.TreeView missing background_color after apply"
        )
        assert isinstance(tree["background_color"], int), (
            "Content.TreeView background_color should resolve to int "
            f"after apply, got {type(tree['background_color']).__name__}"
        )

    def test_apply_global_styles_does_not_overwrite_global(self):
        """Content.* merge must not drop the global Button / Label keys."""
        import ovwidgets.app.style

        ovwidgets.app.style.apply_global_styles()
        result = ui.style.default
        for key in ("Button", "Label", "TreeView"):
            assert key in result, (
                f"Global style {key!r} missing after Content merge"
            )

    def test_theme_switch_updates_content_palette(self):
        """Dark → light theme must change Content.* resolved colour ints."""
        import ovwidgets.app.style

        ovwidgets.app.style.set_theme("dark")
        ovwidgets.app.style.apply_global_styles()
        dark_bg = ui.style.default["Content.TreeView"]["background_color"]

        ovwidgets.app.style.set_theme("light")
        light_bg = ui.style.default["Content.TreeView"]["background_color"]

        assert dark_bg != light_bg, (
            "Content.TreeView background_color did not change between "
            f"dark ({hex(dark_bg)}) and light ({hex(light_bg)}) themes"
        )

        ovwidgets.app.style.set_theme("dark")


# ── Consistency with other domain style modules ──────────────────────────


class TestDomainStyleConsistency:
    def test_content_styles_importable_independently(self):
        """Like STAGE_STYLES / PROPERTY_STYLES, CONTENT_STYLES is an
        attribute of its module (not a function call) so test code can
        introspect it without side effects."""
        from ovwidgets.content import style as content_style_mod

        assert hasattr(content_style_mod, "CONTENT_STYLES")
        assert content_style_mod.CONTENT_STYLES is CONTENT_STYLES
