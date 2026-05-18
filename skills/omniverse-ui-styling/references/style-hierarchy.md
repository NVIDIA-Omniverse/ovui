# Style Hierarchy

Read this when designing the structure of a style dictionary, understanding selector resolution, or reviewing how a surface composes types, states, sub-elements, and named variants.

## Levels

The centralised style dictionary and every per-surface override live in the same six-level hierarchy. Authoring rules:

- Always define style at the most specific level that captures the rule's intent.
- Define every state a widget type actually supports.
- Pair a sub-element selector with the parent type when both need styling.

### Level 0 — Base

Properties with no selector apply to every widget. Use sparingly; this level is for genuine application-wide fonts and colours.

```python
{
    "": {"font_size": fl.font_size_medium, "color": cl.text_primary}
}
```

### Level 1 — Widget type

Every standard widget type gets a base style:

- Shapes: `Rectangle`, `Circle`, `Triangle`, `Line`, `Ellipse`
- Widgets: `Label`, `Button`, `CheckBox`, `RadioButton`, `ComboBox`, `Image`, `ImageWithProvider`
- Fields: `Field`, `StringField`, `IntField`, `FloatField`, `MultiField`
- Sliders / drags: `Slider`, `FloatSlider`, `IntSlider`, `FloatDrag`, `IntDrag`
- Containers: `Frame`, `ScrollingFrame`, `CanvasFrame`, `CollapsableFrame`, `HStack`, `VStack`, `ZStack`
- Tree / grid: `TreeView`, `VGrid`, `HGrid`
- Windows: `Window`, `Menu`, `MenuItem`, `MenuBar`, `Tooltip`, `Separator`

```python
{
    "Button":   {"background_color": cl.interactive_default, "border_radius": fl.radius_small},
    "Label":    {"color": cl.text_primary},
    "TreeView": {"background_color": cl.background_primary},
}
```

### Level 2 — Widget type + state

Every widget type that supports states defines a style for each state it supports:

```python
{
    "Button":          {"background_color": cl.interactive_default},
    "Button:hovered":  {"background_color": cl.interactive_hovered},
    "Button:pressed":  {"background_color": cl.interactive_pressed},
    "Button:disabled": {"background_color": cl.interactive_disabled},
    "Button:checked":  {"background_color": cl.accent_primary},
}
```

### Level 3 — Sub-element

Compound widgets have sub-elements with independent styles:

```python
{
    "Button.Label":               {"color": cl.text_primary},
    "Button.Image":               {"color": cl.text_primary},
    "CollapsableFrame.Header":    {"background_color": cl.background_secondary},
    "TreeView.Item":              {"color": cl.text_primary},
    "TreeView.Header":            {"background_color": cl.background_tertiary},
    "Menu.Item":                  {"color": cl.text_primary},
    "Menu.Separator":             {"color": cl.border_default},
}
```

### Sub-element with named variant: selector syntax

When a sub-element carries a named variant, attach `::name` to the rightmost element. The parser splits the selector as:

1. Everything before the first `.` is the type (optionally `Type::Name`).
2. Everything after `.` and before `::` is the sub-element.
3. Everything after `::` is the name.

```python
# CORRECT - name attaches to the rightmost element
"Button.Label::ok":              {"color": cl.text_on_accent},
"Button.Label::cancel":          {"color": cl.text_primary},
"TreeView.Item::selected_file":  {"color": cl.accent_primary},
"CollapsableFrame.Header::expanded": {"background_color": cl.background_tertiary},

# INCORRECT - parser treats "Button::ok" as the type and ".Label" is invalid
"Button::ok.Label":              {...}
"TreeView::file.Item":           {...}
```

Complete example combining state and named variant:

```python
{
    "Button":                {"background_color": cl.interactive_default},
    "Button.Label":          {"color": cl.text_primary},

    "Button::ok":            {"background_color": cl.accent_primary},
    "Button::ok:hovered":    {"background_color": cl.accent_hovered},

    "Button.Label::ok":            {"color": cl.text_on_accent},
    "Button.Label::ok:disabled":   {"color": cl.text_disabled},
}

ui.Button("OK", name="ok")  # the name="ok" applies to Button::ok and Button.Label::ok
```

