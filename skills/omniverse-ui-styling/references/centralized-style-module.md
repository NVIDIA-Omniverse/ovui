# Centralized Style Module

Read this when designing or reviewing the centralised style module that owns every shared visual constant for the application.

## Layout

The module contains five Python files plus shared assets:

```
common/style/
├── palette.py        # All cl.* colour constants
├── constants.py      # All fl.* float constants
├── urls.py           # All url.* icon and image paths
├── styles.py         # GLOBAL_STYLES dictionary
├── startup.py        # ui.style.default assignment and theme subscription
└── icons/            # Shared icon assets
```

Every importer of the module touches the file that owns the constants they need. `styles.py` imports `palette`, `constants`, and `urls` so the constants are defined before the dictionary references them. `startup.py` runs once when the application initialises.

## palette.py

Every shared colour constant the application uses. Every constant is defined with `cl.shade(...)` so it carries a value for every supported theme:

```python
"""Colour palette for ovui surfaces."""
from omni.ui import color as cl

# Backgrounds
cl.background_primary = cl.shade(
    cl("#1F2123"),          # dark theme (default)
    light=cl("#F5F5F5"),    # light theme
)
cl.background_secondary = cl.shade(cl("#2A2B2C"), light=cl("#FFFFFF"))
cl.background_tertiary  = cl.shade(cl("#343432"), light=cl("#E8E8E8"))
cl.background_elevated  = cl.shade(cl("#3D3B38"), light=cl("#FFFFFF"))

# Text
cl.text_primary    = cl.shade(cl("#CCCCCC"), light=cl("#1A1A1A"))
cl.text_secondary  = cl.shade(cl("#9E9E9E"), light=cl("#666666"))
cl.text_disabled   = cl.shade(cl("#606060"), light=cl("#AAAAAA"))

# Interactive elements
cl.interactive_default = cl.shade(cl("#444444"), light=cl("#E0E0E0"))
cl.interactive_hovered = cl.shade(cl("#9E9E9E"), light=cl("#C8C8C8"))
cl.interactive_pressed = cl.shade(cl("#8A8778"), light=cl("#B0B0B0"))

# Accent / brand
cl.accent_primary   = cl.shade(cl("#8A8777"), light=cl("#5A5A4A"))
cl.accent_secondary = cl.shade(cl("#76B900"), light=cl("#76B900"))

# Utility
cl.transparent = cl(0x00000000)  # fully transparent fill, identical in every theme

# Status, borders, component-specific colours follow the same pattern.
```

## constants.py

Every shared float constant: border radii, spacing, font sizes, scrollbar widths, tree indents, row heights. Use `fl.shade(...)` for any float that should differ between themes:

```python
"""Float constants for ovui surfaces."""
from omni.ui import constant as fl

# Border radius
fl.radius_none   = 0.0
fl.radius_small  = fl.shade(2.0, light=1.0)
fl.radius_medium = fl.shade(4.0, light=2.0)
fl.radius_large  = fl.shade(8.0, light=4.0)

# Spacing
fl.spacing_none   = 0.0
fl.spacing_small  = fl.shade(4.0, light=2.0)
fl.spacing_medium = fl.shade(8.0, light=4.0)
fl.spacing_large  = fl.shade(16.0, light=8.0)

# Font sizes
fl.font_size_small  = fl.shade(12.0, light=14.0)
fl.font_size_medium = fl.shade(14.0, light=16.0)
fl.font_size_large  = fl.shade(16.0, light=18.0)
fl.font_size_xlarge = fl.shade(20.0, light=24.0)

# Component-specific floats
fl.scrollbar_width    = 12.0
fl.treeview_indent    = 16.0
fl.treeview_row_height = 24.0
```

## urls.py

Every shared icon and image path. Use `url.shade(...)` for assets that differ between themes:

```python
"""URL constants for ovui surfaces."""
from omni.ui import url

_ICONS = "${centralised_style_module}/icons"

url.icon_check = url.shade(
    f"{_ICONS}/check_dark.svg",
    light=f"{_ICONS}/check_light.svg",
)
url.icon_close = url.shade(
    f"{_ICONS}/close_dark.svg",
    light=f"{_ICONS}/close_light.svg",
)
url.icon_expand   = f"{_ICONS}/expand.svg"
url.icon_collapse = f"{_ICONS}/collapse.svg"
```

## Authoring rules

- Every shared colour, float, and URL constant lives in this module. Nowhere else.
- Every constant is theme-shaded unless it has an objectively single value across themes.
- Constant names follow the rules in `naming-constants.md`.
- The module exports constants only. The style dictionary that consumes them lives in `styles.py` (see `global-styles-and-startup.md`).
- Per-surface constants stay in the surface's own style file with a domain prefix; they do not enter the centralised module unless multiple surfaces share them.
