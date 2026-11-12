# Inputs, Windows, Docking, Viewport, Styling, And QA

This reference covers interaction systems, window management, docking, viewport-adjacent renderer embedding, styling, lifecycle, and validation.

## Basic Controls

Buttons:

- `ui.Button(text="", clicked_fn=..., image_url=..., image_width=..., image_height=..., spacing=...)`
- `ui.InvisibleButton(...)` for custom hit targets over a `ZStack`.
- `ui.ToolButton(model=ui.SimpleBoolModel(...))` for toggle-like tool buttons.

Use an `InvisibleButton` when the visual design is custom: draw `Rectangle`/`ImageWithProvider`/`Label` underneath, then place the invisible hit target on top.

Check boxes and toggles:

- `ui.CheckBox(model=...)`
- `ui.ToolButton(model=...)`
- Use `model._value_changed()` when external state changes.

Text fields:

- `ui.StringField(model=..., read_only=..., multiline=..., password_mode=..., allow_tab_input=...)`
- `ui.StringFieldLimited(max_length=..., character_limit_reached_fn=...)`
- `field.focus_keyboard()` focuses keyboard input where supported.

Numeric fields and sliders:

- `ui.IntField`, `ui.FloatField`
- `ui.IntSlider`, `ui.UIntSlider`, `ui.FloatSlider`
- `ui.IntDrag`, `ui.UIntDrag`, `ui.FloatDrag`
- `FloatSlider`/`FloatDrag` support `min`, `max`, `step`, `format`, and `precision`.

Combo boxes:

- `ui.ComboBox(current_index, "A", "B")`
- Or pass an `AbstractItemModel`.
- Root model value is the selected index; root children are option rows.

Color widgets:

- `ui.ColorWidget(r, g, b, a)` or model-backed.
- Backing item model normally exposes up to four child value models for RGBA.

## Widget Callbacks

Common callbacks can be passed as kwargs or assigned later with `set_*_fn` methods:

- `mouse_moved_fn(x, y, modifiers, buttons)`
- `mouse_pressed_fn(x, y, button, modifiers)`
- `mouse_released_fn(x, y, button, modifiers)`
- `mouse_double_clicked_fn(x, y, button, modifiers)`
- `mouse_wheel_fn(x, y, modifiers)`
- `mouse_hovered_fn(hovered)`
- `key_pressed_fn(key, modifiers, pressed)`
- `drag_fn() -> str`
- `accept_drop_fn(mime: str) -> bool`
- `drop_fn(event)`, where event has `x`, `y`, and `mime_data`
- `computed_content_size_changed_fn()`
- `checked_changed_fn(checked)`

Set `opaque_for_mouse_events=True` on transparent frames/hit boxes that must receive mouse events. Set `opaque_for_mouse_events=False` on decorative images that should not intercept clicks.

## Menus And Context Menus

Menu bar pattern:

```python
with ui.MenuBar():
    with ui.Menu("File"):
        ui.MenuItem("Open...", triggered_fn=on_open)
        ui.MenuItem("Save", enabled=can_save, triggered_fn=on_save)
```

Context menu pattern:

```python
self._active_menu = ui.Menu("Context")
with self._active_menu:
    for entry in entries:
        ui.MenuItem(
            entry.label,
            enabled=entry.enabled,
            triggered_fn=lambda e=entry: e.run(),
        )
self._active_menu.show_at(float(x), float(y))
```

Important rules:

- Keep a Python reference to the menu while it is shown.
- Closing or hiding a parent menu clears `shown` on popup descendants and emits each closing transition. A descendant with its own visible tear-off window remains open and owns its popup state independently. Destroying the parent closes the full descendant subtree, including tear-offs.
- Destroy or replace the previous menu before showing a new one if stale actions are dangerous.
- Capture loop variables with default arguments in `lambda`.
- Use `ui.Separator()` between non-empty groups.
- Compute `enabled` at build time from current domain state.

## Drag And Drop

For generic widgets:

