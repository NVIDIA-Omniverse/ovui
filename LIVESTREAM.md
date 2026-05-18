# OV Widgets Livestream Browser Proof Runbook

## 1. Title and purpose

This runbook documents the complete zero-to-browser-screenshot path used to
prove OV Widgets running in a browser with an ovrtx-rendered USD viewport. It is
written from the reference build session that produced the browser proof.

All commands use a machine-agnostic workspace variable. Set it once before
starting, and keep the same shell environment while following the runbook:

```bash
export WORKDIR="$HOME/dev/ovui-livestream-work"
mkdir -p "$WORKDIR"
cd "$WORKDIR"
```

The expected final result is a real browser screenshot of the OVSTREAM WebRTC
client. The browser page should show:

- The WebRTC client status as `CONNECTED`.
- The streamed OV Widgets application inside the browser video element.
- The USD scene `simple_scene.usda` loaded.
- The prim `/World/Cube` selected.
- A visible ovrtx-rendered viewport containing the cube, sphere, pyramid, and
  pillar, with the cube outlined/selected and the translate gizmo visible.

The proof screenshot produced by this runbook is:

```text
$WORKDIR/ovui/ovwidgets-browser-proof.png
```

That screenshot was captured from:

```text
http://127.0.0.1:8080/
```

with the OV Widgets livestream server and static WebRTC client server running
for inspection.

## 2. Scope and repository layout

Use the OVUI repository as the source of truth. `ovgear` is no longer a separate
source of truth for this workflow; the application and widgets are part of the
OVUI monorepo.

The relevant OVUI monorepo layout is:

```text
$WORKDIR/ovui/
  README.md
  ovui/
    README.md
    HEADLESS.md
  ovwidgets/
    README.md
    LIVESTREAM.md
    dist/common/
    dist/stage/
    dist/layers/
    dist/content/
    dist/property/
    dist/viewport/
    dist/app/
    tests/data/simple_scene.usda
  ovui-data-adapters/
    README.md
    dist/common/
    dist/openusd/
```

External repositories and build products are also required:

```text
$WORKDIR/ovrtx
  ovrtx Python package, headers, examples, and documented release runtime fetch.

$WORKDIR/usd-build/OpenUSD
  OpenUSD source checkout at v25.11.

$WORKDIR/usd-build/install
  OpenUSD install prefix used by OV Widgets.

$WORKDIR/ovstream
  NVIDIA ovstream checkout, OVSTREAM SDK source, StreamSDK Git LFS
  binaries, browser WebRTC client, and SDK Python package.

$WORKDIR/python-3.12.13-official
  Official Python 3.12.13 built from source for this workflow.

$WORKDIR/openssl-3.5.6
  Local OpenSSL source build used by the official Python build in the successful
  run.
```

The runbook targets latest `main` for OVUI, ovrtx, and ovstream, and the
documented OpenUSD tag required by OV Widgets:

| Component | Path | Version / branch |
| --- | --- | --- |
| OVUI | `$WORKDIR/ovui` | latest `main` |
| ovrtx | `$WORKDIR/ovrtx` | latest `main`, package/release `0.2.0` |
| OpenUSD | `$WORKDIR/usd-build/OpenUSD` | tag `v25.11` |
| ovstream | `$WORKDIR/ovstream` | latest `main`; `VERSION.md` should identify the expected package version |
| Python | `$WORKDIR/python-3.12.13-official` | `Python 3.12.13` |
| OpenSSL | `$WORKDIR/openssl-3.5.6` | `OpenSSL 3.5.6` |

## 3. Prerequisites

### 3.1 Operating system and GPU assumptions

The successful run was on Linux x86_64, compatible with Ubuntu 22.04 style
packages. The GPU path used a real NVIDIA GPU and Vulkan. The runtime log showed:

```text
VulkanBackend: selected device: "NVIDIA RTX A6000"
```

The host GPU/driver details captured during the documentation pass were:

```text
nvidia-smi driver: 595.71.05
GPU:               NVIDIA RTX A6000
Vulkan instance:   1.4.313
NVIDIA Vulkan:     device API 1.4.329, driverInfo 595.71.05
```

For another host, confirm that the NVIDIA driver, CUDA driver library, and Vulkan
ICD are usable before debugging OV Widgets itself.

Useful GPU checks:

```bash
nvidia-smi
vulkaninfo --summary
```

If `vulkaninfo` is missing, install `vulkan-tools`.

### 3.2 System packages

Install the package set before building Python, OpenUSD, OVUI, and
ovstream. The successful run installed packages in phases; this combined
list is the practical starting point.

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    curl \
    wget \
    git \
    git-lfs \
    nodejs \
    npm \
    pkg-config \
    ca-certificates \
    make \
    cmake \
    ninja-build \
    patchelf \
    xz-utils \
    zlib1g-dev \
    libffi-dev \
    libsqlite3-dev \
    libbz2-dev \
    liblzma-dev \
    libreadline-dev \
    libncursesw5-dev \
    libgdbm-dev \
    libnss3-dev \
    uuid-dev \
    tk-dev \
    libgl1-mesa-dev \
    libglx-dev \
    libglu1-mesa-dev \
    libgl-dev \
    libx11-dev \
    libxt-dev \
    libfreetype-dev \
    libglfw3-dev \
    libvulkan1 \
    libvulkan-dev \
    vulkan-tools \
    libegl1-mesa-dev \
    libgles2-mesa-dev \
    mesa-vulkan-drivers \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    libglib2.0-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstrtspserver-1.0-dev
```

Notes:

- `git-lfs` is mandatory for `ovstream`. Without it, StreamSDK `.so`
  files can be Git LFS pointer text files instead of ELF shared libraries.
- Node.js and npm are mandatory for the browser capture script. The successful
  host had `node v24.15.0` and `npm 11.12.1`. If the distro package is older
  than Node 18, install a current Node.js from your standard internal package
  source or NodeSource before running the Playwright capture step.

  Example NodeSource install for a clean Ubuntu host:

  ```bash
  curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
  sudo apt-get install -y nodejs
  node --version
  npm --version
  ```
- `libffi-dev` is mandatory for Python `_ctypes`. The first Python build in the
  successful run lacked `_ctypes`; OpenUSD then failed with
  `ModuleNotFoundError: No module named '_ctypes'`.
- OpenGL headers were required by the OpenUSD imaging dependencies.
- GStreamer headers and libraries were required for the SDK-only `libovstream.so`
  build.

### 3.3 CUDA Toolkit requirement

The OVUI editable install in the successful run found CUDA 12.6.20 under:

```text
/usr/local/cuda-12.6
```

The install command used:

```text
OMNIUI_CMAKE_ARGS='-DCUDAToolkit_ROOT=/usr/local/cuda-12.6'
```

Verify the expected CUDA toolkit:

```bash
ls /usr/local/cuda-12.6/bin/nvcc
/usr/local/cuda-12.6/bin/nvcc --version
```

Expected from the successful run:

```text
Cuda compilation tools, release 12.6, V12.6.20
```

If your CUDA toolkit is installed somewhere else, point `CUDAToolkit_ROOT` at
that prefix. If CUDA is not found, OVUI can still build pieces of the stack, but
the exact GPU/headless streaming proof from this run used CUDA-Vulkan interop
and a real NVIDIA driver. Treat a missing CUDA toolkit as a reproducibility
problem until the OVUI build log clearly shows the expected backend features.

### 3.4 Browser requirement

The successful browser proof used official Google Chrome:

```text
Google Chrome 148.0.7778.96
```

It was installed from:

```text
https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
```

The available `chromium-browser` package resolved to a snap stub in this
environment and was not usable. Playwright could not drive the system Firefox
because that Firefox did not include Playwright's patched Juggler protocol.

### 3.5 ovstream build caveat

`ovstream` is hosted publicly at `https://github.com/NVIDIA-Omniverse/ovstream`.

