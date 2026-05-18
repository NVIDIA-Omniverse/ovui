---
name: omniverse-ui-styling
description: >-
  Use this skill for ovui and ovwidgets styling work: palettes, colour /
  float / URL constants, theme shades, ui.style.default, style dictionaries,
  selector grammar, widget name variants, style_type_name_override values,
  naming conventions, style hierarchy, the centralised style module, and
  styling reviews. This skill is the authoritative target style guide.
author: "NVIDIA ovui Team <ovui-team@nvidia.com>"
license: "LicenseRef-NVIDIA"
---

# OVUI Styling

This skill is the authoritative style guide for ovui and ovwidgets. It defines the target architecture, naming conventions, selector grammar, and centralised module layout that every styling decision must follow.

## Required workflow

1. Identify the styling surface you are working on:
   - colour, float, or URL constant
   - style selector, widget `name`, or `style_type_name_override`
   - `ui.style.default` or the global style dictionary
   - per-surface override or new domain type
   - styling review.
2. Read the references that cover the decision before changing code. The guide is split by topic; load only what is relevant.
3. Inspect existing ovui and ovwidgets style code with `rg` before introducing a new constant or selector. Reuse the existing naming family; do not invent a parallel one.
4. Keep constants and styles in separate layers:
   - constants live in the centralised module (`cl.*`, `fl.*`, `url.*`)
   - style dictionaries map selectors to property values
   - widget `name` values are variants under a type
   - `style_type_name_override` values define semantic widget types.
5. Standard widgets inherit complete defaults from `ui.style.default`. Custom widgets override only the properties that differ.
6. Validate visually when the change affects appearance, and run a content/metadata validation when it does not.

## Reference map

- `references/target-architecture.md` — the target style schema every surface must follow.
- `references/style-mechanics.md` — selector grammar, cascading, the three stores, the shade system, `style_type_name_override`, widget `name`, and `ui.style.default`.
- `references/naming-constants.md` — naming rules and the recommended scheme for colour, float, URL, and icon constants.
- `references/naming-selectors.md` — naming rules and the recommended scheme for `style_type_name_override` values and widget `name` variants.
- `references/style-hierarchy.md` — the six levels of the style dictionary and the resolution order from most-specific to least-specific selector.
- `references/centralized-style-module.md` — layout of the centralised style module and the design of `palette.py`, `constants.py`, and `urls.py`.
- `references/global-styles-and-startup.md` — the `GLOBAL_STYLES` dictionary, the assignment to `ui.style.default`, and theme subscription on startup.
- `references/developer-guide.md` — recipes for building standard-looking and custom-looking surfaces, and for adding constants, selectors, or per-surface styles.

## Non-negotiable rules

- No new hex literals, magic float values, or one-off icon paths in any surface. Every value comes from a constant in the centralised module or from a domain-prefixed surface-local constant.
- Use role-first names for shared constants. Use component-prefixed names only for constants exactly one widget type uses.
- Full words in every constant and selector name. Avoid filler such as `misc`, `default`, `value`, or `thing`.
- `style_type_name_override` defines a semantic widget type. `name` defines a variant within a type. State always lives in the selector suffix.
- Keep selector families coherent. If a surface already uses `Stage.FilterField`, do not add a parallel `stage_filter` selector grammar.
- Standard widgets use the centralised defaults complete. Per-surface style files contain only true overrides.
- Theme switching is automatic via shaded constants. No surface reads the theme setting or maintains parallel dark/light dictionaries.
- `ui.style.default` is written exactly once, by the centralised style module's startup. Nowhere else.

## Common task recipes

### Add or rename a constant

1. Read `references/naming-constants.md`.
2. Search nearby code for existing constants and consumers.
3. Decide whether the constant is shared role-first or component-prefixed (or surface-local with a domain prefix).
4. Add the constant with a shaded variant for every supported theme.
5. Replace literal call sites with the constant.
6. Run the focused tests that cover the changed style surface.

### Add or review a selector

1. Read `references/style-mechanics.md`, `references/naming-selectors.md`, and `references/style-hierarchy.md`.
2. Identify the widget type, semantic domain, named variant, and state.
3. Use the `Type::Name:State` grammar.
4. Use `style_type_name_override` for reusable semantic widget types; use `name` for variants of an existing type.
5. Cover every relevant state: hover, pressed, selected, disabled, checked, drop.

### Design or extend global styles

1. Read `references/centralized-style-module.md` and `references/global-styles-and-startup.md`.
2. Add the constants in `palette.py` / `constants.py` / `urls.py`.
3. Reference them from `GLOBAL_STYLES` in `styles.py`.
4. Verify standard widgets and custom overrides render correctly in every supported theme.

### Review styling work

1. Reject any new hex literal, duplicated dark/light dictionary, surface-local theme detection, selector-family drift, or overbroad surface-level style.
2. Verify constants, selectors, and names against the reference files.
3. Confirm shared values come from the centralised module and surface-specific values are domain-prefixed.
4. Confirm visual proof for any change that affects pixels.
