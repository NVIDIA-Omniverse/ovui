# ovui

<!-- CI status badges for ${OVUI_PROJECT_URL} are added by the release staging filter. -->

`ovui` -- a GPU-accelerated Python UI toolkit built on GLFW and OpenGL. (Distribution name: `ovui`; Python import namespace: `omni.ui`.)

## What is ovui?

`ovui` is the standalone distribution of NVIDIA Omniverse's `omni.ui` UI framework, extracted to run independently outside of Kit. The product/distribution is named `ovui`; the Python import namespace remains `omni.ui`. It provides a declarative, Python-first API for building hardware-accelerated desktop interfaces backed by ImGui. The standalone backend handles window management (GLFW), rendering (OpenGL), and an async frame loop -- so you write pure Python and get native-speed UI. The same widget code runs identically inside Kit or standalone; only the backend differs.

```python
import omni.ui as ui

async def main():
    with ui.Window("Hello", width=400, height=200).frame:
        with ui.VStack():
            ui.Label("Hello, ovui!")
            ui.Button("Click me", clicked_fn=lambda: print("clicked"))
    while True:
        await ui.next_frame()

ui.run(main())
```

Save that as `hello.py`, run `python hello.py`, and a GLFW window appears with a label and a button. Close the window or press Ctrl+C to exit. The async coroutine runs inside the frame loop; `await ui.next_frame()` yields until the next rendered frame.

## Quick Start

`ovui` builds native C++ libraries from source during install, so a few system packages are required first.

### System Dependencies

#### Ubuntu/Debian

```bash
sudo apt install cmake libfreetype-dev libglfw3-dev libgl-dev
```

- **cmake** >= 3.22 -- drives the C++ build
- **libfreetype-dev** -- font rasterization (required)
- **libglfw3-dev** >= 3.3 -- windowing and input
- **libgl-dev** -- OpenGL headers and loader

For headless/Vulkan paths or when building the optional Vulkan backend, also install `libvulkan-dev` (and `mesa-vulkan-drivers` for Lavapipe). The Vulkan backend is auto-detected via `find_package(Vulkan QUIET)` -- it is optional and the build skips it cleanly if Vulkan headers are absent.

#### Windows 11 / Windows Server 2022

You need a native C++ toolchain and the Vulkan headers + loader. If you need
the CUDA-Vulkan byte-image path used by `examples/byte_image_gpu_demo.py`, also
install the NVIDIA CUDA Toolkit before running `python -m pip install .`.
CMake and Ninja do **not** need to be installed separately -- `pyproject.toml`
lists `cmake>=3.22` under `build-system.requires`, so pip auto-installs it in
the isolated build environment, and the default CMake generator on Windows is
the Visual Studio multi-config generator (no Ninja required).

**1. Visual Studio 2022 C++ workload** -- unavoidable for any native build on Windows.

Install either:
- Visual Studio 2022 Community / Professional / Enterprise, **or**
- Visual Studio 2022 Build Tools (lightweight, command-line only)

In either case, select the "Desktop development with C++" workload. This provides MSVC, the Windows SDK, and the Visual Studio CMake generator. Then open an "x64 Native Tools Command Prompt for VS 2022", or prime any shell with the matching `VsDevCmd.bat`.

For Build Tools, the path is usually:

```bat
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
```

For Community, Professional, or Enterprise, use the same `Common7\Tools`
location under that edition's install directory. To find it:

```powershell
& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" `
  -latest -products * -requires Microsoft.VisualStudio.Workload.VCTools `
  -property installationPath
```

Then call `Common7\Tools\VsDevCmd.bat` from the reported installation path. A
quick sanity check is `where cl.exe` and `where link.exe`.

**2. Vulkan headers + loader** -- two options:

If the LunarG Vulkan SDK is already installed, no extra setup is usually
needed. The installer sets `VULKAN_SDK`, which CMake's `find_package(Vulkan)`
picks up automatically:

```powershell
$env:VULKAN_SDK
Test-Path "$env:VULKAN_SDK\Include\vulkan\vulkan.h"
Test-Path "$env:VULKAN_SDK\Lib\vulkan-1.lib"
```

If the SDK is not installed, either install it from https://vulkan.lunarg.com/
or use vcpkg to provide just the Vulkan headers and loader.

*Option A (recommended, ~20 MB) -- vcpkg, mirrors what the wheel CI uses:*

```powershell
vcpkg install vulkan-headers:x64-windows vulkan-loader:x64-windows

# Point CMake at the vcpkg-installed headers and import library:
$installed = "$env:VCPKG_INSTALLATION_ROOT\installed\x64-windows"
$env:Vulkan_INCLUDE_DIR = "$installed\include"
$env:Vulkan_LIBRARY     = "$installed\lib\vulkan-1.lib"
# Add the loader DLL directory to PATH so the runtime can find vulkan-1.dll:
$env:PATH = "$installed\bin;$env:PATH"
```

