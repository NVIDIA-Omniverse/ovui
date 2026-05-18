# Building OvGear on Windows

This is the Windows counterpart to `README.md`'s Linux build instructions.
All four pieces — **OpenUSD 25.11**, **ovui**, **ovrtx**, and **OvGear**
itself — have been brought up and smoke-tested on Windows 10 Enterprise
with Visual Studio 2022 Professional, Python 3.12.3, and CUDA 11.0.

Result: `ovwidgets` launches (`ovgear` retained as alias), opens a USD stage, initializes ovrtx, and
**4702 tests pass** out of the ovgear test suite (the handful of remaining
failures are unrelated to the build — see *Known Test Failures* below).

## Prerequisites

| Tool                        | Version used              | Notes                                              |
|-----------------------------|---------------------------|----------------------------------------------------|
| Windows                     | 10 Enterprise (19044)     |                                                    |
| Visual Studio               | 2022 Professional         | Community and Build Tools both work; C++ workload. |
| MSVC toolset                | 14.44.35207 (VS 17.14)    | Auto-installed with the C++ workload.              |
| Python                      | 3.12.3 at `C:\usr\Python312` | 3.12 exact — same ABI pin as Linux.             |
| CUDA Toolkit                | 11.0                      | `cudart64_110.dll` is a transitive dep of ovui.    |
| NVIDIA driver               | RTX-capable, Vulkan ICD   | Same requirement as Linux.                         |
| Git                         | any                       |                                                    |

CMake and Ninja are installed via `pip` into the project venv — no separate
system installs required.

Expected clone layout (matches this session):

```
C:\dev\ovgear           this repo
C:\dev\ovui             omni.ui sibling repo
C:\dev\ovrtx            ovrtx skills / source (the actual binary comes from PyPI)
C:\dev\OpenUSD          https://github.com/PixarAnimationStudios/OpenUSD
C:\dev\usd-build        USD build/install prefix (created during step 1)
```

## 1. Build OpenUSD v25.11

### 1.1 Check out the pinned tag

```powershell
cd C:\dev\OpenUSD
git checkout v25.11
```

### 1.2 Patch `build_usd.py` for newer oneTBB (Windows only)

On Windows, MSVC 19.40+ does not compile oneTBB 2021.12.0 cleanly; bump to
2021.13.1. The patch is **platform-gated** — Linux continues to use the
upstream-pinned 2021.12.0 URL unchanged.

Replace the line at `build_scripts/build_usd.py:1004`:

```python
ONETBB_URL = "https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.12.0.zip"
```

with:

```python
# Windows needs a newer oneTBB to build cleanly with MSVC 19.40+; Linux
# builds fine on the upstream-pinned 2021.12.0, so leave that path alone.
ONETBB_URL = ("https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.13.1.zip"
              if Windows()
              else "https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.12.0.zip")
```

### 1.3 Create the OvGear venv and add CMake + Ninja

`build_usd.py` calls `cmake` from `PATH`. The cleanest way on Windows is to
install CMake via `pip` into the venv we're going to use for OvGear
anyway — this avoids an MSI install and keeps the build self-contained.

```powershell
C:\usr\Python312\python.exe -m venv C:\dev\ovgear\_venv312
C:\dev\ovgear\_venv312\Scripts\python.exe -m pip install -U pip setuptools wheel
C:\dev\ovgear\_venv312\Scripts\python.exe -m pip install "cmake>=3.26" ninja
```

### 1.4 Run the USD build

Driver script (`C:\dev\usd-build\build.bat`) — stages the VS environment
and invokes `build_usd.py` with the same flags as the Linux README, plus
`--generator "Visual Studio 17 2022"`:

```bat
@echo off
set PATH=C:\dev\ovgear\_venv312\Scripts;%PATH%
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1

cd /d C:\dev\usd-build
C:\usr\Python312\python.exe C:\dev\OpenUSD\build_scripts\build_usd.py ^
    --build-shared ^
    --onetbb ^
    --imaging ^
    --no-usdview ^
    --no-materialx ^
    --no-examples ^
    --no-tutorials ^
    --no-tests ^
    --no-docs ^
    --generator "Visual Studio 17 2022" ^
    -v -j 12 ^
    C:\dev\usd-build\install
```

Run it:

```powershell
mkdir C:\dev\usd-build
cd C:\dev\usd-build
.\build.bat
```

Expected result: ~15–25 minutes on a modern workstation, ending with the
"The following in your PATH environment variable" banner. Verify:

```powershell
# Should report 61 .dll files (non-monolithic USD)
(Get-ChildItem C:\dev\usd-build\install\lib\*.dll).Count

# Python bindings present
Test-Path C:\dev\usd-build\install\lib\python\pxr\Usd\__init__.py
```

No special `--build-python-info` flag is needed on Windows: `build_usd.py`
uses the active `python.exe` automatically.

## 2. Install ovrtx

`ovrtx` ships as a Windows binary wheel on PyPI — no build from source:

```powershell
C:\dev\ovgear\_venv312\Scripts\python.exe -m pip install ovrtx==0.2.0.280040
```

