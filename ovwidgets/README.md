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

USD Viewer requires **OpenUSD v25.11** built non-monolithically with **oneTBB
2021.13.x** under Python 3.12. The PyPI `usd-core` wheel does not work:
`ovrtx` bundles its own USD and conflicts with any monolithic build unless
the custom layout below is used.

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

The `omni.ui` standalone (`ovui`) lives in its own sibling repo at
`~/dev/ovui`. USD Viewer installs it editable so both repos can evolve together.

### 1. Create `_venv312`

```bash
cd ~/dev/ovui/ovwidgets
python3.12 -m venv _venv312
source _venv312/bin/activate
pip install -U pip setuptools wheel
```

### 2. Install `omni.ui` editable from the ovui source tree

```bash
# Point CMake at the Vulkan headers installed above
Vulkan_INCLUDE_DIR=$HOME/.local/include \
    pip install -e ~/dev/ovui
```

`setup.py` forwards `PYTHON_EXECUTABLE` from the active venv, so the C++
bindings are built against the Python 3.12 ABI automatically. Output lands
in `~/dev/ovui/python/omni/ui/` and `~/dev/ovui/python/omni/ui_scene/`.

### 3. Install USD Viewer in editable mode

```bash
pip install -e ".[dev,usd]"
pip install tomli          # used by tests/test_package_distribution.py
```

The `[usd]` extra pulls `usd-core` — it will be **shadowed at runtime** by
the custom build on `PYTHONPATH` (see below), but installing it keeps
editors and import tooling happy.

### 4. Install ovrtx

```bash
pip install ovrtx==0.2.0.280040
```

