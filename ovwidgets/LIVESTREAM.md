# OvGear Livestream — Bring-Up Guide

> **Goal:** Start from a git clone and reach a state where a browser displays
> OvGear's full UI live, mouse clicks select prims, the File menu opens, and
> keyboard input filters the Stage Browser — all over WebRTC.

---

## Table of contents

1. [What this guide is for](#1-what-this-guide-is-for)
2. [Repos and components](#2-repos-and-components)
3. [Prerequisites](#3-prerequisites)
4. [Clone layout](#4-clone-layout)
5. [Build and install](#5-build-and-install)
6. [Environment configuration](#6-environment-configuration)
7. [Launch: server side](#7-launch-server-side)
8. [Launch: browser side](#8-launch-browser-side)
9. [Confirm the UI is visible](#9-confirm-the-ui-is-visible)
10. [Clicks and keyboard input](#10-clicks-and-keyboard-input)
11. [Taking screenshots](#11-taking-screenshots)
12. [Troubleshooting](#12-troubleshooting)
13. [Minimal success checklist](#13-minimal-success-checklist)

---

## 1. What this guide is for

This guide covers the **WebRTC livestream** mode of OvGear. In this mode:

- OvGear runs **headless** on a GPU server (no GLFW window).
- It renders its full 4-panel UI to an offscreen Vulkan surface.
- Each GPU frame is NVENC-encoded and sent to a browser over WebRTC.
- The browser sends mouse and keyboard events back to the server over the same
  WebRTC data channel, enabling real interaction with the running application.

**"Working browser"** means all of the following are true:
- A browser tab shows the live OvGear UI (Stage Browser, Viewport, Properties, menus).
- Mouse cursor movement is visible in the stream.
- Left-clicking a prim row selects it and the Properties panel updates.
- Clicking the File menu opens the dropdown.
- Clicking the Stage Browser filter field focuses it and keyboard input filters the tree.

This was confirmed working on this VM on 2026-05-03.

---

## 2. Repos and components

Four repositories are involved:

| Repo | Role |
|------|------|
| `ovgear` | The 3D editor application |
| `ovui` | `omni.ui` standalone — the UI toolkit (editable install) |
| `ovrtx` | RTX ray tracer — renders the Viewport (pip or editable install) |
| `ovstream` | Contains the WebRTC browser client HTML + JS files |

The **ovstream SDK** (`ovstream` Python package + `libovstream.so`) handles:
- H.264/HEVC NVENC encoding of GPU frames
- WebRTC signaling server (default port **49100**)
- ICE/DTLS transport
- Input event callbacks from the browser back to Python

`ovstream` is installed as a pip wheel in the venv. The wheel bundles
`libovstream.so` directly — no separate native build is required in the
standard setup.

---

## 3. Prerequisites

### 3.1 Operating system

Ubuntu 22.04, x86_64. NVIDIA GPU with Vulkan support (tested: L40).

Required system packages:

```bash
sudo apt-get install -y \
    build-essential cmake ninja-build \
    xvfb \
    libgl-dev libglu-dev libx11-dev libxt-dev \
    libfreetype-dev libglfw3-dev \
    libvulkan1 libvulkan-dev vulkan-tools \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    libgstrtspserver-1.0-dev
```

`libvulkan-dev` installs Vulkan headers at `/usr/include/vulkan/` — no manual
header download required. `xvfb` provides `Xvfb` for the virtual X11 display.
The GStreamer packages satisfy `libovstream.so`'s NEEDED entries
(`libgstapp-1.0.so.0`, `libgstvideo-1.0.so.0`, `libgstrtspserver-1.0.so.0`);
without them, `import ovstream` fails with a linker error at first use.

**CUDA Toolkit 12.x (required for headless export).** `libomniui_standalone.so`
is compiled with CUDA support and links `libcudart.so.12`. Without CUDA, the
ovui headless-frame export pipeline does not initialise and the server log will
show a missing-CUDA failure instead of `[ovgear/headless] export pipeline live`.

On this VM CUDA 12.6 is at `/usr/local/cuda-12.6`. CMake discovers it via
`CUDA_HOME`, `CUDAToolkit_ROOT`, or the default `/usr/local/cuda` symlink.
If CUDA is not at the default path, export one of:

```bash
export CUDA_HOME=/usr/local/cuda-12.6
# or:
export CUDAToolkit_ROOT=/usr/local/cuda-12.6
```

On a fresh machine, install the CUDA Toolkit from
[developer.nvidia.com/cuda-downloads](https://developer.nvidia.com/cuda-downloads)
(select: Linux → x86_64 → Ubuntu → 22.04 → deb(local), CUDA 12.x). The
`cuda-toolkit-12-x` meta-package is sufficient (no need for the full driver
installer if the NVIDIA driver is already installed).

A virtual X11 display is required even in headless Vulkan mode (some ovui/GLFW
paths inspect `DISPLAY`). On this VM `DISPLAY=:99` is already set. On a fresh
machine, run `Xvfb :99 -screen 0 1920x1080x24 &` and `export DISPLAY=:99`.

### 3.2 Python

**Python 3.12 exactly.** The venv, native extensions, and USD bindings are
all built against the 3.12 ABI.

**Important:** `python3.12` is **not in Ubuntu 22.04 apt**. Install it from
the deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get install python3.12 python3.12-dev python3.12-venv
```

Everywhere this guide writes `python3.12`, use the full path to a working
Python 3.12 build (or set an alias). All `pip install` commands below run
inside the venv once created, so the venv interpreter is used automatically.

Verify the right binary is accessible:

```bash
<path-to-python3.12> --version
# Must print 3.12.x
```

### 3.3 Node.js and Chrome (for browser automation)

Only needed if you want Puppeteer-based automation instead of a real browser tab.

```bash
node --version        # v14+ (v18 recommended)
which google-chrome   # /usr/bin/google-chrome
```

---

## 4. Clone layout

Place all four repos under a common parent, e.g. `~/dev/`:

```
~/dev/
├── ovgear/          ← main application
├── ovui/            ← omni.ui (editable install)
├── ovrtx/           ← ray tracer (pip or editable install)
└── ovstream/  ← WebRTC client HTML + browser JS
```

**Access requirements before cloning:**
- `ovgear` — public GitHub repo.
- `ovui` — `NVIDIA-Omniverse` GitHub org.
- `ovrtx` — `NVIDIA-Omniverse` GitHub org.
- `ovstream` — `NVIDIA-Omniverse` GitHub org.

Clone commands:

```bash
mkdir -p ~/dev && cd ~/dev

git clone git@github.com:NVIDIA-Omniverse/ovui.git
git clone git@github.com:NVIDIA-Omniverse/ovrtx.git
git clone https://github.com/NVIDIA-Omniverse/ovstream.git
```

For this guide's bring-up, pin each repo to the exact branch/commit known to
work together (confirmed 2026-05-03):

```bash
# ovgear — livestream feature branch
cd ~/dev/ovgear && git checkout feature/issue-34-ovstream-demo

# ovui — headless export branch; HEAD must be 602410b
cd ~/dev/ovui && git checkout feature/issue-34-headless-export

# ovrtx — commit that matches ovrtx==0.2.0 editable install
cd ~/dev/ovrtx && git checkout v0.2.0   # or the SHA that pip show reports

# ovstream — SDK 0.1.2 release commit
cd ~/dev/ovstream && git checkout ddedd7b
```

---

## 5. Build and install

### 5.1 Create the Python venv

```bash
cd ~/dev/ovgear
python3.12 -m venv _venv312
source _venv312/bin/activate
pip install -U pip setuptools wheel
```

### 5.2 Build and install omni.ui (ovui)

`omni.ui` is a C++ extension that must be compiled. Its CMakeLists.txt uses
the Vulkan headers installed in §3.1:

```bash
Vulkan_INCLUDE_DIR=/usr/include \
    pip install -e ~/dev/ovui
```

This builds `libovui.so` / `libomniui_standalone.so` and their Python bindings.
Build time: ~3–5 minutes on 12 cores.

Verify — import and check that CUDA interop was compiled in:

```bash
_venv312/bin/python3.12 -c "import omni.ui; print('omni.ui ok')"

# Confirm the built standalone library links libcudart (required for headless export):
ldd ~/dev/ovui/build/pip/standalone/libomniui_standalone.so | grep cudart
# Must output a resolved path, e.g.:
#   libcudart.so.12 => /usr/local/cuda-12.6/lib64/libcudart.so.12
# If it shows "not found" or nothing, the build lacks CUDA — rebuild with CUDA_HOME set.
```

### 5.3 Install ovrtx

`ovrtx` must be installed as an editable install from a local clone (the
package is not on the public PyPI index):

```bash
pip install -e ~/dev/ovrtx/python
```

Verify:

```bash
_venv312/bin/python3.12 -c "import ovrtx; print('ovrtx ok')"
```

### 5.4 Install the ovstream SDK

`ovstream` is not on a public pip index. The Python package lives at
`ovstream/sdk/python/`, but `libovstream.so` is **not committed to git** —
it is a native build artifact that must be present before `pip install` copies it
into the site-packages directory.

**Step 1 — Stage the native library.**

From a fresh checkout of `ddedd7b`, `sdk/python/ovstream/` contains only Python
files; no `.so` is bundled. The pre-built `libovstream.so` on this VM is at:

```
~/dev/ovstream/_build_sdk/libovstream.so
```

Copy it into the Python package source directory before installing:

```bash
cp ~/dev/ovstream/_build_sdk/libovstream.so \
   ~/dev/ovstream/sdk/python/ovstream/
```

> If `_build_sdk/` does not exist on a fresh machine, obtain the pre-built
> `libovstream.so` from your team (internal build system). Alternatively,
> skip the staging step and set `OVSTREAM_LIB_PATH` (§6.2) pointing to the
> `.so` — `_find_library()` checks that env var first and the pip install will
> succeed as Python-only; the library is resolved at runtime instead.

**Step 2 — Install the package:**

```bash
pip install ~/dev/ovstream/sdk/python/
```

**Verify the native library loaded** (not just the Python wrapper):

```bash
_venv312/bin/python3.12 -c "import ovstream; print('ovstream:', ovstream.get_version())"
# Expected:  ovstream: 0.1.2
# If it raises OSError: libovstream.so was not staged or OVSTREAM_LIB_PATH not set.
```

### 5.5 Install OvGear (the `ovwidgets` distribution)

```bash
cd ~/dev/ovgear
pip install -e ".[dev]"
```

Verify:

```bash
_venv312/bin/python3.12 -c "from ovuiapp.application import Application; print('ovuiapp ok')"
```

### 5.6 USD (optional for livestream demo)

The livestream demo uses `MockStageAdapter` (8 prims in the Stage Browser
hierarchy) and `MockRendererAdapter` (renders a dark-gray gradient with a
ground grid and **4 colored disk shapes** — blue Sphere, orange Cube, yellow
DomeLight, light-blue Camera). No USD file is required.

If you need real USD scene loading, see `README.md` for the full USD 25.11
source build instructions.

To run without USD:

```python
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")
```

This is set automatically by `ovrtx_renderer_adapter.py` — you do not need to
set it manually.

### 5.7 libovstream.so — runtime dependencies

The wheel bundles `libovstream.so` in the package directory:

```
_venv312/lib/python3.12/site-packages/ovstream/libovstream.so
```

`_find_library()` auto-discovers it — `OVSTREAM_LIB_PATH` is not needed.

**StreamSDK native libraries (critical).**  `libovstream.so` has a fixed RUNPATH
baked in at build time:

```
<path-to-ovstream>/source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64
```

The dynamic linker looks there for `libNvStreamBase.so` and `libNvStreamServer.so`.
Those files must exist at that exact absolute path at runtime. If `ovstream`
is cloned to `~/dev/ovstream` and checked out at commit `ddedd7b`, the files
land at the expected location automatically — no extra steps required.

If your clone is at a different absolute path, override the RUNPATH with
`LD_LIBRARY_PATH`:

```bash
export LD_LIBRARY_PATH=\
~/dev/ovstream/source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64:\
$LD_LIBRARY_PATH
```

**GStreamer runtime libraries.**  `libovstream.so` also NEEDs
`libgstapp-1.0.so.0`, `libgstvideo-1.0.so.0`, and `libgstrtspserver-1.0.so.0`.
These are satisfied by the system packages installed in §3.1 — no extra action
needed if you ran the apt block above.

### 5.8 Verify the full stack

```bash
cd ~/dev/ovgear
_venv312/bin/python3.12 -c "
import omni.ui, ovrtx
import ovstream
from ovuiapp.application import Application
from ovuiviewport._livestream_tap import LivestreamTap
# get_version() calls the native C library — proves libovstream.so loaded:
print('ovstream native lib:', ovstream.get_version())
print('full stack ok')
"
# Expected last two lines:
#   ovstream native lib: 0.1.2
#   full stack ok
```

---

## 6. Environment configuration

All environment variables must be set **before** importing `omni.ui` or `ovuiapp`.
The cleanest approach is to set them inside the server script (see §7).

### 6.1 Required for headless WebRTC streaming

```bash
export DISPLAY=:99                            # virtual X11 (GLFW probes this even headless)
export OMNIUI_HEADLESS=1                      # Vulkan offscreen surface, no GLFW window
export OMNIUI_BACKEND=vulkan                  # Vulkan renderer
export OVGEAR_LIVESTREAM=1                    # arms LivestreamTap
export OVGEAR_LIVESTREAM_PROTOCOL=webrtc      # WebRTC transport
export OVGEAR_LIVESTREAM_SIGNAL_PORT=49100    # TCP signaling port
export OVGEAR_HEADLESS=1                      # headless mode flag
export OVGEAR_HEADLESS_WIDTH=1920             # render width (default: 1280)
export OVGEAR_HEADLESS_HEIGHT=1080            # render height (default: 720)
export OVGEAR_LIVESTREAM_MEDIA_PORT=47999     # UDP RTP/DTLS media port (default: 47999)
# export OVGEAR_LIVESTREAM_PUBLIC_IP=<IP>    # only needed when browser is on a remote host (see §8.2)
```

> **Note on width/height:** The default is 1280×720. The coordinate examples in
> this guide assume 1920×1080. Set these explicitly so the stream resolution
> matches your automation scripts.

### 6.2 Only needed with a custom libovstream.so

```bash
export OVSTREAM_LIB_PATH=~/dev/ovstream/_build_sdk/libovstream.so
```

Skip this if using the pip-installed `ovstream` wheel (§5.7).

### 6.3 Only needed for USD scene loading

```bash
export PYTHONPATH="$HOME/dev/usd-build/install/lib/python:$PYTHONPATH"
export LD_LIBRARY_PATH="$HOME/dev/usd-build/install/lib:$LD_LIBRARY_PATH"
```

Skip this if running with `MockStageAdapter` (no USD file).

---

## 7. Launch: server side

### 7.1 The server script pattern

Environment variables must be set before any `omni.*` or `ovuiapp` import.
The canonical approach is a self-contained Python script written to `/tmp/`:

```python
#!/usr/bin/env python3
"""OvGear headless WebRTC server."""
import asyncio, os, sys, time

# Set env vars BEFORE any omni.* import
os.environ.setdefault("DISPLAY", ":99")
os.environ["OMNIUI_HEADLESS"] = "1"
os.environ["OMNIUI_BACKEND"] = "vulkan"
os.environ["OVGEAR_LIVESTREAM"] = "1"
os.environ["OVGEAR_LIVESTREAM_PROTOCOL"] = "webrtc"
os.environ["OVGEAR_LIVESTREAM_SIGNAL_PORT"] = "49100"
os.environ["OVGEAR_LIVESTREAM_MEDIA_PORT"]  = "47999"
os.environ["OVGEAR_HEADLESS"] = "1"
os.environ["OVGEAR_HEADLESS_WIDTH"] = "1920"
os.environ["OVGEAR_HEADLESS_HEIGHT"] = "1080"
# OVRTX_SKIP_USD_CHECK is auto-set by the adapter, but explicit is fine:
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

import omni.ui as ui
from omni.ui import testing as uitesting
from ovuiapp.application import Application
from ovuiapp.layout import write_split_ini
from ovuiapp.selection import SelectionBus
from ovuiapp.style import apply_global_styles, set_theme

READY_FLAG    = "/tmp/ovgear-ready"
WARMUP_FRAMES = 200     # ~15-20 s on L40; increase to 400 for black-frame issues
LIFETIME_SECS = 300     # how long to keep server alive

async def _main():
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._running = True
    asyncio.ensure_future(app.run_async())

    for _ in range(WARMUP_FRAMES):
        await ui.next_frame()

    with open(READY_FLAG, "w") as f:
        f.write("ready\n")
    sys.stdout.write("READY\n"); sys.stdout.flush()

    deadline = time.monotonic() + LIFETIME_SECS
    while time.monotonic() < deadline:
        await ui.next_frame()

    app._running = False
    ui.shutdown()
    os._exit(0)

if __name__ == "__main__":
    if os.path.exists(READY_FLAG):
        os.unlink(READY_FLAG)
    write_split_ini()
    ui.init("OvGear Livestream", width=1920, height=1080)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
```

Save this as `/tmp/ovgear_server.py`.

### 7.2 Start the server

Always run from the ovgear repo root so `imgui.ini` is written there and not
somewhere that gets accidentally staged:

```bash
cd ~/dev/ovgear
setsid _venv312/bin/python3.12 -u /tmp/ovgear_server.py \
    > /tmp/ovgear_server.log 2>&1 < /dev/null &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"
```

> **Why `setsid`?** It detaches the process from the launching shell's session.
> Without it, the server process exits when the shell's stdout pipe closes
> (e.g. in some CI or remote-exec contexts).

### 7.3 Wait for readiness

Warmup takes approximately **15–20 seconds** on an L40. Poll the ready flag:

```bash
timeout 60 bash -c 'until [ -f /tmp/ovgear-ready ]; do sleep 1; done' \
    && echo "Server ready"
```

If it times out, check the log:

```bash
tail -50 /tmp/ovgear_server.log
```

Common startup log lines (normal):

```
standalone::init: headless Vulkan mode enabled
VulkanBackend: selected GPU: NVIDIA L40
CudaVulkanInterop: initialized (1920x1080), zero-copy path ready
[ovgear/headless] export pipeline live
[ovgear/livestream] linear scratch ring allocated: 2 buffers × 1920x1080x4
```

Benign warnings (ignore these):

```
[ovstream/WARN/ovstream.webrtc] [Utils] The GPU with device ID 9909 is not white-listed.
[ovstream/WARN/ovstream.webrtc] [NattHolePunch] Add destination addresses failed ...
Failed to open [/var/run/utmp]
```

### 7.4 What the ready flag means

After writing the flag, the server has:

1. Initialised the Vulkan offscreen surface and the **mock renderer**
   (`MockRendererAdapter` + `MockStageAdapter`). The Stage Browser shows 8 prim
   rows; the Viewport shows 4 colored disk shapes on a dark grid. The ovrtx
   ray tracer is **not** active — it only activates when a USD file is opened.
2. Written `imgui.ini` with the canonical panel layout.
3. Rendered the full UI (all four panels) at least 200 frames.

The flag does **not** guarantee that port 49100 is listening. The ovstream tap
opens the signal port during its own initialisation, which runs asynchronously
alongside the render loop — it may or may not complete within `WARMUP_FRAMES`.
Always verify the port explicitly (§7.5) before attempting to connect.

### 7.5 Verify the port is open

```bash
ss -ltnp | grep 49100
# Expected: LISTEN on 0.0.0.0:49100
```

### 7.6 Stop the server

```bash
kill $SERVER_PID
```

**Never use `pkill -f` or `killall`** — they are forbidden in this project.
Always use a PID captured from `$!` immediately after the background launch.

---

## 8. Launch: browser side

### 8.1 Serve the WebRTC client

The browser client is two static files. Serve them with Python's HTTP server:

```bash
cd ~/dev/ovstream/sdk/examples/webrtc_client
~/dev/ovgear/_venv312/bin/python3.12 -m http.server 8080 &
HTTP_PID=$!
```

Verify:

```bash
curl -s http://localhost:8080/ | grep connect-button
# Expected: a line containing connect-button
```

### 8.2 Browser locality — same host vs. remote

The OvGear WebRTC stack starts two services:

| Service | Server listen address | Protocol | Port |
|---------|----------------------|----------|------|
| Python HTTP (client files) | `0.0.0.0` | TCP | 8080 |
| ovstream WebRTC signaling | `0.0.0.0` | TCP | 49100 |
| ovstream WebRTC media (RTP/DTLS) | `0.0.0.0` | **UDP** | 47999 |

The browser client page defaults to connecting to `Server: 127.0.0.1`,
`Signal Port: 49100`. Those are the client-side *target* fields, not the
server's bind address.

**Same-host browser (default setup — this is what the rest of the guide
assumes):** Chrome runs on the same machine as the GPU server. All three
services are reachable at `localhost`. This is the documented, tested path.

**Remote browser — what works and what doesn't:**

*SSH TCP port forwarding only tunnels HTTP and signaling; it does NOT carry
UDP media.* The common mistake is:

```bash
# INSUFFICIENT — forwards HTTP and signaling, but NOT WebRTC media (UDP):
ssh -N -L 8080:localhost:8080 -L 49100:localhost:49100 horde@<gpu-server>
```

With only TCP forwarding, the browser reaches the page and the signaling
exchange completes, but the `<video>` element stays black because UDP 47999
never arrives. Standard SSH `-L` only forwards TCP.

**Approaches that actually work for remote browsers:**

1. **Browser on the GPU host** (recommended): use `x2go`, NoMachine, a VNC
   desktop, or Chrome with a remote desktop. No networking changes needed.

2. **VPN / WireGuard** that carries UDP: the laptop joins the GPU server's
   network via VPN. Use the GPU server's **VPN-assigned IP** (not `localhost`)
   in both the browser URL and the client **Server** field:
   - Open `http://<gpu-vpn-ip>:8080/` in the laptop browser.
   - Set the client **Server** field to `<gpu-vpn-ip>`.
   - TCP 8080, TCP 49100, and UDP 47999 must all be reachable over the VPN.

3. **Direct firewall open** (not suitable for all environments):
   ```bash
   # Before starting OvGear:
   export OVGEAR_LIVESTREAM_PUBLIC_IP=<gpu-server-public-ip>
   ```
   Also open firewall rules for TCP 49100 and UDP 47999 from the laptop's IP.
   In the browser client, set **Server** to the GPU server's IP.
   UDP 47999 must be reachable from the browser host — verify with
   `nc -zu <server-ip> 47999` before blaming the OvGear config.

4. **TURN server**: the ovstream SDK supports TURN relay for media; see the
   ovstream SDK documentation for `TurnServer` configuration. Not covered here.

### 8.3 Connect manually

Open Chrome and navigate to `http://localhost:8080/`. The page shows:

- **Server**: `127.0.0.1` (pre-filled)
- **Signal Port**: `49100` (pre-filled)
- **Connect** button

Click **Connect**. After 2–5 seconds the status indicator shows **CONNECTED** and
the `<video>` element fills with the live OvGear stream.

### 8.4 Connect via Puppeteer (automated)

Install Puppeteer-core once:

```bash
mkdir /tmp/browser-test && cd /tmp/browser-test
npm init -y && npm install puppeteer-core
```

Minimal connection script:

```javascript
const puppeteer = require('/tmp/browser-test/node_modules/puppeteer-core');

(async () => {
    const browser = await puppeteer.launch({
        executablePath: '/usr/bin/google-chrome',
        headless: 'new',
        args: [
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--autoplay-policy=no-user-gesture-required',
        ],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto('http://localhost:8080/', { waitUntil: 'networkidle0' });
    await page.click('#connect-button');
    await page.waitForFunction(
        () => document.getElementById('status').textContent.includes('Connected'),
        { timeout: 30000 }
    );
    console.log('Connected');

    // Wait 8 s for stream to stabilise
    await new Promise(r => setTimeout(r, 8000));

    // Your interactions go here (see §10)

    await browser.close();
})();
```

Save to `/tmp/browser-test/connect.js` and run:

```bash
node /tmp/browser-test/connect.js
```

---

## 9. Confirm the UI is visible

### 9.1 Check video element state

In Puppeteer (or the browser console):

```javascript
const v    = document.getElementById('remote-video');
const rect = v.getBoundingClientRect();
console.log({
    readyState: v.readyState,    // must be 4 (HAVE_ENOUGH_DATA)
    videoWidth: v.videoWidth,    // must be 1920
    videoHeight: v.videoHeight,  // must be 1080
    paused: v.paused,            // must be false
    rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
});
```

Expected values at 1920×1080 browser viewport:

```
readyState: 4
videoWidth:  1920
videoHeight: 1080
paused:      false
rect:        { left: 144, top: 133, width: 1632, height: 918 }
```

If `videoWidth` is 0, frames are not flowing — check the server log for NVENC
errors or a port mismatch between server and client.

### 9.2 Take a browser screenshot

```javascript
await page.screenshot({ path: '/tmp/browser_check.png' });
```

The screenshot should show the full OvGear 4-panel layout: Stage Browser on the
left (8 prim rows in a hierarchy tree), Viewport in the centre (dark-gray
gradient background, ground grid, and 4 colored disk shapes — blue Sphere,
orange Cube, yellow DomeLight, light-blue Camera), Properties panel on the
right, Content Browser at the bottom. There is no RTX rendering in the default
mock path — the Viewport looks flat/2D, not photorealistic.

### 9.3 Take a server-side screenshot

Inside the server script, at any point after `READY`:

```python
from omni.ui import testing as uitesting
uitesting.capture_screenshot("/tmp/server_check.png")
await ui.next_frame()  # flush to disk
```

Server-side screenshots are unaffected by WebRTC encoding quality and are the
ground truth for what the server's UI state actually shows.

---

## 10. Clicks and keyboard input

### 10.1 How input flows

```
browser mouse/keyboard
  → NVST JS library (offsetX/offsetY in video element space)
  → WebRTC data channel
  → ovstream SDK callback on server (converts to stream coordinates)
  → RemoteInputBridge queue
  → per-frame drain (_drain_remote_input, before await ui.next_frame())
  → _inject_mouse_move / _inject_mouse_button / _inject_key_event
  → ImGui IO → widget state changes
```

### 10.2 Coordinate mapping — the critical rule

The server renders at **1920×1080**. The browser displays the video scaled down.
The NVST SDK automatically converts browser-element-relative coordinates back to
stream coordinates on the server. You only need to feed the browser coordinates
correctly.

**Always derive click targets from a live screenshot of the current session.**
Hardcoded or reused coordinates cause false negatives — clicks land in dead zones
or on the wrong widget, producing only cursor movement.

```javascript
// Read from live DOM every session — never hardcode
const v    = document.getElementById('remote-video');
const rect = v.getBoundingClientRect();

// Convert stream-space (STREAM_X, STREAM_Y) to browser-space (bx, by)
const bx = Math.round(rect.left + STREAM_X * rect.width  / v.videoWidth);
const by = Math.round(rect.top  + STREAM_Y * rect.height / v.videoHeight);
```

### 10.3 Known-good stream coordinates (confirmed 2026-05-03)

These were derived from screenshots taken at the same session. Use them as a
starting point, then verify with a hover screenshot before clicking.

| Widget | Stream X | Stream Y | Result when correct |
|--------|----------|----------|---------------------|
| World prim row (Stage Browser) | 64 | 102 | Prim selected, Properties panel updated |
| File menu button | 164 | 17 | File dropdown opens |
| Stage Browser filter field | 110 | 58 | Field focused (blue caret visible) |

These coordinates are valid for the MockStageAdapter scene at 1920×1080, DPI=1.0.
Re-derive from a screenshot if the scene, layout, or DPI changes.

### 10.4 Screenshot-first click procedure

Always follow this loop — do not skip the hover screenshot:

```javascript
// 1. Take baseline screenshot
await page.screenshot({ path: '/tmp/before.png' });

// 2. Move mouse to target (derived from baseline)
await page.mouse.move(bx, by);

// 3. Take hover screenshot — verify the right element is highlighted
await page.screenshot({ path: '/tmp/hover.png' });

// 4. Click with a hold so DOWN and UP arrive in separate drain frames
await page.mouse.down();
await new Promise(r => setTimeout(r, 150));
await page.mouse.up();

// 5. Take post-click screenshot — verify state change
await page.screenshot({ path: '/tmp/after_click.png' });
```

### 10.5 Keyboard input

After focusing a widget (e.g. the Stage Browser filter field via a click):

```javascript
// Type text — key events arrive via NVST SDK callbacks
await page.keyboard.type('geo', { delay: 120 });

// Ctrl+A to select all, Delete to clear
await page.keyboard.down('Control');
await page.keyboard.press('a');
await page.keyboard.up('Control');
await page.keyboard.press('Delete');
```

The NVST SDK delivers physical VK codes, not text. The `_nvst_printable_char()`
function in `ovuiapp/_input_drain.py` synthesises printable characters from VK
codes. Control and Alt key combos are correctly suppressed from text synthesis.

### 10.6 Diagnosing click failures

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Cursor moves but no state change | Wrong coordinates | Re-derive from screenshot |
| Nothing happens, no cursor movement | WebRTC input channel not active | Check server log for input callback registration |
| World row highlight visible but no selection | Click DOWN+UP in same drain frame | Add 150 ms hold between `mouse.down()` and `mouse.up()` |
| Filter text not appearing | Filter field not focused (click missed) | Verify hover screenshot shows focus ring before typing |

---

## 11. Taking screenshots

### 11.1 Browser-side (Puppeteer)

```javascript
await page.screenshot({ path: '/tmp/shot.png' });
```

Captures the Chrome window including the OvGear video element. Affected by
WebRTC encoding quality (compression artefacts). Use for verifying visible
state changes from the user's perspective.

### 11.2 Server-side (ground truth)

```python
from omni.ui import testing as uitesting
uitesting.capture_screenshot("/tmp/shot.png")
await ui.next_frame()  # required to flush the screenshot to disk
```

Captures the raw GPU framebuffer. Unaffected by WebRTC. Use to verify the
server-side UI state exactly (e.g., after a filter change, confirm the tree
state on the server even if the browser screenshot is blurry).

### 11.3 Pairing screenshots with interactions

For proof quality, pair every interaction with a server screenshot:

```python
# Inside the server event loop — use a marker file written by the browser script
import pathlib

marker_dir = pathlib.Path("/tmp/ovgear-markers")
marker_dir.mkdir(exist_ok=True)

async def _main():
    # ... (warmup, ready flag) ...
    shot_idx = 0
    deadline = time.monotonic() + LIFETIME_SECS
    while time.monotonic() < deadline:
        await ui.next_frame()
        # Check for marker files from the browser script
        for marker in sorted(marker_dir.glob("*.shot")):
            path = f"/tmp/server_{shot_idx:02d}_{marker.stem}.png"
            uitesting.capture_screenshot(path)
            await ui.next_frame()
            marker.unlink()
            shot_idx += 1
```

Browser script drops a marker file after each interaction, the server catches
it on the next frame and saves a server-side screenshot.

---

## 12. Troubleshooting

### `ModuleNotFoundError: No module named 'omni'`

Wrong Python interpreter. Use only:

```bash
~/dev/ovgear/_venv312/bin/python3.12
```

### `ModuleNotFoundError: No module named 'omni'` even with correct interpreter

Re-run the editable install:

```bash
cd ~/dev/ovgear
_venv312/bin/pip install -e . -e ~/dev/ovui
```

### `libovstream.so: cannot open shared object file`

The pip-installed `ovstream` wheel bundles `libovstream.so`. If you see this
error, the wheel may be broken or a different ovstream was imported. Verify:

```bash
ls _venv312/lib/python3.12/site-packages/ovstream/libovstream.so
# Should exist (~131 KB)
```

If the file is absent, re-stage and reinstall from the local SDK path:

```bash
# Re-stage the native lib first:
cp ~/dev/ovstream/_build_sdk/libovstream.so \
   ~/dev/ovstream/sdk/python/ovstream/
# Then force-reinstall:
_venv312/bin/pip install --force-reinstall ~/dev/ovstream/sdk/python/
```

If `_build_sdk/libovstream.so` is not available, set `OVSTREAM_LIB_PATH` to
point to the built `.so` instead (§6.2) and skip the staging step.

### Server starts but `videoWidth = 0` after connecting

NVENC encoding failed to start. The L40 GPU produces "not white-listed" warnings
that are benign — encoding works despite them. If `videoWidth` stays 0:

1. Check the server log for `[ovgear/livestream] disabled` or `bring-up failed`.
2. Verify port 49100 is open (`ss -ltnp | grep 49100`).
3. Check the signal port matches between server and the browser client's port
   field (both must be `49100`).

### Server ready flag timeout (>60 s)

Warmup can be slow. Common causes:

- `DISPLAY` not set — the server hangs waiting for X11
- Vulkan initialization failure — check for `VulkanBackend: init failed`
- Wrong Python interpreter — check the log for `ImportError`

Increase `WARMUP_FRAMES` to 400 if you see black frames on first connect.

### Browser screenshot shows black frame

The default bring-up path uses `MockRendererAdapter` (no ovrtx). Diagnose in
this order:

1. **Headless export not live**: check server log for `[ovgear/headless] export
   pipeline live`. If missing, the CUDA-Vulkan interop did not initialise —
   check the CUDA Toolkit installation and the `ldd` verification in §5.2.

2. **NVENC pipeline not started**: look for `[ovgear/livestream] linear scratch
   ring allocated` in the log. Absent means the streaming tap didn't arm —
   verify `OVGEAR_LIVESTREAM=1` is set and `OVGEAR_LIVESTREAM_PROTOCOL=webrtc`.

3. **Media not reaching browser**: verify UDP 47999 is reachable from the
   browser host (`nc -zu <server> 47999`). A TCP-only setup (SSH forwarding)
   silently drops media.

4. **Stream started too soon**: give the pipeline more warmup time:
   - Increase `WARMUP_FRAMES` from 200 to 400.
   - Add settle time after connecting: `await new Promise(r => setTimeout(r, 12000))`.

5. **ovrtx-specific (USD path only)**: if you opened a USD file via the File
   menu and the frame went black, ovrtx initialisation may be lagging. Increase
   `WARMUP_FRAMES` further or check the server log for ovrtx errors.

### HTTP server not responding

```bash
curl -s http://localhost:8080/ | grep connect-button
```

If nothing, restart:

```bash
cd ~/dev/ovstream/sdk/examples/webrtc_client
~/dev/ovgear/_venv312/bin/python3.12 -m http.server 8080 &
```

### `imgui.ini` appears in `git status`

This is expected — ovgear writes `imgui.ini` on every run. It is in `.gitignore`
and must not be committed. Discard it:

```bash
git restore imgui.ini
```

If it is staged: `git restore --staged imgui.ini && git restore imgui.ini`.

### Clicks produce no visible state change

The most common cause is stale or incorrect stream coordinates. Follow the
screenshot-first procedure (§10.4). Specifically:

1. Take a screenshot.
2. Measure the target widget's pixel position from the screenshot image.
3. Convert to browser coordinates using the live `getBoundingClientRect()`.
4. Move mouse and take a hover screenshot to confirm the widget is highlighted.
5. Only then click.

---

## 13. Minimal success checklist

Run through this in order. Check each item before proceeding to the next.

```
[ ] _venv312/bin/python3.12 -c "import omni.ui, ovrtx, ovstream; print('ok')"
[ ] Server started: setsid ... /tmp/ovgear_server.py > /tmp/ovgear_server.log 2>&1 &
[ ] Ready flag appears: ls /tmp/ovgear-ready  (within 60 s)
[ ] Port open: ss -ltnp | grep 49100
[ ] HTTP server running: curl -s http://localhost:8080/ | grep connect-button
[ ] Browser connected: page status says "Connected"
[ ] Video streaming: videoWidth=1920, readyState=4, paused=false
[ ] Settle wait: 8 s after "Connected"
[ ] Baseline screenshot taken: /tmp/baseline.png (visible UI panels)
[ ] Hover screenshot confirms target widget highlighted
[ ] Post-click screenshot shows state change (prim selected / menu open / filter focused)
[ ] Keyboard input produces visible text in filter field
```

All boxes checked = working browser session.
