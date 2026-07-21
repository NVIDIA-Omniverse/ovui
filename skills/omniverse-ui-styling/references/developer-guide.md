# Developer Guide

Read this when building a new ovui or ovui-widgets surface, or when reshaping an existing surface so it matches the target architecture.

## Scenario A — standard-looking surface

A surface that uses standard widgets and wants the default ovui look needs **no style code at all**. Build the widgets and the centralised module supplies every visual property:

```python
import omni.ui as ui


class MyWindow(ui.Window):
    def __init__(self, title: str):
        super().__init__(title, width=400, height=300)
        self.frame.set_build_fn(self._build_ui)

    def _build_ui(self):
        with ui.VStack(spacing=8):
            ui.Label("Welcome")

            with ui.HStack(spacing=4):
                ui.Button("OK")
                ui.Button("Cancel")

            ui.StringField()
```

The buttons, label, and field all read their style from `ui.style.default`. The surface imports nothing from the centralised module.

## Scenario B — custom-looking surface

A surface that needs a unique visual identity defines only the differences from the defaults. Use `style_type_name_override` to introduce new semantic types and reference shared constants for every value:

```python
# my_surface/style.py

from omni.ui import color as cl
from omni.ui import constant as fl

# Surface-specific constants, domain-prefixed
cl.myext_highlight = cl.shade(cl("#00B976"), light=cl("#008853"))

MYEXT_STYLES = {
    # Custom button type
    "MyExt.ActionButton": {
        "background_color": cl.myext_highlight,
        "border_radius":    fl.radius_medium,
    },
    "MyExt.ActionButton:hovered": {"background_color": cl.accent_hovered},
    "MyExt.ActionButton.Label":   {"color": cl.text_on_accent},

    # Custom panel background
    "MyExt.Panel": {
        "background_color": cl.background_secondary,
        "border_radius":    fl.radius_large,
    },
}
```

```python
# my_surface/window.py

import omni.ui as ui

from .style import MYEXT_STYLES


class MyWindow(ui.Window):
    def __init__(self, title: str):
        super().__init__(title, width=400, height=300)
        self.frame.set_style(MYEXT_STYLES)
        self.frame.set_build_fn(self._build_ui)

    def _build_ui(self):
        with ui.VStack(style_type_name_override="MyExt.Panel"):
            ui.Label("Custom panel")

            with ui.HStack(spacing=4):
                # Standard widget — inherits ui.style.default
                ui.Button("Cancel")

                # Custom widget — uses MyExt.ActionButton
                ui.Button("Save", style_type_name_override="MyExt.ActionButton")
```

Key points:

- `style_type_name_override` selects a custom type the centralised module does not own.
- Standard widgets continue to inherit from `ui.style.default`; the surface does not redeclare them.
- Surface-specific constants are domain-prefixed (`cl.myext_*`).
- Every value comes from a constant; the surface contains no hex literals or magic floats.

## A concise per-surface style file

A focused surface override is short. Define only the constants the surface needs and only the selectors that override the centralised defaults:

```python
from omni.ui import color as cl
from omni.ui import constant as fl

# Surface-specific constants
cl.filebrowser_card_badge_shadow = cl.shade(cl("#444444DD"), light=cl("#00000044"))

STYLES = {
    "FileBrowser.Card":          {"margin": 8},
    "FileBrowser.Card:hovered":  {"border_width": 2},
    "FileBrowser.Card.Badge::shadow": {"color": cl.filebrowser_card_badge_shadow},

    # ZoomBar is surface-specific
    "FileBrowser.ZoomBar": {
        "background_color": cl.background_elevated,
        "border_radius":    fl.radius_small,
    },
    "FileBrowser.ZoomBar.Slider": {
        "draw_mode":        ui.SliderDrawMode.HANDLE,
        "background_color": cl.background_primary,
        "secondary_color":  cl.text_secondary,
    },
}
```

## Recipes

### Add a new shared colour, float, or URL

1. Confirm the constant belongs in the centralised module: more than one surface uses it, or the application owns the brand of which it is part.
2. Add it to `palette.py`, `constants.py`, or `urls.py` with a role-based name and a shade for every supported theme.
3. Reference the new constant from `GLOBAL_STYLES` in `styles.py`.
4. Replace every literal call site that was using the old value.

### Add a new surface-specific constant

1. Define the constant in the surface's own style file with a domain prefix (`cl.<surface>_<role>`).
2. Use `cl.shade(...)` / `fl.shade(...)` / `url.shade(...)` for any theme variation.
3. Reference it from the surface's `STYLES` dictionary or a frame-level style.
4. If two surfaces start to need the same constant, promote it to the centralised module with a role-based name.

### Add a new style selector

1. Pick the right level: standard widget type, named variant, sub-element, domain type, or named instance.
2. Use `Type::Name:State` consistently. State stays in the selector suffix, never in the type or the name.
3. Cover every relevant state. Hover, pressed, selected, disabled, and checked should be considered explicitly.
4. Place sub-element-with-name selectors as `Type.SubElement::name`, not `Type::name.SubElement`.

### Review a style change

- Look for new hex literals or magic floats. There must be none.
- Look for duplicated dark/light dictionaries or surface-local theme detection. There must be none.
- Confirm new constants follow the naming rules.
- Confirm selector overrides only declare properties that differ from the centralised defaults.
- Validate the change visually for both themes when a colour or float was added or changed.