- `set_drag_fn(lambda: mime_string)` starts a drag with a MIME payload.
- `set_accept_drop_fn(lambda mime: bool)` is called during hover.
- `set_drop_fn(lambda event: ...)` runs on release with `event.mime_data`.

For TreeView, prefer model-level drag/drop (`get_drag_mime_data`, `drop_accepted`, `drop`) so the widget can handle selection drags, between-row inserts, hover state, and auto-scroll.

External file drops often arrive as URL/path strings. Normalize early and validate again at drop time.

## Tooltips And Hover

Use `tooltip="..."` for simple labels. Use `tooltip_fn` for dynamic content. Some widgets support `set_tooltip(...)` after construction.

For dynamic state conveyed by icon only, always provide a tooltip. Example: viewport toolbar buttons should include the tool name and hotkey.

## Keyboard Focus And Shortcuts

The reference application scopes shortcuts by focused window/panel:

- Check `window.focused` for panel-local shortcuts.
- Keep global application shortcuts in one dispatcher.
- Do not let a text field shortcut handler delete stage data while the field is focused.
- A save shortcut must not save a value that an editing field can still cancel. Call `omni.ui.standalone.end_text_input()` to end the edit as a commit (as a click outside the field does), and run the save on the next frame, after the field's end-edit callback. It returns `False` and changes nothing when no field is in typing mode (for example during a mouse drag of a number field); then save at once. The reference application does this for Ctrl+S in the Property Inspector.
- `key_pressed_fn(key, modifiers, pressed)` should ignore key release unless needed.

Common patterns:

- Escape cancels inline rename or closes a popup.
- Delete/Backspace acts on the focused tree/panel.
- W/E/R switch viewport transform tools.
- Ctrl/Shift alter selection behavior.

## Windows

The standalone host window is separate from dockable `ui.Window` widgets.
`omni.ui.standalone.set_window_size(width, height)` can resize it immediately
after `init()`, before a UI loop starts, and returns `True` only when the
framebuffer matches the request. On Windows, resize dimensions are physical
pixels and may exceed the desktop size; `init()` scales its initial dimensions
by the primary monitor's content scale. Read back the framebuffer with
`get_window_size()`. Nonpositive dimensions and headless resizing return `False`.

`ui.Window(title, dockPreference=..., **kwargs)` creates a dockable or floating window. The `frame` property is the content container.

Common flags:

- `ui.WINDOW_FLAGS_NO_TITLE_BAR`
- `ui.WINDOW_FLAGS_NO_RESIZE`
- `ui.WINDOW_FLAGS_NO_MOVE`
- `ui.WINDOW_FLAGS_NO_SCROLLBAR`
- `ui.WINDOW_FLAGS_NO_SCROLL_WITH_MOUSE`
- `ui.WINDOW_FLAGS_NO_COLLAPSE`
- `ui.WINDOW_FLAGS_NO_BACKGROUND`
- `ui.WINDOW_FLAGS_NO_SAVED_SETTINGS`
- `ui.WINDOW_FLAGS_NO_MOUSE_INPUTS`
- `ui.WINDOW_FLAGS_MENU_BAR`
- `ui.WINDOW_FLAGS_FORCE_VERTICAL_SCROLLBAR`
- `ui.WINDOW_FLAGS_FORCE_HORIZONTAL_SCROLLBAR`
- `ui.WINDOW_FLAGS_NO_DOCKING`
- `ui.WINDOW_FLAGS_POPUP`
- `ui.WINDOW_FLAGS_MODAL`
- `ui.WINDOW_FLAGS_NO_CLOSE`

Useful properties and methods:

- `visible`, `title`, `flags`, `width`, `height`, `position_x`, `position_y`
- `auto_resize`, `noTabBar`, `detachable`, `focused`, `docked`, `selected_in_dock`
- `frame`, `menu_bar`, `raster_policy`, `fill_app_window`, `focus_policy`
- `setPosition(x, y)`
- `destroy()`
- `set_top_modal()`
- `dock_in(target_handle, ui.DockPosition.LEFT/RIGHT/TOP/BOTTOM/SAME, ratio=0.5)`
- `deferred_dock_in(target_window: str, active_window=ui.DockPolicy.DO_NOTHING)` — the first arg is named `target_window` in the binding (not `target_title`).

