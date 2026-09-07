@echo off
rem SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
rem SPDX-License-Identifier: Apache-2.0

setlocal
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "CALLER_DIR=%CD%"
cd /d "%SCRIPT_DIR%"

call :find_uv
if %errorlevel% neq 0 (
    echo BLE Log Console build environment is not installed.
    echo Run install.bat first, then run build.bat again.
    exit /b 1
)

if not exist "%SCRIPT_DIR%\.venv" (
    echo BLE Log Console build dependencies are not installed.
    echo Run install.bat first, then run build.bat again.
    exit /b 1
)

echo Building executable ...
uv run python build_exe.py %*
if %errorlevel% neq 0 exit /b %errorlevel%

if not exist "dist\artifact_name.txt" (
    echo ERROR: Build produced no artifact metadata.
    exit /b 1
)

set /p EXE_NAME=<"dist\artifact_name.txt"
if not exist "dist\%EXE_NAME%" (
    echo ERROR: Build produced no executable artifact.
    exit /b 1
)

if exist "%CALLER_DIR%\%EXE_NAME%" (
    del /Q "%CALLER_DIR%\%EXE_NAME%" 2> nul
    if exist "%CALLER_DIR%\%EXE_NAME%" (
        echo ERROR: Cannot replace existing executable: %CALLER_DIR%\%EXE_NAME%
        echo Close any running BLE Log Console window and make sure the file is not locked, then rebuild.
        exit /b 1
    )
)

move /Y "dist\%EXE_NAME%" "%CALLER_DIR%\%EXE_NAME%" > nul
if %errorlevel% neq 0 (
    echo ERROR: Failed to move executable to %CALLER_DIR%\%EXE_NAME%
    echo Check directory permissions and whether antivirus software is holding the file.
    exit /b %errorlevel%
)
echo.
echo Executable ready: %CALLER_DIR%\%EXE_NAME%

rmdir /S /Q "%SCRIPT_DIR%\build" 2> nul
rmdir /S /Q "%SCRIPT_DIR%\dist" 2> nul
del /Q "%SCRIPT_DIR%\*.spec" 2> nul
cd /d "%CALLER_DIR%"
exit /b 0

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
