@echo off
rem SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
rem SPDX-License-Identifier: Apache-2.0

setlocal
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"

call :find_uv
if %errorlevel% neq 0 (
    echo BLE Log Console environment is not installed.
    echo Run install.bat first, then run run.bat again.
    exit /b 1
)

if not exist "%SCRIPT_DIR%\.venv" (
    echo BLE Log Console dependencies are not installed.
    echo Run install.bat first, then run run.bat again.
    exit /b 1
)

uv run --no-sync python console.py %*
exit /b %errorlevel%

:find_uv
where uv > nul 2>&1
if %errorlevel% equ 0 exit /b 0
if defined USERPROFILE if exist "%USERPROFILE%\.local\bin" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if defined APPDATA (
    for /d %%D in ("%APPDATA%\Python\Python*\Scripts") do (
        if exist "%%~fD" set "PATH=%%~fD;%PATH%"
    )
)
where uv > nul 2>&1
if %errorlevel% equ 0 exit /b 0
exit /b 1
