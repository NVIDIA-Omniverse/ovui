# Model-View And TreeView Reference

This reference documents ovui's value-model and item-model system, with TreeView in high detail. It is based on the ovui bindings and the reference Stage Browser, Layers tree, Content detail tree, combo boxes, color widgets, and multi-fields.

## Value Models

`ui.AbstractValueModel` is the scalar model contract used by fields, sliders, check boxes, buttons, progress bars, and item-model cells.

Required methods for custom Python models:

- `get_value_as_bool()`
- `get_value_as_float()`
- `get_value_as_int()`
- `get_value_as_string()`
- `set_value(value)`

Optional edit lifecycle:

- `begin_edit()`
- `end_edit()`

Convenience read-only properties (also from the bindings) avoid calling the `get_value_as_*` getters in tight delegate code: `model.as_bool`, `model.as_float`, `model.as_int`, `model.as_string`.

Notification:

- Call `_value_changed()` after internal value changes.
- Subscribe with either of two equivalent APIs:
  - Plain callbacks: `add_value_changed_fn(fn)` / `remove_value_changed_fn(token)`, `add_begin_edit_fn(fn)`, `add_end_edit_fn(fn)`.
  - Cancellable subscriptions: `subscribe_value_changed_fn(fn)` / `subscribe_begin_edit_fn(fn)` / `subscribe_end_edit_fn(fn)` — each returns an object whose lifetime owns the subscription. Prefer this form when the listener needs to be unsubscribed at a known teardown point.
- The legacy `subscribe_item_changed_fn` on a value model is deprecated; use `subscribe_value_changed_fn` instead.

Simple built-ins:

- `ui.SimpleStringModel(defaultValue="")`
- `ui.SimpleBoolModel(default_value=False, min=..., max=...)`
- `ui.SimpleFloatModel(default_value=0.0, min=..., max=...)`
- `ui.SimpleIntModel(default_value=0, min=..., max=...)`

Keep value model instances stable. A delegate may be rebuilt many times; returning a new value model every call can lose subscriptions, edit state, selection-related state, and row refresh behavior.

## Value-Model Widgets

Common widgets backed by `AbstractValueModel`:

- `ui.CheckBox(model=...)`
- `ui.ToolButton(model=...)`
- `ui.StringField(model=...)`
- `ui.StringFieldLimited(model=..., max_length=...)`
- `ui.IntField`, `ui.FloatField`
- `ui.IntSlider`, `ui.UIntSlider`, `ui.FloatSlider`
- `ui.IntDrag`, `ui.UIntDrag`, `ui.FloatDrag`
- `ui.ProgressBar`

Fields emit begin/end edit on their models. Use those hooks for commit/cancel, focus styling, and undo-group boundaries.

## Item Models

`ui.AbstractItemModel` is the contract for hierarchical/table-like widgets.

Items are `ui.AbstractItem` objects. Subclass them and store domain state on the Python item:

```python
class MyItem(ui.AbstractItem):
    def __init__(self, key, parent=None):
        super().__init__()
        self.key = key
        self.parent = parent
        self.children = None
        self.name_model = None
```

Required model methods:

- `get_item_children(parentItem=None) -> list[AbstractItem]`
- `get_item_value_model_count(item=None) -> int`
- `get_item_value_model(item=None, column_id=0) -> AbstractValueModel`

Optional methods:

- `can_item_have_children(parentItem=None) -> bool`
- `append_child_item(parentItem, model)`
- `remove_item(item)`
- `begin_edit(item)`, `end_edit(item)`
- `get_drag_mime_data(item) -> str`
- `drop_accepted(target_item, source_item_or_string, drop_location=-1) -> bool`
- `drop(target_item, source_item_or_string, drop_location=-1) -> None`

Notification:

- `_item_changed(item)` refreshes one subtree/row.
- `_item_changed(None)` signals root/full structural changes and column count changes.
- `subscribe_item_changed_fn`, `subscribe_begin_edit_fn`, and `subscribe_end_edit_fn` return cancellable subscriptions.

## Item-Model Widgets In This Codebase