The official `ovstream ./build.sh` path pulls additional packages and is the
heaviest setup option. The browser proof therefore used the `ovstream`
repository SDK source plus Git LFS StreamSDK binaries to compile the
standalone `libovstream.so` directly, without running the full `build.sh`.

### 3.6 Disk and time expectations

This is not a small setup.

- Official Python from source is quick, but it must be rebuilt if an extension
  module is missing.
- OpenUSD v25.11 with imaging and oneTBB can take several minutes and produces a
  large install tree.
- OVUI editable install builds native `omni.ui` bindings and may take time.
- The ovrtx runtime release package is downloaded and extracted by CMake.
- The final workspace includes build trees, SDK binaries, a venv, and downloaded
  source archives.

Plan for tens of gigabytes of free disk space and enough time to rebuild Python
and OpenUSD if a prerequisite was missing.

## 4. Clean workspace setup from zero

Use `$WORKDIR` as the workspace root. Keep OVUI, ovrtx, ovstream,
OpenUSD, Python, and all generated proof assets under that directory so the
runbook stays portable across machines.

```bash
export WORKDIR="$HOME/dev/ovui-livestream-work"
mkdir -p "$WORKDIR"
cd "$WORKDIR"
```

Clone or update OVUI:

```bash
cd "$WORKDIR"
if [ ! -d ovui/.git ]; then
    git clone git@github.com:NVIDIA-Omniverse/ovui.git ovui
else
    git -C ovui status -sb
    test -z "$(git -C ovui status --porcelain)" || {
        echo "Existing ovui checkout has local changes. Commit, stash, or choose a clean clone before switching branches."
        exit 1
    }
fi
git -C ovui fetch origin
git -C ovui switch main
git -C ovui pull --ff-only
```

The runbook targets latest `main` for OVUI. Do not check out a specific commit
for this document.

Clone or update ovrtx:

```bash
cd "$WORKDIR"
if [ ! -d ovrtx/.git ]; then
    git clone https://github.com/NVIDIA-Omniverse/ovrtx.git ovrtx
else
    git -C ovrtx status -sb
    test -z "$(git -C ovrtx status --porcelain)" || {
        echo "Existing ovrtx checkout has local changes. Commit, stash, or choose a clean clone before switching branches."
        exit 1
    }
fi
git -C ovrtx fetch origin
git -C ovrtx switch main
git -C ovrtx pull --ff-only
```

Clone or update ovstream:

```bash
cd "$WORKDIR"
if [ ! -d ovstream/.git ]; then
    git clone https://github.com/NVIDIA-Omniverse/ovstream.git ovstream
else
    git -C ovstream status -sb
    test -z "$(git -C ovstream status --porcelain)" || {
        echo "Existing ovstream checkout has local changes. Commit, stash, or choose a clean clone before switching branches."
        exit 1
    }
fi
git -C ovstream fetch origin
git -C ovstream switch main
git -C ovstream pull --ff-only
git -C ovstream lfs install --local
git -C ovstream lfs pull
```

Clone OpenUSD:

```bash
mkdir -p "$WORKDIR/usd-build"
cd "$WORKDIR/usd-build"
if [ ! -d OpenUSD/.git ]; then
    git clone https://github.com/PixarAnimationStudios/OpenUSD.git OpenUSD
fi
git -C OpenUSD fetch --all --tags
git -C OpenUSD checkout v25.11
```

If repositories already exist and are dirty, do not reset blindly. Inspect first:

```bash
git -C "$WORKDIR/ovui" status -sb
git -C "$WORKDIR/ovrtx" status -sb
git -C "$WORKDIR/ovstream" status -sb
git -C "$WORKDIR/usd-build/OpenUSD" status -sb
```

Never delete screenshots, logs, virtualenvs, or build products unless you know
they are yours and no longer needed.

## 5. Build Python 3.12 from official source first

Python 3.12 must be built before the rest of this workflow. Do not replace or
modify system Python. Install it into a local safe prefix.

The successful run used:

```text
Python source URL: https://www.python.org/ftp/python/3.12.13/Python-3.12.13.tar.xz
Python prefix:     $WORKDIR/python-3.12.13-official
Python executable: $WORKDIR/python-3.12.13-official/bin/python3.12
OpenSSL prefix:    $WORKDIR/openssl-3.5.6
```

### 5.1 Build local OpenSSL

The host did not have suitable OpenSSL headers for the Python SSL extension, so
the successful run built OpenSSL 3.5.6 locally.

```bash
: "${WORKDIR:?Set WORKDIR first}"
cd "$WORKDIR"

wget -O openssl-3.5.6.tar.gz https://www.openssl.org/source/openssl-3.5.6.tar.gz
tar -xf openssl-3.5.6.tar.gz
cd openssl-3.5.6

./Configure linux-x86_64 \
    --prefix="$WORKDIR/openssl-3.5.6" \
    --openssldir="$WORKDIR/openssl-3.5.6/ssl" \
    shared zlib

make -j"$(nproc)"
make install_sw

# The OpenSSL build installed libraries under lib64 in this environment.
# Python's configure probe expects a lib path, so provide a local symlink.
ln -sfn lib64 "$WORKDIR/openssl-3.5.6/lib"
```

### 5.2 Build official Python 3.12.13

```bash
: "${WORKDIR:?Set WORKDIR first}"
cd "$WORKDIR"

wget -O Python-3.12.13.tar.xz \
    https://www.python.org/ftp/python/3.12.13/Python-3.12.13.tar.xz
tar -xf Python-3.12.13.tar.xz
cd Python-3.12.13

make distclean || true

CPPFLAGS="-I$WORKDIR/openssl-3.5.6/include" \
LDFLAGS="-L$WORKDIR/openssl-3.5.6/lib64 -Wl,-rpath,$WORKDIR/openssl-3.5.6/lib64 -Wl,-rpath,$WORKDIR/python-3.12.13-official/lib" \
./configure \
    --prefix="$WORKDIR/python-3.12.13-official" \
    --enable-shared \
    --with-ensurepip=install \
    --with-openssl="$WORKDIR/openssl-3.5.6" \
    --with-openssl-rpath=auto

make -j"$(nproc)"
make install
```

The explicit OpenSSL `-Wl,-rpath,$WORKDIR/openssl-3.5.6/lib64` is intentional.
This host's OpenSSL install put libraries in `lib64`; `--with-openssl-rpath=auto`
uses the configured OpenSSL prefix, while the explicit rpath makes the actual
runtime library directory unambiguous.

### 5.3 Verify Python

The local OpenSSL prefix does not carry a CA bundle. Set `SSL_CERT_FILE` when
using this Python for HTTPS operations.

```bash
: "${WORKDIR:?Set WORKDIR first}"
export PY312="$WORKDIR/python-3.12.13-official/bin/python3.12"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

"$PY312" - <<'PY'
import ctypes
import bz2
import lzma
import sqlite3
import ssl
import sys
print(sys.version)
print(ssl.OPENSSL_VERSION)
PY
```

Expected successful-run result:

