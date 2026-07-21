@echo off
REM Windows launcher for ovui-widgets. Activates _venv312, sets USD env vars,
REM and invokes the Python bootstrap that registers USD DLL directories.
REM Pass through all CLI args (e.g. a .usda path).

setlocal
set REPO_ROOT=%~dp0..
if not exist "%REPO_ROOT%\_venv312\Scripts\python.exe" (
    echo [ovui-widgets-win] _venv312 not found at %REPO_ROOT%\_venv312
    echo Create it per WINDOWS-BUILD.md and retry.
    exit /b 1
)

if not defined USD_INSTALL_ROOT set USD_INSTALL_ROOT=C:\dev\usd-build\install
if not defined OVRTX_ROOT set OVRTX_ROOT=C:\dev\ovrtx
set OVRTX_SKIP_USD_CHECK=1

"%REPO_ROOT%\_venv312\Scripts\python.exe" "%REPO_ROOT%\scripts\run_ovui_widgets_windows.py" %*
exit /b %errorlevel%