- `ui.TreeView`: hierarchical rows and columns. Most important.
- `ui.ComboBox`: root value model is selected index; root children are option rows.
- `ui.ColorWidget`: item model children are RGBA value models.
- `ui.MultiFloatField`, `ui.MultiIntField`, `ui.MultiStringField`, `ui.MultiFloatDragField`, `ui.MultiIntDragField`: item-model children are component models.

`ui.SimpleListModel` is used for flat lists such as combo box options and multi-field component lists. It is not enough for a stage hierarchy because it has no nested children.

## Delegates

`ui.AbstractItemDelegate` builds TreeView row content. Override:

- `build_branch(model, item, column_id, level, expanded)`
- `build_widget(model, item, column_id, level, expanded)`
- `build_header(column_id)` if using `header_visible=True`

The delegate is called inside ovui container scopes. Create low-level widgets directly in these methods. Do not return a widget; just build into the current context.

Use `build_branch` for indentation, chevrons, branch hit visuals, and row-leading state. Use `build_widget` for the actual cell content.

## TreeView Public Surface

Constructor:

```python
tree = ui.TreeView(
    model,
    delegate=delegate,
    root_visible=True,
    header_visible=False,
    column_widths=[ui.Fraction(3), ui.Fraction(1), ui.Pixel(28)],
    min_column_widths=[ui.Pixel(160), ui.Pixel(80), ui.Pixel(28)],
    columns_resizable=True,
    drop_between_items=True,
)
```

Important APIs (verified against `bindings/BindTreeView.h`):

- `tree.selection` — read/write the current list of selected items.
- `tree.clear_selection()`
- `tree.toggle_selection(item)`
- `tree.extend_selection(item)`
- `tree.set_selection_changed_fn(fn)` — `fn(items: list)`.
- `tree.set_hover_changed_fn(fn)` — `fn(item)`.
- `tree.is_expanded(item)`
- `tree.set_expanded(item, expanded, recursive)`
- `tree.dirty_widgets()` — force a redraw of all visible row widgets.

Selection callbacks can transiently receive lists containing `None` entries during rebuild/filter transitions, especially around `_item_changed(None)`. Filter `None` before converting selected items to paths or publishing them to a selection bus.

Important properties:

- `delegate`
- `column_widths`
- `min_column_widths`
- `columns_resizable`
- `fixed_width_columns`
- `resizeable_on_columns_resized` — note the unusual spelling (a single `e` between `resiz` and `able`, then a doubled `e` cluster). This is the canonical name in `BindTreeView.h:31` and `BindTreeView.h:59`; the spelling is non-negotiable.
- `header_visible`
- `root_visible`
- `root_expanded`
- `expand_on_branch_click`
- `keep_alive`
- `keep_expanded`
- `drop_between_items`

## TreeView Internal Mental Model

TreeView maintains a node cache keyed by item object identity. Each node tracks children, row widgets, branch widgets, expansion, selection, hover, row height, active state, and drag/drop state.

Population is lazy:

- Child nodes are populated when the parent is expanded or traversed.
- Row widgets are populated when the row is visible.
- Large trees do not build every row up front.
- Average row height is used as an estimate before rows have been measured.

This design is why stable item identity matters. If a model rebuild creates new item objects for paths that already existed, TreeView treats them as unrelated rows.

## Column Widths

`column_widths` uses the same `Length` units:

- Pixel widths are fixed and DPI-scaled.
- Percent widths are percent of the TreeView width.
- Fraction widths share remaining width after fixed/percent columns.

Missing column widths default to `Fraction(1)`. `min_column_widths` clamps computed widths. Resizable columns draw a splitter between columns. When `resizeable_on_columns_resized=True`, resizing tends to convert widths to pixels and can change the TreeView width; otherwise adjacent columns are adjusted.

For stage-like trees, use fixed utility/icon columns and fractional name/type columns:

```python
column_widths = [ui.Fraction(3), ui.Fraction(1), ui.Pixel(28)]
min_column_widths = [ui.Pixel(180), ui.Pixel(80), ui.Pixel(28)]
```

## Selection

TreeView row selection is handled by the widget, but complex apps mirror it to a domain selection bus.

Patterns from the reference Stage Browser:

- Tree callback writes `model._selected_items`.
- Convert selected items to stable domain paths.
- Publish paths to a selection bus with a source tag.
- On external bus events, resolve paths back to items, expand ancestors, assign `tree.selection`, and refresh old/new rows.
- Use a guard flag to avoid publish loops.