Use vcpkg with a standalone/classic vcpkg installation or with your own
manifest. Some Visual Studio bundled vcpkg installs are manifest-only and reject
`vcpkg install` outside a vcpkg project.

`setup.py` forwards `Vulkan_INCLUDE_DIR` / `Vulkan_LIBRARY` to CMake automatically when they are set.

*Option B (heavyweight, ~500 MB+) -- the LunarG Vulkan SDK:*

Install from https://vulkan.lunarg.com/. The installer sets the `VULKAN_SDK` environment variable, which `find_package(Vulkan)` picks up with no further configuration. Convenient if you already use Vulkan tooling (validation layers, RenderDoc, etc.), but it's ~25x the download of Option A for the same build result.

**3. CUDA Toolkit for CUDA-Vulkan byte images** -- required only for the
zero-copy CUDA-Vulkan `ByteImageProvider.set_bytes_data_from_gpu()` path.

ovui enables this path only when CMake finds both `Vulkan` and
`CUDAToolkit` during configure/install. If CUDA Toolkit is missing, the build
still succeeds and `import omni.ui` can work, but
`omni.ui.has_gpu_byte_image()` returns `False` and
`examples/byte_image_gpu_demo.py` exits before showing the image.

Install the CUDA Toolkit major version validated by the ovui release you are
building; for current source builds, use CUDA 12.x when available. CMake
currently does not hard-pin an exact CUDA Toolkit version, but it must be able
to discover a toolkit that provides `CUDA::cudart` and `CUDA::cuda_driver`.

The NVIDIA CUDA installer typically sets `CUDA_PATH`. If it does not, or if
your toolkit is in a non-default location, set one of these before running
`pip install .`:

```powershell
# If the installer did not set CUDA_PATH, point at the toolkit explicitly:
$env:CUDA_PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6"
# Some tooling also reads CUDAToolkit_ROOT or CUDA_HOME:
$env:CUDAToolkit_ROOT = $env:CUDA_PATH
# or:
$env:CUDA_HOME = $env:CUDA_PATH
```

ovui also checks `CUDA_PATH`, `CUDAToolkit_ROOT`, and `CUDA_HOME` at Python
import time on Windows and adds the toolkit `bin` directory to the DLL search
path when it exists.

Before building, verify that the CUDA compiler is visible from the same shell:

```powershell
where.exe nvcc
nvcc --version
if ($env:CUDA_PATH) {
    Test-Path "$env:CUDA_PATH\bin\nvcc.exe"
    Test-Path "$env:CUDA_PATH\lib\x64\cudart.lib"
}
```

(`cmd.exe` users can run `where nvcc`.)

**4. Vulkan runtime / NVIDIA driver** -- the Vulkan ICD shipped with a recent NVIDIA driver is sufficient for running ovui; the SDK is only needed at build time.

The Vulkan backend itself remains optional. If you skip the Vulkan headers and
runtime, the build still produces the GLFW/OpenGL backend and `import omni.ui`
works; only Vulkan-specific features such as headless rendering and streaming
are disabled.

### Python Dependencies

