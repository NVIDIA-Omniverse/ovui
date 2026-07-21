# Ovui Layout Reference

This reference summarizes the low-level layout behavior used by ovui and by the reference Stage Browser, Layers, Property, Content, and Viewport panels.

## Length Units

`omni.ui.Length` has three units:

- `ui.Pixel(value)` or a raw number in a widget kwarg: fixed pixel length, DPI-scaled internally. `ui.Pixel(-20)` and a raw `-20` are both accepted; the integer form is what the reference code uses (`stage_widget.py:233`).
- `ui.Percent(value)`: percentage of the immediate container's available span (post-spacing, post-fixed-children), not of the whole window.
- `ui.Fraction(value)`: weighted share of remaining space in a stack's consecutive axis, or fill against the available span in a non-stacked direction. `ui.Fraction(1)` and `ui.Fraction(3)` mix freely; only their ratios matter once fixed/percent children have been subtracted.

Default widget `width` and `height` are `ui.Fraction(1)`. This is why an unqualified `ui.Label()` or `ui.Frame()` fills its parent in the relevant dimension.

Use explicit lengths for fixed-format UI: row heights, toolbar buttons, icon slots, TreeView columns, resize gutters, and hit targets. Use fractions for proportional space distribution in a row or column.

### Picking units

| Need | Use |
|------|-----|
| Toolbar button, row height, icon slot, separator line | `ui.Pixel(n)` |
| TreeView name column vs. type column ratio | `ui.Fraction(3)` and `ui.Fraction(1)` |
| Fixed action column at the right edge | `ui.Pixel(28)` |
| Side panel that should always be 30% of the parent dock | `ui.Percent(30)` (but prefer dock ratios when docked) |
| Spacer that pushes content to the far edge | `ui.Spacer()` (default `Fraction(1)`) |
| Gutter of exactly 8 px | `ui.Spacer(width=ui.Pixel(8))` |

Avoid `ui.Fraction` in `ui.HGrid`/`ui.VGrid` along the growth direction — the grid's content-size path does not size fractions well there.

## Widget Geometry And State

Every `ui.Widget` has `width`, `height`, `visible`, `enabled`, `selected`, `checked`, `name`, `identifier`, `style_type_name_override`, `style`, `tooltip`, and mouse/key/drag/drop callbacks. Runtime geometry is available through read-only properties such as `computed_width`, `computed_height`, `computed_content_width`, `computed_content_height`, `screen_position_x`, and `screen_position_y`.

Most construction is contextual:

```python
with ui.VStack(spacing=0):
    ui.Label("Header", height=ui.Pixel(22))
    with ui.HStack(height=ui.Pixel(28), spacing=4):
        ui.Button("A", width=ui.Pixel(60))
        ui.Spacer()
        ui.Button("B", width=ui.Pixel(60))
```

Widgets are added to the active container created by the surrounding `with` block.

## Frame

`ui.Frame` holds a single child. It is used for cropping, lazy rebuilding, background isolation, and embedding a child in a larger region.

Important properties (canonical names from ovui bindings, `BindFrame.h`):

- `build_fn` / `set_build_fn(fn)`: lazy build callback; call `frame.rebuild()` to rebuild on the next visible draw.
- `horizontal_clipping` and `vertical_clipping`: clip the child to the frame in that axis. These are the documented init kwargs. (The reference code sometimes passes `clipping=True` because the standalone wrapper accepts it as an alias; prefer the explicit names in new code.)
- `separate_window`: emit the child as a separate ImGui window when needed.
- `raster_policy`: controls cached rasterization (`ui.RasterPolicy.NEVER` to disable).
- `set_tooltip_fn`/`tooltip`.

`ui.CollapsableFrame` is the related collapsible-section container used by the Property Inspector (`ovui_widgets/property/group_widget.py:106-112`):

```python
ui.CollapsableFrame(
    title="Transform",
    collapsed=False,
    height=FIT_CONTENT_HEIGHT,
    style_type_name_override="Property.GroupFrame",
    build_header_fn=build_custom_header,  # optional custom header row
)
```

Use `CollapsableFrame` for grouped sections that should expand/collapse; use plain `Frame` everywhere else.

Frame sizing behavior:

- Pixel length is fixed.
- Percent length is relative to the parent-provided available length.
- Fraction length fills the available length.
- If clipping is disabled, a child whose computed content is larger can expand the frame.
- If clipping is enabled, oversized child content is clipped.

The reference code often wraps a panel body in a `ui.ZStack` with a `ui.Rectangle` background under actual content. This avoids painting over the dock tab strip.

## ScrollingFrame

