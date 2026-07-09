#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "BLE Log Console environment is not installed." >&2
    echo "Run ./install.sh first, then run ./run.sh again." >&2
    exit 1
fi

if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "BLE Log Console dependencies are not installed." >&2
    echo "Run ./install.sh first, then run ./run.sh again." >&2
    exit 1
fi

exec uv run --no-sync python console.py "$@"