### Level 4 — Domain type

Surfaces define their own type names for custom styling, set on widgets via `style_type_name_override`:

```python
{
    "FileBrowser.TreeView":   {"background_color": cl.background_secondary},
    "PropertyPanel.Button":   {"border_radius": fl.radius_none},
    "Viewport.ToolButton":    {"background_color": cl.transparent},
}
```

A domain type is **independent**. When a widget sets `style_type_name_override="PropertyPanel.Button"`, `omni.ui` resolves every property under the `PropertyPanel.Button` group and falls back only to its own named variants (Level 5) and then to the C++ built-in defaults. Resolution does **not** fall back to the widget's normal type (`Button`) or to any other group in `ui.style.default`. Define every property a domain type needs, on the domain type itself.

If a surface wants to keep the standard widget's defaults and only change a few properties, use the widget `name` parameter against the standard type instead of `style_type_name_override`. `Button::compact` inherits from `Button`; `PropertyPanel.Button` does not.

### Level 5 — Named variant of a domain type

The most specific level combines a domain type with a name and a state. Named variants inherit from their domain type's base block (not from the standard widget type):

```python
{
    "PropertyPanel.Button::apply":          {"background_color": cl.accent_primary},
    "PropertyPanel.Button::apply:hovered":  {"background_color": cl.accent_hovered},
}
```

`PropertyPanel.Button::apply` inherits properties from `PropertyPanel.Button` (its parent in the same type group), not from `Button`.

## Resolution order

Resolution walks from most specific to least specific within the chosen type group. For a widget declared as:

```python
ui.Button("Apply", style_type_name_override="PropertyPanel.Button", name="apply")
```

in the hovered state, the engine looks up:

1. `PropertyPanel.Button::apply:hovered`
2. `PropertyPanel.Button::apply` (named variant, normal state — fall back to the variant's base group)
3. `PropertyPanel.Button:hovered` (domain type, same state)
4. `PropertyPanel.Button` (domain type, normal state)
5. Built-in C++ defaults

`Button:hovered` and `Button` from `ui.style.default` are **not** consulted, because `style_type_name_override` replaces the type the widget looks up. Any property a domain type needs must be defined on the domain type.

```
              Resolution chain for PropertyPanel.Button::apply:hovered

   ┌────────────────────────────────────────────────────────────────┐
   │ PropertyPanel.Button::apply:hovered                            │ Level 5
   │  ↓ not found? cascade to normal state                          │
   │ PropertyPanel.Button::apply                                    │ Level 5
   │  ↓ not found? fall back to the variant's base group            │
   │ PropertyPanel.Button:hovered                                   │ Level 4
   │  ↓ not found? cascade to normal state                          │
   │ PropertyPanel.Button                                           │ Level 4
   │  ↓ not found? use C++ hardcoded default                        │
   │ StyleContainer::defaultStyle()                                 │
   └────────────────────────────────────────────────────────────────┘
```

Compare this with the chain for a widget that uses `name="apply"` against the standard `Button` type (no `style_type_name_override`):

```python
ui.Button("Apply", name="apply")
```

in the hovered state:

1. `Button::apply:hovered`
2. `Button::apply`
3. `Button:hovered`
4. `Button`
5. Built-in C++ defaults

Here the named variant inherits from `Button` in `ui.style.default`, because the widget's type lookup is still `Button`.

## Choosing which lookup chain you want

- Use `name=` on a standard widget type when you want the centralised defaults for everything except a few properties. Centralised state styles, sub-element styles, and base properties all apply automatically.
- Use `style_type_name_override` when the surface needs a self-contained type whose look is independent of the standard widget. Provide every property the type needs on the override type itself, including every relevant state and sub-element.
- Combine the two when you have several variants of an independent domain type. Define the base `Domain.WidgetType` block once, then add `Domain.WidgetType::variant` entries that inherit from it.
