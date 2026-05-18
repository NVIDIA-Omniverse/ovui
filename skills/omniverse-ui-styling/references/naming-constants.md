# Naming Constants

Read this when adding or reviewing colour (`cl`), float (`fl`), or URL (`url`) constants. These rules are mandatory for every constant in the centralised style module and in every per-surface override.

## Constants vs. styles

- **Constants** are named values in stores (`cl.background_primary`, `fl.radius_small`, `url.icon_check`). They are theme-switchable atoms.
- **Styles** are selector→property mappings that reference constants.

Keep these layers separate. `palette.py` / `constants.py` / `urls.py` define constants. `styles.py` defines style dictionaries that reference them.

## Rules for every constant name

1. **Full words. No abbreviations.** `background`, not `bg`. `primary`, not `prim`. `secondary`, not `sec`.
2. **No filler prefixes.** `app_` adds nothing. Write `cl.background_primary`, not `cl.app_background_primary`.
3. **Self-descriptive.** A reader who sees `cl.text_secondary` understands the role without looking the constant up.
4. **Underscore separator.** Use `cl.background_primary`. Dot-separated names (`cl.background.primary`) are not supported by the store implementation.
5. **No state in the name.** States belong in selectors (`:hovered`, `:disabled`), never in constant names.

## Naming scheme

Use the **hybrid scheme**: role-based names for shared constants, component-prefixed names for component-specific constants.

A constant is **shared** if two or more widget types use it. Shared constants are role-first and carry no component prefix.

A constant is **component-specific** if exactly one widget type uses it. Component-specific constants start with the component name.

The boundary is mechanical and easy to enforce in review.

## Shared colour names

```python
# Backgrounds
cl.background_primary         # Main window/panel background
cl.background_secondary       # Nested areas, cards
cl.background_tertiary        # Deeply nested areas
cl.background_elevated        # Floating elements (menus, tooltips)

# Text
cl.text_primary               # Main text
cl.text_secondary             # Secondary / muted text
cl.text_disabled              # Disabled state text
cl.text_on_accent             # Text on accent-coloured backgrounds

# Borders
cl.border_default             # Standard borders
cl.border_strong              # Emphasised borders
cl.border_focused             # Focused element borders

# Interactive (buttons and clickable elements)
cl.interactive_default        # Normal state
cl.interactive_hovered        # Hover state
cl.interactive_pressed        # Pressed state
cl.interactive_disabled       # Disabled state

# Accent / brand
cl.accent_primary             # Primary brand colour
cl.accent_secondary           # Secondary brand colour
cl.accent_hovered             # Accent hover state

# Status
cl.status_error               # Error / destructive actions
cl.status_warning             # Warning states
cl.status_success             # Success / positive states
cl.status_info                # Informational highlights

# Utility
cl.transparent                # Fully transparent fill (RGBA 0)
```

## Component-specific colour names

```python
# TreeView
cl.treeview_selection         # Selected item background
cl.treeview_branch_line       # Expand/collapse line colour

# Scrollbar
cl.scrollbar_track            # Track background
cl.scrollbar_thumb            # Thumb colour
cl.scrollbar_thumb_hovered    # Thumb hover state

# Splitter
cl.splitter_handle            # Draggable splitter colour
cl.splitter_handle_hovered    # Splitter hover state
```

## Shared float names

```python
# Border radius
fl.radius_none                # 0  — sharp corners
fl.radius_small               # 2  — subtle rounding
fl.radius_medium              # 4  — standard rounding
fl.radius_large               # 8  — prominent rounding

# Spacing
fl.spacing_none               # 0
fl.spacing_small              # 4
fl.spacing_medium             # 8
fl.spacing_large              # 16

# Font sizes
fl.font_size_small            # 12
fl.font_size_medium           # 14
fl.font_size_large            # 16
fl.font_size_xlarge           # 20
```

## Domain-prefixed names for per-surface constants

When a surface needs a constant that does not belong in the shared palette, define it locally with a domain prefix matching the surface's namespace:

```python
cl.filebrowser_card_background = cl.shade(cl("#2F2F2F"), light=cl("#E8E8E8"))
cl.filebrowser_card_border     = cl.shade(cl("#3A3A3A"), light=cl("#D0D0D0"))
```

Domain prefixes prevent collisions across surfaces. If the same constant turns out to be useful in two or more surfaces, promote it to the shared palette with a role-based name and remove the domain-prefixed duplicates.
