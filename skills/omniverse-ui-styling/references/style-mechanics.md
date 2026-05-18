# Style Mechanics

The mechanics every ovui styling decision is built on. Read this when you need selector syntax, cascading behaviour, the constant stores, shades, `style_type_name_override`, the widget `name` parameter, or `ui.style.default`.

## Selector grammar: Type::Name:State

ovui styles use a three-part selector:

```
Type::Name:State
```

- **Type** — widget class name or a custom override (`Button`, `TreeView`, `FileBrowser.TreeView`).
- **Name** — optional instance identifier, separated by `::` (`Button::ok`, `Button::cancel`).
- **State** — optional pseudo-state, separated by `:` (`Button:hovered`, `Button:pressed`).

Supported states:

| State | Meaning |
|-------|---------|
| (none) | Normal state, no interaction |
| `hovered` | Mouse cursor is over the widget |
| `pressed` | Mouse button is held down on the widget |
| `selected` | Widget is in a selected state (e.g. TreeView item) |
| `disabled` | Widget is disabled |
| `checked` | Widget is in a checked state (e.g. CheckBox, ToggleButton) |
| `drop` | Widget is accepting a drag-and-drop operation |

Style declarations map selectors to property dictionaries:

```python
{
    "Button": {"background_color": cl.interactive_default, "border_radius": fl.radius_small},
    "Button:hovered": {"background_color": cl.interactive_hovered},
    "Button.Label": {"color": cl.text_primary},
}
```

## Cascading

Style properties cascade from container to children inside the same window. A style set on a parent applies to descendants that match its selectors:

```python
with ui.VStack(style={"Button": {"background_color": cl.accent_primary}}):
    ui.Button("One")  # accent background
    ui.Button("Two")  # accent background
```

Cascading does not cross window boundaries. A style set on one window does not affect widgets in another. `ui.style.default` is the only mechanism for application-wide defaults.

## Three stores: `cl`, `fl`, `url`

ovui provides three global stores for named values:

```python
from omni.ui import color as cl
from omni.ui import constant as fl
from omni.ui import url
```

Assign values to arbitrary names, then reference them from style dictionaries:

```python
cl.background_primary = cl("#23211F")
fl.radius_small = 2.0
url.icon_check = "resources/icons/check.svg"

style = {
    "Rectangle": {"background_color": cl.background_primary, "border_radius": fl.radius_small},
    "Image": {"image_url": url.icon_check},
}
```

Stores are mutable at runtime. Changing `cl.background_primary` updates every widget that references it on the next frame.

## The shade system

`shade()` registers a named value with one variant per theme:

```python
cl.background_primary = cl.shade(
    cl("#1F2123"),          # default (dark theme)
    light=cl("#F5F5F5"),    # light theme variant
)
```

`cl.set_shade("light")` switches every shaded colour to its light variant simultaneously. The shade system works identically for floats and URLs:

```python
fl.spacing_default = fl.shade(8.0, light=4.0)
url.logo = url.shade("dark_logo.svg", light="light_logo.svg")
```

This is the theme mechanism. No other infrastructure is required.

## `style_type_name_override` versus `name`

These two widget parameters work together to enable style inheritance.

- **`style_type_name_override="X"`** — widget looks up styles under the `X` type. It does **not** inherit from the widget's normal type (e.g. `Button`). Define `X` completely or fall back to C++ defaults. Use this when a widget category needs its own base style independent of the standard widget type.

- **`name="x"`** — widget looks up styles under `Type::x`. It **does** inherit from the base type (e.g. `Button`); only properties listed under `Type::x` override the base. Use this when you want a variant of the standard widget that differs in specific properties.

```python
STYLES = {
    # Base button (inherited by all Button widgets)
    "Button": {
        "background_color": cl.interactive_default,
        "border_radius": fl.radius_small,
        "margin": fl.spacing_small,
    },
    "Button:hovered": {"background_color": cl.interactive_hovered},
    "Button.Label": {"color": cl.text_primary},

    # Named variant: inherits Button, overrides only the background
    "Button::ok": {"background_color": cl.accent_primary},
    "Button::ok:hovered": {"background_color": cl.accent_hovered},
    "Button.Label::ok": {"color": cl.text_on_accent},

    # Named variant with no overrides: pure inheritance from Button
    "Button::cancel": {},

    # Independent custom type: defines everything it needs
    "OKButton": {
        "background_color": cl.status_success,
        "border_radius": fl.radius_medium,
        "margin": fl.spacing_medium,
    },
    "OKButton:hovered": {"background_color": cl.status_success_hovered},
    "OKButton.Label": {"color": cl.text_on_accent},
}

with ui.HStack():
    ui.Button("OK",     name="ok")                                    # inherits Button + Button::ok
    ui.Button("Cancel", name="cancel")                                # inherits everything from Button
    ui.Button("Confirm", style_type_name_override="OKButton")         # independent type
```

`StyleContainer.cpp` (lines 272-323) implements this: named groups have their parent set to the nameless entry of the same type. When the named block does not define a property, resolution falls back to the parent.

## Combining domain types with named variants

Domain-scoped types compose with named variants. Always attach the `::name` to the rightmost element in the selector:

```python
STYLES = {
    "FileBrowser.ActionButton": {
        "background_color": cl.accent_primary,
        "border_radius": fl.radius_small,
    },
    "FileBrowser.ActionButton:hovered": {"background_color": cl.accent_hovered},

    "FileBrowser.ActionButton::download": {"background_color": cl.status_info},
    "FileBrowser.ActionButton::delete":   {"background_color": cl.status_error},
}

ui.Button("Download", style_type_name_override="FileBrowser.ActionButton", name="download")
ui.Button("Delete",   style_type_name_override="FileBrowser.ActionButton", name="delete")
```

## Choosing `style_type_name_override` versus `name`

- Use `style_type_name_override` for a new semantic widget category (an entry needs its own base style independent of the standard type).
- Use `name` for a property-level variant of an existing type that should inherit everything else.
- Combine both when you have several variants of a domain-specific category in the same view.

## `ui.style.default`: the application-wide default

Every widget queries `ui.style.default` when resolving properties. Set a complete style dictionary here and every window in the application inherits those defaults:

```python
ui.style.default = {
    "Button": {"background_color": cl.interactive_default},
    "Button:hovered": {"background_color": cl.interactive_hovered},
    # ... complete coverage of every widget type and every state
}
```

The centralised style module performs this single assignment at startup. No other code is allowed to write to `ui.style.default`.