Modifier gestures:

- Plain click selects one row.
- Ctrl toggles a row.
- Shift range-selects across the currently expanded flat row list.
- Clicking empty space clears selection.

If delegate-only selected chrome changes, call `_item_changed(item)` on old and new items so row decorations update.

## Expansion

Expansion is stored by item object identity inside TreeView. To persist across model rebuilds, store domain keys (for example USD prim paths) in the model and reapply them after rebuild.

Reference expansion-persistence pattern:

1. Before a structural rebuild, snapshot live expansion with `tree.is_expanded(item)` into a set of paths.
2. Reuse existing item objects from a path cache when loading children.
3. After `_item_changed(None)`, schedule restore on the next frame because `tree.set_expanded()` is a no-op for items TreeView has not walked yet.
4. Resolve paths by walking from the root and lazy-loading ancestors.
5. Retry a small number of frames if `tree.is_expanded(item)` does not stick immediately.

Do not update persisted expansion state from `build_branch()`; that method runs on every render and can erase authoritative state during rebuild.

## Editing And Rename

Inline rename is usually delegate state, not model state:

- A controller marks an item as being renamed.
- The delegate's name column builds a `ui.StringField` instead of a `ui.Label`.
- The field model is initialized with current text.
- `add_end_edit_fn` commits to the domain adapter.
- `set_key_pressed_fn` handles Escape cancellation.
- After commit/cancel, controller clears rename state and calls `_item_changed(item)`.

Avoid creating a new domain item during rename; update the cached value model or invalidate it and refresh the row.

## Drag And Drop

TreeView has item-model drag/drop:

- `get_drag_mime_data(item)` returns a MIME string. Empty string can mean not draggable.
- During hover, `drop_accepted(target_item, source_item_or_string, drop_location=-1)` is called.
- On release, `drop(target_item, source_item_or_string, drop_location=-1)` executes.
- With `drop_between_items=True`, TreeView converts top/bottom row zones into child insert indices. `drop_location == -1` means drop onto the target item; `drop_location >= 0` means insert into a parent at that index.

Reference drag/drop patterns:

- Stage hierarchy validates reparent operations before allowing drop.
- Layers tree supports both item sources and string/file payloads.
- Drop-visual controllers store transient valid/rejected target state; delegates paint overlays by reading that state.
- Hover validation must clear stale drop visuals when the source/target becomes invalid.
- The final `drop()` must validate again; the model may have changed since hover.

## Filtering And Lazy Loading

Filtering belongs in the model:

- Store filter text/predicates on the model.
- Clear/rebuild affected child caches.
- Return only visible children from `get_item_children`.
- Preserve ancestors of matches with a `child_filtered` or similar flag.
- Call `_item_changed(None)` for full filter changes.

Large hierarchy pattern:

- `can_item_have_children` should avoid materializing every child if possible.
- Load children on first expansion.
- For very large child lists, load the first batch and add "load more" behavior or staged model updates.
- Call `_item_changed(parent_item)` after adding a batch.

Use `keep_alive=True` when filtering huge trees and item churn would otherwise destroy/recreate many row widgets.

## Stage Hierarchy Tree From Atomic Primitives

Do not reuse `ovui_widgets.stage.widget.StageWidget` or `StageWindow` when the user asks for atomic widgets. Inspecting them for patterns is allowed; importing them is not. Recreate the pattern from atomic widgets.

The pattern below is distilled from the reference `ovui_widgets/stage/widget/hierarchy_model.py` and `stage_widget.py`. File:line references are provided so the agent can verify when in doubt — but the agent must reimplement, not import.

Model responsibilities:

