# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Spawn-safe IO fault injection without importing pytest-bdd scenario setup."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event
from typing import IO, Any

from src.backend.io.worker import run_io_loop
from src.backend.models import BleLogSource

from tests.helpers import BytesReader, build_frame, xor_checksum


def shutdown_frames() -> tuple[bytes, ...]:
    return tuple(build_frame(b"\0\0\0\0log", int(BleLogSource.LL_TASK), sn, xor_checksum) for sn in range(2))


def run_stalled_io(
    transport_config: Any,
    writer_config: Any,
    parse_queue: Any,
    raw_stats_queue: Any,
    ui_queue: Any,
    stop_requested: Any,
    *,
    blocked: Any,
    release: Any,
    stage: str,
    **kwargs: Any,
) -> None:
    """Run the production IO loop with a byte reader and a releasable read/write/sync stall."""
    first_written = Event()
    frames = shutdown_frames()

    class Reader(BytesReader):
        def read(self, size: int | None = None) -> bytes:
            if self.rx_chunks == 1:
                assert first_written.wait(10), "first raw write did not complete"
                if stage == "read":
                    blocked.set()
                    release.wait()
            return super().read(size)

    class File:
        def __init__(self, path: Path) -> None:
            self.file = path.open("wb")
            self.writes = 0

        def write(self, data: bytes) -> int:
            self.writes += 1
            if stage == "write" and self.writes == 2:
                blocked.set()
                release.wait()
            count = self.file.write(data)
            # Make the first prefix readable before the injected stall.
            self.file.flush()
            first_written.set()
            return count

        def flush(self) -> None:
            self.file.flush()

        def fileno(self) -> int:
            return self.file.fileno()

        def close(self) -> None:
            self.file.close()

    def factory(path: Path) -> IO[bytes]:
        return File(path)  # type: ignore[return-value]

    original_sync = os.fsync

    def sync(fd: int) -> None:
        blocked.set()
        release.wait()
        original_sync(fd)

    if stage == "fsync":
        os.fsync = sync
    try:
        run_io_loop(
            Reader(b"".join(frames), stop_requested, block_size=len(frames[0])),
            writer_config,
            parse_queue,
            raw_stats_queue,
            ui_queue,
            stop_requested,
            writer_file_factory=factory,
            **kwargs,
        )
    finally:
        os.fsync = original_sync
