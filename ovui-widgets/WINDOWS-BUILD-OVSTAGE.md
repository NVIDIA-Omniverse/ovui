# Building ovui-widgets With ovstage And PhysX On Windows

> **Current support boundary:** This page records the older standalone Windows
> ovstage/ovrtx loader setup. It is not an end-to-end validation guide for the
> OVUI 0.2 native OVStage/OVRTX BORROW provider. In particular, the OVRTX
> 0.3 setup below does not provide the required public Python BORROW methods.
> Do not treat a successful package build or this older launcher as proof of
> native open/edit/render/pick/drag/shutdown support on Windows. Windows
> validation remains unproven; the Linux result recorded in the current
> runtime guide does not establish Windows support. Use the
> [Kit runtime guide](../ovui-data-adapters/docs/kit-runtime.md) for the current
> contract.
>
> The public [`NVIDIA-Omniverse/ovstage`](https://github.com/NVIDIA-Omniverse/ovstage)
> repository distributes ovstage as prebuilt C packages (GitHub Releases) and
> Python wheels (PyPI); it does not include the CMake source-build layout
> (root `CMakeLists.txt`, `src\` trees, `setup.bat`) that the legacy steps
> below assume. Follow the ovstage source-build sections only with an ovstage
> source checkout that provides that layout.

This guide records Windows build steps for the ovui-widgets reference app with
the older ovrtx, ovstage, and optional ovphysx setup. It includes the base
OpenUSD/ovrtx steps and then adds PhysX, ovphysx, ovstage, and the legacy
ovstage launcher.

Run native build commands from an x64 Visual Studio developer shell, such as
**x64 Native Tools Command Prompt for VS 2022**, or from a shell where the
Visual Studio compiler environment is already active.

## Prerequisites

- Windows 10 or Windows 11, x64.
- Visual Studio 2022 with the C++ desktop workload.
- Python 3.12.
- Git.
- CMake and Ninja.
- A recent NVIDIA driver.
- CUDA Toolkit 12.8 for building the GPU-capable PhysX SDK from source. This
  is not required for CPU-only SDK builds or for using a released `ovphysx`
  wheel that already contains its native runtime.
- Access to the `ovui`, `OpenUSD`, `ovrtx`, `ovstage`, and `PhysX`
  repositories.

## Workspace Variables

Use variables instead of host-specific absolute paths. The commands below use
PowerShell syntax.

```powershell
$env:WORKDIR = "<workspace-root>"
$env:REPO = Join-Path $env:WORKDIR "ovui"
$env:USD_SRC = Join-Path $env:WORKDIR "OpenUSD"
$env:USD_INSTALL_ROOT = Join-Path $env:WORKDIR "usd-build\install"
$env:OVRTX_ROOT = Join-Path $env:WORKDIR "ovrtx"
$env:OVRTX_BIN_DIR = Join-Path $env:OVRTX_ROOT "bin"
$env:OVSTAGE_ROOT = Join-Path $env:WORKDIR "ovstage"
$env:OVSTAGE_BUILD_DIR = Join-Path $env:OVSTAGE_ROOT "_build\windows-x86_64\release"
$env:PHYSX_ROOT = Join-Path $env:WORKDIR "PhysX"
$env:PYTHON_BIN = "<path-to-python-3.12>\python.exe"
$env:VENV = Join-Path $env:REPO "ovui-widgets\_venv312"
```

The ovstage launcher defaults to the sibling checkout named
`ovstage`. If you build ovstage somewhere else, set `OVSTAGE_ROOT` to
that checkout and set `OVSTAGE_BUILD_DIR` to its
`_build\windows-x86_64\release` directory before building and before running
the launcher.

## Clone Or Update Repositories

```powershell
git clone git@github.com:NVIDIA-Omniverse/ovui.git $env:REPO
git clone https://github.com/PixarAnimationStudios/OpenUSD.git $env:USD_SRC
git clone git@github.com:NVIDIA-Omniverse/ovrtx.git $env:OVRTX_ROOT
git clone git@github.com:NVIDIA-Omniverse/ovstage.git $env:OVSTAGE_ROOT
git clone git@github.com:NVIDIA-Omniverse/PhysX.git $env:PHYSX_ROOT
```

If the repositories already exist, update them instead:

```powershell
Push-Location $env:REPO
git checkout main
git pull --ff-only
Pop-Location

Push-Location $env:USD_SRC
git fetch --tags
git checkout v25.11
Pop-Location

Push-Location $env:OVRTX_ROOT
git checkout main
git pull --ff-only
Pop-Location

Push-Location $env:OVSTAGE_ROOT
if (git status --porcelain) {
    git stash push -u -m "preserve local ovstage work before main build"
}
git fetch origin main
git checkout main
git pull --ff-only origin main
Pop-Location

Push-Location $env:PHYSX_ROOT
git checkout main
git pull --ff-only
Pop-Location
```

Skip the ovstage update block above only when `OVSTAGE_ROOT` points at a
separate checkout that you update independently. The checkout used for
`OVSTAGE_ROOT` must be on `main` for this guide.

The launcher defaults to the sibling checkout named `ovstage`, so the
default no-extra-environment setup is:

```powershell
$env:OVSTAGE_ROOT = Join-Path $env:WORKDIR "ovstage"
$env:OVSTAGE_BUILD_DIR = Join-Path $env:OVSTAGE_ROOT "_build\windows-x86_64\release"
```

If that checkout was previously on an experimental branch, keep the stash from
the update block above until you no longer need those local changes. Do not
build a different ovstage checkout unless you also set `OVSTAGE_ROOT` and
`OVSTAGE_BUILD_DIR` before every launch.

## Create The Python Environment

```powershell
& $env:PYTHON_BIN -m venv $env:VENV
$env:PYTHON_BIN = Join-Path $env:VENV "Scripts\python.exe"
& $env:PYTHON_BIN -m pip install --upgrade pip setuptools wheel
& $env:PYTHON_BIN -m pip install build pytest cmake ninja numpy tomli libcst Pillow packaging fastapi uvicorn
$env:PATH = "$env:VENV\Scripts;$env:PATH"
```

Install `ovphysx` later, after the source-build steps. Some `ovphysx`
packages pin older packaging tooling, and installing it too early can interfere
with subsequent editable package builds.

## Build OpenUSD 25.11

Build OpenUSD into `$env:USD_INSTALL_ROOT`.

```powershell
Push-Location $env:USD_SRC
git checkout v25.11
```

If oneTBB fails to compile with the installed MSVC toolset, apply this
Windows-only OpenUSD patch before building. Keep this patch local to the OpenUSD
checkout; do not commit it to ovui.

```powershell
$buildUsd = Join-Path $env:USD_SRC "build_scripts\build_usd.py"
$text = Get-Content $buildUsd -Raw
$old = 'ONETBB_URL = "https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.12.0.zip"'
$new = @'
# Windows needs a newer oneTBB to build cleanly with MSVC 19.40+; Linux
# builds fine on the upstream-pinned 2021.12.0, so leave that path alone.
ONETBB_URL = ("https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.13.1.zip"
              if Windows()
              else "https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.12.0.zip")
'@
if ($text.Contains($old)) {
    Set-Content -Path $buildUsd -Value $text.Replace($old, $new)
}
```

Run the OpenUSD build:

```powershell
Push-Location $env:USD_SRC

& $env:PYTHON_BIN ".\build_scripts\build_usd.py" `
  --build-shared `
  --onetbb `
  --imaging `
  --no-usdview `
  --no-materialx `
  --no-examples `
  --no-tutorials `
  --no-tests `
  --no-docs `
  --generator "Visual Studio 17 2022" `
  -v `
  -j 12 `
  $env:USD_INSTALL_ROOT

Pop-Location
```

Set the custom USD runtime path before any package imports `pxr`:

```powershell
$env:PATH = "$env:USD_INSTALL_ROOT\lib;$env:USD_INSTALL_ROOT\bin;$env:PATH"
$env:PYTHONPATH = "$env:USD_INSTALL_ROOT\lib\python;$env:PYTHONPATH"
```

Verify OpenUSD:

```powershell
& $env:PYTHON_BIN -c "import os; os.add_dll_directory(os.environ['USD_INSTALL_ROOT'] + r'\lib'); from pxr import Usd; print(Usd.GetVersion())"
```

## Install ovrtx 0.3.0

```powershell
Push-Location $env:OVRTX_ROOT
git checkout main
git pull --ff-only
Get-Content python\pyproject.toml | Select-String 'version = "0.3.0"'
Pop-Location

& $env:PYTHON_BIN -m pip install -e "$env:OVRTX_ROOT\python"
```

Verify ovrtx:

```powershell
Test-Path "$env:OVRTX_BIN_DIR\ovrtx-dynamic.dll"
$env:PATH = "$env:OVRTX_BIN_DIR;$env:PATH"
$env:OVRTX_SKIP_USD_CHECK = "1"
& $env:PYTHON_BIN -c "import ovrtx; print(ovrtx.__version__)"
```

## Build PhysX SDK

The ovui-widgets app consumes the `ovphysx` Python package. The PhysX checkout
also contains the lower-level PhysX SDK. Build it when you need to verify or
produce local PhysX SDK binaries for the same checkout.

Generate a Visual Studio 2022 project with the `vc17win64` preset when CUDA
Toolkit 12.8 is installed:

```powershell
Push-Location "$env:PHYSX_ROOT\physx"
.\generate_projects.bat vc17win64
.\buildtools\steps\build_win_x86_64.bat vc17win64 release
Pop-Location
```

For a CPU-only SDK build, use the `vc17win64-cpu-only` preset instead:

```powershell
Push-Location "$env:PHYSX_ROOT\physx"
.\generate_projects.bat vc17win64-cpu-only
.\buildtools\steps\build_win_x86_64.bat vc17win64-cpu-only release
Pop-Location
```

The CPU-only preset verifies the SDK build on machines without CUDA 12.8, but
it does not validate GPU PhysX simulation. Use the released `ovphysx` package
or a GPU-capable local `ovphysx` build for the app runtime.

## Build ovstage

Build ovstage against the same OpenUSD install used by the app. The build
produces the runtime directory expected by the ovstage launcher:
`_build\windows-x86_64\release`.

ovstage also provides `src\ovstage\setup.bat`, but that script runs ovstage's
own source-tree tests after building. Use the explicit CMake build below for
the ovui-widgets app runtime, then run source-tree tests separately if you need
to validate ovstage itself.

```powershell
Push-Location $env:OVSTAGE_ROOT
$env:USD_ROOT = $env:USD_INSTALL_ROOT

$venvPython = Join-Path $env:VENV "Scripts\python.exe"
$basePrefix = (& $venvPython -c "import sys; print(sys.base_prefix)").Trim()
$pyLib = (& $venvPython -c "import sys; print(f'python{sys.version_info.major}{sys.version_info.minor}.lib')").Trim()
$env:PYTHON_ROOT = $basePrefix
$env:Python3_ROOT_DIR = $basePrefix
$env:Python3_INCLUDE_DIR = Join-Path $basePrefix "Include"
$env:Python3_LIBRARY = Join-Path $basePrefix "libs\$pyLib"
$env:PYTHON_BIN = "python"

$buildRoot = Join-Path $env:OVSTAGE_ROOT "_build"
$pythonLibDir = Split-Path -Parent $env:Python3_LIBRARY

if (Test-Path $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}

cmake -S $env:OVSTAGE_ROOT -B $buildRoot `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -DCMAKE_BUILD_TYPE=Release `
  -DOVSTAGE_ENABLE_CUDA=ON `
  -DOVPOPULATION_BUILD_PYTHON_BRIDGE=ON `
  -DUSD_ROOT="$env:USD_ROOT" `
  -DPython3_ROOT_DIR="$env:Python3_ROOT_DIR" `
  -DPython3_INCLUDE_DIR="$env:Python3_INCLUDE_DIR" `
  -DPython3_LIBRARY="$env:Python3_LIBRARY" `
  -DCMAKE_CXX_FLAGS="/I$env:Python3_INCLUDE_DIR" `
  -DCMAKE_SHARED_LINKER_FLAGS="/LIBPATH:$pythonLibDir" `
  -Wno-dev

cmake --build $buildRoot --config Release --parallel
Pop-Location
```

Verify the ovstage runtime DLLs:

```powershell
Test-Path "$env:OVSTAGE_BUILD_DIR\ovstage.dll"
Test-Path "$env:OVSTAGE_BUILD_DIR\ovpopulation.dll"
Test-Path "$env:OVSTAGE_BUILD_DIR\ovhierarchy.dll"
```

## Install ovui, Adapters, And ovui-widgets

Install the local packages in editable mode. The OpenUSD and ovstage adapter
packages are installed with `--no-deps` so pip does not replace the custom USD
build or the selected ovphysx package.

```powershell
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui"

& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-data-adapters\dist\common" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-data-adapters\dist\openusd" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-data-adapters\dist\ovstage" --no-deps

& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\common" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\content" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\stage" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\layers" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\property" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\viewport" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\app" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\all" --no-deps
```

## Install ovphysx

The ovstage adapter imports `ovphysx` from Python. Install the released ovphysx
package that matches the PhysX branch you are testing, or install the wheel
produced by your PhysX build pipeline.

```powershell
& $env:PYTHON_BIN -m pip install ovphysx
```

If your source checkout provides a local ovphysx wheel, install that wheel
instead:

```powershell
& $env:PYTHON_BIN -m pip install --force-reinstall "<path-to-ovphysx-wheel>"
```

Do not rely on `PhysX\ovphysx\python` by itself unless the native `ovphysx`
runtime libraries have already been staged into that package. A pure editable
install of that folder only supplies the Python wrapper files.

Verify ovphysx:

```powershell
& $env:PYTHON_BIN -c "import ovphysx; print(ovphysx.__version__)"
```

## Runtime Environment

The ovstage launcher sets most of this automatically, but these values are
useful for preflight checks and raw Python commands.

```powershell
$env:USD_ROOT = $env:USD_INSTALL_ROOT
$env:OVSTAGE_LIBRARY_PATH = $env:OVSTAGE_BUILD_DIR
$env:OVPOPULATION_LIBRARY_PATH = $env:OVSTAGE_BUILD_DIR
$env:OVHIERARCHY_LIBRARY_PATH = $env:OVSTAGE_BUILD_DIR
$env:PATH = "$env:OVSTAGE_BUILD_DIR;$env:OVRTX_BIN_DIR;$env:USD_INSTALL_ROOT\lib;$env:USD_INSTALL_ROOT\bin;$env:PATH"
$env:PYTHONPATH = "$env:OVSTAGE_ROOT\src\ovstage\python;$env:OVSTAGE_ROOT\src\ovpopulation\python;$env:OVSTAGE_ROOT\src\ovhierarchy\python;$env:OVRTX_ROOT\python;$env:USD_INSTALL_ROOT\lib\python;$env:PYTHONPATH"
$env:OVRTX_SKIP_USD_CHECK = "1"
$env:OVPHYSX_COEXIST_DIAGNOSTICS = "1"
```

Preflight imports and adapter discovery:

```powershell
& $env:PYTHON_BIN -c "import ovstage, ovpopulation, ovhierarchy, ovphysx, ovrtx; from ovui_data_adapters.common import discover_adapter_modules; r=discover_adapter_modules(); print([p.name for p in r.available_adapters()]); assert any(p.name == 'ovstage' for p in r.available_adapters())"
```

The output should include `openusd` and `ovstage`.

## Run With ovstage And PhysX

The launcher uses `OVSTAGE_ROOT` and `OVSTAGE_BUILD_DIR` when they are set. If
they are not set, it looks for a built sibling `ovstage` checkout.
Keep those environment variables set before launching when ovstage was built in
any other checkout.

```powershell
& "$env:REPO\ovui-widgets\scripts\ovui-widgets-ovstage-physx-win.bat" `
  "$env:REPO\ovui-data-adapters\tests\data\ovstage_physx_rainbow_cubes.usda"
```

In the running app:

1. Use `Physics > Enable PhysX`.
2. Use `Physics > Play Simulation`.

`Play Simulation` is disabled until PhysX is enabled. After simulation starts,
the menu item changes to `Stop Simulation`.

## Smoke Tests

Run the common adapter registry check:

```powershell
& $env:PYTHON_BIN -m pytest "$env:REPO\ovui-data-adapters\tests\common\test_adapter_registry.py"
```

Run ovstage runtime and provider checks only after the optional runtime stack
imports cleanly:

```powershell
& $env:PYTHON_BIN -m pytest `
  "$env:REPO\ovui-data-adapters\tests\ovstage\test_runtime_preflight.py" `
  "$env:REPO\ovui-data-adapters\tests\ovstage\test_provider_registration.py" `
  -q
```

The full `tests\ovstage` suite is a source compatibility suite, not a build
manual gate. Use it when intentionally validating ovstage adapter behavior.

## Troubleshooting

`pxr is already loaded from a different Python package`

Restart the shell and make sure `$env:USD_INSTALL_ROOT\lib\python` is before
site-packages on `PYTHONPATH` before anything imports `pxr`. Avoid installing
or importing `usd-core` in the ovstage environment unless the custom USD path is
guaranteed to win first.

`adapter provider not found: ovstage; available: openusd`

Install `ovui-data-adapters\dist\ovstage`, set `OVSTAGE_ROOT` and
`OVSTAGE_BUILD_DIR`, and verify that `ovstage`, `ovpopulation`, `ovhierarchy`,
`ovphysx`, and `ovrtx` import in the same environment.

`ovrtx-dynamic.dll` cannot be found

Set `OVRTX_BIN_DIR` to the ovrtx runtime `bin` directory and prepend it to
`PATH`.

`ovstage.dll`, `ovpopulation.dll`, or `ovhierarchy.dll` cannot be found

Build ovstage and set `OVSTAGE_BUILD_DIR` to the release output directory that
contains those DLLs. For raw Python commands and tests, also set
`OVSTAGE_LIBRARY_PATH`, `OVPOPULATION_LIBRARY_PATH`, and
`OVHIERARCHY_LIBRARY_PATH` to that same directory.

`ovphysx` imports but PhysX cannot create a GPU simulation

Check that the installed ovphysx package includes native runtime libraries,
that the NVIDIA driver is compatible with the CUDA Toolkit used by the PhysX
build, and that the shell was restarted after changing CUDA or driver paths.
