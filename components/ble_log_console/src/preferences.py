# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Remember the recording directory in the current user's application settings."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from click import get_app_dir


def load_log_dir() -> Path | None:
    try:
        value = (Path(get_app_dir("ble_log_console")) / "last_log_dir.txt").read_text(encoding="utf-8")
        if value and "\x00" not in value and Path(value).is_absolute():
            return Path(value)
    except (OSError, ValueError):
        pass
    return None


def save_log_dir(directory: Path) -> None:
    temporary = None
    try:
        value = str(directory.absolute())
        settings = Path(get_app_dir("ble_log_console")) / "last_log_dir.txt"
        settings.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=settings.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(value)
        temporary.replace(settings)
    except (OSError, ValueError):
        # Preferences must never prevent recording; replacement preserves the previous value on failure.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