```text
3.12.13 ...
OpenSSL 3.5.6
```

Install Python-side build tools that are needed later:

```bash
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
"$PY312" -m pip install --user 'cmake>=3.26' Jinja2

export PATH="$HOME/.local/bin:$PATH"
cmake --version
```

The successful run used CMake 4.3.2 from the local Python user install.

## 6. Build/install OpenUSD

OV Widgets requires OpenUSD v25.11 built for Python 3.12. The successful install
prefix was:

```text
$WORKDIR/usd-build/install
```

The OpenUSD source checkout was:

```text
$WORKDIR/usd-build/OpenUSD
tag: v25.11
```

### 6.1 Patch oneTBB URL

The OV Widgets README requires oneTBB 2021.13.1. The OpenUSD build script had
2021.12.0 pinned, so patch it before building.

```bash
: "${WORKDIR:?Set WORKDIR first}"
cd "$WORKDIR/usd-build/OpenUSD"
git checkout v25.11
sed -i 's|v2021.12.0.zip|v2021.13.1.zip|' build_scripts/build_usd.py
grep 'v2021.13.1.zip' build_scripts/build_usd.py
```

In the v25.11 `build_usd.py` used here, the oneTBB download URL is not paired
with an expected SHA256 argument. No oneTBB hash patch was required in the
successful run.

### 6.2 Build OpenUSD

```bash
: "${WORKDIR:?Set WORKDIR first}"
export PY312="$WORKDIR/python-3.12.13-official/bin/python3.12"
export USD_SRC="$WORKDIR/usd-build/OpenUSD"
export USD_INSTALL="$WORKDIR/usd-build/install"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export PATH="$HOME/.local/bin:$PATH"

"$PY312" "$USD_SRC/build_scripts/build_usd.py" \
    --build-shared \
    --onetbb \
    --imaging \
    --no-usdview \
    --no-materialx \
    --no-examples \
    --no-tutorials \
    --no-tests \
    --no-docs \
    --build-python-info "$PY312" \
                        "$WORKDIR/python-3.12.13-official/include/python3.12" \
                        "$WORKDIR/python-3.12.13-official/lib/libpython3.12.so" \
                        3.12 \
    -v -j 12 \
    "$USD_INSTALL"
```

Notes from the successful run:

- OpenSubdiv configure failed until OpenGL development packages were installed.
- Build schema tools were omitted until `Jinja2` was installed into the local
  Python.
- The build uses the official local Python, not `/usr/bin/python3`.

### 6.3 Verify OpenUSD

```bash
: "${WORKDIR:?Set WORKDIR first}"
export PY312="$WORKDIR/python-3.12.13-official/bin/python3.12"
export USD_INSTALL="$WORKDIR/usd-build/install"

find "$USD_INSTALL/lib" -maxdepth 1 -name 'libusd*.so' | wc -l

PYTHONPATH="$USD_INSTALL/lib/python" \
LD_LIBRARY_PATH="$USD_INSTALL/lib" \
"$PY312" -c "from pxr import Usd; print(Usd.GetVersion())"

test -x "$USD_INSTALL/bin/usdcat"
test -x "$USD_INSTALL/bin/usdGenSchema"
```

Expected:

```text
61
(0, 25, 11)
```

At runtime, always put this OpenUSD build ahead of any `usd-core` wheel:

```bash
export PYTHONPATH=$WORKDIR/usd-build/install/lib/python:$PYTHONPATH
export LD_LIBRARY_PATH=$WORKDIR/usd-build/install/lib:$LD_LIBRARY_PATH
```

## 7. Prepare/build ovrtx against USD

The successful run used:

```text
ovrtx repo:    $WORKDIR/ovrtx
ovrtx branch:  latest main
ovrtx package: 0.2.0
Runtime lib:   $WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin/libovrtx-dynamic.so
```

Important caveat: the ovrtx repo used in the run does not include C/C++ source
for `libovrtx-dynamic.so`. It includes headers, examples, Python ctypes
bindings, and a CMake helper that downloads the documented ovrtx v0.2.0 release
runtime. Therefore:

- The C example/link integration was compiled locally.
- The Python package was installed locally.
- The native ovrtx runtime library was consumed from the documented release
  package.
- This is the repo-documented path; it is not a native-from-source build of
  `libovrtx-dynamic.so`.

Use the release package URL and checksum documented by
`examples/c/cmake/ovrtx.cmake` in the ovrtx checkout. Do not hard-code a release
archive hash in this runbook; the checkout's CMake helper is the source of
truth.

### 7.1 Build the minimal ovrtx example

```bash
: "${WORKDIR:?Set WORKDIR first}"
export PATH="$HOME/.local/bin:$PATH"

cmake \
    -S "$WORKDIR/ovrtx/examples/c/minimal" \
    -B "$WORKDIR/ovrtx/examples/c/minimal/build" \
    -DCMAKE_BUILD_TYPE=Release

cmake --build "$WORKDIR/ovrtx/examples/c/minimal/build" -j"$(nproc)"
```

This downloads and extracts the ovrtx runtime through the helper at:

```text
$WORKDIR/ovrtx/examples/c/cmake/ovrtx.cmake
```

Expected runtime artifact:

```text
$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin/libovrtx-dynamic.so
```

### 7.2 Run the minimal render

```bash
: "${WORKDIR:?Set WORKDIR first}"
export ovrtx_RUNTIME="$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin"

LD_LIBRARY_PATH="$ovrtx_RUNTIME" \
"$WORKDIR/ovrtx/examples/c/minimal/build/minimal"
```

Expected successful-run artifact:

```text
$WORKDIR/ovrtx/examples/c/minimal/out.png
```

Warnings about optional NGX features can appear and are not the failure signal
for this proof. The important result is that the executable completes and writes
the PNG.

### 7.3 Verify ovrtx Python renderer construction

```bash
: "${WORKDIR:?Set WORKDIR first}"
export PY312="$WORKDIR/python-3.12.13-official/bin/python3.12"
export ovrtx_RUNTIME="$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin"

env OVRTX_SKIP_USD_CHECK=1 \
PYTHONPATH="$WORKDIR/ovrtx/python" \
LD_LIBRARY_PATH="$ovrtx_RUNTIME" \
"$PY312" - <<'PY'
import ovrtx
print("ovrtx", ovrtx.__version__)
renderer = ovrtx.Renderer(ovrtx.RendererConfig())
print("renderer constructed")
PY
```

Expected:

```text
ovrtx 0.2.0
renderer constructed
```

The case-sensitive ovrtx library environment variable
`OVRTX_SKIP_USD_CHECK` is required for the combined OV Widgets workflow. Its
name is preserved in uppercase because the ovrtx Python package reads it
verbatim from `os.environ`.

## 8. Create the Python 3.12 virtual environment for OV Widgets

The successful venv path was:

```text
$WORKDIR/ovui/ovwidgets/_venv312
```

### 8.0 Build order

Section 8 and Section 9 intentionally interleave. `ovstream/sdk/python`
depends on the SDK output from Section 9, but the venv and earlier OV Widgets
packages are created in Section 8 first.

Follow this exact order:

```text
8.1 -> 8.2 -> 8.3 -> 8.4 -> 8.5 -> 8.6 -> 8.7 -> 9.2 -> 9.3 -> 8.8 -> 8.9 -> 9.4 -> 10
```

### 8.1 Create and upgrade the venv

