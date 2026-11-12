# Headless Vulkan Rendering

`ovui` supports fully headless GPU rendering via Vulkan — no display server (X11/Wayland), no window manager, and no GLFW required at runtime.

This is designed for **cloud and server deployments** where you need GPU-accelerated UI rendering without a physical display.

## Requirements

- **Vulkan-capable GPU** with a driver installed (NVIDIA, AMD, or Intel)
- **Vulkan ICD** (Installable Client Driver) — typically comes with the GPU driver
- No display server needed (`DISPLAY` can be unset)

### Typical server setup (Ubuntu/Debian)

```bash
# NVIDIA driver (includes Vulkan ICD)
apt-get install nvidia-driver-535

# Or for AMD
apt-get install mesa-vulkan-drivers

# Verify Vulkan works
vulkaninfo --summary
```

## Building

### Standard build (GLFW + headless)

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

Both the windowed (GLFW) and headless (Vulkan) paths are compiled. At runtime, set `OMNIUI_HEADLESS=1` to use headless mode.

### Headless-only build (no GLFW/OpenGL dependency)

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release -DOMNIUI_HEADLESS_ONLY=ON
cmake --build build
```

This skips GLFW and OpenGL entirely — only Vulkan is required.

## Usage

### Environment variables

| Variable | Values | Description |
|---|---|---|
| `OMNIUI_HEADLESS` | `1`, `true` | Enable headless mode (no window created) |
| `OMNIUI_BACKEND` | `vulkan`, `vk` | Select Vulkan backend (default is OpenGL) |

### Running headless

```bash
# Unset DISPLAY to prove no windowing system is needed
DISPLAY= OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan ./your_app
```

### From C++

```cpp
#include "StandaloneInit.h"

// Set environment before init
setenv("OMNIUI_HEADLESS", "1", 1);
setenv("OMNIUI_BACKEND", "vulkan", 1);

omni::ui::standalone::init("My App", 1920, 1080);

// Render frames
for (int i = 0; i < 10; ++i)
    omni::ui::standalone::tick();

// Capture screenshot
omni::ui::standalone::scheduleScreenshot("output.png");
omni::ui::standalone::tick();  // triggers capture
omni::ui::standalone::pollScreenshotDone();

omni::ui::standalone::shutdown();
```

### From Python

```python
import omni.ui as ui

# Set env vars before importing standalone
import os
os.environ["OMNIUI_HEADLESS"] = "1"
os.environ["OMNIUI_BACKEND"] = "vulkan"

ui.standalone_init("Headless App", 1920, 1080)

