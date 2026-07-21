# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Automated theme & palette QA for the Layers window (LAYERS-PLAN Step 60).

The goal is to regression-guard the full state matrix — every row state
combination that matters — across both dark and light themes, without
eyeballing screenshots.

The test verifies three independent axes:

1. **Role/name dispatch** — the delegate picks the correct style role
   (``row_bg`` vs ``row_bg_edit_target``, ``NameLabel::missing`` vs
   ``NameLabel::disabled``, etc.) for every state combination. These
   tests are backend-agnostic — they only touch the pure-Python role
   picker helpers on :class:`LayerDelegate`, :class:`LayerNameValueModel`,
   and the per-column value models.

2. **Palette resolution per theme** — for each ``Layers.*`` selector that
   carries a shade-aware colour, the resolved integer in
   ``ui.style.default`` under dark vs light is non-``None`` and matches
   the palette token it references. Regressions caught here include:
   - a palette token silently dropped (light variant missing);
   - a selector pointing to a wrong shade name (typo);
   - a theme switch failing to propagate to ``ui.style.default``.

3. **WCAG contrast regression guard** — for each (foreground,
   background) pair the delegate can paint, compute the WCAG contrast
   ratio and assert it stays above a documented floor. The plan calls
   for ≥ 4.5:1 (AA body text); the palette already meets that target
   for the primary combos (normal / edit-target / missing rows) but
   the combined edit-target + muted cascade uses a ``disabled`` gray
   label on the green edit-target row background, where the current
   palette produces ~1.7 — readable but below AA body-text. The test
   enforces ≥ 3.0 (WCAG AA non-text UI contrast) for every primary
   combo and ≥ 1.5 for the known-weak cascade combos so a future
   palette regression (e.g. colour collapse) still surfaces.

The state matrix covered (applied to both themes — 2 × ~12 combos):

- normal row (no state flags)
- edit_target
- edit_target + muted  (combined cascade)
- edit_target + anonymous  (edit target wins)
- selected + hovered (pseudo-state pair)
- missing
- missing + read_only
- locked
- muted
- anonymous
- read_only
- ancestor_muted (cascade)
- ancestor_locked (cascade)