- **Python** 3.12, 3.13, 3.14 or 3.15 (CPython)
- **pybind11** >= 2.13.6, < 3 (installed automatically by pip, or `pip install "pybind11>=2.13.6,<3"`). The 2.13 line is the first with Python 3.13 support. pybind11 3.x is not supported: it needs source changes. On Windows, the modules are built without the compiler version that pybind11 2.13.6 adds to the key of the shared type registry, so they share types with modules built with pybind11 2.11.1 (Kit's), as on Linux. The wheel builds require 2.13.6 or later, below 3, through `pyproject.toml`. The `ovui` CMake files still accept pybind11 2.11.1 or later for Kit-hosted builds
- **setuptools** >= 84.0.0

### Python versions

This section describes the 0.3.1 native UI wheels. The published
0.2.0 and 0.3.0 `ovui` wheels have only the `cp312` tag: they are for CPython
3.12 only.

The native `ovui` package ships one wheel per platform
for all four Python versions. The wheel file name carries the combined tag, for
example `ovui-<version>-cp312.cp313.cp314.cp315-cp312.cp313.cp314.cp315-manylinux_2_35_x86_64.whl`.
The wheel holds one native module per version (`_ui.cpython-313-x86_64-linux-gnu.so`,
`_ui.cp313-win_amd64.pyd`, and so on); Python imports the one that fits the
running interpreter. The native libraries that do not depend on Python
(`libovui`, the standalone library, the ImGui library, the CUDA runtime) are in
the wheel once. The wheel is about one third larger than a single-version wheel.
Free-threaded Python (`cp313t` and later) is not supported.

Known dependency limits:

- `usd-core==25.11`, the version of the `standalone` extra of
  `ovui-data-adapters-openusd`, has wheels for Python 3.8 to 3.13 and none for
  Python 3.14 or 3.15. On Python 3.14 and 3.15 the extra (and
  `ovui-widgets-all`, which requests it) cannot be installed. usd-core 26.11
  has Python 3.14 wheels, but the OpenUSD adapter is not validated with it,
  and usd-core has no Python 3.15 wheel at all. On these versions, use the
  OVStage provider, or supply a matching `pxr` from the environment and
  install the plain `ovui-data-adapters-openusd` wheel.
- `ovrtx`, `ovstage`, `ovstream`, `ovphysx` and `cuda-python` are `py3-none`
  packages that this repository does not build. They are not tested here on
  every version; Python 3.15 is the most likely to meet a problem, as is any
  tool that has not yet published Python 3.15 support.
- `numpy` publishes wheels for all four versions.
- The WebAssembly build stays on its own static Python 3.12.

### Third-Party Dependencies

`third_party/` intentionally contains only the vendored ImGui source tree, the
CMake FetchContent declarations, and the `glad_extensions.txt` input used by the
glad generator. ImGui remains vendored because ovui carries local patches; see
`third_party/imgui/PATCHES.md` before replacing it. The other C++ dependencies
are downloaded automatically by CMake at build time and cached under the build
directory.

| Dependency | Version | Source | Upstream |
|------------|---------|--------|----------|
| ImGui | 1.92.7-docking | Vendored in `third_party/imgui/` with local patches | https://github.com/ocornut/imgui |
| Boost.Preprocessor | 1.85.0 | FetchContent | https://github.com/boostorg/preprocessor |
| GLM | 0.9.9.8 | FetchContent | https://github.com/g-truc/glm |
| glad | v0.1.36, GL 3.3 core, 616 extensions | FetchContent; generated with `third_party/glad_extensions.txt` | https://github.com/Dav1dde/glad |
| md4c | 0.5.2 | FetchContent | https://github.com/mity/md4c |
| stb | image v2.30 / write v1.16 | FetchContent | https://github.com/nothings/stb |

### Install

When `ovui` is published to a Python package index, `pip install ovui` will install the latest release. Until then, install from source by cloning this repo and running:

```bash
# From this ovui directory:
pip install .

# Or for development (editable install):
pip install -e .
```

From the monorepo root, use `pip install ovui` or `pip install -e ovui`
instead. On Windows, run the same commands from an "x64 Native Tools Command
Prompt for VS 2022" or any shell where `VsDevCmd.bat -arch=x64 -host_arch=x64`
has been sourced so that `cl.exe` and `link.exe` are on `PATH` when CMake
configures.

### Verify

```bash
python -c "import omni.ui as ui; print(ui.Window.__name__)"
```

If this prints `Window`, the native libraries compiled and loaded correctly.

For CUDA-Vulkan byte-image support, verify the capability probe too:

```bash
python -c "import omni.ui as ui; print(ui.has_gpu_byte_image())"
```

This should print `True` for a `Vulkan` + `CUDAToolkit`-enabled build on
supported NVIDIA hardware. If it prints `False`, inspect the CMake cache that
`setup.py` uses:

```powershell
cmake -LA -N .\build\pip | findstr /I "CUDA CUDAToolkit Vulkan"
```

The `build\pip` path is relative to the `ovui\` source directory; from the
monorepo root use `ovui\build\pip` instead. Look for valid
CUDA/CUDAToolkit paths as well as Vulkan paths. The
`examples/byte_image_gpu_demo.py` demo requires this capability; installing
CUDA after the fact is not enough unless you rebuild/reinstall ovui so CMake
can detect it.
## Building from Scratch

For C++ contributors who want to invoke CMake directly -- useful for debugging the native layer or working on the bindings.

The native build uses pybind11 2.13.x for the wheel workflows, and the
Python you build with (3.12 to 3.15). Direct CMake invocation does not install the
build dependencies declared in `pyproject.toml`.

```bash
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
  -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())")