# Create widgets, render frames, capture screenshots...
ui.standalone_tick()
ui.standalone_shutdown()
```

### Running without a GPU (Lavapipe / software ICD)

`ovui` can run entirely without a GPU using [Mesa Lavapipe](https://docs.mesa3d.org/drivers/lavapipe.html), a CPU-based software Vulkan implementation. This is useful for CI pipelines, containers, and developer machines without a discrete GPU.

#### Requirements

```bash
# Ubuntu 22.04+
apt-get install mesa-vulkan-drivers libglfw3-dev
```

#### Usage

Set `OMNIUI_LAVAPIPE=1` before calling `init()`. The standalone library probes for the Lavapipe ICD at standard paths and injects `VK_DRIVER_FILES` before Vulkan instance creation:

```bash
OMNIUI_LAVAPIPE=1 OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan ./your_app
```

On non-Ubuntu distributions where the Lavapipe ICD lives at a different path, override it:

```bash
OMNIUI_LAVAPIPE=1 \
OMNIUI_LAVAPIPE_ICD_PATH=/usr/lib/x86_64-linux-gnu/vulkan/icd.d/lvp_icd.x86_64.json \
OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan ./your_app
```

The library probes these paths in order: `lvp_icd.x86_64.json`, `lvp_icd.aarch64.json`, `lvp_icd.json` (all under `/usr/share/vulkan/icd.d/`). Set `OMNIUI_LAVAPIPE_ICD_PATH` to override.

#### Confirming Lavapipe is selected

When `OMNIUI_LAVAPIPE=1` is active the init log shows:

```
standalone::init: injecting VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json
VulkanBackend: selected device: "llvmpipe (LLVM 15.0.7, 256 bits)" (vendorID=0x10005, type=CPU (software renderer))
VulkanBackend: device does not support VK_KHR_external_semaphore_fd, CUDA interop disabled
```

The `type=CPU (software renderer)` suffix confirms Lavapipe was selected as the physical device. In builds with CUDA support, the second line shows that the CUDA interop extensions were skipped because Lavapipe does not provide all of them; the UI still initializes and renders.

#### Limitations

| Feature | Status |
|---|---|
| CUDA-Vulkan interop | Not available (Lavapipe does not provide all the external memory/semaphore extensions it needs) |
| NVENC hardware encoder | Not available |
| `headless_frame` export | Not available |
| Screenshot / `scheduleScreenshot()` | Works |

#### Troubleshooting

**`standalone::init: OMNIUI_LAVAPIPE=1 but no Lavapipe ICD found at: ...`**
— `mesa-vulkan-drivers` is not installed, or the ICD is at a non-standard path.
Install: `apt-get install mesa-vulkan-drivers`
Verify: `ls /usr/share/vulkan/icd.d/lvp_icd.x86_64.json`
Or set `OMNIUI_LAVAPIPE_ICD_PATH` to the correct ICD path.

**`standalone::init: OMNIUI_LAVAPIPE_ICD_PATH=<path>: file not found`**
— The path set via `OMNIUI_LAVAPIPE_ICD_PATH` does not exist. Verify the ICD file is present at that path.

**`VulkanBackend: no Vulkan-capable GPU found`**
— `mesa-vulkan-drivers` is not installed, or `OMNIUI_LAVAPIPE=1` was not set on a no-GPU host.
Verify: `ls /usr/share/vulkan/icd.d/lvp_icd.x86_64.json`

**`VulkanBackend: vkCreateDevice failed (-7)`**
— The device rejected a requested extension. The optional CUDA interop extensions are only requested when the device provides all of them, so this points to a missing required extension (for example `VK_KHR_swapchain` in windowed mode). If `init()` fails it raises `RuntimeError`.

**`standalone::init: injecting VK_DRIVER_FILES=` does not appear**
— `OMNIUI_LAVAPIPE=1` was not exported before `init()` was called. Ensure the env var is set in the shell before running the binary.

---

## Frame export to CUDA (`omni.ui.standalone.headless_frame`)

When a downstream consumer (e.g. a livestream / NVENC pipeline) needs
direct GPU access to the rendered frame instead of a PNG, use the
`headless_frame` submodule. It exposes ovui's offscreen Vulkan render
target as a CUDA pitched-linear buffer via CUDA-Vulkan interop — no
host roundtrip.

The submodule is a thin wrapper over the `_ui._headless_frame_*`
pybind11 bindings; the underlying contract is documented in
`bindings/StandalonePlatformBindings.cpp` and implemented in
`standalone/src/StandaloneInit.cpp`.

### Surface

| Function | Purpose |
|---|---|
| `init() -> bool` | Initialise the export pipeline. Refuses unless `OMNIUI_HEADLESS=1` and `OMNIUI_BACKEND=vulkan`. |
| `shutdown() -> None` | Tear it down. Safe when never initialised. |
| `extent() -> (w, h)` | Width/height of the offscreen image (RGBA8). |
| `format() -> str` | Pixel format string (currently `'rgba8'`, alpha premultiplied; see [Clear color and alpha](#clear-color-and-alpha-overlay-export)). |
| `wait_ready(timeout_ns) -> bool` | Queue an async CUDA wait on the V→C semaphore. |
| `copy_to_linear(dst_dev_ptr, dst_pitch_bytes, cuda_stream_handle=0) -> bool` | `cudaMemcpy2DFromArrayAsync` into a caller-owned pitched buffer. |
| `signal_consumed() -> None` | Signal the C→V semaphore so ovui can reuse the image. |

### Per-frame ordering

`wait_ready` → `copy_to_linear` → (consumer reads / re-encodes the
buffer) → `signal_consumed`. This pairs with the offscreen image's
two-semaphore rhythm: ovui signals V→C after rendering, the consumer
signals C→V after reading.

### Example (Python)

```python
import os
os.environ["OMNIUI_HEADLESS"] = "1"
os.environ["OMNIUI_BACKEND"] = "vulkan"

from omni.ui import standalone
from omni.ui.standalone import headless_frame

standalone.init("Headless App", 1920, 1080)

assert headless_frame.init(), "headless export refused — check env vars"
w, h = headless_frame.extent()
assert headless_frame.format() == "rgba8"

