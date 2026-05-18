@echo off
REM Run the OvGear pytest suite with the Windows USD bootstrap in place.

setlocal
set REPO_ROOT=%~dp0..
if not defined USD_INSTALL_ROOT set USD_INSTALL_ROOT=C:\dev\usd-build\install
set OVRTX_SKIP_USD_CHECK=1
set PYTHONPATH=%USD_INSTALL_ROOT%\lib\python;%PYTHONPATH%
REM The USD DLL dirs are registered by scripts/_winusd_sitecustomize.py
set PYTHONSTARTUP=
set OVGEAR_USD_DIR=%USD_INSTALL_ROOT%

"%REPO_ROOT%\_venv312\Scripts\python.exe" -c "import os; os.add_dll_directory(r'%USD_INSTALL_ROOT%\lib'); os.add_dll_directory(r'%USD_INSTALL_ROOT%\bin'); import pytest, sys; sys.exit(pytest.main(sys.argv[1:]))" tests %*
exit /b %errorlevel%