- Keep a stable item (`PrimItem` / `HierarchyItem`) per prim path. Store it in `self._path_cache: dict[str, PrimItem]` (`hierarchy_model.py:117`).
- Store parent pointer, adapter item/prim handle, and a lazily-instantiated `children: list[PrimItem] | None` on each item.
- Lazy-load children from the adapter on first access to `get_item_children(item)`. Use a small batch size (the reference code uses 100) for very large parents to avoid stalls.
- Keep value models on the item: `name_model`, `type_model`, `visibility_model`, and any status models. Instantiate lazily and cache.
- Cache derived flags/badges (inactive, default prim, class, abstract, instance proxy, references, payloads, inherits, specializes). Track a `flags_dirty` bit so re-derivation is on-demand.
- Track a per-item `filtered` and `child_filtered` flag for filter rendering. Both: this item passes the filter, or any descendant does.
- Subscribe to stage change notices or adapter events.
- On structural changes, snapshot expansion (`set[str]` of paths) before invalidating, then invalidate children, prune stale path cache entries, and call `_item_changed(None)`.
- On flag/value changes only, keep item object identity and call `_item_changed(item)` or `_value_changed()` on the relevant inner model.
- Guard re-entrant selection updates with a boolean flag (`self._selection_guard`) so external bus events do not feed back into the bus.

Delegate responsibilities:

- `build_branch(model, item, column_id, level, expanded)` — only handles column 0. Indent by `level * INDENT`, draw a chevron image (or text glyph) only when `model.can_item_have_children(item)` is true. Do **not** write expansion state into model data from `build_branch`; this method runs on every render and can clobber authoritative state.
- `build_widget(model, item, column_id, level, expanded)` — dispatches per column:
  - column 0 (Name): icon slot + composition badges + label (or `ui.StringField` in rename mode).
  - column 1 (Type): low-emphasis label backed by `type_model`.
  - column 2 (Visibility): `ui.ZStack` with a label/icon underneath and a `ui.InvisibleButton` on top whose `set_clicked_fn` toggles the boolean visibility value model. Use the inverted convention from `visibility_value_model.py` if it makes downstream styling simpler.
- `build_column_header(column_widths)` — manual header row drawn above the TreeView (see `stage_delegate.py:111`). Use the same `column_widths` list both here and on the TreeView so columns stay aligned.
- Context menu / right-click: build `ui.Menu` at mouse position and **store it on `self`** so Python keeps it alive until dismissed.
- Rename: a separate controller object swaps the label for a `ui.StringField` when an item is in rename mode; the controller commits via the adapter and clears the rename flag.
- Drop visuals: a separate drop-visual controller stores transient valid/rejected target state; the delegate paints row overlays by reading that state.

Expansion-persistence pattern (`hierarchy_model.py:121-122`, `stage_widget.py:250-253`):

1. Before any rebuild, snapshot live expansion: iterate visible items and store `item.path` into `self._expanded_paths` for every item where `tree.is_expanded(item) is True`.
2. After `_item_changed(None)`, schedule a restore on the next frame using `ui.next_frame()` or an equivalent deferred callback. The first paint must complete before `tree.set_expanded()` will actually expand items it has not yet walked.
3. For each saved path: resolve it via `model.resolve_path(path)` (which walks from root, calling `get_item_children` to lazy-load ancestors), then call `tree.set_expanded(item, True, recursive=False)`.
4. Retry resolution up to a small number of frames in case path resolution depends on adapter events not yet applied.

This is why item-object identity matters: if the rebuild creates a new `PrimItem` for a path that already had one, the snapshot becomes useless because the new item is not the one TreeView's internal node cache remembers as "expanded". Always read from and write into `path_cache`.

Stage selection integration:

- Tree -> bus: selected items -> prim paths -> publish.
- Bus -> tree: paths -> resolve items -> expand ancestors -> assign `tree.selection`.
- Viewport pick -> bus -> tree follows selection.

## Failure Modes

- Selection/expansion resets: item object identity changed; add a path cache or reuse items.
- No row update after data change: forgot `_item_changed()` or `_value_changed()`.
- Chevrons wrong: `can_item_have_children()` is too expensive, stale, or inconsistent with `get_item_children()`.
- Inline controls do not update: delegate returned new value models on every call; cache them on items.
- Header gap above rows: avoid TreeView's built-in header; build a manual header and use a clipping/Placer workaround if needed.
- Drag hover is stale: `drop_accepted()` did not clear previous visual state on rejection/exit.
- External selection path does nothing: ancestors are collapsed and item has never been walked; resolve by walking from root and retry expansion next frame.
- Huge tree is slow: eager child creation, eager value-model creation, or delegate does too much work per visible row.