# Caller-owned pitched RGBA8 buffer (allocate via cuda-python,
# CuPy, ctypes-cudart, etc.). Pseudocode:
#   dst, pitch = cudart.malloc_pitch(width=w*4, height=h)
dst, pitch = allocate_pitched_rgba8(w, h)

try:
    for _ in range(num_frames):
        standalone.tick()  # or whatever drives the run loop

        headless_frame.wait_ready(timeout_ns=10_000_000)
        headless_frame.copy_to_linear(dst, pitch, cuda_stream_handle=0)
        # ...consume `dst` (encode, swap channels, etc.) ...
        headless_frame.signal_consumed()
finally:
    headless_frame.shutdown()
    standalone.shutdown()
```

The pipeline does not allocate the destination buffer — the caller
owns it (typical pattern: a 2-buffer ring of `cudaMallocPitch`
allocations rotated each frame).

## Clear color and alpha (overlay export)

Each headless Vulkan frame starts with a clear of the offscreen RGBA8
image. The pixels that no widget draws keep the clear color. The default
clear color is the opaque `(0.12, 0.13, 0.14, 1.0)`, which is
`(31, 33, 36, 255)` in 8-bit values.

To export only the UI, for example a gizmo, and composite it over a frame
from a different renderer, set a transparent clear color. Also give the
windows the flag `ui.WINDOW_FLAGS_NO_BACKGROUND`, because a window
background covers the clear color.

```python
import os
os.environ["OMNIUI_HEADLESS"] = "1"
os.environ["OMNIUI_BACKEND"] = "vulkan"

import omni.ui as ui
from omni.ui import standalone

ui.init("Overlay", 1920, 1080)
standalone.set_clear_color(0.0, 0.0, 0.0, 0.0)
# Build the overlay, then export it with headless_frame or a screenshot.
```

| Function | Purpose |
|---|---|
| `standalone.set_clear_color(red, green, blue, alpha) -> None` | Set the clear color. |
| `standalone.get_clear_color() -> (red, green, blue, alpha)` | Return the clear color, or `None` when there is no headless Vulkan backend. |

In C++, use `omni::ui::standalone::setClearColor(red, green, blue, alpha, &error)`
and `getClearColor(&red, &green, &blue, &alpha)` from `StandaloneInit.h`.

### When the setting takes effect

- Call `set_clear_color` after `init()`. `init()` draws no frame, so a
  call before the first frame applies to the first frame.
- A change applies from the next frame that starts after the call.
- The color stays until `shutdown()`. After the next `init()`, the clear
  color is the default again.

### Alpha: premultiplied in memory, straight in PNG and BMP files

ovui draws each shape, text and image with color `C` and alpha `A` over
the pixel `P` below it: `rgb = C * A + P.rgb * (1 - A)` and
`alpha = A + P.alpha * (1 - A)`. So the frame in memory is premultiplied
by alpha: on a transparent clear, a drawn pixel holds its color times its
alpha. Image files store straight (not premultiplied) color instead,
because the readers of these formats expect it.

| Output | Color form | Composite the frame `F` over an opaque image `B` |
|---|---|---|
| `headless_frame` export (`copy_to_linear`) | premultiplied | `out.rgb = F.rgb + B.rgb * (1 - F.alpha)` |
| Vulkan read-back (C++ `VulkanBackend::readbackPixels`, the bytes that a screenshot starts from) | premultiplied | `out.rgb = F.rgb + B.rgb * (1 - F.alpha)` |
| `.png` screenshot | straight, as the PNG format defines | any PNG reader, for example Pillow `Image.alpha_composite`; the formula is `out.rgb = F.rgb * F.alpha + B.rgb * (1 - F.alpha)` |
| `.bmp` screenshot (32 bits with alpha) | straight, as image readers take it | the same as `.png` |
| `.jpg` screenshot | no alpha | the file is the frame over black |

- For a `.png` or `.bmp` file, ovui divides the color of each pixel that is
  not opaque by its alpha (`rgb * 255 / alpha`, rounded; `0` where alpha
  is `0`). Opaque pixels keep their bytes, so with an opaque clear color
  the file holds the same bytes as the export.
- A pixel that no widget draws holds the clear color. In the export and the
  read-back, each 8-bit value is the clear value times 255, rounded: the
  clear `(0.2, 0.4, 0.6, 0.6)` is `(51, 102, 153, 153)`. A `.png` file holds
  the straight form of it, `(85, 170, 255, 153)`. A transparent clear is
  `(0, 0, 0, 0)` in both.
- Use the formula of the output. Premultiplied pixels multiplied by alpha
  again give dark shapes and dark edges (halos) around smooth edges, text
  and half-transparent shapes. Straight pixels used as premultiplied give
  bright edges.
- The clear color that you set uses the premultiplied form. Red, green and
  blue must each be at most alpha.

### Values that are not valid

| Cause | Python | C++ `setClearColor` |
|---|---|---|
| A value is not a number from 0 to 1 (also NaN or infinity). | `ValueError` | returns `false` |
| Red, green or blue is greater than alpha. | `ValueError` | returns `false` |
| `init()` did not run, or the backend is not headless Vulkan (a window, or headless EGL). These backends do not use this color. | `RuntimeError` | returns `false` |

In each case the current color stays, and the message gives the value and
the cause. ovui also writes the message to stderr.

## Test executable

A test binary `headless_test` is built automatically when Vulkan is available:

```bash
# Run the headless test (renders widgets, saves screenshot)
DISPLAY= OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan ./build/standalone/headless_test output.png

