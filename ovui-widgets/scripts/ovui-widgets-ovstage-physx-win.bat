@echo off
REM Windows launcher for USD Viewer with ovstage, ovphysx, and ovrtx 0.3.
REM Pass a USD file path as the first argument, or omit it to open the falling-cube demo.

setlocal

set "SCRIPT_DIR=%~dp0"
set "OVUI_ROOT=%SCRIPT_DIR%..\.."
for %%I in ("%OVUI_ROOT%") do set "OVUI_ROOT=%%~fI"
set "OVUI_WIDGETS_ROOT=%OVUI_ROOT%\ovui-widgets"

if "%~1"=="/?" goto usage
if "%~1"=="--help" goto usage
if "%~1"=="-h" goto usage

if not defined USD_INSTALL_ROOT (
    for %%I in ("%OVUI_ROOT%\..\usd-build\install") do set "USD_INSTALL_ROOT=%%~fI"
)

if not defined OVRTX_ROOT for %%I in ("%OVUI_ROOT%\..\ovrtx") do set "OVRTX_ROOT=%%~fI"
for %%I in ("%OVUI_ROOT%\..\ovstage") do set "DEFAULT_OVSTAGE_ROOT=%%~fI"
if not defined OVSTAGE_ROOT (
    set "OVSTAGE_ROOT=%DEFAULT_OVSTAGE_ROOT%"
) else if not exist "%OVSTAGE_ROOT%\src\ovstage\python\ovstage\__init__.py" (
    if exist "%DEFAULT_OVSTAGE_ROOT%\src\ovstage\python\ovstage\__init__.py" (
        echo [ovui-widgets-ovstage-physx-win] Ignoring OVSTAGE_ROOT without ovstage Python package: %OVSTAGE_ROOT%
        echo [ovui-widgets-ovstage-physx-win] Using sibling ovstage checkout: %DEFAULT_OVSTAGE_ROOT%
        set "OVSTAGE_ROOT=%DEFAULT_OVSTAGE_ROOT%"
        set "OVSTAGE_BUILD_DIR="
    )
)
if not defined OVRTX_BIN_DIR set "OVRTX_BIN_DIR=%OVRTX_ROOT%\bin"
if not defined OVSTAGE_BUILD_DIR set "OVSTAGE_BUILD_DIR=%OVSTAGE_ROOT%\_build\windows-x86_64\release"

if not exist "%OVUI_WIDGETS_ROOT%\_venv312\Scripts\python.exe" (
    echo [ovui-widgets-ovstage-physx-win] Missing venv: %OVUI_WIDGETS_ROOT%\_venv312
    exit /b 1
)

if not exist "%USD_INSTALL_ROOT%\lib\python" (
    echo [ovui-widgets-ovstage-physx-win] Missing USD install: %USD_INSTALL_ROOT%
    exit /b 1
)

if not exist "%OVRTX_BIN_DIR%\ovrtx-dynamic.dll" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovrtx runtime: %OVRTX_BIN_DIR%\ovrtx-dynamic.dll
    exit /b 1
)

if not exist "%OVSTAGE_BUILD_DIR%\ovstage.dll" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovstage.dll: %OVSTAGE_BUILD_DIR%\ovstage.dll
    exit /b 1
)

if not exist "%OVSTAGE_BUILD_DIR%\ovpopulation.dll" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovpopulation.dll: %OVSTAGE_BUILD_DIR%\ovpopulation.dll
    exit /b 1
)

if not exist "%OVSTAGE_BUILD_DIR%\ovhierarchy.dll" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovhierarchy.dll: %OVSTAGE_BUILD_DIR%\ovhierarchy.dll
    exit /b 1
)

if not exist "%OVSTAGE_ROOT%\src\ovstage\python\ovstage\__init__.py" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovstage Python package: %OVSTAGE_ROOT%\src\ovstage\python\ovstage
    exit /b 1
)

if not exist "%OVSTAGE_ROOT%\src\ovpopulation\python\ovpopulation\__init__.py" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovpopulation Python package: %OVSTAGE_ROOT%\src\ovpopulation\python\ovpopulation
    exit /b 1
)