```bash
: "${WORKDIR:?Set WORKDIR first}"
export PY312="$WORKDIR/python-3.12.13-official/bin/python3.12"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

"$PY312" -m venv "$VENV"
"$VENV/bin/python" -m pip install -U pip setuptools wheel build
"$VENV/bin/python" -m pip install pytest pytest-asyncio ruff mypy cmake pybind11
```

### 8.2 Common environment variables

Use this block for install checks and runtime:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export USD_INSTALL="$WORKDIR/usd-build/install"
export ovrtx_RUNTIME="$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin"
export OVSTREAM_SDK="$WORKDIR/ovstream/_build/linux-x86_64/release/sdk"

export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH="$USD_INSTALL/lib/python"
export LD_LIBRARY_PATH="$USD_INSTALL/lib:$ovrtx_RUNTIME:$OVSTREAM_SDK"
export OVSTREAM_LIB_PATH="$OVSTREAM_SDK/libovstream.so"
```

### 8.3 Install OVUI editable

The successful OVUI install used Vulkan and CUDA discovery. It set
`CUDAToolkit_ROOT` to the CUDA 12.6 installation on the machine:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export PATH="$VENV/bin:$PATH"

Vulkan_INCLUDE_DIR=/usr/include \
Vulkan_LIBRARY=/usr/lib/x86_64-linux-gnu/libvulkan.so \
OMNIUI_CMAKE_ARGS='-DCUDAToolkit_ROOT=/usr/local/cuda-12.6' \
"$VENV/bin/python" -m pip install -e "$WORKDIR/ovui/ovui"
```

The build output in the successful run showed:

- CUDA 12.6.20 was found.
- Vulkan backend was enabled.
- Streaming/headless support was enabled.
- CUDA-Vulkan interop was enabled.
- NVENC was not found for the OVUI build; CPU fallback encoder was available.

### 8.4 Install ovrtx Python package

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

"$VENV/bin/python" -m pip install -e "$WORKDIR/ovrtx/python"
```

### 8.5 Keep the source-built USD on the environment

This runbook uses the OpenUSD build exported earlier through `PYTHONPATH` and
`LD_LIBRARY_PATH`. Do not install the PyPI `usd-core` wheel into this venv for
this path; it can shadow the custom build. The repository no longer carries a
local package to satisfy `usd-core` metadata, so there is no separate
`usd-core` install step here.

### 8.6 Install OVUI data adapters

Install common first, then the remaining runtime dependency that does not come
from Section 8.4. Install the OpenUSD adapter without dependency resolution so
`pip` does not fetch PyPI `usd-core` into this source-built USD environment:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

"$VENV/bin/python" -m pip install -e \
    "$WORKDIR/ovui/ovui-data-adapters/dist/common"

"$VENV/bin/python" -m pip install numpy

"$VENV/bin/python" -m pip install --no-deps -e \
    "$WORKDIR/ovui/ovui-data-adapters/dist/openusd"
```

### 8.7 Install OV Widgets packages in dependency order

The successful run installed these dists together after the common/adapters
layers were present:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

"$VENV/bin/python" -m pip install --no-deps \
    -e "$WORKDIR/ovui/ovwidgets/dist/common[testing]" \
    -e "$WORKDIR/ovui/ovwidgets/dist/stage" \
    -e "$WORKDIR/ovui/ovwidgets/dist/layers" \
    -e "$WORKDIR/ovui/ovwidgets/dist/content" \
    -e "$WORKDIR/ovui/ovwidgets/dist/property" \
    -e "$WORKDIR/ovui/ovwidgets/dist/viewport" \
    -e "$WORKDIR/ovui/ovwidgets/dist/app"
```

### 8.8 Install ovstream SDK Python package

Before this step: complete Section 9.2 and Section 9.3 so
`$WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so`
exists and the StreamSDK binaries have passed the Git LFS sanity checks.

Build `libovstream.so` first using Section 9, then install the Python package:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

"$VENV/bin/python" -m pip install -e \
    "$WORKDIR/ovstream/sdk/python"
```

### 8.9 Combined import check

Run this only after Sections 6, 7, 8, and 9 are complete:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export USD_INSTALL="$WORKDIR/usd-build/install"
export ovrtx_RUNTIME="$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin"
export OVSTREAM_SDK="$WORKDIR/ovstream/_build/linux-x86_64/release/sdk"

env OVRTX_SKIP_USD_CHECK=1 \
PYTHONPATH="$USD_INSTALL/lib/python" \
LD_LIBRARY_PATH="$USD_INSTALL/lib:$ovrtx_RUNTIME:$OVSTREAM_SDK" \
OVSTREAM_LIB_PATH="$OVSTREAM_SDK/libovstream.so" \
"$VENV/bin/python" - <<'PY'
from pxr import Usd
import ovrtx
import omni.ui
from omni.ui import headless_frame
import ovstream
from ovwidgets.app.application import Application
from ovwidgets.viewport._livestream_tap import LivestreamTap

print("USD", Usd.GetVersion())
print("ovrtx", ovrtx.__version__)
print("omni.ui ok")
print("headless_frame ok")
print("ovstream", ovstream.get_version())
print("Application ok", Application)
print("LivestreamTap ok", LivestreamTap)
PY
```

Expected successful-run values:

```text
USD (0, 25, 11)
ovrtx 0.2.0
omni.ui ok
headless_frame ok
ovstream 0.1.2
Application ok ...
LivestreamTap ok ...
```

## 9. ovstream / OVSTREAM setup

The required repo is:

```text
$WORKDIR/ovstream
```

Use latest `main`. `VERSION.md` should identify the SDK/package version expected
by the repository. In the reference run it identified:

```text
110.0.0
```

Docs read in the successful run:

- `$WORKDIR/ovstream/README.md`
- `$WORKDIR/ovstream/sdk/README.md`
- `$WORKDIR/ovstream/sdk/python/README.md`
- `$WORKDIR/ovstream/sdk/docs/GETTING_STARTED.md`
- Relevant `$WORKDIR/ovstream/TROUBLESHOOTING.md` OVSTREAM/WebRTC
  sections

### 9.1 Official documented path

The official path is:

```bash
cd $WORKDIR/ovstream
./build.sh
```

Expected documented SDK output:

```text
$WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so
```

The successful run attempted this path first. It did not complete because of
additional package dependencies pulled by the official build.

Observed blocker after bypassing only bootstrap/publishing helper packages:

```text
the kit-kernel package required by the ovstream SDK version
```

The SDK-only fallback in Section 9.3 is the supported lightweight path and
avoids these extra dependencies entirely.

### 9.2 Git LFS requirement

Before using the fallback, make sure StreamSDK libraries are real ELF files:

```bash
cd $WORKDIR/ovstream
git lfs install --local
git lfs pull

file source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64/libNvStreamServer.so
```

If `file` is unavailable, use size as a quick sanity check:

```bash
ls -lh source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64/libNvStreamServer.so
```

It should be a large binary shared library. A tiny text file means Git LFS did
not pull the real content.

Run this mandatory size check before compiling the fallback:

```bash
cd $WORKDIR/ovstream
STREAMSDK=source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64

stat -c '%n %s bytes' \
    "$STREAMSDK/libNvStreamServer.so" \
    "$STREAMSDK/libNvStreamBase.so" \
    "$STREAMSDK/libAudioStreamShared.so"