cmake --build . --parallel $(nproc)
```

### SVG images

The standalone backend draws `.svg` files with its own SVG reader and painter
(`standalone/src/StandaloneSvgDocument.h`); it uses no other library.
`ui.Image` and `ui.ImageWithProvider` draw an `.svg` file at the content size
of the widget, and images of the same file and size share one texture.
`ui.MarkdownWidget` draws an `.svg` image at the size of the file (the width
and height of its root `<svg>`), as it draws a PNG file. The CMake option
`OMNIUI_ENABLE_SVG` builds this support and is ON by default.

- Drawn: `<svg>`, `<g>`, `<use>`, `<symbol>`, `<defs>`, `<path>`, `<rect>`,
  `<circle>`, `<ellipse>`, `<line>`, `<polyline>`, `<polygon>`; colors, linear
  and radial gradients, fill rules, strokes with caps, joins, miter limit and
  dashes, transforms, opacity, `clip-path`, presentation attributes, the
  `style` attribute and `<style>` sheets (type, class, id and descendant
  selectors).
- Not drawn: `<text>`, `<image>`, `<foreignObject>`, `<pattern>` paint, masks,
  filters and markers (also on the root `<svg>`), and a `transform` attribute
  on an `<svg>` element (the root or a nested one). A file with such parts
  draws its shapes and logs one warning that names the parts left out. A part
  drawn differently from the file (a dash pattern too fine to draw dash by
  dash, a path drawn up to an error in its data) logs one warning with the cause.
- A file that is missing, empty, larger than 32 MiB, not well-formed XML (the
  error gives the line, the column and the cause), without any shape, or over a
  work limit of the reader or painter (for example entity text, shapes after
  `<use>` references, style rules, gradient stops, line pieces, pixels or layer
  memory; see [`docs/svg-images.md`](docs/svg-images.md)) draws nothing and
  logs one error with the cause. An exception while a file is read or painted
  (for example `std::bad_alloc`) is caught and logged the same way.
- The test `standalone_svg_rasterizer_tests` compares the pixels of every file
  in `tests/svg_corpus/` with the picture Google Chrome makes of it. The
  results, side-by-side pictures and speed numbers are in
  [`docs/svg-images.md`](docs/svg-images.md).

```bash
cmake .. -DOMNIUI_ENABLE_SVG=OFF   # no SVG support: .svg images draw nothing and log one error that names the option
```

### Native frame pacing

The standalone backend carries a native frame-pacing coordinator that drives
render and presentation independently of the UI tick. It has no build option
and no renderer dependency: ovui owns the image slots, the CUDA/Vulkan upload,
the Vulkan presentation and its present worker. The render worker and every
renderer call belong to the package that fills ovui's renderer slot; that
worker drives ovui back through a host table ovui hands over for each session.

An optional package supplies that table. It fills the slot before `ui.init`
with `omni.ui._ui._set_native_frame_pacing_hooks(capsule)`, the same shape as
`_set_native_timing_hooks`; `standalone/src/NativeFramePacingHooks.h` is its
layout and ships with the ovui SDK. Without such a package the slot stays
empty, `omni.ui.get_frame_pacing_status()` reports `supported = False` with the
reason `hooks_unavailable`, and the viewport presents on the ordinary UI tick.

`ovui` depends on no renderer and no scene library. A renderer package and a
scene provider live in their own packages and drive ovui through the generic
renderer-borrow entry points (`omni.ui._ui._native_frame_pacing_*`) rather than
putting their code into ovui.

The build produces three shared libraries:

| Artifact                      | Source directory | Purpose                              |
|-------------------------------|-----------------|--------------------------------------|
| `libovui.so`                 | `core/`         | Widget tree, layout engine, styling  |
| `libomniui_standalone.so`    | `standalone/`   | GLFW/OpenGL backend, frame loop      |
| `_ui.cpython-*.so`           | `bindings/`     | pybind11 bridge exposing C++ to Python |

All three are linked with `RPATH=$ORIGIN` so they find each other at runtime without `LD_LIBRARY_PATH`.

## Your First App

The hello world above is deliberately minimal. Here is a more realistic example exercising several widget types and the `with window.frame:` pattern that you will use in every app:

```python
import omni.ui as ui

async def main():
    window = ui.Window("Dashboard", width=580, height=380)
    with window.frame:
        with ui.VStack(spacing=8):
            ui.Label("System Dashboard", style={"font_size": 22})

            with ui.HStack(height=0):
                ui.Label("Threshold:", width=80)
                slider = ui.FloatSlider(min=0.0, max=1.0)
                slider.model.set_value(0.75)

            with ui.HStack(height=0):
                ui.Label("Name:", width=80)
                field = ui.StringField()
                field.model.set_value("default")

            progress = ui.ProgressBar()
            progress.model.set_value(0.42)

            def on_click():
                val = slider.model.get_value_as_float()
                name = field.model.get_value_as_string()
                print(f"Running '{name}' with threshold {val:.2f}")

            ui.Button("Run", clicked_fn=on_click, height=30)

    while True:
        await ui.next_frame()

ui.run(main())
```

Key patterns to note:

- **`ui.run(coroutine)`** -- pass an async coroutine to `ui.run()`. It initializes the backend, then runs your coroutine inside the frame loop. The loop exits when either the window is closed or the coroutine finishes.
- **`with window.frame:`** -- every `ui.Window` has a `.frame` property. Children are added inside its context manager. Note: `ui.Window` itself is **not** a context manager -- always use `.frame`.
- **`with ui.VStack():`** / **`with ui.HStack():`** -- layout containers that stack children vertically or horizontally.
- **Models** -- value-holding widgets (sliders, fields, progress bars) expose a `.model` for reading and writing their state.

## Architecture

The project is a three-layer stack. Python code talks to a pybind11 binding layer, which delegates to two C++ shared libraries that handle the heavy lifting:

```
 ┌──────────────────────────────────────────────────┐
 │  Python application code                         │
 │    import omni.ui as ui                          │
 ├──────────────────────────────────────────────────┤
 │  Python package: omni.ui                         │
 │    standalone.py   run(), next_frame(), init()   │
 │    testing.py      mouse_click(), type_text()    │
 │    __init__.py     Kit/standalone auto-detect    │
 ├──────────────────────────────────────────────────┤
 │  _ui.cpython-*.so  (pybind11 bindings)           │
 │    Exposes all C++ widget classes to Python       │
 ├──────────────┬───────────────────────────────────┤
 │  core.so     │  standalone.so                    │
 │  Widget tree │  GLFW window + OpenGL context     │
 │  Layout      │  ImGui frame management           │
 │  Styling     │  Input injection (for testing)    │
 │  Font atlas  │  Screenshot capture               │
 ├──────────────┴───────────────────────────────────┤
 │  System: Freetype ─ GLFW ─ OpenGL ─ ImGui        │
 └──────────────────────────────────────────────────┘
