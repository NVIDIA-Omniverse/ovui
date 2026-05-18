# Inputs, Windows, Docking, Viewport, Styling, And QA

This reference covers interaction systems, window management, docking, viewport-adjacent ovrtx embedding, styling, lifecycle, and validation.

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
- `key_pressed_fn(key, modifiers, pressed)` should ignore key release unless needed.

Common patterns:

- Escape cancels inline rename or closes a popup.
- Delete/Backspace acts on the focused tree/panel.
- W/E/R switch viewport transform tools.
- Ctrl/Shift alter selection behavior.

## Windows

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
3. Renderer loop: an ovrtx renderer or adapter that produces frames and supports pick/highlight APIs.

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

ovrtx basics (verified against the reference `ovrtx/python/ovrtx/_src/renderer.py`):

- `renderer = ovrtx.Renderer(config=None)`
- `renderer.add_usd(usd_file_path: str, path_prefix: Optional[str] = None)` loads a USD file from disk.
- `renderer.add_usd_layer(usd_layer_content: str, path_prefix: Optional[str] = None)` composes a USDA string (a session layer with camera + render product) under an optional prefix.
- Load order matters: set environment/import order first, construct `ovrtx.Renderer()` early, call `renderer.add_usd(scene_path)` first for the root stage, and only then call `renderer.add_usd_layer(session_usda, path_prefix=...)` for session camera/render-product scaffolding. Calling `add_usd_layer(...)` before the root scene and then `add_usd(...)` can fail with `Root layer can only be added to an empty stage`.
- `products = renderer.step(render_products: set[str], delta_time: float)` returns a dict-like `RenderProductSetOutputs`. Index it as `products[render_product_path]`; each value has `.frames`, and each frame has `.render_vars` keyed by render-var name.
- Map a render var to CPU memory inside a context manager, then **copy the tensor before exit** because the underlying buffer is unmapped on `__exit__`:

```python
import numpy as np
from ovrtx import Device

with rv.map(device=Device.CPU) as mapping:
    arr = mapping.tensor.numpy()
    arr = np.array(arr, copy=True)  # mandatory before context exit
```

- `LdrColor` is the standard 8-bit RGBA output. Shape: `(H, W, 4)` uint8.
- Clamp `delta_time` to `[1/300, 0.1]` seconds. Larger values can destabilize ovrtx sensors on stalled frames.

Session-USDA template (the camera + render product + var triplet ovrtx needs). All paths nest under a single root so they cannot collide with the user's stage. The reference adapter uses a fixed session root; a prototype can use any unique root (e.g. `/MyPrototypeSession`):

```usda
#usda 1.0
(
    defaultPrim = "MyPrototypeSession"
    upAxis = "Y"
)

def Scope "MyPrototypeSession"
{
    def Scope "Cameras"
    {
        def Camera "Main"
        {
            float focalLength = 18
            float horizontalAperture = 20.955
            float verticalAperture = 15.2908
            float2 clippingRange = (0.01, 10000)
            token projection = "perspective"
            matrix4d xformOp:transform = ( (1,0,0,0), (0,1,0,0), (0,0,1,0), (0,0,0,1) )
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }
    }
    def Scope "Render"
    {
        def RenderProduct "Viewport"
        {
            rel camera = </MyPrototypeSession/Cameras/Main>
            rel orderedVars = </MyPrototypeSession/Render/Vars/LdrColor>
            uniform int2 resolution = (1280, 720)
        }
        def Scope "Vars"
        {
            def RenderVar "LdrColor"
            {
                uniform string sourceName = "LdrColor"
            }
        }
    }
}
```

Do not compress USDA metadata or prim bodies into single-line forms such as `( defaultPrim = "X" upAxis = "Y" )` or `def RenderVar "LdrColor" { ... }`; the local USD parser rejected those forms during validation. Load the root scene first, then load the session layer with `renderer.add_usd_layer(usda_string, path_prefix="/MyPrototypeSession")`, and step with `renderer.step({"/MyPrototypeSession/Render/Viewport"}, delta_time=dt)`.

Per-frame camera updates (push intrinsics + world xform into the camera prim) use `renderer.write_attribute([camera_path], "omni:xform", world_mat_4x4, semantic=Semantic.XFORM_MAT4x4)` for the world transform. Intrinsics (focal length, aperture, clipping range) are pushed via separate `write_attribute` calls; for a simple prototype these can be left at the default in the USDA layer.

The reference `OvRtxRendererAdapter` adds the production details (`ovui_data_adapters/openusd/renderer_adapter.py`):

- Import `ovrtx` lazily and set `os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")` before import.
- Construct the ovrtx renderer before the first `pxr.Usd.Stage.Open` in the same process to avoid USD/MDL load-order conflicts.
- In environments where a user-site `pxr` from `usd-core` collides with ovrtx's bundled USD and crashes with `TF_SCRIPT_MODULE_LOADER` / USD/MDL load-order errors, launch viewport prototypes with `PYTHONNOUSERSITE=1`, set `PYTHONPATH` to only the needed local ovui and ovrtx checkouts, and if numpy disappears under `PYTHONNOUSERSITE`, symlink or copy `numpy`/`numpy.libs` into a temporary site directory instead of exposing the whole user-site. Import/construct ovrtx before opening any `pxr.Usd.Stage`.
- Mirror camera intrinsics and world transform into ovrtx each frame. Convert a GL view matrix to USD world-row form (transpose `inverse(view)`).
- Reinject the session layer when render resolution changes, with a debounce window during active resize (8 px threshold, 200 ms active window, 250 ms debounce).
- Return black frames (`np.zeros((h, w, 4), dtype=np.uint8)`) instead of raising on transient renderer failures.
- Support `pick(x, y, callback, query_name)`, `pick_rect(...)`, `set_selection_highlight(paths)`, and `shutdown()`.

For a validation prototype, build a temporary atomic shell rather than importing `ViewportWidget` or any high-level adapter. Call `ovrtx.Renderer` directly. If the prototype needs picking or selection highlighting and the user has not pre-authorized using an adapter, **stop and ask Victor to authorize the adapter or extend the skill** — recreating the picking ray and AABB pipeline from scratch is out of scope.

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
- Use PNG/raster assets with standalone ovui when SVG loading is unreliable.
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