test "$(stat -c %s "$STREAMSDK/libNvStreamServer.so")" -gt $((1000 * 1000)) || {
    echo "LFS pull failed: libNvStreamServer.so is too small"
    exit 1
}
test "$(stat -c %s "$STREAMSDK/libNvStreamBase.so")" -gt 100000 || {
    echo "LFS pull failed: libNvStreamBase.so is too small"
    exit 1
}
test "$(stat -c %s "$STREAMSDK/libAudioStreamShared.so")" -gt 50000 || {
    echo "LFS pull failed: libAudioStreamShared.so is too small"
    exit 1
}
```

Expected approximate sizes from the reference run:

```text
libNvStreamServer.so      about 10 MB
libNvStreamBase.so        about 180 KB
libAudioStreamShared.so   about 95 KB
```

### 9.3 SDK-only fallback used for the browser proof

The fallback compiles the SDK source with system GStreamer headers and links it
against the StreamSDK binaries from Git LFS. This produced the `libovstream.so`
used by the browser proof.

```bash
: "${WORKDIR:?Set WORKDIR first}"
export KIT="$WORKDIR/ovstream"
export OUT="$KIT/_build/linux-x86_64/release/sdk"
export STREAMSDK="$KIT/source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64"

mkdir -p "$OUT"

cp -a "$STREAMSDK"/*.so* "$OUT"/

cd "$KIT"

CXXFLAGS="-std=c++17 -fPIC -O2 -DOVSTREAM_BUILD \
-Isdk/include \
-Isdk/src \
-Isource/extensions/omni.kit.livestream.webrtc/streamsdk/include \
$(pkg-config --cflags gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0 gstreamer-rtsp-server-1.0 glib-2.0 gobject-2.0)"

LIBS="-L$STREAMSDK \
-lNvStreamBase \
-lNvStreamServer \
-lAudioStreamShared \
$(pkg-config --libs gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0 gstreamer-rtsp-server-1.0 glib-2.0 gobject-2.0) \
-ldl -lpthread"

g++ $CXXFLAGS -shared \
    sdk/src/core/api.cpp \
    sdk/src/core/error.cpp \
    sdk/src/core/logging.cpp \
    sdk/src/core/registry.cpp \
    sdk/src/init.cpp \
    sdk/src/rtsp/register.cpp \
    sdk/src/rtsp/server.cpp \
    sdk/src/webrtc/audio_handler.cpp \
    sdk/src/webrtc/input_handler.cpp \
    sdk/src/webrtc/register.cpp \
    sdk/src/webrtc/server.cpp \
    sdk/src/webrtc/session_handler.cpp \
    $LIBS \
    -Wl,-rpath,'$ORIGIN' \
    -o "$OUT/libovstream.so"

ldd "$OUT/libovstream.so"
```

This source list reflects the ovstream `main` revision used for the
build. If the SDK source tree changes, re-enumerate `sdk/src/**/*.cpp` and
update this list accordingly.

Sanity-check the source list before updating this command:

```bash
cd $WORKDIR/ovstream
find sdk/src -type f -name '*.cpp' | sort
```

Expected artifact:

```text
$WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so
```

The successful artifact was about 132 KB. Most runtime work is in the linked
StreamSDK and system GStreamer libraries.

Copying all `*.so*` files is deliberate. The successful runtime directly needed
`libNvStreamBase.so`, `libNvStreamServer.so`, `libAudioStreamShared.so`,
`libcrypto_nvst.so.3`, and `libssl_nvst.so.3`, and the StreamSDK directory also
contained helper/runtime libraries such as `libPoco.so`,
`libStreamClientShared.so`, `libNicllsHandlerServer.so`, `libcudart.so.12`, and
`libNvcfBlasUpload.so`. Staging all shared objects keeps the SDK output
self-contained for loader resolution.

### 9.4 Verify OVSTREAM

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export OVSTREAM_SDK="$WORKDIR/ovstream/_build/linux-x86_64/release/sdk"

OVSTREAM_LIB_PATH="$OVSTREAM_SDK/libovstream.so" \
LD_LIBRARY_PATH="$OVSTREAM_SDK:$LD_LIBRARY_PATH" \
"$VENV/bin/python" - <<'PY'
import ovstream
print(ovstream.get_version())
ovstream.initialize()
ovstream.shutdown()
PY
```

Expected:

```text
0.1.2
```

## 10. Launch the OV Widgets livestream app

The successful proof used a generated helper script at:

```text
$WORKDIR/tmp/ovwidgets_livestream_server.py
```

It was not committed. It exists to launch the app headlessly, load the USD file,
select `/World/Cube`, and enable WebRTC livestreaming.

This helper intentionally reaches into application internals from the current
OVUI `main` implementation: `Application._instance`, `app._stage_window._widget`,
`app._stage_adapter`, `app._headless_tap`, `app.call_later`, and
`app.selection_bus`. When updating to a newer OVUI main revision, inspect the
current `ovwidgets.app.Application` and stage widget APIs before assuming the
helper still works unchanged.

The helpers in Section 10.1 and Section 12.3 live under `$WORKDIR/tmp`. If that
directory is cleaned or the machine is rebuilt, re-run those sections to
recreate the helpers before restarting the servers.

### 10.1 Generated livestream server script

Create the script:

```bash
mkdir -p "$WORKDIR/tmp"
cat > $WORKDIR/tmp/ovwidgets_livestream_server.py <<'PY'
import os
import sys
import time

WORKDIR = os.environ["WORKDIR"]
READY_FLAG = os.path.join(WORKDIR, "tmp", "ovwidgets-livestream-ready")
USD_PATH = os.path.join(WORKDIR, "ovui", "ovwidgets", "tests", "data", "simple_scene.usda")
SELECTED_PATH = "/World/Cube"

os.environ.setdefault("OMNIUI_HEADLESS", "1")
os.environ.setdefault("OMNIUI_BACKEND", "vulkan")
os.environ.setdefault("OVGEAR_HEADLESS", "1")
os.environ.setdefault("OVGEAR_HEADLESS_WIDTH", "1280")
os.environ.setdefault("OVGEAR_HEADLESS_HEIGHT", "720")
os.environ.setdefault("OVGEAR_LIVESTREAM", "1")
os.environ.setdefault("OVGEAR_LIVESTREAM_PROTOCOL", "webrtc")
os.environ.setdefault("OVGEAR_LIVESTREAM_SIGNAL_PORT", "49100")
os.environ.setdefault("OVGEAR_LIVESTREAM_MEDIA_PORT", "47999")
os.environ.setdefault("OVGEAR_LIVESTREAM_FPS", "60")
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")
os.environ.setdefault(
    "OVSTREAM_LIB_PATH",
    os.path.join(WORKDIR, "ovstream", "_build", "linux-x86_64", "release", "sdk", "libovstream.so"),
)

import omni.ui as ui
from ovwidgets.app.application import Application


def _mark_ready_once(app: Application) -> None:
    try:
        widget = getattr(getattr(app, "_stage_window", None), "_widget", None)
        if widget is None or getattr(app, "_stage_adapter", None) is None:
            app.call_later(0.25, lambda: _mark_ready_once(app))
            return
        widget.set_selection([SELECTED_PATH])
        snap = app.selection_bus.get_snapshot()
        if SELECTED_PATH not in snap.paths():
            app.call_later(0.25, lambda: _mark_ready_once(app))
            return
        tap = getattr(app, "_headless_tap", None)
        if tap is None:
            app.call_later(0.25, lambda: _mark_ready_once(app))
            return
        state, n_clients, last_error = tap.status()
        with open(READY_FLAG, "w", encoding="utf-8") as f:
            f.write(
                f"ready selected={SELECTED_PATH} state={state} "
                f"clients={n_clients} error={last_error}\n"
            )
        print(
            f"READY selected={SELECTED_PATH} state={state} clients={n_clients}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"READY_CHECK_RETRY {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        app.call_later(0.25, lambda: _mark_ready_once(app))


def main() -> None:
    if os.path.exists(READY_FLAG):
        os.unlink(READY_FLAG)
    Application._instance = None
    app = Application()
    app.call_later(2.0, lambda: _mark_ready_once(app))
    app.run(usd_path=USD_PATH)


if __name__ == "__main__":
    main()
PY
```

