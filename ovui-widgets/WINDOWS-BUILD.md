# Building ovui-widgets on Windows

This guide builds and runs the ovui-widgets reference app on Windows with the
OpenUSD data adapter and ovrtx renderer. It does not build or install ovstage or
ovphysx. For the ovstage plus PhysX setup, use `WINDOWS-BUILD-OVSTAGE.md`.

Run native build commands from an x64 Visual Studio developer shell, such as
**x64 Native Tools Command Prompt for VS 2022**, or from a shell where the
Visual Studio compiler environment is already active.

## Prerequisites

- Windows 10 or Windows 11, x64.
- Visual Studio 2022 with the C++ desktop workload.
- Python 3.12.
- Git.
- A recent NVIDIA driver.
- Access to the `ovui`, `OpenUSD`, and `ovrtx` repositories.

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
$env:PYTHON_BIN = "<path-to-python-3.12>\python.exe"
$env:VENV = Join-Path $env:REPO "ovui-widgets\_venv312"
```

## Clone Or Update Repositories

```powershell
git clone git@github.com:NVIDIA-Omniverse/ovui.git $env:REPO
git clone https://github.com/PixarAnimationStudios/OpenUSD.git $env:USD_SRC
git clone git@github.com:NVIDIA-Omniverse/ovrtx.git $env:OVRTX_ROOT
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
```

## Create The Python Environment

```powershell
& $env:PYTHON_BIN -m venv $env:VENV
$env:PYTHON_BIN = Join-Path $env:VENV "Scripts\python.exe"
& $env:PYTHON_BIN -m pip install --upgrade pip setuptools wheel
& $env:PYTHON_BIN -m pip install build pytest cmake ninja numpy tomli libcst Pillow
$env:PATH = "$env:VENV\Scripts;$env:PATH"
```

If this checkout was previously used for the ovstage build, remove stale
generated ovstage package metadata before validating the no-ovstage adapter
set:

```powershell
$staleOvstageMetadata = Join-Path $env:REPO "ovui-data-adapters\ovui_data_adapters_ovstage.egg-info"
if (Test-Path $staleOvstageMetadata) {
    Remove-Item -LiteralPath $staleOvstageMetadata -Recurse -Force
}
```

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

Set the runtime search path for the custom USD build:

```powershell
$env:PATH = "$env:USD_INSTALL_ROOT\lib;$env:USD_INSTALL_ROOT\bin;$env:PATH"
$env:PYTHONPATH = "$env:USD_INSTALL_ROOT\lib\python;$env:PYTHONPATH"
```

Verify that the expected OpenUSD Python bindings are used:

```powershell
& $env:PYTHON_BIN -c "import os; os.add_dll_directory(os.environ['USD_INSTALL_ROOT'] + r'\lib'); from pxr import Usd; print(Usd.GetVersion())"
```

## Install ovrtx 0.3.0

ovui-widgets imports ovrtx from the `ovrtx\python` package and loads native
libraries from the ovrtx runtime `bin` directory.

```powershell
Push-Location $env:OVRTX_ROOT
git checkout main
git pull --ff-only
Get-Content python\pyproject.toml | Select-String 'version = "0.3.0"'
Pop-Location

& $env:PYTHON_BIN -m pip install -e "$env:OVRTX_ROOT\python"
```

Make sure the native runtime is available:

```powershell
Test-Path "$env:OVRTX_BIN_DIR\ovrtx-dynamic.dll"
$env:PATH = "$env:OVRTX_BIN_DIR;$env:PATH"
$env:OVRTX_SKIP_USD_CHECK = "1"
& $env:PYTHON_BIN -c "import ovrtx; print(ovrtx.__version__)"
```

If you need a direct ovrtx runtime check:

```powershell
Push-Location "$env:OVRTX_ROOT\examples\c\minimal"
cmake -B build
cmake --build build --config Release
.\build\Release\minimal.exe
Pop-Location
```

## Install ovui, Adapters, And ovui-widgets

Install local packages in editable mode. The OpenUSD adapter is installed with
`--no-deps` so pip does not replace the custom OpenUSD build with a separate
`usd-core` package.

```powershell
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui"

& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-data-adapters\dist\common" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-data-adapters\dist\openusd" --no-deps

& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\common" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\content" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\stage" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\layers" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\property" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\viewport" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\app" --no-deps
& $env:PYTHON_BIN -m pip install -e "$env:REPO\ovui-widgets\dist\all" --no-deps
```

Verify adapter discovery:

```powershell
& $env:PYTHON_BIN -c "from ovui_data_adapters.common import discover_adapter_modules; r=discover_adapter_modules(); print([p.name for p in r.available_adapters()])"
```

The output should include `openusd`.

## Run The App

The launcher reads `USD_INSTALL_ROOT`, `OVRTX_ROOT`, and `OVRTX_BIN_DIR` from
the environment.

```powershell
$env:USD_INSTALL_ROOT = $env:USD_INSTALL_ROOT
$env:OVRTX_ROOT = $env:OVRTX_ROOT
$env:OVRTX_BIN_DIR = $env:OVRTX_BIN_DIR
$env:OVRTX_SKIP_USD_CHECK = "1"

& "$env:REPO\ovui-widgets\scripts\ovui-widgets-win.bat" `
  "$env:REPO\ovui-data-adapters\tests\data\ovstage_falling_cube_scene.usda"
```

You can also launch without a file:

```powershell
& "$env:REPO\ovui-widgets\scripts\ovui-widgets-win.bat"
```

## Smoke Tests

Run a lightweight package and adapter check:

```powershell
& $env:PYTHON_BIN -m pytest "$env:REPO\ovui-data-adapters\tests\common\test_adapter_registry.py"
```

Run OpenUSD adapter checks:

```powershell
& $env:PYTHON_BIN -m pytest "$env:REPO\ovui-data-adapters\tests\common" "$env:REPO\ovui-data-adapters\tests\openusd" -q
```

## Troubleshooting

`DLL load failed while importing _tf`

Make sure the app is launched through `ovui-widgets\scripts\ovui-widgets-win.bat`,
and make sure `$env:USD_INSTALL_ROOT\lib` is in `PATH` while
`$env:USD_INSTALL_ROOT\lib\python` is first in `PYTHONPATH`.

`from pxr import Usd` imports the wrong USD package

Move `$env:USD_INSTALL_ROOT\lib\python` before site-packages on `PYTHONPATH`.
If `usd-core` was installed into the venv, uninstall it or keep the custom USD
path ahead of it for every launch.

`ovrtx-dynamic.dll` cannot be found

Set `OVRTX_BIN_DIR` to the ovrtx runtime `bin` directory and prepend it to
`PATH`.

`adapter provider not found: openusd`

Install both `ovui-data-adapters\dist\common` and
`ovui-data-adapters\dist\openusd` into the same Python environment used by the
launcher.
