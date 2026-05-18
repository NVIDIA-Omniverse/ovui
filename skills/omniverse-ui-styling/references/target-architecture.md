# Target Style Architecture

This is the authoritative architecture every ovui and ovwidgets surface must adopt for styling. Use it as the target schema when adding new widgets, adding new style, or reviewing existing style code.

## Single source of truth

One centralised style module owns every shared visual constant: colours, floats, and URLs. Constants are defined once, with a shaded variant for every theme that ships. No widget code defines hex literals, magic floats, or one-off icon paths.

## Complete default styles for every widget type

The same style module populates `ui.style.default` with a comprehensive style dictionary that covers every standard widget type and every relevant state: `Button`, `Label`, `TreeView`, `ComboBox`, `Field`, `Slider`, `CheckBox`, `CollapsableFrame`, `Menu`, `Tooltip`, and so on. Each type lists the states that matter for it: normal, hovered, pressed, selected, disabled, checked.

A surface that uses standard widgets with no extra naming inherits the polished default look without writing a single style entry.

## Overrides only contain differences

A surface that needs a unique appearance overrides only the specific properties that differ from the defaults. It does not redeclare an entire parallel style system. Customisation uses `style_type_name_override` for new semantic types and the widget `name` parameter for named variants of existing types.

## Theme switching is one call

A single call to `cl.set_shade("light")` updates every shaded constant in the process. All widgets read their new value on the next frame. Style code does not re-execute, listeners do not have to refresh, and no widget needs to detect the theme on its own. The centralised module is the only piece of code that subscribes to the theme setting.

## Architecture diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Centralised style module                       │
│                                                                     │
│   palette.py            constants.py            urls.py             │
│   ───────────           ────────────            ───────             │
│   cl.background_*       fl.radius_*             url.icon_*          │
│   cl.text_*             fl.spacing_*            url.image_*         │
│   cl.interactive_*      fl.font_size_*                              │
│   cl.accent_*                                                       │
│   cl.status_*                                                       │
│                                                                     │
│   styles.py             startup.py                                  │
│   ─────────             ──────────                                  │
│   GLOBAL_STYLES         ui.style.default = GLOBAL_STYLES            │
│   (every widget type    cl.set_shade(theme) on theme change         │
│    + every state)                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ ui.style.default applies everywhere
                                  ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │ Surface A        │   │ Surface B        │   │ Surface C        │
   │                  │   │                  │   │                  │
   │ no style.py      │   │ overrides only   │   │ domain types     │
   │ inherits all     │   │ Button:hovered   │   │ FileBrowser.*    │
   │ defaults         │   │ from defaults    │   │ named variants   │
   └──────────────────┘   └──────────────────┘   └──────────────────┘
```

## What every styling decision must satisfy

- Shared visual constants live exactly once, in the centralised module.
- Standard widgets inherit complete defaults without per-surface boilerplate.
- Custom widgets express only the properties they change.
- Theme switching is automatic; no surface detects the theme by itself.
- Selector grammar is `Type::Name:State`, used consistently across the codebase.
- Naming conventions for constants and selectors are uniform across all surfaces (see the naming references).

Read the other references for the concrete rules behind each item above.
