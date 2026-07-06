#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CALLER_DIR="$(pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1 || [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "BLE Log Console build environment is not installed." >&2
    echo "Run ./install.sh first, then run ./build.sh again." >&2
    exit 1
fi

echo "Building executable ..."
uv run --no-sync python build_exe.py "$@"

if [ ! -f "dist/artifact_name.txt" ]; then
    echo "ERROR: Build produced no artifact metadata." >&2
    exit 1
fi

EXE_NAME="$(cat "dist/artifact_name.txt")"
if [ -f "dist/$EXE_NAME" ]; then
    mv "dist/$EXE_NAME" "$CALLER_DIR/$EXE_NAME"
    echo ""
    echo "Executable ready: $CALLER_DIR/$EXE_NAME"
else
    echo "ERROR: Build produced no executable." >&2
    exit 1
fi

rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist" "$SCRIPT_DIR"/*.spec
cd "$CALLER_DIR"
