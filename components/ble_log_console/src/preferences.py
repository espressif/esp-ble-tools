# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Remember recording paths in the current user's application settings."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from click import get_app_dir


def _load_value(name: str) -> str | None:
    try:
        value = (Path(get_app_dir("ble_log_console")) / name).read_text(encoding="utf-8")
        if "\x00" not in value and (not value or Path(value).is_absolute()):
            return value
    except (OSError, ValueError):
        pass
    return None


def load_log_dir() -> Path | None:
    value = _load_value("last_log_dir.txt")
    return Path(value) if value else None


def save_log_dir(directory: Path) -> None:
    _save_path("last_log_dir.txt", directory)


def load_log_database(*, default: Path | None = None) -> Path | None:
    value = _load_value("last_log_database.txt")
    if value == "":
        return None
    if value is not None:
        path = Path(value)
        try:
            if (path / "BLE_HOST_logs.json").is_file():
                return path
        except OSError:
            pass
    return default


def save_log_database(directory: Path | None) -> None:
    _save_path("last_log_database.txt", directory)


def _save_path(name: str, directory: Path | None) -> None:
    temporary = None
    try:
        value = str(directory.absolute()) if directory is not None else ""
        settings = Path(get_app_dir("ble_log_console")) / name
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
