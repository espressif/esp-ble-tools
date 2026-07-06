@echo off
rem SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
rem SPDX-License-Identifier: Apache-2.0

setlocal
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"

if "%~1"=="--help" goto :usage
if "%~1"=="-h" goto :usage

where uv > nul 2>&1
if %errorlevel% neq 0 (
    echo Installing environment manager with Python pip ...
    py -3 -m pip install --user uv
    if %errorlevel% neq 0 (
        echo.
        echo ERROR: Failed to prepare the environment manager with pip.
        echo Try one of these alternatives, then run install.bat again:
        echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
        echo   copy uv.exe into a PATH directory
        exit /b 1
    )
)

where uv > nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Environment manager was installed, but it is not on PATH.
    echo Open a new terminal and run install.bat again.
    exit /b 1
)

echo Installing BLE Log Console dependencies ...
uv sync --all-extras
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo BLE Log Console environment is ready.
echo Run it with: run.bat
exit /b 0

:usage
echo Install BLE Log Console runtime environment.
echo.
echo Usage:
echo   install.bat
echo.
echo This creates/updates .venv and installs runtime/build dependencies up front.
exit /b 0