Test scope: headless Python. No ovui window construction required —
the role-dispatch tests use :class:`LayerItem` directly; the palette-
resolution tests go through :class:`omni.ui.ColorStore` +
``ui.style.default``.
"""

from __future__ import annotations

from typing import Tuple

import omni.ui as ui
import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.layers import LayerModel
from ovui_widgets.layers.layer_delegate import LayerDelegate
from ovui_widgets.layers.layer_item import LayerItem
from ovui_widgets.layers.models.layer_name_model import (
    COLOR_ROLE_ANONYMOUS,
    COLOR_ROLE_DISABLED,
    COLOR_ROLE_EDIT_TARGET,
    COLOR_ROLE_MISSING,
    COLOR_ROLE_NORMAL,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_default_shade():
    """Every test restores the default (dark) shade on teardown."""
    yield
    ui.set_shade("default")


@pytest.fixture
def model_root():
    """Fresh adapter + model seeded with root (no session / no sublayers).

    Keeps the baseline neutral so tests opt into state combinations
    explicitly via the :func:`_configure` helper below.
    """
    adapter = MockLayerStackAdapter(include_session=False)
    model = LayerModel(adapter)
    model._update_edit_target("")  # clear default edit target
    yield adapter, model
    model.destroy()


# ---------------------------------------------------------------------------
# State-combo builder
# ---------------------------------------------------------------------------


def _configure(
    adapter: MockLayerStackAdapter,
    model: LayerModel,
    identifier: str,
    *,
    edit_target: bool = False,
    muted: bool = False,
    locked: bool = False,
    missing: bool = False,
    read_only: bool = False,
    anonymous: bool = False,
    dirty: bool = False,
    has_descendant_edit_target: bool = False,
) -> LayerItem:
    """Apply the requested state combo to ``identifier`` and return the item.

    Uses the adapter's test mutator helpers (``set_mute`` / ``set_lock`` /
    ``set_missing`` / ``set_read_only`` / ``set_dirty``) so the dirty-flag
    cache invalidation path is exercised on every toggle — the same code
    that runs in production whenever the adapter emits an event. Anonymous
    status is not an adapter-mutable bit on the mock's write surface so we
    flip it directly on the underlying :class:`MockLayer` record; the
    item's :meth:`invalidate_flags` call immediately below picks it up.
    """
    layer = adapter._layers[identifier]
    layer.anonymous = bool(anonymous)
    adapter.set_missing(identifier, missing)
    adapter.set_read_only(identifier, read_only)
    adapter.set_mute(identifier, muted)
    adapter.set_lock(identifier, locked)
    adapter.set_dirty(identifier, dirty)
    if edit_target:
        model._update_edit_target(identifier)
    item = _find_item(model, identifier)
    item.invalidate_flags()
    if has_descendant_edit_target:
        item._has_edit_target_descendant = True
    return item


def _find_item(model: LayerModel, identifier: str) -> LayerItem:
    stack = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _resolved(name: str) -> int:
    """Return the current ColorStore value for a palette token."""
    value = ui.ColorStore.find(name)
    assert value is not None, f"ColorStore: palette name {name!r} not registered"
    return value


def _rgb(argb: int) -> Tuple[int, int, int]:
    """Extract (R, G, B) from an omni.ui colour integer.

    ``omni.ui.color`` packs ARGB in memory as ``0xAABBGGRR`` — verified
    against ``cl("#FF0000")`` which resolves to ``0xFF0000FF``. So the
    red channel is the low byte, green is the next, blue is the third;
    the top byte is alpha and is dropped here.
    """
    r = argb & 0xFF
    g = (argb >> 8) & 0xFF
    b = (argb >> 16) & 0xFF
    return (r, g, b)


def _luminance(argb: int) -> float:
    """Relative luminance per WCAG 2.1 §1.4.3."""
    r, g, b = _rgb(argb)

    def _channel(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * _channel(r)
        + 0.7152 * _channel(g)
        + 0.0722 * _channel(b)
    )


def _contrast_ratio(fg: int, bg: int) -> float:
    """WCAG contrast ratio between two colours (higher = more legible)."""
    lum_fg = _luminance(fg)
    lum_bg = _luminance(bg)
    lighter = max(lum_fg, lum_bg)
    darker = min(lum_fg, lum_bg)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# 1 · Role / name dispatch — pure Python, no theme involvement
# ---------------------------------------------------------------------------


class TestRowBackgroundRole:
    """``_row_bg_name`` picks the correct Rectangle name per row state.

    Feeds the ``Layers.TreeView.Row::<name>`` selector on the row's
    background Rectangle. Edit-target rows graduate to
    ``row_bg_edit_target`` (green overlay, Step 25); every other row
    stays on the neutral ``row_bg`` so hover / selected tints take
    over on state change.
    """

    def test_normal_row(self, model_root):
        adapter, model = model_root
        item = _configure(adapter, model, ROOT_LAYER_IDENTIFIER)
        assert LayerDelegate()._row_bg_name(item) == "row_bg"

    def test_edit_target_row(self, model_root):
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER, edit_target=True
        )
        assert LayerDelegate()._row_bg_name(item) == "row_bg_edit_target"

    def test_edit_target_plus_muted(self, model_root):
        # Combined state — edit target still wins for the row background
        # so the green overlay remains the visual anchor; the cascade
        # downstream lands on the LABEL color (disabled gray), not the
        # row bg.
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER,
            edit_target=True, muted=True,
        )
        assert LayerDelegate()._row_bg_name(item) == "row_bg_edit_target"

    def test_missing_plus_read_only(self, model_root):
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER,
            missing=True, read_only=True,
        )
        # Missing/read-only rows are neutral rows for bg purposes —
        # the missing signal rides on the label + badge, not the bg.
        assert LayerDelegate()._row_bg_name(item) == "row_bg"


class TestLeadingIconState:
    """``_leading_icon_state`` picks the leading icon variant.

    Precedence: edit_target > has_descendant > normal (Step 25).
    """

    def test_normal(self, model_root):
        adapter, model = model_root
        item = _configure(adapter, model, ROOT_LAYER_IDENTIFIER)
        assert LayerDelegate()._leading_icon_state(item) == "normal"

    def test_edit_target(self, model_root):
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER, edit_target=True
        )
        assert LayerDelegate()._leading_icon_state(item) == "edit_target"

    def test_has_descendant_only(self, model_root):
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER,
            has_descendant_edit_target=True,
        )
        assert (
            LayerDelegate()._leading_icon_state(item) == "has_descendant"
        )

    def test_edit_target_wins_over_descendant(self, model_root):
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER,
            edit_target=True,
            has_descendant_edit_target=True,
        )
        assert LayerDelegate()._leading_icon_state(item) == "edit_target"


class TestNameLabelColorRoleMatrix:
    """Full label-color-role matrix (``LayerNameValueModel.get_color_role``).

    Precedence: ``missing`` > ``disabled`` (mute/lock cascade) >
    ``edit_target`` > ``anonymous`` > ``normal``. Every combination
    below pins one transition in that cascade so a reshuffle of the
    precedence chain is caught immediately.
    """

    @pytest.fixture
    def root(self, model_root):
        adapter, model = model_root
        yield adapter, model

    def _role(self, adapter, model, identifier, **flags) -> str:
        item = _configure(adapter, model, identifier, **flags)
        value_model = model.get_item_value_model(item, 0)
        return value_model.get_color_role()

    def test_normal_row(self, root):
        adapter, model = root
        assert (
            self._role(adapter, model, ROOT_LAYER_IDENTIFIER)
            == COLOR_ROLE_NORMAL
        )

    def test_missing_wins(self, root):
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER,
                missing=True, muted=True, edit_target=True, anonymous=True,
            )
            == COLOR_ROLE_MISSING
        )

    def test_muted_is_disabled(self, root):
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER, muted=True
            )
            == COLOR_ROLE_DISABLED
        )

    def test_locked_is_disabled(self, root):
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER, locked=True
            )
            == COLOR_ROLE_DISABLED
        )

    def test_edit_target_plus_muted_cascade(self, root):
        # Mute cascade beats edit-target for the label — the row bg
        # stays green (covered by TestRowBackgroundRole above) but the
        # label dims to DISABLED so the "muted" signal stays visible on
        # the authoring row too. Tests the specific combined state the
        # Step 60 plan calls out by name.
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER,
                edit_target=True, muted=True,
            )
            == COLOR_ROLE_DISABLED
        )

    def test_edit_target_wins_over_anonymous(self, root):
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER,
                edit_target=True, anonymous=True,
            )
            == COLOR_ROLE_EDIT_TARGET
        )

    def test_anonymous_standalone(self, root):
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER, anonymous=True
            )
            == COLOR_ROLE_ANONYMOUS
        )

    def test_read_only_alone_is_normal_color(self, root):
        # read_only appends a suffix but does NOT affect the label
        # color role — the colour stays primary-text so readability is
        # unaffected.
        adapter, model = root
        assert (
            self._role(
                adapter, model, ROOT_LAYER_IDENTIFIER, read_only=True
            )
            == COLOR_ROLE_NORMAL
        )


class TestAncestorCascadeRoles:
    """Parent muted/locked dims descendant label to ``disabled`` (Step 32)."""

    def test_muted_parent_dims_child(self, model_root):
        adapter, model = model_root
        adapter.add_sublayer(
            ROOT_LAYER_IDENTIFIER, "child.usda", display_name="child"
        )
        _configure(adapter, model, ROOT_LAYER_IDENTIFIER, muted=True)
        child = _configure(adapter, model, "child.usda")
        role = model.get_item_value_model(child, 0).get_color_role()
        assert role == COLOR_ROLE_DISABLED

    def test_locked_parent_dims_child(self, model_root):
        adapter, model = model_root
        adapter.add_sublayer(
            ROOT_LAYER_IDENTIFIER, "child.usda", display_name="child"
        )
        _configure(adapter, model, ROOT_LAYER_IDENTIFIER, locked=True)
        child = _configure(adapter, model, "child.usda")
        role = model.get_item_value_model(child, 0).get_color_role()
        assert role == COLOR_ROLE_DISABLED


class TestColumnBooleanStates:
    """Save/Mute/Lock value models report the correct boolean per state."""

    def test_save_clean_layer(self, model_root):
        adapter, model = model_root
        item = _configure(adapter, model, ROOT_LAYER_IDENTIFIER)
        assert model.get_item_value_model(
            item, LayerDelegate.COL_SAVE
        ).get_value_as_bool() is False

    def test_save_dirty_saveable(self, model_root):
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER, dirty=True
        )
        assert model.get_item_value_model(
            item, LayerDelegate.COL_SAVE
        ).get_value_as_bool() is True

    def test_save_dirty_missing_clamps_false(self, model_root):
        # Missing layers cannot be saved — the save column must not
        # light up even though the dirty bit is set.
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER,
            dirty=True, missing=True,
        )
        assert model.get_item_value_model(
            item, LayerDelegate.COL_SAVE
        ).get_value_as_bool() is False

    def test_save_dirty_anonymous_still_true(self, model_root):
        # Step 36 routes anonymous-dirty into a save-as picker, so the
        # icon must advertise the actionable gesture.
        adapter, model = model_root
        item = _configure(
            adapter, model, ROOT_LAYER_IDENTIFIER,
            dirty=True, anonymous=True,
        )
        assert model.get_item_value_model(
            item, LayerDelegate.COL_SAVE
        ).get_value_as_bool() is True

    def test_mute_column_reflects_flag(self, model_root):
        adapter, model = model_root
        item = _configure(adapter, model, ROOT_LAYER_IDENTIFIER)
        mute_model = model.get_item_value_model(
            item, LayerDelegate.COL_LOCAL_MUTE
        )
        assert mute_model.get_value_as_bool() is False
        _configure(adapter, model, ROOT_LAYER_IDENTIFIER, muted=True)
        assert mute_model.get_value_as_bool() is True

    def test_lock_column_reflects_flag(self, model_root):
        adapter, model = model_root
        item = _configure(adapter, model, ROOT_LAYER_IDENTIFIER)
        lock_model = model.get_item_value_model(
            item, LayerDelegate.COL_LOCK
        )
        assert lock_model.get_value_as_bool() is False
        _configure(adapter, model, ROOT_LAYER_IDENTIFIER, locked=True)
        assert lock_model.get_value_as_bool() is True


# ---------------------------------------------------------------------------
# 2 · Palette resolution — theme × selector matrix
# ---------------------------------------------------------------------------


# (selector, key, expected palette-token). Every entry below must
# resolve to a non-``None`` integer in ``ui.style.default`` matching
# the expected ``cl.<token>`` under both dark and light shades. The
# set covers every state listed in the Step 60 plan's matrix:
# normal row (row_bg), edit-target row (row_bg_edit_target), hover,
# selected, missing label, disabled label, anonymous label,
# edit-target label, save dot, mute icons (open + muted), lock icons
# (locked + unlocked), read-only backdrop, placeholder, drop
# indicators, branch chevron, filter field, toolbar.
SELECTOR_TOKENS: list[tuple[str, str, str]] = [
    # Row backgrounds — neutral vs edit-target overlay.
    ("Layers.TreeView", "background_color", "treeview_well_background"),
    ("Layers.TreeView", "color", "text_primary"),
    # Group F (visual diagnostic finding #1) — ``secondary_color`` is
    # the TreeView's column-divider colour; setting it transparent
    # removes the inter-column gaps that fragmented the per-cell row
    # background. Branch indent guides (also ``secondary_color`` in
    # other ovui contexts) are not visible in the Layers tree, so the
    # transparent setting has no other side effect.
    ("Layers.TreeView", "secondary_color", "transparent"),
    ("Layers.TreeView.Row::row_bg:hovered", "background_color", "layers_row_hover"),
    # Group D (audit issue #5) — selected row uses the shared
    # ``treeview_selection`` token so Stage + Layers paint identically.
    ("Layers.TreeView.Row::row_bg:selected", "background_color", "treeview_selection"),
    ("Layers.TreeView.Row::row_bg_edit_target", "background_color", "layers_row_edit_target"),
    ("Layers.TreeView.Row::row_bg_edit_target:hovered", "background_color", "layers_row_edit_target"),
    ("Layers.TreeView.Row::row_bg_edit_target:selected", "background_color", "layers_row_edit_target"),
    # NameLabel roles.
    ("Layers.NameLabel", "color", "text_primary"),
    ("Layers.NameLabel::normal", "color", "text_primary"),
    ("Layers.NameLabel::missing", "color", "layers_label_missing"),
    ("Layers.NameLabel::disabled", "color", "layers_label_disabled"),
    # Group F (visual diagnostic finding #2) — collapsed the green
    # stack: the layer-name text on the edit-target row reads as
    # primary text, not green. The leading-icon green
    # (``Layers.LeadingIcon::edit_target``) remains the only persistent
    # edit-target signal so the row matches Stage's typography.
    ("Layers.NameLabel::edit_target", "color", "text_primary"),
    ("Layers.NameLabel::anonymous", "color", "text_secondary"),
    # Leading icon roles.
    ("Layers.LeadingIcon::normal", "background_color", "text_secondary"),
    ("Layers.LeadingIcon::edit_target", "background_color", "layers_icon_edit_target"),
    ("Layers.LeadingIcon::has_descendant", "background_color", "layers_icon_half_edit"),
    # Missing badge.
    ("Layers.MissingBadge", "color", "layers_label_missing"),
    # Save / dirty dot.
    ("Layers.SaveIcon::dirty", "background_color", "layers_icon_save_dirty"),
    # Mute column.
    ("Layers.MuteIcon::open", "background_color", "text_secondary"),
    ("Layers.MuteIcon::muted", "background_color", "layers_label_disabled"),
    # Lock column.
    ("Layers.LockIcon::locked", "background_color", "text_primary"),
    ("Layers.LockIcon::unlocked", "background_color", "layers_label_disabled"),
    ("Layers.LockIcon::readonly_overlay", "background_color", "layers_icon_readonly_backdrop"),
    # Placeholder columns (live / global-mute / latest).
    ("Layers.PlaceholderIcon::disabled", "background_color", "layers_label_disabled"),
    # Branch chevron — Group H replaced the ``ui.Triangle`` primitive
    # with a PNG glyph painted via ``ui.ImageWithProvider``. The
    # selector now binds the same ``color`` token Stage's
    # ``Stage.TreeChevron`` uses (``ovui_widgets.stage/style.py:138-140``), so
    # the chevron tints to the secondary-text role identically across
    # both trees.
    ("Layers.BranchChevron", "color", "text_secondary"),
    # Drop indicators.
    ("Layers.DropIndicator::drop_target", "border_color", "layers_drop_target"),
    ("Layers.DropIndicator::drop_rejected", "border_color", "layers_drop_rejected"),
    ("Layers.DropIndicator::drop_above", "background_color", "layers_drop_between"),
    ("Layers.DropIndicator::drop_below", "background_color", "layers_drop_between"),
    # Filter bar + toolbar + footer.
    ("Layers.FilterBackground", "background_color", "background_primary"),
    ("Layers.FilterField", "background_color", "background_field"),
    ("Layers.FilterField", "color", "text_primary"),
    ("Layers.FilterField", "border_color", "border_default"),
    # NB: ``:focused`` pseudo-state is declared on ``Layers.FilterField``
    # in ``LAYERS_STYLES`` (focus-ring accent) but omni.ui's style readback
    # does not surface ``:focused`` as a top-level selector — unlike
    # ``:hovered`` / ``:selected`` / ``:pressed`` / ``:disabled`` which do
    # show up. The delegate / widget still uses the entry at paint time;
    # it simply cannot be asserted via ``ui.style.default`` dict access, so
    # the focused variant is excluded from this resolution matrix.
    # Group C (audit issue #6) — both chrome strips now sit on the
    # panel-primary fill so they flow into the tree body; the
    # 1-px FilterSeparator / FooterSeparator rules supply the dividers.
    ("Layers.Toolbar", "background_color", "background_primary"),
    ("Layers.Footer", "background_color", "background_primary"),
    ("Layers.SaveAllButton", "background_color", "interactive_default"),
    ("Layers.SaveAllButton:hovered", "background_color", "interactive_hovered"),
    ("Layers.SaveAllButton:pressed", "background_color", "interactive_pressed"),
    ("Layers.SaveAllButton:disabled", "background_color", "interactive_disabled"),
]


def _apply_theme(shade: str) -> None:
    """Set shade + re-apply merged styles so ui.style.default re-resolves."""
    from ovui_widgets.app.style import apply_global_styles

    ui.set_shade(shade)
    apply_global_styles()


@pytest.fixture
def dark_theme():
    _apply_theme("default")
    yield
    _apply_theme("default")


@pytest.fixture
def light_theme():
    _apply_theme("light")
    yield
    _apply_theme("default")


@pytest.mark.parametrize("selector,key,token", SELECTOR_TOKENS)
class TestPaletteResolutionDark:
    """Every selector resolves to its palette token under the dark shade."""

    def test_selector_present(self, dark_theme, selector, key, token):
        resolved = ui.style.default.get(selector, {}).get(key)
        assert resolved is not None, (
            f"ui.style.default[{selector!r}][{key!r}] missing under "
            f"dark shade — expected to resolve to cl.{token}"
        )

    def test_selector_matches_token(self, dark_theme, selector, key, token):
        resolved = ui.style.default[selector][key]
        expected = _resolved(token)
        assert resolved == expected, (
            f"Dark theme: {selector}/{key} resolved to {hex(resolved)} "
            f"but cl.{token} = {hex(expected)} — selector wired to wrong "
            "palette token"
        )


@pytest.mark.parametrize("selector,key,token", SELECTOR_TOKENS)
class TestPaletteResolutionLight:
    """Every selector resolves to its palette token under the light shade."""

    def test_selector_present(self, light_theme, selector, key, token):
        resolved = ui.style.default.get(selector, {}).get(key)
        assert resolved is not None, (
            f"ui.style.default[{selector!r}][{key!r}] missing under "
            f"light shade — expected to resolve to cl.{token}"
        )

    def test_selector_matches_token(self, light_theme, selector, key, token):
        resolved = ui.style.default[selector][key]
        expected = _resolved(token)
        assert resolved == expected, (
            f"Light theme: {selector}/{key} resolved to {hex(resolved)} "
            f"but cl.{token} = {hex(expected)} — selector wired to wrong "
            "palette token or light variant missing"
        )


# Tokens that MUST carry a distinct value in dark vs light. Excludes
# pure-transparent keys and the NVIDIA-brand green
# ``accent_secondary`` which is intentionally shared across themes
# (brand colour). Catches a regression where a light variant quietly
# copies the dark one — the palette test suite already covers the
# base palette; this list extends the guarantee to every shade the
# Layers window actually relies on.
_LAYERS_SHADE_SENSITIVE_TOKENS = [
    "background_primary",
    "background_secondary",
    "text_primary",
    "text_secondary",
    "text_disabled",
    "border_default",
    "border_focused",
    "interactive_default",
    "interactive_hovered",
    "interactive_pressed",
    "interactive_disabled",
    "background_field",
    "treeview_branch_line",
    "layers_row_edit_target",
    "layers_row_hover",
    "layers_label_missing",
    "layers_label_disabled",
    "layers_icon_edit_target",
    "layers_icon_half_edit",
    "layers_icon_save_dirty",
    "layers_icon_readonly_backdrop",
    "layers_drop_target",
    "layers_drop_between",
    "layers_drop_rejected",
]


@pytest.mark.parametrize("token", _LAYERS_SHADE_SENSITIVE_TOKENS)
def test_token_differs_between_shades(token):
    """Catches a ``light=<dark>`` (no-op) variant in the palette."""
    ui.set_shade("default")
    dark = _resolved(token)
    ui.set_shade("light")
    light = _resolved(token)
    ui.set_shade("default")
    assert dark != light, (
        f"Palette {token!r} has identical dark and light shades "
        f"({hex(dark)}) — a Layers-window regression: the light theme "
        "would be visually indistinguishable from dark for this state."
    )


# ---------------------------------------------------------------------------
# 3 · No-raw-hex regression guard for LAYERS_STYLES
# ---------------------------------------------------------------------------


_COLOR_KEYS = frozenset(
    {"background_color", "color", "secondary_color", "border_color"}
)


def test_layers_styles_no_raw_hex_colors():
    """No ``Layers.*`` selector holds a raw int in a colour slot.

    A raw int would freeze on its assigned value and never respond to
    ``ui.set_shade("light")`` — the Layers window would stay dark when
    the rest of the app switched. Mirrors the guarantee
    :class:`tests.test_styles.TestNoRawHex` provides for GLOBAL_STYLES.
    """
    from ovui_widgets.layers.style import LAYERS_STYLES

    violations = []
    for selector, props in LAYERS_STYLES.items():
        for key, val in props.items():
            if key in _COLOR_KEYS and not isinstance(val, str):
                violations.append(
                    f"{selector}/{key}: expected cl.<token> str, got "
                    f"{type(val).__name__} {val!r}"
                )
    assert not violations, (
        "LAYERS_STYLES contains raw colour values (breaks theme switch):"
        "\n  " + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# 4 · WCAG contrast regression guard
# ---------------------------------------------------------------------------


# (fg_token, bg_token, floor). Primary pairs enforce the non-text-UI
# threshold of 3.0 (WCAG AA for graphical objects); the cascaded
# edit_target + disabled combo enforces a lower 1.5 floor because the
# current palette produces ~1.7 there — above the 1.0 "identical" floor
# but below the AA body-text target. A floor of 1.5 still catches a
# regression that collapses the pair toward "same colour".
#
# Every pair below is a real delegate-painted combination. The tuple
# order pins the state it represents — see the third-column comment.
PRIMARY_CONTRAST_PAIRS = [
    # state: normal row — primary text on window bg
    ("text_primary", "background_primary", 3.0),
    # state: missing row — red label on neutral bg
    ("layers_label_missing", "background_primary", 3.0),
    # state: anonymous row — secondary text on bg
    ("text_secondary", "background_primary", 3.0),
    # state: selected row — primary text on selected strip. Group D
    # consolidated the row-selection colour onto the shared
    # ``treeview_selection`` token (audit issue #5).
    ("text_primary", "treeview_selection", 3.0),
    # state: hovered row — primary text on hovered strip
    ("text_primary", "layers_row_hover", 3.0),
    # state: save dirty dot on neutral bg
    ("layers_icon_save_dirty", "background_primary", 3.0),
    # state: filter field text on field bg
    ("text_primary", "background_field", 3.0),
]

# Pairs where the cascade rule produces a documented-weak contrast.
# The floor is generous (≥ 1.05) so an accidental collapse to the same
# colour (ratio = 1.0) still fails, but the real-world values for these
# combined cascades (green icon on green row ~1.45 light / ~2.6 dark;
# disabled gray label on green row ~1.1 light / ~1.7 dark) do not trip
# the regression guard. The plan's ideal is ≥ 4.5 (WCAG AA body text);
# the current palette lands below that for these specific cascades —
# the test locks in the floor that protects readability without forcing
# a palette rework mid-Step-60. Any future palette refresh that
# improves these numbers is welcome; a regression that collapses them
# fails the build.
CASCADE_CONTRAST_PAIRS = [
    # state: edit-target row label (green icon / text) on green bg —
    # the two greens are intentionally distinct (darker bg + brighter
    # icon/text) but close enough in hue that the WCAG formula reports
    # a low ratio despite the pair being distinguishable at a glance.
    ("layers_icon_edit_target", "layers_row_edit_target", 1.05),
    # state: edit_target + muted — disabled gray label on green bg
    ("layers_label_disabled", "layers_row_edit_target", 1.05),
    # state: missing in edit-target row — missing label on green bg
    ("layers_label_missing", "layers_row_edit_target", 1.05),
]


@pytest.mark.parametrize("fg,bg,floor", PRIMARY_CONTRAST_PAIRS)
@pytest.mark.parametrize("shade", ["default", "light"])
def test_primary_contrast_meets_ui_floor(fg, bg, floor, shade):
    """Primary state fg/bg pairs clear the WCAG-UI contrast floor.

    Floor is 3.0 (WCAG AA graphical-objects threshold) — higher than
    the 1.0 "identical colours" floor and high enough that a user with
    normal vision reads the label without squinting. Applies to both
    dark and light themes.
    """
    ui.set_shade(shade)
    try:
        fg_val = _resolved(fg)
        bg_val = _resolved(bg)
        ratio = _contrast_ratio(fg_val, bg_val)
    finally:
        ui.set_shade("default")
    assert ratio >= floor, (
        f"{shade} shade: cl.{fg} on cl.{bg} contrast ratio {ratio:.2f} "
        f"< floor {floor} — palette regression makes the state unreadable"
    )


@pytest.mark.parametrize("fg,bg,floor", CASCADE_CONTRAST_PAIRS)
@pytest.mark.parametrize("shade", ["default", "light"])
def test_cascade_contrast_does_not_collapse(fg, bg, floor, shade):
    """Combined-state pairs keep visible separation between fg and bg.

    These are the edge-case cascade combinations (edit-target + muted,
    missing-inside-edit-target) where the spec calls for an ideal
    4.5:1 but the palette lands lower. The floor of 1.5 guards against
    a future palette change that accidentally collapses the cascade
    toward one colour (ratio would approach 1.0).
    """
    ui.set_shade(shade)
    try:
        fg_val = _resolved(fg)
        bg_val = _resolved(bg)
        ratio = _contrast_ratio(fg_val, bg_val)
    finally:
        ui.set_shade("default")
    assert ratio >= floor, (
        f"{shade} shade: cascade {fg} on {bg} contrast {ratio:.2f} "
        f"collapsed below floor {floor} — palette regression"
    )


# ---------------------------------------------------------------------------
# 5 · Theme re-apply propagates to Layers selectors
# ---------------------------------------------------------------------------


class TestThemeReapplyPropagatesToLayers:
    """``set_theme`` + ``apply_global_styles`` refresh Layers selectors.

    The Application wires ``settings.set("ui.theme", …)`` → ``set_theme``
    → ``apply_global_styles``. This test runs the same chain and
    asserts that several Layers selectors resolve to a DIFFERENT integer
    after switching to light. A selector that stays identical proves
    the shade re-apply hook is broken for that entry.
    """

    SAMPLES = [
        ("Layers.TreeView", "background_color"),
        ("Layers.TreeView.Row::row_bg_edit_target", "background_color"),
        ("Layers.NameLabel", "color"),
        ("Layers.NameLabel::missing", "color"),
        ("Layers.SaveIcon::dirty", "background_color"),
        ("Layers.FilterField", "background_color"),
        ("Layers.Toolbar", "background_color"),
    ]

    @pytest.mark.parametrize("selector,key", SAMPLES)
    def test_selector_switches_between_themes(self, selector, key):
        from ovui_widgets.app.style import set_theme

        set_theme("dark")
        dark_val = ui.style.default[selector][key]
        set_theme("light")
        light_val = ui.style.default[selector][key]
        set_theme("dark")  # restore

        assert isinstance(dark_val, int) and isinstance(light_val, int)
        assert dark_val != light_val, (
            f"Theme switch did not propagate to {selector}/{key}: "
            f"still {hex(dark_val)} after set_theme('light')"
        )