```

- **`core/`** contains the platform-independent widget model: the tree of UI elements, the constraint-based layout solver, the style/shade system, and the font atlas backed by Freetype. It has no dependency on any windowing library.
- **`standalone/`** provides the GLFW/OpenGL backend: window creation, the per-frame tick (poll events, ImGui new-frame, render, swap), and input injection hooks used by the test harness.
- **`bindings/`** is a set of pybind11 header files (one per widget class) that expose the C++ API as `omni.ui._ui`. The Python package re-exports everything from `_ui` so users see `ui.Button`, `ui.Label`, etc.

## The Async Model

`ovui` does not use `asyncio.run()`. Instead, `ui.run()` creates its own event loop and pumps it manually each frame -- matching the run-loop model used by Kit. This means you can `await ui.next_frame()` to yield control until the next rendered frame, then resume your coroutine with the UI fully updated.

### Simple blocking app (no async)

When you just need widgets with callbacks, call `ui.init()` first, then create your windows, then call `ui.run()` with no arguments to block until the window is closed:

```python
import omni.ui as ui

ui.init("Counter", width=300, height=100)

window = ui.Window("Counter", width=300, height=100)
with window.frame:
    with ui.VStack():
        label = ui.Label("Count: 0")
        count = [0]

        def increment():
            count[0] += 1
            label.text = f"Count: {count[0]}"

        ui.Button("Increment", clicked_fn=increment)

ui.run()  # blocks until window close
```

**Important:** `ui.init()` must be called before creating any `ui.Window`. If you skip it, the window manager is not yet initialized and you will get errors. The async pattern (passing a coroutine to `ui.run()`) avoids this because `ui.run()` calls `init()` internally before executing the coroutine.

### Async animation

When you need frame-by-frame control, pass a coroutine to `ui.run()`:

```python
import omni.ui as ui

async def animate():
    with ui.Window("Progress", width=400, height=80).frame:
        with ui.VStack():
            bar = ui.ProgressBar()

    for i in range(101):
        bar.model.set_value(i / 100.0)
        await ui.next_frame()

ui.run(animate())
```

The coroutine runs cooperatively inside the frame loop. Each `await ui.next_frame()` suspends until the backend has polled events, rendered, and swapped buffers. The loop exits when either the window is closed or the coroutine finishes.

### Frame lifecycle

Here is what happens during a single iteration of the run-loop:

```
    ui.run(coro)
        │
        ▼
 ┌─── frame loop ──────────────────────────────────────────────┐
 │                                                              │
 │  1. _standalone_tick()                                       │
 │     ├─ glfwPollEvents()        poll OS input                 │
 │     ├─ ImGui_ImplOpenGL3_NewFrame()                          │
 │     ├─ ImGui::NewFrame()       begin widget submission       │
 │     ├─ <render all ui.Window widget trees>                   │
 │     ├─ ImGui::Render()         finalize draw lists           │
 │     └─ glfwSwapBuffers()       present to screen             │
 │                                                              │
 │  2. Resolve next_frame() futures                             │
 │     └─ All awaiters of next_frame() resume                   │
 │                                                              │
 │  3. Pump asyncio                                             │
 │     └─ loop.call_soon(loop.stop); loop.run_forever()         │
 │         runs all ready callbacks / coroutine steps            │
 │                                                              │
 │  4. Check exit conditions                                    │
 │     ├─ GLFW window closed?  → break                          │
 │     └─ coroutine finished?  → break                          │
 │                                                              │
 └──────────────────────────────────────────────────────────────┘
```

For embedding in an existing asyncio application, use `await ui.run_async()` instead. It yields to the outer event loop every frame via `await asyncio.sleep(0)`.

## Testing

The test suite lives in `tests/` and uses a custom `OmniUiTest` base class that initializes the standalone backend, creates per-test windows, and supports golden-image screenshot comparison.

### Running the test suite

```bash
# Run all tests (uses pytest if installed, falls back to unittest):
python tests/run_tests.py

# Run a specific test module:
python tests/run_tests.py test_label

# Verbose output:
python tests/run_tests.py -v