if not exist "%OVSTAGE_ROOT%\src\ovhierarchy\python\ovhierarchy\__init__.py" (
    echo [ovui-widgets-ovstage-physx-win] Missing ovhierarchy Python package: %OVSTAGE_ROOT%\src\ovhierarchy\python\ovhierarchy
    exit /b 1
)

set "OVUI_DATA_ADAPTER_PROVIDER=ovstage"
set "OVUI_WIDGETS_REQUIRE_OVRTX=1"
set "OVRTX_SKIP_USD_CHECK=1"
set "OVPHYSX_COEXIST_DIAGNOSTICS=1"
if not defined OVGEAR_ZERO_COPY set "OVGEAR_ZERO_COPY=1"
if not defined OVSTAGE_RETENTION_WINDOW set "OVSTAGE_RETENTION_WINDOW=512"

set "OVSTAGE_LIBRARY_PATH=%OVSTAGE_BUILD_DIR%"
set "OVPOPULATION_LIBRARY_PATH=%OVSTAGE_BUILD_DIR%"
set "OVHIERARCHY_LIBRARY_PATH=%OVSTAGE_BUILD_DIR%"

set "OVUIINSPECT_ENABLE_EXECUTE=1"
if not defined OVUIINSPECT_PORT set "OVUIINSPECT_PORT=9910"

set "OVSTAGE_PYTHONPATH=%OVSTAGE_ROOT%\src\ovstage\python;%OVSTAGE_ROOT%\src\ovpopulation\python;%OVSTAGE_ROOT%\src\ovhierarchy\python"
set "PYTHONPATH=%OVUI_ROOT%\skills\omniverse-ui-inspector;%OVRTX_ROOT%\python;%USD_INSTALL_ROOT%\lib\python;%OVSTAGE_PYTHONPATH%;%PYTHONPATH%"
set "PATH=%OVRTX_BIN_DIR%;%OVSTAGE_BUILD_DIR%;%USD_INSTALL_ROOT%\lib;%USD_INSTALL_ROOT%\bin;%PATH%"

"%OVUI_WIDGETS_ROOT%\_venv312\Scripts\python.exe" -c "import importlib, sys; [importlib.import_module(m) for m in ('ovstage', 'ovpopulation', 'ovhierarchy')]; from ovui_data_adapters.common import discover_adapter_modules; registry = discover_adapter_modules(); names = [p.name for p in registry.available_adapters()]; print('[ovui-widgets-ovstage-physx-win] adapters: ' + (', '.join(names) or 'none')); ok = 'ovstage' in names; [print('[ovui-widgets-ovstage-physx-win] adapter load failure: ' + str(getattr(f, 'name', '?')) + ': ' + str(getattr(f, 'message', f))) for f in getattr(registry, 'load_failures', ()) if not ok]; sys.exit(0 if ok else 2)"
if errorlevel 1 (
    echo [ovui-widgets-ovstage-physx-win] ovstage adapter preflight failed.
    echo [ovui-widgets-ovstage-physx-win] OVSTAGE_ROOT=%OVSTAGE_ROOT%
    echo [ovui-widgets-ovstage-physx-win] OVSTAGE_BUILD_DIR=%OVSTAGE_BUILD_DIR%
    exit /b 1
)

if "%~1"=="" (
    echo [ovui-widgets-ovstage-physx-win] Opening default falling-cube demo: %OVUI_ROOT%\ovui-data-adapters\tests\data\ovstage_falling_cube_scene.usda
    call "%OVUI_WIDGETS_ROOT%\scripts\ovui-widgets-win.bat" "%OVUI_ROOT%\ovui-data-adapters\tests\data\ovstage_falling_cube_scene.usda"
) else (
    call "%OVUI_WIDGETS_ROOT%\scripts\ovui-widgets-win.bat" %*
)

exit /b %ERRORLEVEL%

:usage
echo Usage:
echo   %~nx0 [path\to\scene.usda]
echo.
echo Without a scene path, opens:
echo   %OVUI_ROOT%\ovui-data-adapters\tests\data\ovstage_falling_cube_scene.usda
echo.
echo Environment variables override sibling-directory defaults:
echo   USD_INSTALL_ROOT
echo   OVRTX_ROOT
echo   OVSTAGE_ROOT
echo.
echo Optional environment variables:
echo   OVRTX_BIN_DIR
echo   OVSTAGE_BUILD_DIR
exit /b 0
