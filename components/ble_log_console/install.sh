#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

UV_INSTALL_URL="${BLE_LOG_CONSOLE_UV_INSTALL_URL:-https://astral.sh/uv/install.sh}"
PIP_INDEX_ARGS="${BLE_LOG_CONSOLE_PIP_INDEX_ARGS:-}"
UV_SYNC_ARGS="${BLE_LOG_CONSOLE_UV_SYNC_ARGS:-}"
METHOD="auto"
SYNC=1

usage() {
    cat <<EOF
Install BLE Log Console runtime environment.

Usage:
  ./install.sh [--auto|--pip|--script] [--no-sync] [--help]

What this does:
  1. Ensures the project environment manager is available.
  2. Creates/updates .venv for BLE Log Console.
  3. Installs runtime and build dependencies up front, so run.sh starts quickly.

Methods:
  --auto     Try Python pip first, then the standalone install script. Default.
  --pip      Install the environment manager with python3 -m pip install --user uv.
  --script   Install the environment manager with curl -LsSf URL | sh.
  --no-sync  Only install/check the environment manager; do not install project deps.

Environment:
  BLE_LOG_CONSOLE_PIP_INDEX_ARGS   Extra pip args, e.g. "-i https://pypi.example.com/simple"
  BLE_LOG_CONSOLE_UV_INSTALL_URL   Standalone installer URL. Default: https://astral.sh/uv/install.sh
  BLE_LOG_CONSOLE_UV_SYNC_ARGS     Extra uv sync args, e.g. "--index-url https://pypi.example.com/simple"

Manual fallback:
  Put a uv/uv.exe binary in PATH, then run ./install.sh again.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --auto|--pip|--script)
            METHOD="${1#--}"
            ;;
        --no-sync)
            SYNC=0
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

install_with_pip() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 not found; cannot use the pip install method." >&2
        return 1
    fi

    echo "Installing environment manager with Python pip ..."
    # shellcheck disable=SC2086
    python3 -m pip install --user uv $PIP_INDEX_ARGS
}

install_with_script() {
    if ! command -v curl >/dev/null 2>&1; then
        echo "curl not found; cannot use the standalone install method." >&2
        return 1
    fi

    echo "Installing environment manager from $UV_INSTALL_URL ..."
    curl -LsSf "$UV_INSTALL_URL" | sh
}

if ! command -v uv >/dev/null 2>&1; then
    case "$METHOD" in
        pip)
            install_with_pip
            ;;
        script)
            install_with_script
            ;;
        auto)
            install_with_pip || install_with_script
            ;;
    esac
fi

export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: Environment manager was not found after installation." >&2
    echo "Try opening a new terminal, or add ~/.local/bin to PATH:" >&2
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2
    exit 1
fi

if [ "$SYNC" -eq 0 ]; then
    echo "Environment manager ready: $(command -v uv)"
    uv --version
    exit 0
fi

echo "Installing BLE Log Console dependencies ..."
# shellcheck disable=SC2086
uv sync --all-extras $UV_SYNC_ARGS

echo ""
echo "BLE Log Console environment is ready."
echo "Run it with: ./run.sh"