# Filter by test name pattern (requires pytest):
python tests/run_tests.py -k test_general
```

### Writing a test

Tests inherit from `OmniUiTest` and use `async def test_*` methods. The base class handles backend init, window creation, frame pumping, and teardown:

```python
from test_base import OmniUiTest
import omni.ui as ui


class TestMyWidget(OmniUiTest):

    async def test_button_label(self):
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack():
                label = ui.Label("before")
                ui.Button("Press", clicked_fn=lambda: setattr(label, "text", "after"))

        await self.wait_n_updates(3)

        # At this point the UI is laid out and rendered.
        # finalize_test() captures a screenshot and compares
        # it against a golden image (if configured).
        await self.finalize_test()
```

### Input injection

The `omni.ui.testing` module provides async helpers for programmatic interaction. These handle the multi-frame sequences that ImGui requires (e.g., hover must precede click):

- **`await mouse_click(x, y)`** -- move cursor, wait for hover, press, release
- **`await mouse_double_click(x, y)`** -- two clicks within ImGui's double-click window
- **`await mouse_drag(x0, y0, x1, y1, steps=10)`** -- drag between two points over N frames
- **`await type_text("hello")`** -- inject text into the focused widget
- **`await press_key(key_code)`** -- press and release a key
- **`await wait_frames(n)`** -- idle for N frames

### Screenshot comparison

`OmniUiTest.finalize_test()` optionally captures the framebuffer and compares it pixel-by-pixel against a golden image stored in `tests/golden/`. This requires PyOpenGL and Pillow as optional dependencies. If they are not installed, the visual comparison is silently skipped -- the functional test still runs. Set the golden directory via the `OMNI_UI_GOLDEN_DIR` environment variable or the `GOLDEN_IMG_DIR` class attribute.

## Standalone Testing Strategy

This section covers how to write automated tests for `ovui` apps,
including 2D widgets and interactive 3D scene manipulators.

### Headless mode

Set `OMNIUI_HEADLESS=1` to run without a physical display. The standalone backend
switches from GLFW+OpenGL to a Vulkan offscreen renderer that produces real
GPU-rendered frames, which `capture_screenshot()` can save to disk:

```bash
OMNIUI_HEADLESS=1 python my_app.py --screenshot
```

This is the canonical CI environment. The rendered output is pixel-identical to
a display-connected run (same shaders, same font atlas), so screenshots taken
headless are valid golden images.

### Screenshot-first workflow

The recommended pattern for interactive testing is:

1. Build your UI/scene.
2. Wait several frames (`await wait_frames(n)`) for layout to settle.
3. Capture an **initial state screenshot** as visual proof.
4. Inject input (mouse clicks, drags, key presses).
5. Wait for the UI to react.
6. Capture an **after-action screenshot**.
7. Assert on widget state (text, model values, object positions).

```python
import omni.ui as ui
from omni.ui import testing

async def _main():
    # 1. Build UI
    win = ui.Window("Test", width=400, height=200)
    with win.frame:
        with ui.VStack():
            label = ui.Label("initial")
            ui.Button("Change", clicked_fn=lambda: setattr(label, "text", "changed"))

    # 2. Settle
    await testing.wait_frames(6)

    # 3. Initial screenshot
    testing.capture_screenshot("/tmp/before.png")

    # 4. Click the button (pixel coordinates of the button centre)
    await testing.mouse_click(200, 150)

    # 5. Wait for callback
    await testing.wait_frames(3)

    # 6. After screenshot
    testing.capture_screenshot("/tmp/after.png")

    # 7. Assert
    assert label.text == "changed", f"expected 'changed', got {label.text!r}"

ui.run(_main())
```

### `omni.ui.testing` API reference

All helpers are `async` and must be awaited inside an `async def` body that
runs under `ui.run(coro)` or `ui.run_async()`.

| Function | Description |
|---|---|
| `await mouse_click(x, y, button=0)` | Move cursor, wait two frames for hover, press, release. |
| `await mouse_double_click(x, y, button=0)` | Two clicks within ImGui's double-click window (~300 ms at default frame rates). |
| `await mouse_drag(x0, y0, x1, y1, button=0, steps=10)` | Press at (x0,y0), move over `steps` frames to (x1,y1), release. Re-injects button state each frame so drag state persists. |
| `await mouse_move(x, y)` | Move cursor without pressing. |
| `await mouse_scroll(x, y, dx=0, dy=0)` | Scroll at position (x, y). |
| `await type_text(text)` | Inject text into the focused widget. Two frames are pumped. |
| `await press_key(key_code)` | Press and release an ImGui key. |
| `await wait_frames(n)` | Idle for exactly n frames. |
| `capture_screenshot(filepath)` | Synchronous. Schedules a pre-swap capture, ticks one frame, returns True on success. Supported formats: `.png`, `.jpg`, `.bmp`. |

**Coordinate system:** all coordinates are window-relative pixels with (0, 0)
at the top-left corner of the OS window. Widget positions match what you would
read from `ui.Widget.screen_position_x` / `screen_position_y`.

### Mouse multi-frame protocol

ImGui requires that hover state is established before a click registers. The
testing helpers handle this automatically:

```
mouse_click(200, 80)
  ├── inject_mouse_move(200, 80)
  ├── await next_frame()   ← ImGui registers hover
  ├── await next_frame()   ← hover confirmed
  ├── inject_mouse_button(0, True)   ← button down
  ├── await next_frame()
  ├── inject_mouse_button(0, False)  ← release
  ├── await next_frame()
  └── await next_frame()   ← ImGui processes click event