`ui.DockPolicy` values: `DO_NOTHING` (keep current focus, default), `CURRENT_WINDOW_IS_ACTIVE`, `TARGET_WINDOW_IS_ACTIVE`.

`ui.Window.FocusPolicy` values: `DEFAULT`, `FOCUS_ON_LEFT_MOUSE_DOWN`, `FOCUS_ON_ANY_MOUSE_DOWN`, `FOCUS_ON_HOVER`.

Use `ui.RasterPolicy.NEVER` for windows whose content changes externally or every frame, such as viewports and consoles.

## Docking

Core API:

- `ui.DockSpace(None)` creates the root dock area. Construct it before any panel `ui.Window`.
- `ui.Workspace.get_window(title)` returns a `WindowHandle` after windows have rendered at least once.
- `ui.Workspace.get_windows()` lists handles.
- `WindowHandle.dock_id` is non-zero only after ImGui has anchored the window in a dock node.
- `ui.DockPosition`: `LEFT`, `RIGHT`, `TOP`, `BOTTOM`, `SAME`.
- `ui.DockPreference`: `DISABLED`, `MAIN`, `RIGHT`, `LEFT`, `RIGHT_TOP`, `RIGHT_BOTTOM`, `LEFT_BOTTOM`. Use `MAIN` for workbench panels.

Practical sequence:

1. Create `ui.DockSpace(None)` before panel windows.
2. Create all panel `ui.Window` objects with `dockPreference=ui.DockPreference.MAIN`.
3. Build content under each `window.frame` (typically via `frame.set_build_fn(self._build)`).
4. `await ui.next_frame()` at least once so ImGui assigns dock IDs.
5. Fetch target handles with `ui.Workspace.get_window(title)` and check `handle.dock_id != 0` before docking against them.
6. Call `panel_window.dock_in(target_handle, position, ratio=...)`.
7. If a target dock_id is still 0 because nothing has been anchored, dock one panel into the root DockSpace first (e.g. by accepting whatever ImGui places, or by loading an `imgui.ini` layout file at startup), then split the others off that anchor.

Reference default docking pattern:

- Stage Browser docks left of Viewport.
- Property Inspector docks right of Viewport.
- Content docks below Viewport.
- Layers docks below Stage Browser.
- Menu bar is a separate non-dockable top strip.
- Status bar is a non-interactive full-window overlay pushed to the bottom by a `VStack` plus `Spacer`.

Dock IDs are not reliable before the first frame. If `dock_id == 0`, anchor the target in the root DockSpace first, then split.

## Standalone Launch Bootstrap

For temporary standalone prototypes, import `omni.ui` and start the UI event loop explicitly:

```python
import omni.ui as ui

_LIFETIME_REFS = {}

async def main_coroutine():
    _LIFETIME_REFS["workspace"] = await build_workspace()
    while True:
        await ui.next_frame()

if __name__ == "__main__":
    ui.run(main_coroutine())  # blocking standalone launch
```

Use `ui.run_async(main_coroutine())` only when embedding into an already-running compatible event loop. Keep every `Window`, model, delegate, image provider, renderer, and subscription referenced for the app lifetime; otherwise Python garbage collection can silently close menus, drop rows, or stop image updates.

## Modal And Popup Windows

For small dialogs, use a `ui.Window` with `WINDOW_FLAGS_MODAL`, `NO_DOCKING`, `NO_SCROLLBAR`, and fixed width/height. Keep a strong reference until dismissed. On dismiss:

1. Set `visible=False`.
2. Call `destroy()`.
3. Clear Python references and subscriptions.

Do not rely on GC timing for popup teardown.

## Viewport-Like Atomic Shells

A viewport-like panel has three independent concerns:

1. Rendered pixels: `ui.ByteImageProvider` or another image provider displayed via `ui.ImageWithProvider`.
2. Interaction/overlays: `omni.ui_scene.scene.SceneView` for 3D gestures/manipulators, plus `ZStack` HUD layers.
3. Renderer loop: a renderer or adapter that produces frames and supports pick/highlight APIs.

Atomic viewport shell structure:

```python
with ui.VStack(spacing=0):
    build_toolbar_row()
    with ui.ZStack():
        image = ui.ImageWithProvider(
            bridge.provider,
            fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
        )
        scene_view = sc.SceneView()
        with scene_view.scene:
            sc.Screen(gestures=[...])
        build_hud_overlay()
```

`ImageBridge` pattern:

- Own `ui.ByteImageProvider()`.
- Initialize it with an opaque blank `(height, width, 4)` `uint8` array.
- On each frame, call `provider.set_data_array(frame, [w, h])` for CPU frames.
- If using GPU zero-copy, call `set_bytes_data_from_gpu(ptr, [w, h])` synchronously and close the GPU mapping afterward.

The renderer is not part of ovui. To produce real frames, follow `references/renderer-direct.md` in the `omniverse-ui-widgets` skill, which ships with the application packages.

## Styling And Themes

The reference style uses:

- `ui.style.default = merged_style_dict`
- `style_type_name_override="Domain.Component"`
- `name="state"` for style variants such as `"Stage.VisibilityIcon::hidden"` or `"Viewport.Toolbar.Button::active"`
- `omni.ui.color as cl` for shade-aware colors
- `omni.ui.constant as fl` for theme-aware numeric constants

Theme changes:

- Call `ui.set_shade("light")` or `ui.set_shade("default")`.
- Reassign `ui.style.default` with a freshly merged dict.
- Rebuild window frames that painted background rectangles from shade-aware colors.

Icon pattern:

- Resolve icon files with `importlib.resources` or the local style URL helper.
- `ui.Image`, `ui.ImageWithProvider` and `ui.MarkdownWidget` draw `.svg` files in standalone ovui when the build has `OMNIUI_ENABLE_SVG=ON` (the default); the two image widgets draw the file at their content size with the same picture, and the Markdown widget at the size of the file. A bad file, or one over a work limit of the SVG reader or painter, logs one error. `<text>`, `<image>`, `<pattern>` paint, masks, filters, markers and a `transform` on `<svg>` are not drawn (one warning names them), so use PNG/raster assets for those and for builds with `OMNIUI_ENABLE_SVG=OFF` (there an `.svg` draws nothing and logs one error that names the option).
- Cache `ui.RasterImageProvider(path)` per icon path.
- Render with `ui.ImageWithProvider(provider, width=..., height=...)`.

Do not instantiate a new raster provider per row paint in a large TreeView.

## Lifecycle And Cleanup

For windows/panels:

- Store subscriptions and cancel/unsubscribe on destroy.
- Destroy menus/popups before destroying models/delegates they reference.
- Call `window.destroy()` and clear the reference.
- Release renderer resources with `renderer.shutdown()` or the adapter's shutdown method.
- Tear down `DockSpace` after child windows if the app owns the full workspace.

For model-view:

- Keep model/delegate alive as long as the TreeView exists.
- Keep popup menus alive as long as visible.
- Avoid callbacks that close over destroyed objects without guards.

## Strict UI QA Constraints

For interactive UI validation, follow the screenshot-first methodology from the workspace QA prompt:

- Take a screenshot before each action.
- Derive coordinates from screenshots, not guesses.
- Interact only with mouse and keyboard simulation.
- Take a screenshot after each action.
- Do not use Python snippets, API calls, direct state mutation, or programmatic shortcuts to replace user interaction.
- Report failures with evidence rather than working around them.

The concrete module for screenshot and input simulation is `omni.ui.testing`. Useful APIs observed in validation are:

