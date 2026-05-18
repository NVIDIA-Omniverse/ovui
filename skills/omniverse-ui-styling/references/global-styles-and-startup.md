# Global Styles and Startup

Read this when authoring `styles.py` (the global style dictionary) or `startup.py` (the assignment to `ui.style.default` and theme subscription).

## styles.py: the global style dictionary

`styles.py` exposes `GLOBAL_STYLES`, the dictionary the application assigns to `ui.style.default`. It imports `palette`, `constants`, and `urls` so every constant it references is defined before lookup.

`GLOBAL_STYLES` covers every standard widget type and every relevant state. A widget that uses no `style_type_name_override` and no `name` reads its style entirely from this dictionary.

```python
"""Global styles for ovui surfaces."""
from omni.ui import color as cl
from omni.ui import constant as fl

from . import palette    # noqa: F401  — registers cl.* constants
from . import constants  # noqa: F401  — registers fl.* constants
from . import urls       # noqa: F401  — registers url.* constants

GLOBAL_STYLES = {
    # =====================================================================
    # Button
    # =====================================================================
    "Button": {
        "background_color": cl.interactive_default,
        "border_radius":    fl.radius_small,
        "margin":           fl.spacing_small,
        "padding":          fl.spacing_small,
    },
    "Button:hovered":  {"background_color": cl.interactive_hovered},
    "Button:pressed":  {"background_color": cl.interactive_pressed},
    "Button:disabled": {"background_color": cl.interactive_default},
    "Button:checked":  {"background_color": cl.accent_primary},
    "Button.Label":           {"color": cl.text_primary},
    "Button.Label:disabled":  {"color": cl.text_disabled},

    # Named variants of Button. Inherit everything else from Button.
    "Button::ok":         {"background_color": cl.accent_primary},
    "Button::ok:hovered": {"background_color": cl.accent_hovered},
    "Button.Label::ok":   {"color": cl.text_on_accent},

    "Button::cancel": {},  # inherits everything from Button

    "Button::destructive":         {"background_color": cl.status_error},
    "Button::destructive:hovered": {"background_color": cl.status_error_hovered},
    "Button.Label::destructive":   {"color": cl.text_on_accent},

    # =====================================================================
    # OKButton / CancelButton — independent semantic types
    # Use these via style_type_name_override when a dialog needs a button
    # category with distinct base properties (radius, padding, border).
    # =====================================================================
    "OKButton": {
        "background_color": cl.accent_primary,
        "border_radius":    fl.radius_medium,
        "margin":           fl.spacing_small,
        "padding":          fl.spacing_medium,
    },
    "OKButton:hovered": {"background_color": cl.accent_hovered},
    "OKButton:pressed": {"background_color": cl.accent_pressed},
    "OKButton.Label":   {"color": cl.text_on_accent, "font_size": fl.font_size_medium},

    "CancelButton": {
        "background_color": cl.background_secondary,
        "border_radius":    fl.radius_medium,
        "border_width":     1.0,
        "border_color":     cl.border_default,
        "margin":           fl.spacing_small,
        "padding":          fl.spacing_medium,
    },
    "CancelButton:hovered": {
        "background_color": cl.background_tertiary,
        "border_color":     cl.border_strong,
    },
    "CancelButton:pressed": {"background_color": cl.interactive_pressed},
    "CancelButton.Label":   {"color": cl.text_primary, "font_size": fl.font_size_medium},

    # =====================================================================
    # Label
    # =====================================================================
    "Label": {"color": cl.text_primary, "font_size": fl.font_size_medium},

    # =====================================================================
    # Field
    # =====================================================================
    "Field": {
        "background_color": cl.background_primary,
        "color":            cl.text_primary,
        "border_radius":    fl.radius_small,
    },
    "Field:pressed": {"background_color": cl.background_secondary},

    # =====================================================================
    # TreeView
    # =====================================================================
    "TreeView": {
        "background_color":          cl.background_primary,
        "background_selected_color": cl.treeview_selection,
        "secondary_color":           cl.scrollbar_thumb,
    },
    "TreeView:selected": {"background_color": cl.accent_primary},
    "TreeView.Item":             {"color": cl.text_secondary},
    "TreeView.Item:selected":    {"color": cl.text_on_accent},
    "TreeView.Header": {
        "background_color": cl.background_tertiary,
        "color":            cl.text_primary,
        "font_size":        fl.font_size_medium,
    },

    # =====================================================================
    # CollapsableFrame
    # =====================================================================
    "CollapsableFrame": {
        "background_color": cl.background_secondary,
        "secondary_color":  cl.background_secondary,
        "color":            cl.text_primary,
        "border_radius":    fl.radius_medium,
        "padding":          fl.spacing_small,
    },
    "CollapsableFrame:hovered": {"secondary_color": cl.background_tertiary},
    "CollapsableFrame:pressed": {"secondary_color": cl.interactive_pressed},

    # =====================================================================
    # ScrollingFrame
    # =====================================================================
    "ScrollingFrame": {
        "scrollbar_size":   fl.scrollbar_width,
        "background_color": cl.background_primary,
        "secondary_color":  cl.scrollbar_thumb,
    },

    # =====================================================================
    # Menu
    # =====================================================================
    "Menu.Window":     {"background_color": cl.background_elevated, "border_radius": fl.radius_medium},
    "Menu.Item":       {"color": cl.text_primary, "margin_height": fl.spacing_small},
    "Menu.Item:disabled": {"color": cl.text_disabled},
    "Menu.Item:hovered":  {"background_color": cl.interactive_hovered},
    "Menu.Separator":  {"color": cl.border_default},

    # =====================================================================
    # Tooltip
    # =====================================================================
    "Tooltip": {
        "background_color": cl.background_elevated,
        "color":            cl.text_primary,
        "border_radius":    fl.radius_small,
        "padding":          fl.spacing_small,
    },

    # Add the same coverage for every other widget type the application uses.
}
```

## startup.py: assignment and theme subscription

`startup.py` runs once when the application initialises. It performs two actions:

1. Assigns `GLOBAL_STYLES` to `ui.style.default`.
2. Reads the theme setting once, applies it via `cl.set_shade(...)`, and subscribes to changes so future theme switches call `cl.set_shade(...)` again.

```python
"""Centralised style startup."""
import carb.settings
import omni.ui as ui
from omni.ui import color as cl

from .styles import GLOBAL_STYLES


_THEME_SETTING = "/persistent/app/window/uiStyle"
_theme_subscription = None


def _apply_theme(value: str | None) -> None:
    cl.set_shade("light" if value and "Light" in value else "default")


def on_startup() -> None:
    global _theme_subscription

    ui.style.default = GLOBAL_STYLES

    settings = carb.settings.get_settings()
    _apply_theme(settings.get_as_string(_THEME_SETTING))

    _theme_subscription = settings.subscribe_to_node_change_events(
        _THEME_SETTING,
        lambda _item, _event: _apply_theme(
            carb.settings.get_settings().get_as_string(_THEME_SETTING)
        ),
    )


def on_shutdown() -> None:
    global _theme_subscription
    _theme_subscription = None
```

The startup module owns the theme subscription. No surface subscribes to the theme setting on its own; every widget receives theme updates automatically because the constants it references are shaded.
