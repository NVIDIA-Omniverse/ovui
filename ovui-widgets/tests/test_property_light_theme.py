# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Light-theme verification tests for the Property Inspector styles.

These structural guardrails pin the invariants that keep the Property Inspector
working under both shades:

1. ``ovui_widgets.property/style.py``'s ``PROPERTY_STYLES`` contains zero raw hex
   integers or ``cl("#...")`` literals in colour slots. Every Property
   selector references a palette shade name so ``ui.set_shade("light")``
   propagates.

2. Every palette name the ``PROPERTY_STYLES`` dict references is
   registered in :class:`omni.ui.ColorStore` for both the default (dark)
   and the ``"light"`` shade. A missing light variant would freeze the
   Property Inspector at the dark-theme value when the rest of the app
   switched.

3. A representative set of ``cl.*`` names used by the Property Inspector
   actually resolves to *different* integers under ``default`` vs
   ``light``. Catches a palette entry that accidentally set
   ``light=<dark-value>`` (no-op override) — tests #2 would still pass,
   the user would see no visual change, #3 catches it.

Parallel to :class:`tests.test_styles.TestNoRawHex` for the global
``GLOBAL_STYLES`` — Step 8.3 extends the same guarantee to the Property
Inspector's domain styles so Phase-8 polish can't regress into
dark-only hex later.
"""

from __future__ import annotations

import omni.ui as ui
import pytest

# Importing the app's style package runs the palette and constants
# modules whose top-level code populates ColorStore / FloatStore. The
# shade-sensitive lookups below resolve to 0x0 without this side
# effect, so the registration import must happen before any test
# function runs.
import ovui_widgets.app.style  # noqa: F401

_COLOR_KEYS = frozenset(
    {"background_color", "color", "secondary_color", "border_color"}
)


@pytest.fixture(autouse=True)
def restore_shade():
    """Every test restores the default shade on teardown."""
    yield
    ui.set_shade("default")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolved_color(name: str) -> int:
    """Resolve a ``cl.*`` shade-name reference to its current integer."""
    value = ui.ColorStore.find(name)
    assert value is not None, (
        f"ColorStore: palette name {name!r} is not registered — "
        "PROPERTY_STYLES refers to it but it has no shade definition"
    )
    return value


def _iter_color_values():
    """Yield ``(selector, key, value)`` for every colour-typed slot.

    Colour-typed slots are the four keys listed in ``_COLOR_KEYS``
    plus any selector/key pair whose value is a palette-name string
    (shade names register in ``ColorStore`` at import time, so
    ``ColorStore.find`` returns non-None).
    """
    from ovui_widgets.property.style import PROPERTY_STYLES
    for selector, props in PROPERTY_STYLES.items():
        for key, val in props.items():
            if key in _COLOR_KEYS:
                yield selector, key, val


# ---------------------------------------------------------------------------
# #1 — PROPERTY_STYLES holds no raw hex in colour slots
# ---------------------------------------------------------------------------


class TestNoRawHexInPropertyStyles:
    """Every colour-typed value must be a ``cl.*`` palette reference.

    Mirrors :class:`tests.test_styles.TestNoRawHex` for the Property
    Inspector's domain styles. A raw ``int`` would freeze on the value
    it was assigned — ``ui.set_shade("light")`` would have no effect
    and the panel would remain dark-themed even when the rest of the
    application switched.
    """

    def test_all_color_values_are_strings(self):
        """Every colour key holds a palette-name string, not a raw int."""
        violations = []
        for selector, key, val in _iter_color_values():
            if not isinstance(val, str):
                violations.append(
                    f"{selector}/{key}: expected palette-name str, "
                    f"got {type(val).__name__} {val!r}"
                )
        assert not violations, (
            "PROPERTY_STYLES contains raw colour values:\n  "
            + "\n  ".join(violations)
        )

    def test_no_raw_argb_integers(self):
        """Catches any ``int >= 0x80000000`` anywhere in a style dict.

        Complements the per-key check above by scanning *every* value
        in *every* selector (not just the four colour keys). A stray
        ``"border_color": 0xFF202020`` escaped the first check if the
        key name changes; this test catches it regardless of key name.
        """
        from ovui_widgets.property.style import PROPERTY_STYLES
        violations = []
        for selector, props in PROPERTY_STYLES.items():
            for key, val in props.items():
                if isinstance(val, int) and val >= 0x80000000:
                    violations.append(f"{selector}/{key}: {hex(val)}")
        assert not violations, (
            "Raw ARGB integers in PROPERTY_STYLES:\n  "
            + "\n  ".join(violations)
        )


# ---------------------------------------------------------------------------
# #2 — Every referenced palette name has both dark and light shades
# ---------------------------------------------------------------------------


class TestPropertyStylesHaveLightShade:
    """Each palette name used by PROPERTY_STYLES resolves under both shades.

    ``cl.shade(dark, light=..., name=X)`` registers two variants under
    the single name ``X``. If a palette entry were defined as
    ``cl.shade(dark, name=X)`` without a ``light=`` argument the entry
    would fall back to the dark value under ``set_shade("light")``.
    The test asserts *registration*, not distinctness — Step 8.3
    #3 below covers distinctness.
    """

    def test_every_referenced_name_is_registered(self):
        """Every colour slot's shade name resolves in both shades."""
        for shade in ("default", "light"):
            ui.set_shade(shade)
            missing = []
            for selector, key, val in _iter_color_values():
                if not isinstance(val, str):
                    # The raw-hex test catches this path; don't double-report.
                    continue
                if ui.ColorStore.find(val) is None:
                    missing.append(f"{shade}: {selector}/{key} → {val!r}")
            assert not missing, (
                f"Unregistered palette names in {shade} shade:\n  "
                + "\n  ".join(missing)
            )


