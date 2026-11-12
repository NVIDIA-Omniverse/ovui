# Driving A Renderer Directly From An Atomic Viewport Shell

The `omniverse-ui-apis` skill builds the viewport shell from ovui primitives. ovui contains no renderer, so the renderer side lives here, with the application packages.

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
- When the viewport size changes, write only the `resolution` of the session render product (`renderer.write_attribute([product_path], "resolution", np.array([[w, h]], dtype=np.int32))`), and do it when the size has stayed the same for 200 ms; until then, render at the old size and scale the image. After the write, call `renderer.reset()`: the rendering history still holds the frames of the old size, and without the reset the picture at the new size stays smeared and ghosted after the renderer settles. Do not remove and add the session layer for a resize.
- Return black frames (`np.zeros((h, w, 4), dtype=np.uint8)`) instead of raising on transient renderer failures.
- Support `pick(x, y, callback, query_name)`, `pick_rect(...)`, `set_selection_highlight(paths)`, and `shutdown()`.

For a validation prototype, build a temporary atomic shell rather than importing `ViewportWidget` or any high-level adapter. Call `ovrtx.Renderer` directly. If the prototype needs picking or selection highlighting and the user has not pre-authorized using an adapter, **stop and ask the skill maintainer to authorize the adapter or extend the skill** — recreating the picking ray and AABB pipeline from scratch is out of scope.

## Recipe: Direct Renderer Path

ovrtx direct renderer path (sketch):

```python
import os
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")  # required before import
# In local shells with user-site usd-core installed, launch with:
# PYTHONNOUSERSITE=1 PYTHONPATH="${OVRTX_ROOT}/python:${OVUI_REPO}/ovui/python:..."

import numpy as np
import ovrtx
from ovrtx import Device

_SESSION_ROOT = "/MyPrototypeSession"
_RENDER_PRODUCT_PATH = f"{_SESSION_ROOT}/Render/Viewport"

SESSION_USDA = """#usda 1.0
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
"""

renderer = ovrtx.Renderer()
renderer.add_usd("/path/to/scene.usda")
renderer.add_usd_layer(SESSION_USDA, path_prefix=_SESSION_ROOT)

dt = max(1.0 / 300.0, min(0.1, 1.0 / 60.0))
products = renderer.step({_RENDER_PRODUCT_PATH}, delta_time=dt)
product = products[_RENDER_PRODUCT_PATH]
rv = product.frames[0].render_vars["LdrColor"]
with rv.map(device=Device.CPU) as mapping:
    frame = np.array(mapping.tensor.numpy(), copy=True)  # copy before context exits
```

`frame` is `(H, W, 4)` uint8 RGBA — feed it straight into `ImageBridge.update(frame)`.

If the agent needs more than this — pick rays, selection highlight, GPU zero-copy, or the resolution change on resize — stop and ask the skill maintainer to authorize the high-level adapter or extend this skill.
