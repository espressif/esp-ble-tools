# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Copy a suffix from finalized raw files after recording has stopped."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO

from src.backend.io.writer import RAW_FILE_BUFFER_BYTES, Writer, WriterConfig


@dataclass(frozen=True)
class AnalysisCopyResult:
    paths: tuple[Path, ...] = ()
    bytes_written: int = 0
    error: str | None = None


def copy_recording_suffix(
    config: WriterConfig, raw_paths: tuple[Path, ...], *, offset: int, raw_bytes: int
) -> AnalysisCopyResult:
    """Copy from saved raw parts, never from the lossy analysis queue.

    Partial files are not published until all parts are synced. A cancelled
    analysis process can leave .partial files; the original remains untouched.
    """
    owned: list[Path] = []
    published: list[Path] = []

    def open_part(path: Path) -> IO[bytes]:
        if path.exists():
            raise FileExistsError(f"Analysis output already exists: {path}")
        partial = path.with_name(path.name + ".partial")
        handle = partial.open("xb", buffering=RAW_FILE_BUFFER_BYTES)
        owned.append(partial)
        return handle

    base = config.base_path.with_name(f"{config.base_path.stem}_analysis{config.base_path.suffix}")
    writer = Writer(replace(config, base_path=base), file_factory=open_part)
    try:
        if not raw_paths or not 0 < offset < raw_bytes:
            raise ValueError("Invalid raw recording suffix")
        skip, source_bytes = offset, 0
        for path in raw_paths:
            with path.open("rb") as source:
                size = os.fstat(source.fileno()).st_size
                source_bytes += size
                prefix = min(skip, size)
                source.seek(prefix)
                skip -= prefix
                while block := source.read(1024 * 1024):
                    writer.write(block)
        writer.finalize()
        if source_bytes != raw_bytes or writer.status().bytes_written != raw_bytes - offset:
            raise OSError("Saved raw files do not match the recorded byte count")
        for path in writer.paths:
            # Publish without replacing existing files. Unsupported filesystems
            # fall back to the original recording with an explicit copy error.
            os.link(path.with_name(path.name + ".partial"), path)
            published.append(path)
        return AnalysisCopyResult(tuple(published), raw_bytes - offset)
    except Exception as error:
        for path in published:
            with contextlib.suppress(OSError):
                path.unlink()
        return AnalysisCopyResult(error=str(error))
    finally:
        with contextlib.suppress(OSError):
            writer.finalize()
        for path in owned:
            with contextlib.suppress(OSError):
                path.unlink()
