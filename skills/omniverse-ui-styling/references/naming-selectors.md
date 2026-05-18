# Naming Selectors

Read this when adding or reviewing `style_type_name_override` values and widget `name` variants.

## `style_type_name_override` rules

1. **Never encode state in the type name.** State belongs in selectors (`:hovered`, `:pressed`, `:disabled`). Bad: `style_type_name_override="HoveredButton"`.
2. **Use PascalCase segments.** Bad: `style_type_name_override="ok"`. Good: `style_type_name_override="OKButton"`.
3. **Full words. No abbreviations.** Good: `Button`. Bad: `Btn`.
4. **No filler prefixes** (`AppButton`, `UiButton`) unless they are meaningful domain identifiers.
5. **Self-descriptive and semantic.** The reader understands what the type represents from the name alone.

## `style_type_name_override` scheme

Use **domain-scoped dot notation** with PascalCase segments:

```
<Domain>.<WidgetCategory>
```

- `<Domain>` identifies the surface that owns the type (`FileBrowser`, `PropertyPanel`, `Viewport`, `Stage`).
- `<WidgetCategory>` identifies the widget category inside that surface (`Toolbar`, `TreeView`, `Button`, `Card`).

Domain scoping prevents collisions across surfaces and makes ownership obvious at a glance.

```python
# Domain-scoped (the default)
"FileBrowser.Card"
"FileBrowser.TreeView"
"PropertyPanel.Button"
"Viewport.Toolbar"
"Viewport.ToolButton"

# Shared semantic types (only when truly global and centrally owned)
"OKButton"
"CancelButton"
"DestructiveButton"
```

Reserve unscoped PascalCase names (`OKButton`, `CancelButton`) for genuinely application-wide semantic types defined in the centralised style module. Everything else carries a domain prefix.

## `name` rules

1. **Short and semantic.** Describe the role, not the appearance. Good: `ok`, `cancel`, `primary`. Bad: `red_button`, `big_one`.
2. **Local to the type.** `Button::ok` and `TreeView::ok` are independent variants of independent types.
3. **No state in the name.** State belongs in the selector suffix.
4. **Do not repeat the widget type.** Good: `name="ok"`. Bad: `name="button_ok"`.

## `name` scheme

Use **`snake_case`** for every `name` value. It is Python-native, matches the existing selector examples in the codebase, and avoids the case-folding friction of `camelCase` or the visual collision of `kebab-case` with selector punctuation.

## Recommended `name` values

```python
# Core role variants
"ok"
"cancel"
"primary"
"secondary"
"destructive"

# Size / layout variants
"compact"
"dense"

# Surface-specific variants (introduce only when the role is genuinely new)
"selection_area"
"download"
"upload"
```
