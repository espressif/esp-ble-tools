@echo off
rem SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
rem SPDX-License-Identifier: Apache-2.0

setlocal
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"

set "SYNC=1"

:parse_args
if "%~1"=="" goto :main
if "%~1"=="--help" goto :usage
if "%~1"=="-h" goto :usage
if "%~1"=="--no-sync" (
    set "SYNC=0"
    shift
    goto :parse_args
)
echo ERROR: Unknown option: %~1
goto :usage_error

:main
call :ensure_uv
if %errorlevel% neq 0 exit /b %errorlevel%

if "%SYNC%"=="0" (
    echo Environment manager ready:
    uv --version
    exit /b %errorlevel%
)

echo Installing BLE Log Console dependencies ...
uv sync --all-extras %BLE_LOG_CONSOLE_UV_SYNC_ARGS%
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install BLE Log Console dependencies.
    echo Check network access to the Python package index, or set BLE_LOG_CONSOLE_UV_SYNC_ARGS.
    exit /b %errorlevel%
)

echo.
echo BLE Log Console environment is ready.
echo Run it with: run.bat
exit /b 0

:ensure_uv
call :add_common_uv_paths
where uv > nul 2>&1
if %errorlevel% equ 0 exit /b 0

call :find_python
if %errorlevel% neq 0 (
    echo ERROR: Python was not found, and uv is not available on PATH.
    echo Install Python 3.11 or later, or put uv.exe in PATH, then run install.bat again.
    echo.
    echo Alternative uv install methods:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo   copy uv.exe into %%USERPROFILE%%\.local\bin or another PATH directory
    exit /b 1
)

echo Installing environment manager with Python pip ...
%PY_CMD% -m pip install --user uv %BLE_LOG_CONSOLE_PIP_INDEX_ARGS%
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to prepare the environment manager with pip.
    echo Check Python, pip, network/proxy settings, or set BLE_LOG_CONSOLE_PIP_INDEX_ARGS.
    echo.
    echo Alternative uv install methods:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo   copy uv.exe into %%USERPROFILE%%\.local\bin or another PATH directory
    exit /b 1
)

call :add_python_user_scripts
call :add_common_uv_paths
where uv > nul 2>&1
if %errorlevel% equ 0 exit /b 0

echo.
echo ERROR: uv was installed, but uv.exe was not found on PATH.
echo This usually means Python's user Scripts directory is not in PATH.
echo The installer tried to add it for this session, but could not find uv.exe.
echo.
echo Try opening a new terminal, or add this directory to PATH:
if defined PY_USER_SCRIPTS echo   %PY_USER_SCRIPTS%
echo.
echo You can also run uv by absolute path if it exists there, then rerun install.bat.
exit /b 1

:find_python
set "PY_CMD="
py -3 -c "import sys" > nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py -3"
    exit /b 0
)
python -c "import sys" > nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
    exit /b 0
)
python3 -c "import sys" > nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python3"
    exit /b 0
)
exit /b 1

:add_python_user_scripts
if not defined PY_CMD exit /b 0
for /f "delims=" %%D in ('%PY_CMD% -c "import os, site; print(os.path.join(site.USER_BASE, 'Scripts'))" 2^>nul') do (
    set "PY_USER_SCRIPTS=%%D"
    if exist "%%D" set "PATH=%%D;%PATH%"
)
exit /b 0

:add_common_uv_paths
if defined USERPROFILE if exist "%USERPROFILE%\.local\bin" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if defined APPDATA (
    for /d %%D in ("%APPDATA%\Python\Python*\Scripts") do (
        if exist "%%~fD" set "PATH=%%~fD;%PATH%"
    )
)
exit /b 0

:usage
echo Install BLE Log Console runtime environment.
echo.
echo Usage:
echo   install.bat [--no-sync] [--help]
echo.
echo This creates/updates .venv and installs runtime/build dependencies up front.
echo.
echo Environment:
echo   BLE_LOG_CONSOLE_PIP_INDEX_ARGS   Extra pip args, e.g. -i https://pypi.example.com/simple
echo   BLE_LOG_CONSOLE_UV_SYNC_ARGS     Extra uv sync args, e.g. --index-url https://pypi.example.com/simple
echo.
exit /b 0

:usage_error
call :usage
exit /b 2