(pre-release, from NVIDIA's internal package index)

## Building `libovstream.so` from `kit-livestream`

USD Viewer's optional WebRTC livestream tap (`ovwidgets.viewport._livestream_tap`)
loads the **OVSTREAM SDK** native library (`libovstream.so`) at runtime
through the `ovstream` Python package. The pip-installed `ovstream` wheel
**does not bundle the .so** in this layout — it expects to find the
library either in `$OVSTREAM_LIB_PATH` or alongside an in-tree
`kit-livestream` checkout at
`<repo>/_build/linux-x86_64/release/sdk/libovstream.so`.

Without it, every frame logs:
```
[ovgear/livestream] server bring-up failed:
libovstream.so: cannot open shared object file: No such file or directory
```

The upstream `build.sh` / `repo.sh build` flow uses NVIDIA-internal package
infrastructure that is not reachable outside NVIDIA-internal networks. The
recipe below builds the SDK directly from the source tree using system
CMake — no NVIDIA-internal package access required.

### What ships with the source vs. what you install

| Dependency        | Where it comes from                              |
|-------------------|--------------------------------------------------|
| **StreamSDK** (NvStreamBase / NvStreamServer / AudioStreamShared / Poco / cudart / OpenSSL `_nvst` fork) | Already vendored under `kit-livestream/source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64/` — proprietary, prebuilt, no fetch needed. |
| **GStreamer 1.20** + `gst-rtsp-server` + `glib 2.72` | Ubuntu 22.04 `apt` packages. The upstream build pins 1.24 from NVIDIA-internal packages, but the SDK only uses stable 1.x APIs (`appsrc`, `rtsp-server`, `video`) and links against 1.20 cleanly. |
| **CUDA driver** (`libcuda.so.1`)                | NVIDIA display driver (already on this VM). |
| **CUDA toolkit / nvcc**                          | Only needed to build the C *examples* (`.cu` files). Not needed for `libovstream.so` itself. |

### 1. Install system prerequisites

```bash
sudo apt-get install -y \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstrtspserver-1.0-dev \
    libglib2.0-dev \
    cmake patchelf build-essential
```

Verify pkg-config sees them:

```bash
pkg-config --modversion gstreamer-1.0 gstreamer-rtsp-server-1.0 \
                       gstreamer-app-1.0 gstreamer-video-1.0 glib-2.0
# → 1.20.3 / 1.20.1 / 1.20.1 / 1.20.1 / 2.72.4
```

### 2. Drop a `CMakeLists.txt` next to `sdk/premake5.lua`

The upstream SDK uses premake5 (`sdk/premake5.lua`), which is wired
through `repo.sh` and the NVIDIA-internal package system. The CMake recipe
below is a stripped-down
equivalent that compiles the same `sdk/src/**/*.cpp` set, links against
the vendored StreamSDK and the apt-installed GStreamer, and produces a
single `libovstream.so` with `$ORIGIN` RPATH:

```cmake
# kit-livestream/sdk/CMakeLists.txt
cmake_minimum_required(VERSION 3.18)
project(ovstream LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(SDK_ROOT ${CMAKE_CURRENT_SOURCE_DIR})
set(REPO_ROOT ${SDK_ROOT}/..)
set(STREAMSDK_DIR ${REPO_ROOT}/source/extensions/omni.kit.livestream.webrtc/streamsdk)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET
    gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0
    gstreamer-rtsp-server-1.0 glib-2.0 gobject-2.0
)

file(GLOB_RECURSE OVSTREAM_SRC ${SDK_ROOT}/src/*.cpp ${SDK_ROOT}/src/*.h)

add_library(ovstream SHARED ${OVSTREAM_SRC})
target_include_directories(ovstream PRIVATE
    ${SDK_ROOT}/include ${SDK_ROOT}/src ${STREAMSDK_DIR}/include)
target_compile_definitions(ovstream PRIVATE OVSTREAM_BUILD)
target_link_directories(ovstream PRIVATE
    ${STREAMSDK_DIR}/lib/linux/x86_64)
target_link_libraries(ovstream PRIVATE
    PkgConfig::GSTREAMER NvStreamBase NvStreamServer AudioStreamShared)
set_target_properties(ovstream PROPERTIES
    BUILD_RPATH "$ORIGIN" INSTALL_RPATH "$ORIGIN")
```

This file lives next to `sdk/premake5.lua` and is independent of it —
the premake build is untouched.

### 3. Configure and build

```bash
cd ~/dev/kit-livestream
cmake -S sdk -B _build_local -DCMAKE_BUILD_TYPE=Release
cmake --build _build_local -j$(nproc)
```

Build artefact: `_build_local/libovstream.so` (≈ 130 KB, all real
work is in the linked `libNvStreamServer.so` / GStreamer / etc.).

### 4. Stage at the path the `ovstream` Python wheel expects

`ovstream._bindings._find_library` walks four paths in order
(`OVSTREAM_LIB_PATH`, the wheel's own dir, the distribution-zip layout,
then the dev-tree `_build/linux-x86_64/release/sdk/`). Stage there and
copy the StreamSDK runtime libs alongside so `$ORIGIN` resolves:

```bash
SDK_OUT=~/dev/kit-livestream/_build/linux-x86_64/release/sdk
mkdir -p "$SDK_OUT"
cp ~/dev/kit-livestream/_build_local/libovstream.so "$SDK_OUT/"

SS=~/dev/kit-livestream/source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64
cp -a \
    "$SS"/libNvStreamBase.so \
    "$SS"/libNvStreamServer.so \
    "$SS"/libAudioStreamShared.so \
    "$SS"/libPoco.so \
    "$SS"/libcrypto_nvst.so.3 \
    "$SS"/libssl_nvst.so.3 \
    "$SS"/libNicllsHandlerServer.so \
    "$SS"/libcudart.so.12 \
    "$SDK_OUT/"

# Force RUNPATH→RPATH = $ORIGIN so the staged StreamSDK libs are
# preferred over anything CMake baked in from absolute link dirs.
patchelf --force-rpath --set-rpath '$ORIGIN' "$SDK_OUT/libovstream.so"
```

Note: GStreamer / glib are **not** copied here — the system loader
resolves them from `/lib/x86_64-linux-gnu/` since they're apt-installed.
The upstream NVIDIA-internal build copies them in because it ships its
own GStreamer 1.24; for an in-place dev build against system 1.20 they
already exist on the loader's default path.

### 5. Verify

Two checks. First a raw `ctypes.CDLL` to confirm every transitive
`NEEDED` symbol resolves:

```bash
python3 -c "import ctypes; \
    ctypes.CDLL('$HOME/dev/kit-livestream/_build/linux-x86_64/release/sdk/libovstream.so'); \
    print('OK')"
# → OK
```

Then through the `ovstream` Python wheel inside the ovwidgets venv. The
wheel's dev-layout walk only matches if the `ovstream` package is
imported from `<repo>/sdk/python/ovstream/`; for a pip-installed wheel
in `_venv312`, set `OVSTREAM_LIB_PATH` instead:

```bash
export OVSTREAM_LIB_PATH=$HOME/dev/kit-livestream/_build/linux-x86_64/release/sdk/libovstream.so

~/dev/ovui/ovwidgets/_venv312/bin/python -c "
import ovstream
ovstream.initialize()
print('version:', ovstream.get_version())
ovstream.shutdown()
"
# → version: 0.1.2
```

And finally that USD Viewer's livestream tap module imports without the
`OSError`:

```bash
~/dev/ovui/ovwidgets/_venv312/bin/python -c \
    "from ovwidgets.viewport._livestream_tap import LivestreamTap; print('ok')"
# → ok
```

Add `OVSTREAM_LIB_PATH` to the env-var block alongside
`OVRTX_SKIP_USD_CHECK` / `PYTHONPATH` / `LD_LIBRARY_PATH` for any shell
that runs USD Viewer with the livestream tap enabled.

### Caveats

- **No `gstnvenc` plugin.** The full upstream build also produces a
  custom NVENC GStreamer plugin (built from source under
  `source/extensions/omni.kit.livestream.rtsp/gstnvenc/`, LGPL).
  Without it, RTSP streams of *raw CUDA buffers* fail to negotiate the
  encoder. **Pre-encoded RTSP** (the caller hands H.264/H.265 bytes)
  and **all WebRTC streaming** (encoded inside StreamSDK) work without
  it — that covers USD Viewer's current livestream tap which feeds
  pre-encoded frames. If you need raw-CUDA RTSP, build `gstnvenc`
  separately and place `libgstnvenc.so` under `$SDK_OUT/gst-plugins/`
  with `GST_PLUGIN_PATH` pointing at it.
- **GStreamer version skew.** apt's 1.20.3 vs. upstream's 1.24 has not
  been observed to cause runtime issues for the SDK's appsrc → RTSP
  path on this VM, but no test sweep has been done against 1.20.

## Environment Variables

USD Viewer needs three env vars at runtime:

| Variable              | Value                                           | Why                                                                    |
|-----------------------|-------------------------------------------------|------------------------------------------------------------------------|
| `OVRTX_SKIP_USD_CHECK`| `1`                                             | Bypass ovrtx's startup check that refuses to load when `pxr` is also imported. Required for the viewport to construct `Renderer()` in the same process as the stage adapter. |
| `PYTHONPATH`          | `~/dev/usd-build/install/lib/python:$PYTHONPATH`| Resolve `pxr` to the custom 25.11 build instead of the `usd-core` 26.3 wheel from the `[usd]` extra. |
| `LD_LIBRARY_PATH`     | `~/dev/usd-build/install/lib:$LD_LIBRARY_PATH`  | So the 61 non-monolithic `libusd_*.so` files find each other. `omni.ui`'s own native libs set `$ORIGIN` RPATH at build time so they do **not** need to be on this path. |
| `OVSTREAM_LIB_PATH`   | `~/dev/kit-livestream/_build/linux-x86_64/release/sdk/libovstream.so` | Only when running with the WebRTC livestream tap. See *Building `libovstream.so` from `kit-livestream`* above. |

Export them together:

```bash
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH="$HOME/dev/usd-build/install/lib/python:$PYTHONPATH"
export LD_LIBRARY_PATH="$HOME/dev/usd-build/install/lib:$LD_LIBRARY_PATH"
```

## Running USD Viewer

Activate the venv, export env vars, launch:

```bash
source ~/dev/ovui/ovwidgets/_venv312/bin/activate
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH="$HOME/dev/usd-build/install/lib/python:$PYTHONPATH"
export LD_LIBRARY_PATH="$HOME/dev/usd-build/install/lib:$LD_LIBRARY_PATH"

ovwidgets                           # empty stage
ovwidgets ~/dev/ovui/ovwidgets/tests/data/simple_scene.usda   # open a USD file
python -m ovwidgets.app             # equivalent to `ovwidgets`
# Legacy alias still works:
ovgear                              # backward-compatible alias for ovwidgets
```

One-liner without activating the venv:

```bash
OVRTX_SKIP_USD_CHECK=1 \
PYTHONPATH=$HOME/dev/usd-build/install/lib/python \
LD_LIBRARY_PATH=$HOME/dev/usd-build/install/lib \
~/dev/ovui/ovwidgets/_venv312/bin/ovwidgets
```

For headless / server deployments set `OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan`
before launch; no `DISPLAY` needed.

## Running the Test Suite

```bash
source ~/dev/ovui/ovwidgets/_venv312/bin/activate
export PYTHONPATH="$HOME/dev/usd-build/install/lib/python:$PYTHONPATH"
export LD_LIBRARY_PATH="$HOME/dev/usd-build/install/lib:$LD_LIBRARY_PATH"
cd ~/dev/ovui/ovwidgets && pytest tests/ -q
```

Expected: full suite passes (10000+ tests, ~8 s). A small number of
tests are skipped when no GPU or display is available.

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

Concrete example we hit (`ovwidgets/viewport/viewport_widget.py:106-115`): the
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

### Summary table

| Symptom                                            | First thing to check                                                  |
|----------------------------------------------------|------------------------------------------------------------------------|
| Works in test, breaks with real mouse              | `ovui` rev ≥ `65587d5`; re-test with `xdotool` + `scrot`.              |
| Gizmo stuck at `(0,0,0)` after stage load          | State built in `_build_ui` but needed by `attach_stage` — move to `__init__`. |
| `from pxr import Usd` gives version `(0, 26, 3)`   | `PYTHONPATH` is missing — `usd-core` wheel is shadowing the custom build. |
| `ImportError` on `ovrtx` at startup                | `OVRTX_SKIP_USD_CHECK=1` not set.                                      |
| `libusd_tf.so: cannot open shared object file`     | `LD_LIBRARY_PATH` is missing the custom USD `lib/` dir.                |

## Project Structure

```
ovwidgets/app/                 (ovwidgets.app)      Application, UndoManager, SelectionBus, style, startup
ovwidgets/content/             (ovwidgets.content)  Content Browser, file backends
ovwidgets/stage/               (ovwidgets.stage)    Stage Browser widget
ovwidgets/property/            (ovwidgets.property) Property Inspector widget
ovwidgets/viewport/            (ovwidgets.viewport) Viewport, camera, gestures, transform manipulator
ovwidgets/layers/              (ovwidgets.layers)   Layers window
ovui-data-adapters/common/     Common adapter contracts and records
ovui-data-adapters/openusd/    OpenUSD adapters and ovrtx renderer adapter
docs/architecture/             Static architecture summary sections
tests/                         Test suite (10000+ tests)
```

See `../docs/architecture.html` for the architecture summary.

## Known Limitations

- Renderer-backed viewport picking and native selection outlines require the
  OpenUSD/ovrtx adapter path; mock adapters cover non-GPU test scenarios.
- `TransformManipulator`: only the translate gizmo is implemented;
  rotate / scale handles are stubs.
- `SurfaceSnapProvider`: stub; always returns the input point.
- No virtual list rendering — very large stages (100K+ prims) may be slow.

See `CHANGELOG.md` for the full known-limitations list.

## License

Copyright (c) NVIDIA Corporation. All rights reserved.
