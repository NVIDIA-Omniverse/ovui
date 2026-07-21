# SRD Viewport Public API

This document records the ovui viewport API that supports the SRD vfi backend
architecture. vfi embeds the stock ovui viewport behavior through these public
seams; it must not copy viewport internals or draw browser-side manipulator
handles.

## Surface And Widget

`ovui_widgets.viewport.ViewportSurface` is the embeddable viewport body. It owns
the same renderer image layer, SceneView, camera gestures, pick and
marquee gestures, transform manipulator, tool registry, HUD update path, and
frame hooks used by the desktop viewport.

Hosts may build it in the current UI context:

```python
surface.build()
```

or install it into a caller-owned frame:

```python
surface.build_into(frame)
```

`ViewportWidget` remains the desktop `ManagedWindow` wrapper around
`ViewportSurface`. Backend stream hosts should use `ViewportSurface` when they
own the stream window/frame.

## Hidden Chrome

`ViewportChromeOptions` controls server-side viewport chrome:

```python
ViewportChromeOptions(
    show_toolbar=False,
    show_text_hud=False,
    show_livestream_overlay=False,
    show_anchored_panels=False,
)
```

The default options preserve desktop behavior. Setting all four fields to
`False` hides the server toolbar, textual HUD, livestream overlay, and anchored
panels while keeping the renderer image, SceneView, camera gestures, picking,
marquee selection, transform manipulator, tool registry, and frame update flow
active.

## Backend-Owned Inputs

`ViewportSurface` receives backend-owned collaborators through its constructor
and public methods:

- `renderer`: the renderer adapter used for viewport pixels;
- `bus`: the authoritative selection bus;
- `services.selection_bus`: the service surface used by viewport internals;
- `stage_adapter_provider`: a callable returning the live stage adapter;
- `attach_stage(...)`: stage, transform, undo, snap, and renderer wiring;
- `sync_selection_from_bus()`: public mirror from the authoritative selection
  bus into renderer highlights, manipulator registry, and transform model.

The selection sync method does not synthesize selection or transform state. It
copies the current bus snapshot into the stock viewport state that already owns
selection outline and manipulator visibility.

## Streamed Transform Gestures

Browser/AppStreamer input arrives in stream-pixel coordinates. The public
streamed transform route is:

```python
surface.handle_streamed_transform_pointer_event(
    event_type="button" | "move" | "key_down" | "cancel",
    x=<stream-x>,
    y=<stream-y>,
    button=<button>,
    pressed=<bool>,
    modifiers=<modifiers>,
    key_code=<key>,
    width=<stream-width>,
    height=<stream-height>,
)
```

This method routes pointer input into the real ovui transform gesture/model
path. It hit-tests the real viewport-projected translate handles and then
drives the existing `PrimTranslateChangedGesture` lifecycle. Escape or a
`cancel` event cancels the live preview without committing. Mouse release
commits through the real backend undo/command path.

`get_streamed_transform_handle_projections(width, height)` is a read-only QA
diagnostic. It returns the real viewport-projected handle segments computed
from the same camera, pivot, and scale path used by the streamed gesture route.
It must not be used to synthesize handles or transform state.

## No-Fake Boundary

ovui owns viewport interaction visuals inside the stream:

- camera interaction remains backend/ovui camera behavior;
- point pick and marquee stay viewport/backend hit-test behavior;
- selection outline and transform manipulators are drawn in the backend
  viewport pixels;
- transform preview, cancel, and commit use the real gesture/model/undo path.

React may render toolbar and HUD chrome outside the video, but React must not
draw viewport hit-test overlays, transform handles, SVG/canvas gizmos, or
synthetic manipulator state.

## Targeted Verification

Run these ovui checks after changing this API:

```bash
_venv312/bin/python -m py_compile \
  ovui-widgets/ovui_widgets/viewport/viewport_widget.py \
  ovui-widgets/tests/test_viewport_widget.py

_venv312/bin/python -m pytest -q \
  ovui-widgets/tests/test_viewport_widget.py \
  ovui-widgets/tests/test_transform_manipulator.py
```
