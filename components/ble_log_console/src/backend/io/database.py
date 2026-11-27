# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Save the selected firmware dictionaries alongside a recording."""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory


def save_database_copy(source: Path, recording: Path) -> Path:
    destination = recording.with_name(f"{recording.stem}_database")
    with TemporaryDirectory(prefix=".ble-database-", dir=recording.parent) as temporary:
        staged = Path(temporary) / "database"
        staged.mkdir(mode=0o700)
        # Discovery also accepts the working directory, which can contain unrelated project files.
        for path in source.iterdir():
            if path.name.endswith("_logs.json") and path.is_file():
                shutil.copyfile(path, staged / path.name)
        if not (staged / "BLE_HOST_logs.json").is_file():
            raise FileNotFoundError(source / "BLE_HOST_logs.json")
        if destination.exists():
            raise FileExistsError(destination)
        staged.rename(destination)
    return destination