# ---------------------------------------------------------------------------
# #3 — Representative tokens actually differ between shades
# ---------------------------------------------------------------------------


# Palette names the Property Inspector relies on that are expected to
# carry visually distinct dark vs light variants. What this list catches
# specifically is: a palette name currently registered with a
# ``light=<same>`` (no-op override) that would escape #2 because it's
# registered but would make the light theme illegible.
_PROPERTY_SHADE_SENSITIVE_TOKENS = [
    "background_secondary",  # Property.GroupFrame.background_color
    "background_tertiary",   # Property.GroupFrame:hovered.secondary_color
    "text_primary",          # Property.GroupFrame.color
    "text_secondary",        # Property.LabelColumn.color, ::inner color
    "text_disabled",         # Property.LabelColumn::ambiguous color
    "background_field",      # Property.SearchField.background_color
    "border_default",        # Property.ComponentSeparator.background_color
    "background_primary",    # Property.GroupFrame.background_color
]


@pytest.mark.parametrize("name", _PROPERTY_SHADE_SENSITIVE_TOKENS)
def test_token_differs_between_shades(name):
    """Each listed shade-sensitive token resolves to distinct dark/light.

    If this fails, either the palette entry was defined without a
    ``light=`` argument (caught by #2) or with ``light=<dark-value>``
    (no-op override, caught only here).
    """
    ui.set_shade("default")
    dark = _resolved_color(name)
    ui.set_shade("light")
    light = _resolved_color(name)
    assert dark != light, (
        f"Palette {name!r} has identical dark and light shades: "
        f"{hex(dark)} — a visible regression in the Property Inspector."
    )


def test_property_scroll_uses_step19_scrollbar_tokens():
    from ovui_widgets.property.style import PROPERTY_STYLES

    entry = PROPERTY_STYLES["Property.Scroll"]
    assert entry["background_color"] == "scrollbar_track"
    assert entry["secondary_color"] == "scrollbar_thumb"
    assert entry["scrollbar_size"] == "scrollbar_width"
    assert entry["border_radius"] == "radius_small"


def test_property_scroll_hover_uses_hover_thumb():
    from ovui_widgets.property.style import PROPERTY_STYLES

    assert (
        PROPERTY_STYLES["Property.Scroll:hovered"]["secondary_color"]
        == "scrollbar_thumb_hovered"
    )
    assert (
        PROPERTY_STYLES["Property.Scroll:pressed"]["secondary_color"]
        == "scrollbar_thumb_hovered"
    )


# ---------------------------------------------------------------------------
# #4 — ui.style.default propagates PROPERTY_STYLES when set_theme flips
# ---------------------------------------------------------------------------


class TestThemeSwitchPropagatesToStyleDefault:
    """:func:`ovui_widgets.app.style.set_theme` re-resolves PROPERTY_STYLES on shade switch.

    The Application wires ``_on_theme_changed`` → ``set_theme`` →
    ``apply_global_styles`` (see ``ovui_widgets.app/style/__init__.py`` —
    ``set_theme`` calls ``apply_global_styles`` internally). This test
    exercises the same chain and asserts that a Property selector
    resolves to a *different* integer after switching to light.
    """

    def test_property_group_frame_background_differs_after_light_switch(self):
        from ovui_widgets.app.style import set_theme

        set_theme("dark")
        dark_bg = ui.style.default["Property.GroupFrame"]["background_color"]

        set_theme("light")
        light_bg = ui.style.default["Property.GroupFrame"]["background_color"]

        assert isinstance(dark_bg, int) and isinstance(light_bg, int), (
            "ui.style.default values should resolve to ints, got "
            f"{type(dark_bg).__name__} / {type(light_bg).__name__}"
        )
        assert dark_bg != light_bg, (
            "Property.GroupFrame.background_color did not switch between "
            f"dark ({hex(dark_bg)}) and light ({hex(light_bg)})"
        )

        set_theme("dark")

    def test_property_label_column_color_differs_after_light_switch(self):
        from ovui_widgets.app.style import set_theme

        set_theme("dark")
        dark_color = ui.style.default["Property.LabelColumn"]["color"]

        set_theme("light")
        light_color = ui.style.default["Property.LabelColumn"]["color"]

        assert dark_color != light_color, (
            "Property.LabelColumn.color did not switch between "
            f"dark ({hex(dark_color)}) and light ({hex(light_color)})"
        )

        set_theme("dark")
