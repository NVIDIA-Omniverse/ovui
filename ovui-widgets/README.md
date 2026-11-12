# USD Viewer

Standalone 3D viewport / scene editor built on [`omni.ui`](https://docs.omniverse.nvidia.com/kit/docs/omni.ui)
+ `omni.ui.scene`, rendered through **ovrtx** (NVIDIA's RTX ray tracer).
Kit-free — zero imports from `omni.kit` or `carb`.

## What It Does

USD Viewer loads and edits USD scenes in a GPU-accelerated ray-traced viewport.
It is a small standalone application, not a Kit extension: the window, event
loop, and docking layout are all driven by `omni.ui` standalone and rendered
through either GLFW/OpenGL (desktop) or Vulkan (headless / server).

## Features

- **Viewport** — orbit / tumble / pan / zoom / fly camera with inertia;
  ray-traced rendering via `ovrtx`; HUD (FPS + prim count).
- **Transform Manipulator** — translate gizmo (rotate/scale are stubbed);
  follows selection; real-mouse-drag-tested.
- **Stage Browser** — prim hierarchy with type badges, visibility toggles,
  filter, rename (F2), drag-and-drop reparent.
- **Property Inspector** — type-dispatched attribute editors; multi-selection
  mixed-value indicator.
- **Undo / Redo** — full command stack (`Ctrl+Z` / `Ctrl+Y`). Every edit is
  reversible.
- **Themes** — dark / light palettes, switchable at runtime.
- **Settings** — JSON-persisted (grid snap, themes, recent files).
- **USD** — loads `.usd` / `.usda` / `.usdc` / `.usdz`; all stage access lives
  behind an adapter ABC so tests run without USD or a GPU.

## Installing from built wheels (current, supported)

The supported way to install and run the USD Viewer is from the built
distributions. For the OpenUSD provider path you do not need to build USD or
ovui from source (for the native OVStage provider, see below: it needs a compatible
`ovstage` and `ovrtx` pair).

**Release packages:** 0.3.1 includes the `ovui` wheels,
the four `ovui-data-adapters-*` wheels, and the eight `ovui-widgets-*` wheels
(`all`, `app`, `common`, `content`, `layers`, `property`, `stage`,
`viewport`). See [Packages](../README.md#4a-packages) for what each wheel
gives you.

```bash
python -m pip install ovui-widgets-app "ovui-data-adapters-openusd[standalone]" ovrtx
python -m ovui_widgets.app path/to/scene.usda
```

To install from a directory of wheels, add `--find-links /path/to/wheels`. Add
`--pre` while the version in `VERSION.md` is a release candidate: without it,
pip takes the final release from PyPI and ignores the wheels in the directory.

- **Upgrade from 0.2** — include the application package in the upgrade
  command, for example
  `python -m pip install --upgrade --pre --find-links /path/to/wheels ovui-widgets-app "ovui-data-adapters-openusd[standalone]"`.
  From 0.3, each first-party package requires the other first-party packages
  at its own version, so pip also upgrades `ovui`,
  `ovui-data-adapters-common` and the other libraries. Do not upgrade only
  the libraries: the 0.2.0 `ovui-widgets-app` accepts any library version, and
  it does not start with 0.3 libraries.
- **OpenUSD provider (standalone)** — the `standalone` extra installs the
  supported `usd-core==25.11` runtime. If your environment already provides
  a compatible `pxr`, install the plain `ovui-data-adapters-openusd` wheel
  instead and do not add the extra on top of it.
  `usd-core==25.11` has wheels for Python 3.8 to 3.13 and none for Python
  3.14 or 3.15, so the extra, and with it `ovui-widgets-all`, cannot be
  installed on Python 3.14 or 3.15 (`ovui-widgets-all` lists only 3.12 and
  3.13). There, use the OVStage provider or a matching `pxr` from the
  environment.
- **Renderer** — the rendered viewport uses the external `ovrtx` renderer,
  importable from the environment or resolved through `OVRTX_ROOT`. Setting
  `OVUI_WIDGETS_REQUIRE_OVRTX=0` opts into a fallback renderer **only for
  providers that support one** (the OpenUSD provider does); the native
  `ovstage` provider always requires ovrtx in BORROW mode and fails closed.
- **Native OVStage provider** — `ovui-data-adapters-ovstage` drives the
  external native OVStage runtime and attaches ovrtx in BORROW mode for
  rendering and picking. The 0.3.1 provider reads both supported tensor
  layouts; install a compatible `ovstage` and `ovrtx` pair from PyPI. Historical 0.3.0
  wheels need the `ovstage` and `ovrtx` of the 0.3.0 release: with the ones
  that came after 0.3.0, the start camera is zoomed in on the objects and a
  selected prim gets no move gizmo. The section
  [ovstage + ovrtx](../skills/omniverse-ui-widgets-app/SKILL.md#ovstage--ovrtx-native-ovstage)
  of the USD Viewer skill gives the command for each release. A Kit
  rendering build can also supply them, importable from the environment or
  resolved via `OVSTAGE_ROOT` / `OVRTX_ROOT`; see
  [`ovui-data-adapters/docs/kit-runtime.md`](../ovui-data-adapters/docs/kit-runtime.md).
  Durable new-document/save/export/layer-composition workflows are
  unavailable natively. The current native end-to-end validation is Linux;
  Windows native end-to-end validation is incomplete.

Everything from **Prerequisites** through **Install ovrtx**
below is a **historical source-build recipe** (custom non-monolithic USD
build plus early ovrtx builds). It is retained for reference only
and is not the supported installation path; several of its pins and layouts
predate the current distribution topology.

## Prerequisites

- **OS** — Linux (tested on Ubuntu 22.04 with an NVIDIA L40 / DGX Cloud VM).
- **Python** — **3.12** exactly. The `_venv312` layout and the custom USD
  build are both pinned to this ABI.
- **GPU** — NVIDIA GPU with a driver that ships a Vulkan ICD (tested L40).
- **System packages**:

  ```bash
  sudo apt-get install -y \
      build-essential cmake ninja-build \
      libgl-dev libglu-dev libx11-dev libxt-dev \
      libfreetype-dev libglfw3-dev \
      libvulkan1 vulkan-tools \
      xdotool scrot
  ```

  Vulkan **headers** (`vulkan/vulkan.h`) are not in the 22.04 repos. Grab
  them from Khronos:

  ```bash
  mkdir -p ~/.local/include
  curl -L https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.3.204.tar.gz \
      | tar -xz -C /tmp
  cp -r /tmp/Vulkan-Headers-1.3.204/include/vulkan ~/.local/include/
  ```

## Building USD from Source

This historical recipe builds **OpenUSD v25.11** non-monolithically with
**oneTBB 2021.13.x** under Python 3.12. Within this specific custom-build
recipe the PyPI `usd-core` wheel is not used, because the early
`ovrtx` builds it targeted bundled their own USD and conflicted with a
monolithic build. This is not a general statement: the **supported** current
path installs `usd-core==25.11` through the OpenUSD adapter's `standalone`
extra, as described in *Installing from built wheels* above.

### 1. Clone the sources

```bash
mkdir -p ~/dev/usd-build && cd ~/dev/usd-build
git clone --branch v25.11 --depth 1 https://github.com/PixarAnimationStudios/OpenUSD.git
```

### 2. Patch `build_usd.py` to use oneTBB 2021.13.1

`build_usd.py` ships with oneTBB 2021.12.0 pinned; bump the URL:

```bash
sed -i 's|v2021.12.0.zip|v2021.13.1.zip|' OpenUSD/build_scripts/build_usd.py
```

### 3. Install a recent CMake (≥ 3.26)

Ubuntu 22.04 ships 3.22, which is too old for USD 25.11:

```bash
pip install --user 'cmake>=3.26'
export PATH=$HOME/.local/bin:$PATH
```

### 4. Build and install

```bash
PATH=$HOME/.local/bin:$PATH python3.12 OpenUSD/build_scripts/build_usd.py \
    --build-shared \
    --onetbb \
    --imaging \
    --no-usdview \
    --no-materialx \
    --no-examples \
    --no-tutorials \
    --no-tests \
    --no-docs \
    --build-python-info /usr/bin/python3.12 \
                        /usr/include/python3.12 \
                        /usr/lib/x86_64-linux-gnu/libpython3.12.so 3.12 \
    -v -j 12 \
    ~/dev/usd-build/install
```

This takes ~9 minutes on 16 cores. The install lands in
`~/dev/usd-build/install/` with 61 non-monolithic `libusd_*.so` files and
Python bindings under `install/lib/python/pxr/`.

Verify:

```bash
ls ~/dev/usd-build/install/lib/libusd*.so | wc -l      # → 61
PYTHONPATH=~/dev/usd-build/install/lib/python \
LD_LIBRARY_PATH=~/dev/usd-build/install/lib \
python3.12 -c "from pxr import Usd; print(Usd.GetVersion())"
# → (0, 25, 11)
```

## Setting Up the Venv

The `omni.ui` standalone (`ovui`) is the `ovui/` project of this repository.
This recipe uses `~/dev/ovui` for the repository root, so the native project
is `~/dev/ovui/ovui`. USD Viewer installs it editable so both evolve together.

### 1. Create `_venv312`

```bash
cd ~/dev/ovui/ovui-widgets
python3.12 -m venv _venv312
source _venv312/bin/activate
pip install -U pip setuptools wheel
```

### 2. Install `omni.ui` editable from the ovui source tree

```bash
# Point CMake at the Vulkan headers installed above
Vulkan_INCLUDE_DIR=$HOME/.local/include \
    pip install -e ~/dev/ovui/ovui
```

`setup.py` forwards `PYTHON_EXECUTABLE` from the active venv, so the C++
bindings are built against the Python 3.12 ABI automatically. Output lands
in `~/dev/ovui/ovui/python/omni/ui/` and
`~/dev/ovui/ovui/python/omni/ui_scene/`.

### 3. Install USD Viewer in editable mode

The historical top-level `.[dev,usd]` extras no longer exist; the current
distributions live under `ovui-widgets/dist/` and are installed per project.
First-party packages require each other at the same version, so install the
data adapters that `ovui-widgets-common` requires first. The paths are
relative to the repository root, so go there first (step 1 left the shell in
`ovui-widgets/`):

```bash
cd ~/dev/ovui
pip install -e ovui-data-adapters/dist/common
pip install -e ovui-data-adapters/dist/services
pip install -e ovui-widgets/dist/common
pip install -e ovui-widgets/dist/content
pip install -e ovui-widgets/dist/stage
pip install -e ovui-widgets/dist/layers
pip install -e ovui-widgets/dist/property
pip install -e ovui-widgets/dist/viewport
pip install -e ovui-widgets/dist/app
pip install tomli          # used by tests/test_package_distribution.py
```

Any `usd-core` wheel installed in the environment is **shadowed at runtime**
by the custom build on `PYTHONPATH` (see below) when following this
historical recipe.

### 4. Install ovrtx

```bash
pip install ovrtx
```

## Environment Variables

The variables the application reads at runtime. Rows marked *historical
custom-USD recipe only* apply exclusively to the historical source-build
recipe above and are **not** used on the supported built-wheel path:

| Variable              | Value                                           | Why                                                                    |
|-----------------------|-------------------------------------------------|------------------------------------------------------------------------|
| `OVRTX_SKIP_USD_CHECK`| `1`                                             | Bypass ovrtx's startup check that refuses to load when `pxr` is also imported. Required for the viewport to construct `Renderer()` in the same process as the stage adapter. |
| `OVRTX_ROOT`          | path to an external ovrtx install root          | Optional. Used only when `import ovrtx` from the active environment fails; the app checks `$OVRTX_ROOT/python` and `$OVRTX_ROOT`. |
| `OVSTAGE_ROOT`        | path to an external ovstage checkout/install root | Optional. Used only when the ovstage provider is selected and `import ovstage` from the active environment fails; the app checks source-layout Python roots and derives ovstage native runtime paths from the root. |
| `OVUI_WIDGETS_REQUIRE_OVRTX` | unset or `1`                                | ovrtx is required by default. False values allow a fallback only for providers that support one; the native `ovstage` provider always requires OVRTX BORROW and fails closed. |
| `PXR_WORK_THREAD_LIMIT` | unset or a thread count                       | OpenUSD's own setting for its work thread pool. When it is unset, OpenUSD is installed, and the process may use fewer CPUs than the host has (its CPU affinity or its cgroup CPU quota), the application sets it to that CPU count at start, before anything loads OpenUSD, and writes one line about it. A value that you set is kept. |
| `PYTHONPATH`          | `~/dev/usd-build/install/lib/python:$PYTHONPATH`| Historical custom-USD recipe only: resolve `pxr` to the custom 25.11 build ahead of any other `usd-core` wheel in the environment. The supported built-wheel path uses `ovui-data-adapters-openusd[standalone]` (`usd-core==25.11`) and needs no `PYTHONPATH` override. |
| `LD_LIBRARY_PATH`     | `~/dev/usd-build/install/lib:$LD_LIBRARY_PATH`  | Historical custom-USD recipe only: so the 61 non-monolithic `libusd_*.so` files find each other. `omni.ui`'s own native libs set `$ORIGIN` RPATH at build time so they do **not** need to be on this path. Not needed on the supported built-wheel path. |

## Running USD Viewer

On the supported built-wheel path (see *Installing from built wheels* at the
top), no environment exports are required beyond an installed environment:

```bash
ovui-widgets                           # empty stage
ovui-widgets path/to/scene.usda        # open a USD file
python -m ovui_widgets.app             # equivalent to `ovui-widgets`
ovgear                                 # backward-compatible alias
```

For headless / server deployments set `OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan`
before launch; no `DISPLAY` needed.

**When the viewport renders.** By default (`app.renderer.renderPolicy` is
`on_change`) the viewport renders a new picture only after a change: the camera
moves, the viewport size changes, the stage is edited, the selection or a
render setting changes, or another scene opens. After each change it renders
`app.renderer.renderSettleFrames` (512) more frames, so that the renderer's
accumulation settles and the real-time picture is sharp, and then it keeps the
picture on screen. The renderer
keeps some memory on every step, so a viewer that renders a still picture again
and again grows without limit. A change of Eco Mode renders
nothing: Eco Mode only says when the renderer stops refining a still picture.
The renderer gets the value, and the picture stays. Only when Eco Mode stopped
the picture on screen early (before the renderer's default frame limit), and the
change lets the renderer refine it further, is the picture rendered again.
A setting change that keeps the effective value (for example the
reset of a render mode that is set to its default) renders nothing and does not
restart the renderer. The OpenUSD renderer adapter also stores the picture of
each render-settings state (at most 4 pictures, 128 MiB). When Undo or Redo
returns to a stored state and nothing else changed (camera, size, scene,
selection), the stored picture is shown again: no frame is rendered and the
renderer is not restarted. A picture that was left before it settled is
finished while a stored picture is on screen, with steps that are not shown.
The renderer gets the settings of the picture on screen before it renders again.
Path tracing renders until the
sample target (*Total Samples per Pixel*) of the active render product; with no
target (0) it renders every frame. While a livestream, point clouds, render-var
outputs, several render products or a pick need frames, the viewport renders
every frame. The queued render flow of the OVStage provider
(`--/app/renderer/flowMode=fast`) also renders every frame, as before. To render
every frame always, start with `--/app/renderer/renderPolicy=continuous`.

**Historical custom-USD environment only** — when running inside the
historical source-build recipe above, activate its `_venv312` and export its
paths first:

```bash
source ~/dev/ovui/ovui-widgets/_venv312/bin/activate
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH="$HOME/dev/usd-build/install/lib/python:$PYTHONPATH"
export LD_LIBRARY_PATH="$HOME/dev/usd-build/install/lib:$LD_LIBRARY_PATH"
ovui-widgets
```

## Running the Test Suite

From a repository checkout with the `dist/` projects installed (editable or
wheel), the suite needs no USD path exports:

```bash
cd ovui-widgets && pytest tests/ -q
```

Expected: full suite passes (10000+ tests, ~8 s). A small number of
tests are skipped when no GPU or display is available. (Inside the
historical custom-USD environment, activate `_venv312` and export its
`PYTHONPATH`/`LD_LIBRARY_PATH` as shown above before running pytest.)

## Debugging — Why Tests Pass But the Real App Is Broken

**Symptom you will eventually hit:** unit tests and `omni.ui.testing`
integration tests are green, but clicking / dragging in the real window
misbehaves (dead handles, stale gizmo position, selection that doesn't
propagate).

### The classic cause: divergent input paths in `omni.ui.testing`

Historically `omni.ui.testing.mouse_*` wrote directly into
`ImGuiIO::MousePos` / `MouseDown[]` / `MouseWheel`. That is ImGui's
**deprecated** path — it skips the state machine that updates
`io.MouseDownDuration`, so `IsMouseClicked()` and `IsMouseReleased()`
fired on a different timeline than under a real GLFW event. Bugs that
only surfaced under real X11 input passed the test suite silently.

**Fixed in `ovui` commit `65587d5`** — injected events now go through the
queued `io.AddMousePosEvent()` / `io.AddMouseButtonEvent()` API, the same
pipeline GLFW uses. If your `ovui` checkout predates that commit, rebuild
from `main` first.

### Always reproduce with real OS input

When a test passes but the real app breaks, **do not trust the simulated
path** — reproduce with a real mouse or `xdotool`, and take screenshots
with `scrot`, not with `omni.ui.testing.capture_screenshot`:

```bash
# Real cursor move + click:
xdotool mousemove 640 400
xdotool click 1

# Real drag:
xdotool mousedown 1
xdotool mousemove_relative -- 120 0
xdotool mouseup 1

# Real key press:
xdotool key Tab
xdotool key ctrl+z

# Real screenshot of the whole screen (not just the FBO):
scrot /tmp/real.png
```

### Initialization / wiring order — the other usual suspect

If something works in tests (which typically build the whole UI before
loading a stage) but fails when loaded via the real launch path, suspect
**lazy construction inside `_build_ui`**.

`omni.ui.Frame` builds its children on the first render frame, not at
`__init__`. If `Application._load_stage()` calls `attach_stage(...)` before
that first frame fires, anything constructed inside `_build_ui` is still
`None` and the attach silently no-ops.

Concrete example we hit (`ovui_widgets/viewport/viewport_widget.py:106-115`): the
transform manipulator's `PrimTransformModel` was built inside `_build_ui`.
Early `attach_stage` calls found `_transform_model is None`, so
`attach_adapters` was skipped and every `get_pivot_world()` returned the
fallback origin — parking the gizmo at `(0,0,0)` regardless of selection.
The fix was to move the model construction to `__init__` so it exists
before the first frame:

```python
# In ViewportWidget.__init__ — NOT in _build_ui:
self._transform_model: Optional[PrimTransformModel] = PrimTransformModel()
```

Checklist when a widget "doesn't receive" early lifecycle calls:

1. Is the relevant state constructed in `__init__`, or inside `_build_ui`?
2. Does the owning `Window` / `Frame` get its build callback *before*
   `attach_stage` / `set_selection` / similar bus traffic?
3. If yes to "built in `_build_ui`", move pure-data objects (models,
   registries) out to `__init__`. Only actual `omni.ui` widgets need to
   live inside the frame build.

### Viewport chrome suppression API

`ViewportWidget` and the embeddable `ViewportSurface` accept public
`chrome_options` for hosts that need the stock viewport behavior without
drawing server-side viewport chrome into streamed pixels:

```python
from ovui_widgets.viewport import ViewportChromeOptions, ViewportSurface, ViewportWidget

viewport = ViewportWidget(
    services=services,
    renderer=renderer,
    chrome_options=ViewportChromeOptions(
        show_toolbar=False,
        show_text_hud=False,
        show_livestream_overlay=False,
        show_anchored_panels=False,
    ),
)

surface = ViewportSurface(
    services=services,
    renderer=renderer,
    chrome_options=ViewportChromeOptions(
        show_toolbar=False,
        show_text_hud=False,
        show_livestream_overlay=False,
        show_anchored_panels=False,
    ),
)
surface.build_into(caller_owned_frame)
```

All four `ViewportChromeOptions` fields default to `True`, preserving the
desktop viewport. The options suppress only the corresponding UI chrome:
the renderer image, `SceneView`, camera manipulator, transform manipulator,
pick gestures, `ToolRegistry`, and viewport frame hooks still use the stock
viewport implementation. Use `ViewportWidget` when the viewport should own a
desktop `ui.Window`; use `ViewportSurface` when a host already owns the
window/frame and needs ovui to fill that caller-provided surface.

### Viewport toolbar/HUD state snapshot

Hidden server chrome does not remove the state needed by browser-hosted
toolbar and HUD surfaces. `ViewportSurface.get_viewport_state_snapshot()`
returns immutable state for the active transform tool, tool availability,
camera choices, generic toolbar contributions, output-preset contributions,
scene label, FPS, resolution, and livestream status:

```python
snapshot = surface.get_viewport_state_snapshot()
active_tool = snapshot.active_tool
resolution_text = snapshot.hud.resolution_text
stream_text = snapshot.hud.stream_text
```

Catalogs that are unavailable in the current backend are reported as empty
tuples or `None`; the snapshot does not fabricate render targets, RenderVars,
render-progress, or backend-specific telemetry.

### Summary table

| Symptom                                            | First thing to check                                                  |
|----------------------------------------------------|------------------------------------------------------------------------|
| Works in test, breaks with real mouse              | `ovui` rev ≥ `65587d5`; re-test with `xdotool` + `scrot`.              |
| Gizmo stuck at `(0,0,0)` after stage load          | State built in `_build_ui` but needed by `attach_stage` — move to `__init__`. |
| `from pxr import Usd` reports an unexpected USD version | Historical custom-USD recipe: `PYTHONPATH` is missing — another `usd-core` wheel is shadowing the custom build. |
| `ImportError` on `ovrtx` at startup                | `OVRTX_SKIP_USD_CHECK=1` not set.                                      |
| `libusd_tf.so: cannot open shared object file`     | `LD_LIBRARY_PATH` is missing the custom USD `lib/` dir.                |

## Project Structure

```
ovui_widgets/app/                 (ovui_widgets.app)      Application, UndoManager, SelectionBus, style, startup
ovui_widgets/content/             (ovui_widgets.content)  Content Browser, file backends
ovui_widgets/stage/               (ovui_widgets.stage)    Stage Browser widget
ovui_widgets/property/            (ovui_widgets.property) Property Inspector widget
ovui_widgets/viewport/            (ovui_widgets.viewport) Viewport, camera, gestures, transform manipulator
ovui_widgets/layers/              (ovui_widgets.layers)   Layers window
ovui-data-adapters/common/     Common adapter contracts and records
ovui-data-adapters/openusd/    OpenUSD adapters and ovrtx renderer adapter
docs/architecture/             Static architecture summary sections
tests/                         Test suite (10000+ tests)
```

See `../docs/architecture.html` for the architecture summary.

## Known Limitations

- Renderer-backed viewport picking requires a renderer-backed provider path —
  OpenUSD + ovrtx, or the native OVStage provider's ovrtx BORROW attach (which
  supports rendering and picking, though selected borrowed objects may not
  show a visible selection outline). Mock adapters cover non-GPU test
  scenarios.
- `TransformManipulator`: only the translate gizmo is implemented;
  rotate / scale handles are stubs.
- `SurfaceSnapProvider`: stub; always returns the input point.
- No virtual list rendering — very large stages (100K+ prims) may be slow.

See `CHANGELOG.md` for the full known-limitations list.

## License

Licensed under the Apache License, Version 2.0. See the [`LICENSE`](../LICENSE) file for the full license text. Copyright (c) NVIDIA Corporation. All rights reserved.