Note: the app chrome in the successful screenshot still showed legacy `OvGear`
branding in one place. That does not mean `$WORKDIR/ovgear` is the source
of truth. The code was installed and run from the OVUI monorepo.

### 10.2 Start the livestream server

Do not use `pkill`, `killall`, or pattern-based killing. Start the process and
record the exact PID.

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"
export USD_INSTALL="$WORKDIR/usd-build/install"
export ovrtx_RUNTIME="$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin"
export OVSTREAM_SDK="$WORKDIR/ovstream/_build/linux-x86_64/release/sdk"

cd "$WORKDIR/ovui"

env OVRTX_SKIP_USD_CHECK=1 \
PYTHONPATH="$USD_INSTALL/lib/python" \
LD_LIBRARY_PATH="$USD_INSTALL/lib:$ovrtx_RUNTIME:$OVSTREAM_SDK" \
OVSTREAM_LIB_PATH="$OVSTREAM_SDK/libovstream.so" \
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
setsid "$VENV/bin/python" $WORKDIR/tmp/ovwidgets_livestream_server.py \
    > $WORKDIR/tmp/ovwidgets-livestream-server.log 2>&1 &

echo "livestream server pid: $!"
```

This process should remain running; record the PID printed by the shell.

Watch readiness:

```bash
tail -f $WORKDIR/tmp/ovwidgets-livestream-server.log
cat $WORKDIR/tmp/ovwidgets-livestream-ready
```

Expected readiness line:

```text
ready selected=/World/Cube state=LISTENING clients=0 error=None
```

Expected ports:

```text
WebRTC signal port: 49100
WebRTC media port:  47999
```

### 10.3 Start the static browser client server

The successful browser client was served from the ovstream SDK example:

```bash
: "${WORKDIR:?Set WORKDIR first}"
export VENV="$WORKDIR/ovui/ovwidgets/_venv312"

cd "$WORKDIR/ovstream/sdk/examples/webrtc_client"

setsid "$VENV/bin/python" -m http.server 8080 \
    > $WORKDIR/tmp/ovwidgets-webrtc-http.log 2>&1 &

echo "http server pid: $!"
```

This process should remain running; record the PID printed by the shell.

Verify:

```bash
curl -sS -I http://127.0.0.1:8080/ | sed -n '1,8p'
```

Expected:

```text
HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.12.13
```

### 10.4 Exact-PID cleanup only

If you must stop the servers, identify exact PIDs and kill only those PIDs:

```bash
ps -p <livestream-pid>,<http-pid> -o pid,ppid,stat,etime,cmd
kill <livestream-pid>
kill <http-pid>
```

If the PIDs differ, use the PIDs printed when you started the processes. Do not
use `pkill`, `killall`, or broad process-name matching.

## 11. Load scene and select prim

The server script loads:

```text
$WORKDIR/ovui/ovwidgets/tests/data/simple_scene.usda
```

The script selects:

```text
/World/Cube
```

The expected streamed UI state is:

- Stage tree is visible on the left.
- `Cube` is highlighted/selected in the stage tree.
- The properties panel on the right shows `Cube` and `/World/Cube`.
- The central viewport shows the scene geometry.
- The selected cube has a visible selection outline and translate gizmo.
- The scene HUD shows `SCENE simple_scene.usda`.

The stage also contains `Sphere`, `Pyramid`, `Pillar`, and the session prims.
The successful screenshot showed `15 prims`.

## 12. Capture browser screenshot

### 12.1 Install Google Chrome if needed

```bash
mkdir -p "$WORKDIR/tmp"
wget -O "$WORKDIR/tmp/google-chrome-stable_current_amd64.deb" \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt-get install -y "$WORKDIR/tmp/google-chrome-stable_current_amd64.deb"
which google-chrome
google-chrome --version
```

Expected in the successful run:

```text
Google Chrome 148.0.7778.96
```

### 12.2 Prepare Playwright core

The successful run used `playwright-core` and the system Chrome executable. It
did not rely on a Playwright-managed browser download.

```bash
mkdir -p $WORKDIR/tmp/ovwidgets-browser-proof
cd $WORKDIR/tmp/ovwidgets-browser-proof
npm init -y
npm install playwright-core@1.60.0
```

### 12.3 Browser capture script

Create `$WORKDIR/tmp/ovwidgets-browser-proof/capture.js`:

```bash
cat > $WORKDIR/tmp/ovwidgets-browser-proof/capture.js <<'JS'
const { chromium } = require('playwright-core');