# Verify output
file output.png  # should show PNG image data
```

## Architecture

```
                          +-------------------+
                          |  StandaloneInit   |
                          +-------------------+
                         /         |           \
              HEADLESS_GL  HEADLESS=1        default
                       v  no HEADLESS_GL       v
  +--------------------+  +---------------------+  +----------------+
  |HeadlessEglPlatform |  |HeadlessVulkanPlatform|  |  GlfwPlatform  |
  |(OpenGL via EGL)    |  |(Vulkan, no display)  |  |  (windowed)    |
  +--------------------+  +---------------------+  +----------------+
           |                       |                       |
           v                       v                       v
  +----------------+  +----------------------------+  +--------------+
  | EGL FBO (RGBA8)|  | VulkanBackend              |  |VulkanBackend |
  | glReadPixels   |  | .initHeadless()            |  |.init(window) |
  | → PNG          |  | Offscreen VkImage (RGBA8)  |  +--------------+
  +----------------+  | readbackPixels() → CPU     |
                       +----------------------------+
```

- **HeadlessVulkanPlatform** implements `IUiPlatform` without any windowing system
- **VulkanBackend::initHeadless()** creates a Vulkan instance with zero surface extensions
- **HeadlessEglPlatform** uses EGL to create an OpenGL context without a display
- All rendering goes to an offscreen surface — no swapchain, no presentation
- `readbackPixels()` / `glReadPixels()` copies rendered image to CPU memory for saving

## Troubleshooting

**"no Vulkan-capable GPU found"**
- Ensure GPU driver is installed: `nvidia-smi` or `lspci | grep VGA`
- Check Vulkan ICD: `ls /usr/share/vulkan/icd.d/`
- Run `vulkaninfo --summary` to verify

**"vkCreateInstance failed"**
- Check that the Vulkan loader is installed: `dpkg -l | grep libvulkan`
- On containers, ensure the GPU device is mapped: `docker run --gpus all ...`

**Blank/black screenshot**
- Ensure at least 2-3 `tick()` calls before capturing (ImGui needs warmup frames)
- Check that widgets are being created before the render loop

---

## Headless OpenGL via EGL

`ovui` supports headless OpenGL rendering using [EGL](https://www.khronos.org/egl) — no display server (X11/Wayland) required. This path uses `HeadlessEglPlatform` and renders to an FBO (framebuffer object) via OpenGL.

This is an alternative to the Vulkan headless path when Vulkan is unavailable or undesired.

### Requirements

```bash
# Ubuntu 22.04+
apt-get install libegl1-mesa-dev libgles2-mesa-dev libglfw3-dev libfreetype-dev
```

### Building

The EGL path is opt-in and must be enabled at configure time:

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release -DOMNIUI_HEADLESS_GL=ON
cmake --build build
```

### Usage

Set both `OMNIUI_HEADLESS=1` and `OMNIUI_HEADLESS_GL=1` before calling `init()`:

```bash
OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 ./your_app
```

The init log confirms EGL mode:

```
standalone::init: EGL headless GL mode enabled
```

### EGL strategy selection

`HeadlessEglPlatform` tries two EGL strategies in order:

1. **Device enumerate** (`EGL_EXT_platform_device`): creates a `EGLDeviceEXT` from the first enumerated EGL device. Used on GPU hosts with a driver-provided EGL device.
2. **Surfaceless fallback** (`EGL_MESA_platform_surfaceless`): a Mesa-specific no-display backend. Used when no EGL device is enumerated (e.g. pure no-GPU CI runners).