```

`mouse_drag` only injects the button-down transition once at the start of the
drag. Button state persists between frames the same way real GLFW input does,
because `applyInjectedInput()` forwards events through ImGui's queued event
API (`io.AddMouseButtonEvent`) rather than writing `io.MouseDown[]` directly:

```python
inject_mouse_button(button, True)
for i in range(1, steps + 1):
    t = i / steps
    inject_mouse_move(lerp(x0, x1, t), lerp(y0, y1, t))
    await next_frame()
inject_mouse_button(button, False)
```

### Headless-mode `isHovered` behaviour

In normal (windowed) mode, `SceneView._captureInput()` gates mouse-click
events on `isHovered() && isWindowHovered`. In headless mode the GLFW event
loop is not running, so `isWindowHovered` may be False even when the cursor is
inside the widget. `mouse_drag` naturally works around this because it moves the
cursor to the target first: by the time the button is pressed, `isHovered()` has
been set by ImGui's item-hover logic. No special workaround is needed for
standard widget testing.

For scene gesture testing (see below), the `_HeadlessGestureManager` technique
can be used to synthesise `clicked` from button-down transitions in cases where
the hover guard cannot be satisfied.

### Testing `omni.ui.scene` manipulators

3D scene gestures (`DragGesture`, `HoverGesture`) use ray-casting against
projected line and shape primitives. Testing them requires knowing where the
shapes project in screen space.

#### Project world coordinates to screen pixels

```python
def project_world_to_screen(world_pt, view_mat, proj_mat,
                             scene_x, scene_y, scene_w, scene_h):
    """Return (px, py) pixel position of a 3D world point.

    view_mat and proj_mat are flat 16-element column-major matrices from
    camera.get_as_floats(camera.get_item("view")) etc.
    scene_x/y is the top-left corner of the SceneView widget in window pixels.
    """
    def mv(m, v):
        return [sum(m[c*4+r]*v[c] for c in range(4)) for r in range(4)]
    eye  = mv(view_mat,  [*world_pt, 1.0])
    clip = mv(proj_mat, eye)
    ndc_x = clip[0] / clip[3]
    ndc_y = clip[1] / clip[3]
    px = scene_x + (ndc_x + 1.0) * 0.5 * scene_w
    py = scene_y + (1.0 - ndc_y) * 0.5 * scene_h
    return (px, py)
```

#### Dragging a translate-manipulator axis arrow

```python
from omni.ui_scene import scene as sc

# Camera setup
camera = OrbitCamera(aspect=900 / 580)
scene_view = sc.SceneView(camera, height=580)

# Project X arrow shaft midpoint (0.95, 0, 0) to screen
view = camera.get_as_floats(camera.get_item("view"))
proj = camera.get_as_floats(camera.get_item("projection"))
# SceneView starts at y=36 (after a 36px header)
start = project_world_to_screen([0.95, 0, 0], view, proj, 0, 36, 900, 580)
end   = project_world_to_screen([2.80, 0, 0], view, proj, 0, 36, 900, 580)

await testing.mouse_drag(*start, *end, button=0, steps=15)
await testing.wait_frames(8)

assert manipulator._pos[0] > 1.0, "cube should have moved along +X"
```

#### Intersection thickness

`sc.Line` accepts an `intersection_thickness` kwarg (screen pixels). The default
is `max(1.0, line_thickness * 0.5)`. For testing, set it to 12–20 px so the
projected coordinates don't need pixel-perfect accuracy:

```python
sc.Line([0, 0, 0], tip,
        color=red, thickness=5.0,
        intersection_thickness=12.0,
        gesture=drag)
```

Avoid very large values (≥ 30 px) when multiple arrows are close together in
screen space — adjacent axes can inadvertently capture the gesture.

#### Stable gesture objects across rebuilds

`Manipulator.on_build()` is called every time `invalidate()` is triggered.
If `DragGesture` objects are created fresh on each call, they start in
`GestureState.POSSIBLE` and cannot continue an in-progress drag:

```python
# ✗ Creates a new gesture every rebuild — breaks multi-frame drags
def on_build(self):
    drag = sc.DragGesture(on_changed_fn=self._changed)  # new object!
    sc.Line([0,0,0], tip, gesture=drag)
    ...
    self.invalidate()  # triggers on_build() next frame → drag lost