(async () => {
  const workdir = process.env.WORKDIR || `${process.env.HOME}/dev/ovui-livestream-work`;
  const out = process.env.OUT || `${workdir}/ovui/ovwidgets-browser-proof.png`;
  const browser = await chromium.launch({
    executablePath: '/usr/bin/google-chrome',
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--autoplay-policy=no-user-gesture-required',
      '--use-fake-ui-for-media-stream',
      '--window-size=1440,960',
    ],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 960 },
    ignoreHTTPSErrors: true,
  });

  page.on('console', msg => console.log(`[browser:${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => console.log(`[browser:pageerror] ${err.stack || err.message}`));

  await page.goto('http://127.0.0.1:8080/', { waitUntil: 'domcontentloaded' });
  await page.fill('#server-ip', '127.0.0.1');
  await page.fill('#signal-port', '49100');
  await page.click('#connect-button');

  await page.waitForFunction(() => {
    const s = document.querySelector('#status');
    return s && /Connected/i.test(s.textContent || '');
  }, null, { timeout: 45000 });

  await page.waitForFunction(() => {
    const v = document.querySelector('#remote-video');
    return v && v.videoWidth > 0 && v.videoHeight > 0 && v.readyState >= 2;
  }, null, { timeout: 45000 });

  await page.waitForTimeout(3500);
  await page.screenshot({ path: out, fullPage: true });
  const info = await page.evaluate(() => {
    const v = document.querySelector('#remote-video');
    const s = document.querySelector('#status');
    return {
      status: s ? s.textContent : null,
      videoWidth: v ? v.videoWidth : 0,
      videoHeight: v ? v.videoHeight : 0,
      readyState: v ? v.readyState : 0,
      currentTime: v ? v.currentTime : 0,
    };
  });
  console.log(`SCREENSHOT=${out}`);
  console.log(`VIDEO=${JSON.stringify(info)}`);
  await browser.close();
})().catch(err => {
  console.error(err.stack || err);
  process.exit(1);
});
JS
```

### 12.4 Capture screenshot

```bash
cd $WORKDIR/tmp/ovwidgets-browser-proof
OUT=$WORKDIR/ovui/ovwidgets-browser-proof.png \
node $WORKDIR/tmp/ovwidgets-browser-proof/capture.js
```

Successful run output:

```text
[browser:log] update {action: start, status: inProgress, info: Starting stream.}
[browser:log] connect() returned {action: start, status: inProgress, info: Starting stream.}
SCREENSHOT=$WORKDIR/ovui/ovwidgets-browser-proof.png
VIDEO={"status":"Connected","videoWidth":1280,"videoHeight":720,"readyState":4,"currentTime":3.568634}
```

Non-fatal browser console messages can include 404s for ancillary files such as
favicon resources. The key checks are:

- `status` is `Connected`.
- `videoWidth` is `1280`.
- `videoHeight` is `720`.
- `readyState` is `4` or at least `>= 2`.
- `currentTime` is greater than zero.
- The screenshot exists and has nonzero size.

The successful screenshot size was:

```bash
stat -c '%n %s bytes' $WORKDIR/ovui/ovwidgets-browser-proof.png
```

```text
$WORKDIR/ovui/ovwidgets-browser-proof.png 224487 bytes
```

## 13. Validation checklist

Use this checklist before declaring success.

### Python/OpenSSL

```bash
$WORKDIR/python-3.12.13-official/bin/python3.12 - <<'PY'
import ssl, ctypes, sqlite3, bz2, lzma, sys
print(sys.version)
print(ssl.OPENSSL_VERSION)
PY
```

Expected:

```text
Python 3.12.13
OpenSSL 3.5.6
```

### OpenUSD

```bash
find $WORKDIR/usd-build/install/lib -maxdepth 1 -name 'libusd*.so' | wc -l

PYTHONPATH=$WORKDIR/usd-build/install/lib/python \
LD_LIBRARY_PATH=$WORKDIR/usd-build/install/lib \
$WORKDIR/python-3.12.13-official/bin/python3.12 \
    -c "from pxr import Usd; print(Usd.GetVersion())"
```

Expected:

```text
61
(0, 25, 11)
```

### ovrtx

```bash
test -f $WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin/libovrtx-dynamic.so
test -f $WORKDIR/ovrtx/examples/c/minimal/out.png
```

Python construction check:

```bash
PYTHONPATH=$WORKDIR/ovrtx/python \
LD_LIBRARY_PATH=$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin \
$WORKDIR/python-3.12.13-official/bin/python3.12 - <<'PY'
import ovrtx
print(ovrtx.__version__)
renderer = ovrtx.Renderer(ovrtx.RendererConfig())
print("ok")
PY
```

Expected:

```text
0.2.0
ok
```

### OVUI / OV Widgets / OVSTREAM

```bash
env OVRTX_SKIP_USD_CHECK=1 \
PYTHONPATH=$WORKDIR/usd-build/install/lib/python \
LD_LIBRARY_PATH=$WORKDIR/usd-build/install/lib:$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin:$WORKDIR/ovstream/_build/linux-x86_64/release/sdk \
OVSTREAM_LIB_PATH=$WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so \
$WORKDIR/ovui/ovwidgets/_venv312/bin/python - <<'PY'
from pxr import Usd
import ovrtx
import omni.ui
from omni.ui import headless_frame
import ovstream
from ovwidgets.app.application import Application
from ovwidgets.viewport._livestream_tap import LivestreamTap

print("USD", Usd.GetVersion())
print("ovrtx", ovrtx.__version__)
print("headless_frame ok", headless_frame)
print("ovstream", ovstream.get_version())
print("Application", Application)
print("LivestreamTap", LivestreamTap)
PY
```

Expected:

```text
USD (0, 25, 11)
ovrtx 0.2.0
headless_frame ok ...
ovstream 0.1.2
```

### Runtime servers

```bash
ps -p <livestream-pid>,<http-pid> -o pid,ppid,stat,etime,cmd
curl -sS -I http://127.0.0.1:8080/ | sed -n '1,8p'
cat $WORKDIR/tmp/ovwidgets-livestream-ready
```

Expected:

```text
HTTP/1.0 200 OK
ready selected=/World/Cube state=LISTENING clients=0 error=None
```

### Browser/WebRTC screenshot

```bash
OUT=$WORKDIR/ovui/ovwidgets-browser-proof.png \
node $WORKDIR/tmp/ovwidgets-browser-proof/capture.js
stat -c '%n %s bytes' $WORKDIR/ovui/ovwidgets-browser-proof.png
```

Expected:

```text
VIDEO={"status":"Connected","videoWidth":1280,"videoHeight":720,"readyState":4,...}
nonzero screenshot size
```

## 14. Troubleshooting

### 14.1 ovstream `./build.sh` package failure

Symptoms:

- `./build.sh` in `ovstream` fails while pulling packages.
- The failure mentions:

```text
the kit-kernel package required by the ovstream SDK version
```

Meaning:

- The full official `ovstream` build pulls additional dependencies beyond
  the SDK itself.
- This is not an OVUI, ovrtx, or Python build bug.

Action:

- Use the SDK-only fallback in Section 9.3 for browser proof.
- The SDK-only fallback is the supported lightweight path and avoids these
  extra dependencies entirely.

### 14.2 Git LFS missing binaries

Symptoms:

- Linking `libovstream.so` fails.
- `ldd` reports invalid or missing StreamSDK libraries.
- StreamSDK `.so` files are tiny text files.

Fix:

```bash
cd $WORKDIR/ovstream
git lfs install --local
git lfs pull
ls -lh source/extensions/omni.kit.livestream.webrtc/streamsdk/lib/linux/x86_64/libNvStreamServer.so
```

### 14.3 Browser installation issues

Symptoms:

- `chromium-browser` launches a snap error or is just a stub.
- Playwright Firefox times out waiting for `-juggler-pipe`.

Fix:

Install official Chrome and point Playwright at `/usr/bin/google-chrome`:

```bash
mkdir -p "$WORKDIR/tmp"
wget -O "$WORKDIR/tmp/google-chrome-stable_current_amd64.deb" \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt-get install -y "$WORKDIR/tmp/google-chrome-stable_current_amd64.deb"
```

### 14.4 WebRTC does not connect

Check the server process:

```bash
ps -p <LIVESTREAM_PID> -o pid,ppid,stat,etime,cmd
tail -n 120 $WORKDIR/tmp/ovwidgets-livestream-server.log
```

Check that the client can load:

```bash
curl -sS -I http://127.0.0.1:8080/
```

Check ports:

```bash
ss -ltnp | grep -E ':49100|:47999|:8080'
```

Common causes:

- Wrong signal port in the browser. Use `49100`.
- Livestream server did not initialize `libovstream.so`.
- `OVSTREAM_LIB_PATH` is missing or wrong.
- `LD_LIBRARY_PATH` does not include the OVSTREAM SDK output directory.
- The process is not running with `OMNIUI_HEADLESS=1` and `OMNIUI_BACKEND=vulkan`.
- The HTTP server is serving the wrong directory; serve
  `$WORKDIR/ovstream/sdk/examples/webrtc_client`.

### 14.5 Missing libraries or wrong `LD_LIBRARY_PATH`

Symptoms:

- Import errors for `pxr`.
- Loader errors for `libusd*.so`.
- Loader errors for `libovrtx-dynamic.so`.
- Loader errors for `libovstream.so` or StreamSDK libraries.

Use the combined runtime environment:

```bash
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH=$WORKDIR/usd-build/install/lib/python
export LD_LIBRARY_PATH=$WORKDIR/usd-build/install/lib:$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin:$WORKDIR/ovstream/_build/linux-x86_64/release/sdk
export OVSTREAM_LIB_PATH=$WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so
```

Inspect native dependencies:

```bash
ldd $WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so
ldd $WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin/libovrtx-dynamic.so
```

### 14.6 Port conflicts and cleanup

Do not use `pkill`, `killall`, or pattern-based process killing. Identify exact
PIDs:

```bash
ss -ltnp | grep -E ':8080|:49100|:47999'
ps -p <PID> -o pid,ppid,stat,etime,cmd
kill <PID>
```

Then restart the exact server you need.

### 14.7 Python version mismatch

Symptoms:

- Extension import errors.
- USD Python binding import errors.
- Venv uses `/usr/bin/python3` instead of the official Python.

Check:

```bash
$WORKDIR/ovui/ovwidgets/_venv312/bin/python -c "import sys; print(sys.executable); print(sys.version)"
```

Expected executable should be the venv created from:

```text
$WORKDIR/python-3.12.13-official/bin/python3.12
```

If not, recreate the venv using Section 8.

### 14.8 ovrtx/USD mismatch

Symptoms:

- ovrtx refuses to initialize when `pxr` is imported.
- The viewport logs USD/ovrtx compatibility errors.

Fix:

- Use OpenUSD v25.11 from `$WORKDIR/usd-build/install`.
- Use ovrtx 0.2.0 runtime from the documented release package.
- Export:

```bash
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH=$WORKDIR/usd-build/install/lib/python
export LD_LIBRARY_PATH=$WORKDIR/usd-build/install/lib:$WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin:$LD_LIBRARY_PATH
```

## 15. Final expected result

The screenshot should visibly show:

- Browser UI for `OVSTREAM SDK - Example WebRTC Client`.
- A green `CONNECTED` badge.
- The server input set to `127.0.0.1`.
- Signal port set to `49100`.
- The streamed OV Widgets app inside the video area.
- The stage tree with `Cube` highlighted.
- The properties panel for `Cube` with path `/World/Cube`.
- The central viewport rendering `simple_scene.usda`.
- A visible selection outline and transform gizmo on the cube.

This proves ovrtx rendering is visible because the browser is not displaying a
static screenshot. It is receiving the live OV Widgets frame over OVSTREAM
WebRTC, and that frame contains the application viewport rendered through the
OV Widgets ovrtx renderer path against the loaded USD scene.

The successful capture metadata was:

```text
status:      Connected
videoWidth:  1280
videoHeight: 720
readyState:  4
currentTime: 3.568634
screenshot:  $WORKDIR/ovui/ovwidgets-browser-proof.png
size:        224487 bytes
```

## 16. Appendix: reference run summary

### 16.1 Docs read during the successful run

OVUI and OV Widgets:

- `$WORKDIR/ovui/README.md`
- `$WORKDIR/ovui/ovui/README.md`
- `$WORKDIR/ovui/ovui/HEADLESS.md`
- `$WORKDIR/ovui/ovwidgets/README.md`
- `$WORKDIR/ovui/ovwidgets/LIVESTREAM.md`
- `$WORKDIR/ovui/ovui-data-adapters/README.md`

ovrtx:

- `$WORKDIR/ovrtx/README.md`
- `$WORKDIR/ovrtx/examples/README.md`
- `$WORKDIR/ovrtx/examples/c/cmake/ovrtx.cmake`
- `$WORKDIR/ovrtx/python/pyproject.toml`
- `$WORKDIR/ovrtx/VERSION.md`

ovstream:

- `$WORKDIR/ovstream/README.md`
- `$WORKDIR/ovstream/sdk/README.md`
- `$WORKDIR/ovstream/sdk/python/README.md`
- `$WORKDIR/ovstream/sdk/docs/GETTING_STARTED.md`
- `$WORKDIR/ovstream/TROUBLESHOOTING.md`

### 16.2 Reference versions and paths

```text
OVUI repo:
  $WORKDIR/ovui
  latest main

ovrtx repo:
  $WORKDIR/ovrtx
  latest main
  package/release 0.2.0

OpenUSD:
  source $WORKDIR/usd-build/OpenUSD
  tag v25.11
  install $WORKDIR/usd-build/install

ovstream:
  $WORKDIR/ovstream
  latest main
  VERSION.md identifies the expected SDK/package version

Python:
  source https://www.python.org/ftp/python/3.12.13/Python-3.12.13.tar.xz
  prefix $WORKDIR/python-3.12.13-official
  executable $WORKDIR/python-3.12.13-official/bin/python3.12
  version Python 3.12.13

OpenSSL:
  source https://www.openssl.org/source/openssl-3.5.6.tar.gz
  prefix $WORKDIR/openssl-3.5.6
  version OpenSSL 3.5.6

OV Widgets venv:
  $WORKDIR/ovui/ovwidgets/_venv312

ovrtx runtime:
  $WORKDIR/ovrtx/examples/c/_deps/ovrtx-src/bin/libovrtx-dynamic.so

OVSTREAM runtime:
  $WORKDIR/ovstream/_build/linux-x86_64/release/sdk/libovstream.so

USD scene:
  $WORKDIR/ovui/ovwidgets/tests/data/simple_scene.usda

Selected prim:
  /World/Cube

Browser proof:
  $WORKDIR/ovui/ovwidgets-browser-proof.png
```

### 16.3 Successful runtime state

The successful run leaves these process roles running:

```text
<livestream-pid>  $WORKDIR/ovui/ovwidgets/_venv312/bin/python $WORKDIR/tmp/ovwidgets_livestream_server.py
<http-pid>        $WORKDIR/ovui/ovwidgets/_venv312/bin/python -m http.server 8080
```

The successful URL was:

```text
http://127.0.0.1:8080/
```

The ready file was:

```text
$WORKDIR/tmp/ovwidgets-livestream-ready
ready selected=/World/Cube state=LISTENING clients=0 error=None
```

The browser automation reported:

```text
SCREENSHOT=$WORKDIR/ovui/ovwidgets-browser-proof.png
VIDEO={"status":"Connected","videoWidth":1280,"videoHeight":720,"readyState":4,"currentTime":3.568634}
```

### 16.4 Repository hygiene from the successful run

The previous proof intentionally did not commit build outputs or screenshots.
Generated/untracked items included:

```text
$WORKDIR/ovui/ovwidgets-browser-proof.png
$WORKDIR/tmp/ovwidgets_livestream_server.py
$WORKDIR/tmp/ovwidgets-browser-proof/capture.js
$WORKDIR/tmp/ovwidgets-livestream-server.log
$WORKDIR/tmp/ovwidgets-webrtc-http.log
```

Local source-tree patches outside OVUI were also part of the build environment:

```text
$WORKDIR/usd-build/OpenUSD/build_scripts/build_usd.py
  patched oneTBB URL from v2021.12.0.zip to v2021.13.1.zip

$WORKDIR/ovstream/deps/repo-deps.packman.xml
  locally patched only to bypass internal bootstrap/publish helper packages
  while diagnosing the official build blocker
```

The `repo-deps.packman.xml` patch is not required for the SDK-only fallback
documented in Section 9.3. It is recorded only as a diagnostic note for anyone
attempting the official `./build.sh` path.

Those patches are environment/build notes, not OVUI documentation changes.

### 16.5 Final success statement from the run

The browser proof was successful. The final screenshot shows the browser
connected to the OVSTREAM WebRTC server and receiving the OV Widgets application
frame. The application frame shows `simple_scene.usda`, `/World/Cube` selected,
the Cube property panel, and the ovrtx-rendered viewport.