`ui.ScrollingFrame` extends `Frame` with scroll state and scrollbars. Use it to keep filter bars, manual column headers, footers, and toolbars pinned while the body scrolls.

Important properties:

- `horizontal_scrollbar_policy`
- `vertical_scrollbar_policy`
- `scroll_x`, `scroll_y`, `scroll_x_max`, `scroll_y_max`

Policies are `ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED`, `SCROLLBAR_ALWAYS_OFF`, and `SCROLLBAR_ALWAYS_ON`.

For tree panels, a common pattern is:

```python
with ui.VStack(spacing=0):
    build_filter_bar()
    build_manual_header()
    with ui.ScrollingFrame(
        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
        vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
    ):
        ui.TreeView(model, delegate=delegate, header_visible=False)
    build_footer()
```

## Stacks

`ui.Stack` lays out children in one of six directions. `ui.HStack`, `ui.VStack`, and `ui.ZStack` are convenience variants.

Directions:

- `LEFT_TO_RIGHT`, `RIGHT_TO_LEFT`
- `TOP_TO_BOTTOM`, `BOTTOM_TO_TOP`
- `BACK_TO_FRONT`, `FRONT_TO_BACK`

Properties:

- `spacing`: fixed pixel gap between visible children.
- `content_clipping`: clip stack content.
- `send_mouse_events_to_back`: important for overlapping `ZStack` hit testing.

### HStack and VStack Fraction Rules

Along the consecutive axis (`width` in `HStack`, `height` in `VStack`):

1. Invisible children are skipped.
2. Spacing is subtracted from the available length first.
3. Pixel and percent children are computed first.
4. Pixel values consume fixed space.
5. Percent values consume a percentage of the stack's post-spacing available length.
6. Fraction children divide only the remaining length by their fraction weights.

Example:

```python
with ui.HStack(width=ui.Pixel(1000), spacing=10):
    ui.Frame(width=ui.Pixel(200))      # 200 px
    ui.Frame(width=ui.Percent(25))     # 25 percent of 980 = 245 px
    ui.Frame(width=ui.Fraction(1))     # half of remaining
    ui.Frame(width=ui.Fraction(1))     # half of remaining
```

The two fractions share `1000 - 20 spacing - 200 - 245 = 535` px.

Along the simultaneous axis (`height` in `HStack`, `width` in `VStack`), `Fraction` behaves like fill against the available span rather than a weighted share.

## ZStack And Overlays

`ui.ZStack` overlays children. It is the standard tool for:

- Drawing a full-row/background `ui.Rectangle` behind content.
- Layering an `ui.InvisibleButton` over icons or custom row chrome.
- Viewport panels: rendered image, `SceneView`, HUD, status overlays.
- Empty-state overlays above a TreeView or content region.

Put non-interactive visual layers underneath hit targets. If image/icon layers block clicks, set `enabled=False` and `opaque_for_mouse_events=False` where supported.

## Grid

`ui.Grid` arranges children in rows/columns. `HGrid` and `VGrid` control growth direction. It supports `column_width`, `row_height`, `column_count`, and `row_count`.

Avoid fractional child sizes in the grid's growing direction. The grid content-size path treats fractions poorly in that dimension. Prefer explicit pixel cell sizes or derive counts from fixed `column_width`/`row_height`.

Use grids for uniform cards, thumbnails, icon sheets, and repeated controls, not for complex panels with pinned headers and proportional panes.

## Placer

`ui.Placer` positions one child by `offset_x` and `offset_y`, each a `Length`.

Offset semantics:

- Pixel offset: fixed DPI-scaled offset.
- Percent offset: percentage of the parent dimension.
- Fraction offset: full parent dimension semantics, not a weighted share.

Important properties:

- `stable_size=True`: child gets the full parent size even when offset.
- `draggable`, `drag_axis`, `frames_to_start_drag`: useful for direct manipulation.

The reference code uses a `Placer` with a negative Y offset to hide the standalone-ovui `TreeView`'s internal top strip behind a clipping frame. The comment in `ovui_widgets/stage/widget/stage_widget.py:215-249` documents this workaround:

> "The standalone `ovui` `TreeView` reserves a ~20-px strip at the top of its body that isn't reachable from the delegate or from any `TreeView.*` style selector. We hide it by placing the TreeView inside a clipping `ui.Frame` with a negative top margin via a `ui.Placer` — the first row slides up so it sits flush under our manual column header."

```python
_TREEVIEW_TOP_OFFSET = 20

with ui.Frame(horizontal_clipping=True, vertical_clipping=True):
    with ui.Placer(offset_y=-_TREEVIEW_TOP_OFFSET, stable_size=True):
        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
        ):
            ui.TreeView(model, delegate=delegate, header_visible=False, column_widths=column_widths)
```