# ✓ Create once in __init__, reuse in on_build()
def __init__(self, **kw):
    super().__init__(**kw)
    self._drag = sc.DragGesture(on_changed_fn=self._changed)

def on_build(self):
    sc.Line([0,0,0], tip, gesture=self._drag)   # same object every build
    self.invalidate()   # gesture stays in eChanged across rebuild ✓
```

`AbstractShape.setGestures()` only assigns the scene's default
`GestureManager` when `gesture.getManager() is None`, so pre-assigning a
manager in `__init__` is also preserved.

#### Full working example

`examples/scene_manipulator.py` is a complete, runnable demonstration:

```bash
# Interactive window
python examples/scene_manipulator.py

# Headless screenshots (initial state + post-drag)
OMNIUI_HEADLESS=1 python examples/scene_manipulator.py --screenshot
```

It implements a perspective orbit camera, a three-axis translate manipulator with
`DragGesture` on each shaft, `HoverGesture` for highlight feedback, a reference
grid, and a wireframe cube as the "selected object". The `--screenshot` path
programmatically drags the X arrow and saves before/after PNGs.

## Project Structure

```
ovui/
├── CMakeLists.txt              Top-level CMake (project v0.1.1, C++17)
├── setup.py                    pip install entry point (drives CMake)
├── pyproject.toml              PEP 517 build config
├── core/
│   ├── CMakeLists.txt          Builds libovui.so
│   ├── include/                Public C++ headers
│   └── src/                    Widget tree, layout, styling, font atlas
├── standalone/
│   ├── CMakeLists.txt          Builds libomniui_standalone.so
│   └── src/                    GLFW window, GL context, frame tick, input injection
├── bindings/
│   ├── Bind*.h                 One pybind11 header per widget class
│   └── ...                     (~80 binding headers)
├── python/
│   └── omni/
│       └── ui/
│           ├── __init__.py     Package root
│           ├── standalone.py   run(), run_async(), next_frame(), init()
│           ├── testing.py      mouse_click(), type_text(), capture_screenshot()
│           ├── color_utils.py  Shade-aware color() helper
│           ├── constant_utils.py  Shade-aware constant() helper
│           ├── style_utils.py  Style dictionary utilities
│           ├── url_utils.py    Resource URL resolution
│           ├── singleton.py    Singleton metaclass
│           └── abstract_shade.py  Base class for shade-aware lookups
├── resources/
│   ├── fonts/                  Bundled .ttf files
│   └── glyphs/                 Icon glyphs
├── third_party/
│   ├── CMakeLists.txt          FetchContent declarations + imgui OBJECT target
│   ├── glad_extensions.txt     616-extension allowlist for glad generation
│   └── imgui/                  Vendored ImGui with local patches
├── tests/
│   ├── run_tests.py            Test runner (pytest or unittest fallback)
│   ├── test_base.py            OmniUiTest base class
│   ├── test_label.py           Label widget tests
│   ├── test_checkbox.py        CheckBox tests
│   ├── test_container.py       Container layout tests
│   ├── test_field.py           Field widget tests
│   ├── test_rectangle.py       Rectangle shape tests
│   ├── test_slider.py          Slider widget tests
│   └── golden/                 Golden images for screenshot comparison
└── build/                      CMake build artifacts (generated)
```

## License

Licensed under the Apache License, Version 2.0. See the `LICENSE` file for the full license text and the SPDX headers in individual source files. Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.

## Kit / Standalone File Sync Status

This section tracks which files are shared between Kit (`~/dev/kit/kit/source/extensions/omni.ui/`) and standalone (`~/dev/ovui/`) and whether they are byte-identical.

### Files That Match (192 files)

| Category | Count | Status |
|----------|-------|--------|
| Core source (.cpp) | 81 | All identical |
| ImageProvider source | 6 | All identical |
| Private headers (*Data.h) | 12 | All identical |
| Platform headers | 11 | All identical |
| Binding headers (Bind*.h) | 81 of 82 | 1 differs (BindGlyph.h) |
| Python files | 7 of 8 | 1 differs (__init__.py) |

### Files That Don't Match (4 files)

| File | Reason |
|------|--------|
| `BindGlyph.h` | Kit has `#include <carb/InterfaceUtils.h>` for IGlyphManager lookup. Standalone stubs it. |
| `BindByteImageProvider.h` | Kit exposes carb::Format-dependent methods (set_bytes_data, set_raw_bytes_data). Standalone omits these. |
| `BindImageProvider.h` | Kit exposes RpResource and carb::Format methods. Standalone omits these. |
| `platform/Log.h` | Kit version routes OMNIUI_LOG_* to CARB_LOG_*. Standalone defaults to fprintf(stderr). |

### Architecture Rule

Shared files (core, bindings, python) should be byte-identical between Kit and standalone. Carb-specific code belongs ONLY in:
- Kit: `source/extensions/omni.ui/source/adapter/` and `source/extensions/omni.ui/source/main.cpp`
- Standalone: `standalone/src/` (GLFW/OpenGL backend)