The wheel drops `ovrtx-dynamic.dll` into
`_venv312\Lib\site-packages\ovrtx\bin\` and the loader in
`ovrtx\_src\bindings.py` finds it automatically.

## 3. Install ovui (editable)

### 3.1 Build & install

```powershell
C:\dev\ovgear\_venv312\Scripts\python.exe -m pip install -e C:\dev\ovui
```

The CMake build produced by `setup.py` drops three DLLs plus two `.pyd`
files next to the Python package:

```
C:\dev\ovui\python\omni\ui\
    _ui.cp312-win_amd64.pyd
    ovui.dll
    omniui_standalone.dll

C:\dev\ovui\python\omni\ui_scene\
    _scene.cp312-win_amd64.pyd
    ovuiscene.dll
```

### 3.2 Patch `standalone/src/GlfwPlatform.cpp` for font discovery

The font-path finder in `GlfwPlatform::findFontPath` used to walk up 8
parent directories on **Linux** (so dev / editable builds would find
`<repo_root>/resources/fonts/*.ttf`) but on **Windows** it only looked in
exactly one directory — `<DLL dir>/resources/fonts/`. In the editable
layout `omniui_standalone.dll` is staged into `python/omni/ui/` with no
adjacent `resources/`, so the old code fell back to the ImGui default
font and the UI looked bad (bitmappy ProggyClean instead of NVIDIA Sans).

Applied to `C:\dev\ovui\standalone\src\GlfwPlatform.cpp` (around line 51):
the Windows branch now does the same walk-up-to-8-parents as Linux, so
`C:\dev\ovui\python\omni\ui\` → walks up to `C:\dev\ovui\` → finds
`C:\dev\ovui\resources\fonts\NVIDIASans_Rg.ttf`.

After the patch, rebuild ovui:

```powershell
C:\dev\ovgear\_venv312\Scripts\python.exe -m pip install -e C:\dev\ovui --force-reinstall --no-deps
```

Verify: the launch log should now print
`GlfwPlatform: loaded font C:\dev\ovui\resources\fonts\NVIDIASans_Rg.ttf`
instead of `No custom font found, using ImGui default`.

### 3.3 Patch `omni/ui_scene/__init__.py` for cold imports

`_scene.pyd` links against four non-system DLLs — `omniui_standalone.dll`,
`ovuiscene.dll`, `ovui.dll`, and (transitively) `cudart64_110.dll`.

`omni/ui/__init__.py` registers all those DLL directories with
`os.add_dll_directory()` on Windows, but **`omni/ui_scene/__init__.py`
did not.** As a result, `from omni.ui_scene import scene` would fail with
`DLL load failed while importing _scene` unless `omni.ui` was imported
first (OvGear's viewport modules import `omni.ui_scene` at module load,
and several test modules do the same).

Applied this patch (`C:\dev\ovui\python\omni\ui_scene\__init__.py`):

```python
import sys as _sys
import os as _os
if _sys.platform == "win32" and hasattr(_os, "add_dll_directory"):
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    _os.add_dll_directory(_pkg_dir)
    _ui_dir = _os.path.join(_os.path.dirname(_pkg_dir), "ui")
    if _os.path.isdir(_ui_dir):
        _os.add_dll_directory(_ui_dir)
    for _cuda_env in ("CUDA_PATH", "CUDAToolkit_ROOT", "CUDA_HOME"):
        _cuda_root = _os.environ.get(_cuda_env)
        if _cuda_root:
            _cuda_bin = _os.path.join(_cuda_root, "bin")
            if _os.path.isdir(_cuda_bin):
                _os.add_dll_directory(_cuda_bin)
                break
```

No-op on non-Windows platforms — Linux is untouched.

## 4. Install OvGear (editable)

```powershell
cd C:\dev\ovgear
.\_venv312\Scripts\python.exe -m pip install -e ".[dev]"
.\_venv312\Scripts\python.exe -m pip install tomli
```

**Do not** install the `[usd]` extra on Windows. On Linux the README
installs `usd-core` and then shadows it at runtime via `PYTHONPATH`; on
Windows the shadowing story is fiddlier because USD's Python package
directory also needs `os.add_dll_directory` (Python 3.8+ ignores `PATH`
for extension-module DLL resolution). Easier to just skip the PyPI
`usd-core` entirely and rely on the custom v25.11 build.

## 5. Environment: how Windows differs from Linux

The Linux README wires three env vars at runtime:

| Linux var            | Windows equivalent                                                          |
|----------------------|-----------------------------------------------------------------------------|
| `OVRTX_SKIP_USD_CHECK=1` | same — just set it                                                      |
| `PYTHONPATH=...USD/lib/python` | same — prepend `C:\dev\usd-build\install\lib\python`             |
| `LD_LIBRARY_PATH=...USD/lib`   | **`os.add_dll_directory(...)`** (not `PATH`). See bootstrap below.|

Windows detail: since Python 3.8 the DLL search path for extension
modules no longer honors `PATH`. It honors directories explicitly
registered with `os.add_dll_directory()`. Setting `PATH=...\install\lib`
will *look* right in the shell but `from pxr import Usd` will still
blow up with `DLL load failed while importing _tf`.

## 6. Launching OvGear

Two helpers are provided under `scripts/`:

- **`scripts/run_ovgear_windows.py`** — Python bootstrap that registers
  the USD DLL directories, prepends `pxr` to `sys.path`, and hands off
  to `ovwidgets.app.__main__`.
- **`scripts/ovwidgets-win.bat`** — primary batch wrapper: points
  `USD_INSTALL_ROOT` at `C:\dev\usd-build\install` (overridable),
  exports `OVRTX_SKIP_USD_CHECK=1`, and invokes the Python bootstrap
  through the venv's interpreter.
- **`scripts/ovgear-win.bat`** — backward-compatible alias; delegates
  entirely to `ovwidgets-win.bat`.

Typical use:

```powershell
# Empty stage
C:\dev\ovgear\scripts\ovwidgets-win.bat

# Open a USD file
C:\dev\ovgear\scripts\ovwidgets-win.bat tests\data\simple_scene.usda

# Legacy alias also works:
C:\dev\ovgear\scripts\ovgear-win.bat tests\data\simple_scene.usda
```

Expected first-run output:

```
GlfwPlatform: No custom font found, using ImGui default
standalone::init: initialized successfully (1280x720)
[USD Compatibility] Warning: Cannot verify compatibility with unknown USD version
#  HD_ENABLE_SCENE_INDEX_EMULATION is overridden to 'false'.  Default is 'true'.
#  OMNI_USD_RESOLVER_MDL_BUILTIN_BYPASS is overridden to 'true'.  Default is 'false'.
```

A 1280×720 GLFW window appears showing the viewport; the Stage Browser on
the left lists prims (Cube, Sphere, Pyramid for `simple_scene.usda`); the
Property Inspector on the right lights up on selection.

## 7. Running the tests

```powershell
C:\dev\ovgear\scripts\pytest-win.bat
```

Current status on Windows:

- **4702 passed**, 14 skipped (GPU/optional), 3 flaky / env-sensitive
  failures, 10 test_docs errors.
- The 10 test_docs errors are all `UnicodeDecodeError: 'charmap' codec
  can't decode byte 0x90` from `ARCHITECTURE.md` — `Path.read_text()` in
  those tests needs `encoding="utf-8"`. Linux defaults to UTF-8 so the
  same code works there. Fix belongs in `tests/test_docs.py`, not in the
  build.
- `test_runtime_prim_pngs_are_monochrome_line_glyphs` needs `Pillow`; the
  `[dev]` extra doesn't require it.
- The remaining two failures
  (`test_callback_fires_after_real_delay`,
  `test_imgui_splitter_style_applies_to_active_context`) are
  timing/context-sensitive flakes.

None of these block day-to-day use.

## 8. Troubleshooting

| Symptom                                                          | Cause / Fix                                                                                       |
|------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| `DLL load failed while importing _tf`                            | USD DLL dirs not registered. Launch via `scripts/ovwidgets-win.bat`, not a raw `python -m ovwidgets.app`.   |
| `DLL load failed while importing _scene`                         | Did you pull the `omni/ui_scene/__init__.py` patch from §3.2?                                     |
| `from pxr import Usd` returns version `(0, 26, 5)`               | `sys.path` is finding the wrong pxr. `USD_INSTALL_ROOT` wrong, or the `[usd]` extra was installed.|
| `ovrtx` refuses to import                                        | `OVRTX_SKIP_USD_CHECK` not set. The bat wrapper sets it; raw invocations need `set OVRTX_SKIP_USD_CHECK=1`. |
| oneTBB build fails with `error C2039` or similar template errors | `build_usd.py` patch from §1.2 not applied (still on 2021.12.0).                                  |
| `'vswhere.exe' is not recognized`                                | Harmless — `vcvars64.bat` sometimes emits this before succeeding. Look for the                    |
|                                                                  | `[vcvarsall.bat] Environment initialized for: 'x64'` line just after it.                          |

## 9. What's different from Linux, summarized

1. **Paths** — everything under `C:\dev\...` instead of `~/dev/...`.
2. **USD venv** — the same `_venv312` that holds ovgear also provides
   `cmake` + `ninja` for the USD build; no system CMake required.
3. **USD build script** — needs `--generator "Visual Studio 17 2022"`
   (or newer) and a `vcvars64.bat`-primed environment before invoking.
4. **oneTBB** — MSVC 19.40+ needs 2021.13.1; the patch is platform-gated
   so Linux keeps its original 2021.12.0.
5. **Font discovery** — `GlfwPlatform::findFontPath` needed the same
   walk-up logic on Windows as Linux; without it the ImGui default font
   is used. See §3.2.
6. **ui_scene DLL loader** — needs the `os.add_dll_directory` patch from
   §3.3 so cold imports work.
7. **USD DLL discovery** — cannot rely on `PATH`; use
   `os.add_dll_directory()` via `scripts/run_ovgear_windows.py`.
8. **`usd-core` extra** — skip it; just use the custom build.
