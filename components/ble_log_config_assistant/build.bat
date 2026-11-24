@echo off
rem SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
rem SPDX-License-Identifier: Apache-2.0
setlocal
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv ".venv" || goto :failed
)
set "PYTHON=.venv\Scripts\python.exe"
"%PYTHON%" -m pip install -e ".[build,test]" || goto :failed
"%PYTHON%" -m pytest -q || goto :failed
"%PYTHON%" build.py || goto :failed
popd
exit /b 0

:failed
popd
exit /b 1