This workaround is observed against the standalone (non-Kit) `ovui` runtime. It is a real, durable observation — not a workaround for a fixed bug.

## Spacer

`ui.Spacer()` consumes remaining fractional space by default. Use fixed spacers for precise gutters:

```python
ui.Spacer(width=ui.Pixel(8))
ui.Spacer()  # push following widgets to the far edge
```

## Nested Panel Patterns

For complex production-style tools:

- Use one outer `ui.VStack(spacing=0)` per panel.
- Use fixed heights for filter bars, column headers, footers, toolbars, and status bars.
- Put the flexible body in a `ui.Frame`, `ui.ScrollingFrame`, or `ui.ZStack` with default fraction size.
- Put overlay empty states and HUDs in the same `ZStack` as the body, above content but below active modal controls.
- Keep row heights stable: Stage rows use about 16 px; property rows about 20 px; toolbar buttons about 24-28 px.
- Keep icon slots fixed so labels do not shift when state badges appear/disappear.

## Docked Workbench Layout Pattern

The reference application (`ovui_widgets/app/application.py:1044-1142`) creates:

1. `self._dockspace = ui.DockSpace(None)` first.
2. Dockable panel windows. The reference application builds these via a `ManagedWindow` base class (`ovui_widgets/common/managed_window.py`) but atomic prototypes should just call `ui.Window(title, dockPreference=ui.DockPreference.MAIN, ...)` directly. Each `Window` has a `.frame` whose content is built via `set_build_fn`.
3. A menu-bar window with flags `NO_DOCKING | NO_TITLE_BAR | NO_RESIZE | MENU_BAR | NO_BACKGROUND`.
4. A status overlay window with `NO_DOCKING | NO_TITLE_BAR | NO_RESIZE | NO_MOUSE_INPUTS` and `fill_app_window=True`. Inside, a `ui.VStack` with `ui.Spacer()` pushes the status row to the bottom so the rest of the window stays transparent.
5. `await ui.next_frame()` before any programmatic `dock_in()` call, because ImGui dock IDs do not exist before the first rendered frame.

Programmatic docking:

```python
await ui.next_frame()
viewport_handle = ui.Workspace.get_window("Viewport")
if viewport_handle is not None and viewport_handle.dock_id != 0:
    stage_window.dock_in(viewport_handle, ui.DockPosition.LEFT, ratio=0.20)
    property_window.dock_in(viewport_handle, ui.DockPosition.RIGHT, ratio=0.25)
    content_window.dock_in(viewport_handle, ui.DockPosition.BOTTOM, ratio=0.30)
    stage_handle = ui.Workspace.get_window("Stage Browser")
    if stage_handle is not None and stage_handle.dock_id != 0:
        layers_window.dock_in(stage_handle, ui.DockPosition.BOTTOM, ratio=0.50)
```

`DockPosition` values: `LEFT`, `RIGHT`, `TOP`, `BOTTOM`, `SAME` (`SAME` adds a tab to an existing tab strip).

`DockPreference` values: `DISABLED`, `MAIN`, `RIGHT`, `LEFT`, `RIGHT_TOP`, `RIGHT_BOTTOM`, `LEFT_BOTTOM`. Use `MAIN` for dockable workbench panels.

If `dock_id == 0`, the target window has not been anchored in the dock space yet. Anchor an arbitrary panel into the root DockSpace via `panel.dock_in(None, ui.DockPosition.SAME)` or rely on a saved `imgui.ini` layout to seed dock IDs, then retry on the next frame.

`window.deferred_dock_in(target_window: str, active_window=ui.DockPolicy.DO_NOTHING)` defers docking until the named window exists. `DockPolicy` controls which side wins focus: `DO_NOTHING`, `CURRENT_WINDOW_IS_ACTIVE`, `TARGET_WINDOW_IS_ACTIVE`.

Persisted layouts can be written to `imgui.ini` before startup. Runtime fallback should still call `dock_in()` after the first frame for missing/floating windows.

## Layout Debugging Checklist

- Check `computed_width` and `computed_height` after at least one frame.
- If a widget is invisible, verify parent `visible`, zero size, clipping, and `visible_min/visible_max`.
- If fractions seem wrong, subtract spacing and fixed/percent siblings first.
- If a scrolled body moves the header, the header is inside the `ScrollingFrame`; move it above.
- If a click hits the wrong overlay, inspect `ZStack` order and `opaque_for_mouse_events`.
- If a dynamic viewport freezes, use `raster_policy=ui.RasterPolicy.NEVER` on the window or invalidate raster explicitly.
