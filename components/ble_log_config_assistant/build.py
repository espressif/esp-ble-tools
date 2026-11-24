# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: INP001 -- standalone entry point

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).parent.resolve()
    sys.path.insert(0, str(root / "src"))
    from ble_log_config_assistant import __version__

    platform = "windows" if sys.platform == "win32" else "ubuntu"
    name = f"ble_log_config_assistant_{platform}_v{__version__}"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--collect-data",
        "textual",
        "--collect-data",
        "textual_fspicker",
        "--collect-submodules",
        "textual.drivers",
        "--name",
        name,
        "--paths",
        str(root / "src"),
    ]
    command.append(str(root / "assistant.py"))
    subprocess.run(command, cwd=root, check=True)
    executable = root / "dist" / (name + (".exe" if sys.platform == "win32" else ""))
    version = subprocess.check_output([str(executable), "--version"], text=True, timeout=30).strip()
    if version != __version__:
        raise RuntimeError(f"{executable.name} reported version {version!r}, expected {__version__}")
    print(f"Built {executable}")


if __name__ == "__main__":
    main()