- `omni.ui.testing.capture_screenshot(path_or_name)`
- `omni.ui.testing.mouse_move(...)`
- `omni.ui.testing.mouse_click(...)`
- `omni.ui.testing.mouse_drag(...)`
- `omni.ui.testing.press_key(...)`
- `omni.ui.testing.type_text(...)`
- `omni.ui.testing.wait_frames(...)`

`press_key(key_code)` expects ImGui key codes, not GLFW key codes. Validated examples: Backspace=523, Enter=525, Escape=526. GLFW values such as 259 or 257 may be silently ignored, so inspect the local ImGui key enum or `omni.ui.testing` docs before sending unfamiliar keys.

If an exact call signature is uncertain in a future build, inspect the local `omni.ui.testing` module/signature before use; do not replace user-like interaction with direct widget state mutation.

For lightweight documentation validation, static checks and file inspection are acceptable. Do not run heavy interactive QA unless it directly helps the requested task.

## Process Safety

When managing long-running UI processes, never use `pkill`, `killall`, or pattern-based process killing. Identify the exact PID and kill only that PID when stopping a process is necessary.

## `DragGesture.on_changed` payload rules

- `on_began` and `on_ended` are called once for each drag. `on_changed` is called in each frame of the drag in which the
  payload of the shape changed (the item closest point or the ray closest point is not the one of the previous frame),
  except a frame that only shows the follow of the last call (below). Pointer movements queued before one frame give one
  call, with the payload of the last of them. A frame in which nothing changed gives no call, also when the pointer is held.
- The payload changes when the pointer moves, when the camera moves, and when the shape or an item above it is written by
  any code. Every such change is called, also under a still pointer, however small it is (one unit of the last digit of a
  number counts): a turn, a scale, an edit of the geometry (a `Points` position edit is called with `moved == 0` and the new
  `item_closest_point`), a move of the shape. A color, a thickness or a size is not geometry and is not a change.
- `payload.moved` (and the other `moved_*` values) is the change of the payload values since the last call. The change of a
  frame that has no call stays in the next call, so the `moved` of the calls add up to the change since the drag began.
  `angle` of an `sc.Arc` is continuous across the full turn.
- The follow of the pointer. A consumer that moves the shape, or an `sc.Transform` above it, by the `moved` that a call
  reported gets no second call for that movement. The next frame has the payload of the new place under the same pointer and
  camera; it has no call when the pointer and the camera are the same, nothing has written to the shape or above it since the
  callback returned, and the writes of the callback are the follow. They are the follow when
  - the consumer declares them: `with gesture.following():` around the write, inside the callback or in a later update that
    applies the movement. Use it when the write goes through a model, a stage or a parent that turns or scales (the
    translate gizmo does);
  - or each is exactly what the movement gives, to the last digit, with only plain translations above (no rotation, scale,
    `scale_to`, `look_at` or basis): the translation of one `Transform` is the old one plus `moved`; the translations of several `Transform` are each the
    old one plus `moved` divided by their number; both ends of a `Line`, or every position of a `Points` of any size, are each
    the old one plus `moved`, each written once in the callback (a second write to the same item is called). A consumer that
    writes another number (the start plus the sum of the `moved`, an absolute point) is called whenever that number is not the
    old one plus `moved`: an edit of one unit of the last digit writes the same number, so the call is delivered every time
    and nothing is learned from it. Declare such a write with `following()` to get no call.
- Everything else is called, so a consumer must not drop a call because the pointer ray did not change: a write that is one
  unit of the last digit away from the follow, a snapped write, a write through a parent that turns or scales, an edit of the
  geometry, and a movement that is applied in a later update without `following()`. Such a call has exactly the data of the
  call for an independent edit that writes the same numbers (the payload is a function of the scene only), so the two cannot
  be told apart, and the call is delivered: a lost real update is worse than one extra call.
- The tests are `ovui/tests/scene/test_drag_changed_follow.py`, `test_drag_changed_edits.py` and
  `ovui-widgets/tests/test_translate_gizmo_dispatch.py`.