The selected strategy is logged:

```
HeadlessEglPlatform: EGL_EXT_platform_device active. GL vendor: NVIDIA ...
```

or

```
HeadlessEglPlatform: EGL_MESA_platform_surfaceless active. GL vendor: Mesa ...
```

To force the surfaceless path (for CI or testing):

```bash
OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 OMNIUI_EGL_FORCE_SURFACELESS=1 \
  MESA_GL_VERSION_OVERRIDE=3.3 ./your_app
```

### Screenshot error checking

After `scheduleScreenshot()` + `tick()`, callers must check both flags before trusting the output file:

```cpp
bool captured = standalone::pollScreenshotDone();
bool hasError = standalone::hadLastScreenshotError();
if (!captured || hasError) { /* handle failure */ }
```

`hadLastScreenshotError()` returns true if the PNG write failed (e.g. EGL context lost during readback). Checking `pollScreenshotDone()` alone is not sufficient.

### Limitations

| Feature | Status |
|---|---|
| CUDA-Vulkan interop | Not available (OpenGL path) |
| NVENC hardware encoder | Not available |
| `headless_frame` export | Not available |
| `set_clear_color()` | Not available (`RuntimeError`) |
| Screenshot / `scheduleScreenshot()` | Works |
| Window creation / `DISPLAY` | Not required |

### Troubleshooting

**`standalone::init: EGL headless GL mode enabled` does not appear**
— `OMNIUI_HEADLESS_GL=1` was not set, or the binary was not built with `-DOMNIUI_HEADLESS_GL=ON`.

**`HeadlessEglPlatform: EGL_MESA_platform_surfaceless not available at compile time`**
— The binary was built without surfaceless support. Ensure `libegl1-mesa-dev` was installed before configuring: `apt-get install libegl1-mesa-dev`, then reconfigure and rebuild.

**`HeadlessEglPlatform: surfaceless: eglGetPlatformDisplayEXT unavailable`**
— The EGL loader does not export `eglGetPlatformDisplayEXT`. Install the Mesa EGL library: `apt-get install libegl1-mesa`.

**`HeadlessEglPlatform: surfaceless: eglGetPlatformDisplayEXT returned EGL_NO_DISPLAY`**
— The surfaceless platform could not create an EGL display. Verify `libegl1-mesa` is installed and supports `EGL_MESA_platform_surfaceless`.

**`HeadlessEglPlatform: surfaceless: eglInitialize failed (error 0x...)`**
— EGL initialisation failed on the surfaceless display. Ensure `libegl1-mesa` is installed and up to date.

**`HeadlessEglPlatform: surfaceless: eglChooseConfig returned 0 configs`**
— No EGL config matching RGBA8 + depth24 + core OpenGL was found. Set `MESA_GL_VERSION_OVERRIDE=3.3` so Mesa advertises a GL 3.3 core profile.

**`HeadlessEglPlatform: surfaceless: eglCreateContext failed (error 0x...)`**
— OpenGL 3.3 core context creation failed. Set `MESA_GL_VERSION_OVERRIDE=3.3`.

**`HeadlessEglPlatform: surfaceless eglMakeCurrent failed (error 0x...)`**
— Context activation failed on the surfaceless display. Reinstall: `apt-get reinstall libegl1-mesa`.

**`HeadlessEglPlatform: gladLoadGLLoader failed`** (device-enumerate or surfaceless path)
— GLAD could not resolve GL function pointers. Ensure the Mesa EGL libraries are installed: `apt-get install libegl1-mesa libgles2-mesa`.

**`HeadlessEglPlatform: surfaceless: gladLoadGLLoader failed`**
— Same as above, in the surfaceless path. Ensure `libegl1-mesa` and `libgles2-mesa` are installed.

**`HeadlessEglPlatform: FBO incomplete (status 0x...)` / `HeadlessEglPlatform: ImGui_ImplOpenGL3_Init failed`**
— Framebuffer or ImGui GL backend setup failed. Set `MESA_GL_VERSION_OVERRIDE=3.3` to ensure Mesa advertises the GL 3.3 version that ImGui requires.

**Blank screenshot on no-GPU runner**
— Set `MESA_GL_VERSION_OVERRIDE=3.3` to prevent Mesa from advertising a GL version below what ImGui requires.
