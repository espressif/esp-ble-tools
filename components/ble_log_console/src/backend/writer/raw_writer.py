# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""RawWriterProcess entrypoints for capture pipelines."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from typing import Any
from typing import Callable
from typing import IO

CAPTURE_PART_MAX_BYTES = 200 * 1024 * 1024
FLUSH_INTERVAL_SEC = 1.0
RAW_FILE_BUFFER_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RawWriterConfig:
    """Configuration for raw binary capture output."""

    base_path: Path
    part_max_bytes: int = CAPTURE_PART_MAX_BYTES
    flush_interval_sec: float = FLUSH_INTERVAL_SEC


@dataclass(frozen=True)
class RawWriterStatus:
    """Status emitted by the raw writer."""

    base_path: Path
    paths: tuple[Path, ...]
    bytes_written: int
    chunks_written: int
    current_part: int
    finalized: bool
    last_error: str | None = None


@dataclass(frozen=True)
class RawWriterProcessEvent:
    """Status or error emitted by the raw writer loop."""

    kind: str
    message: str = ''
    status: RawWriterStatus | None = None


FileFactory = Callable[[Path], IO[bytes]]
Clock = Callable[[], float]


def capture_part_path(base_path: Path, part_index: int) -> Path:
    """Return the raw capture part path matching the legacy app naming."""

    if part_index <= 1:
        return base_path
    return base_path.with_name(f'{base_path.stem}_part{part_index:03d}{base_path.suffix}')


def _default_file_factory(path: Path) -> IO[bytes]:
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, 'wb', buffering=RAW_FILE_BUFFER_BYTES)  # noqa: SIM115


def _flush_and_close_file(file_obj: IO[bytes]) -> None:
    try:
        file_obj.flush()
        try:
            os.fsync(file_obj.fileno())
        except OSError:
            pass
    finally:
        file_obj.close()


def _put_event(event_queue: Any, event: RawWriterProcessEvent) -> None:
    if event_queue is not None:
        event_queue.put(event)


class RawWriter:
    """Write raw byte chunks to rotated capture files without dropping chunks."""

    def __init__(
        self,
        config: RawWriterConfig,
        *,
        clock: Clock = time.monotonic,
        file_factory: FileFactory = _default_file_factory,
    ) -> None:
        self._config = config
        self._clock = clock
        self._file_factory = file_factory
        self._file: IO[bytes] | None = None
        self._paths: list[Path] = []
        self._bytes_written = 0
        self._chunks_written = 0
        self._current_part = 1
        self._current_part_bytes = 0
        self._last_flush_at = self._clock()
        self._finalized = False
        self._last_error: str | None = None

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self._paths)

    def status(self) -> RawWriterStatus:
        return RawWriterStatus(
            base_path=self._config.base_path,
            paths=tuple(self._paths),
            bytes_written=self._bytes_written,
            chunks_written=self._chunks_written,
            current_part=self._current_part,
            finalized=self._finalized,
            last_error=self._last_error,
        )

    def write(self, block: bytes) -> None:
        if self._finalized:
            raise RuntimeError('raw writer is already finalized')
        if not block:
            return

        try:
            self._ensure_open()
            self._rotate_if_needed()
            if self._file is None:
                raise RuntimeError('raw writer failed to open output file')
            self._file.write(block)
            self._bytes_written += len(block)
            self._chunks_written += 1
            self._current_part_bytes += len(block)
            self._flush_if_due()
        except Exception as e:
            self._last_error = str(e)
            raise

    def finalize(self) -> None:
        if self._finalized:
            return
        try:
            if self._file is not None:
                _flush_and_close_file(self._file)
        except Exception as e:
            self._last_error = str(e)
            raise
        finally:
            self._file = None
            self._finalized = True

    def _ensure_open(self) -> None:
        if self._file is not None:
            return
        path = capture_part_path(self._config.base_path, self._current_part)
        self._file = self._file_factory(path)
        self._paths.append(path)
        self._last_flush_at = self._clock()

    def _rotate_if_needed(self) -> None:
        if self._file is None:
            return
        if self._current_part_bytes < self._config.part_max_bytes:
            return
        _flush_and_close_file(self._file)
        self._current_part += 1
        self._current_part_bytes = 0
        path = capture_part_path(self._config.base_path, self._current_part)
        self._file = self._file_factory(path)
        self._paths.append(path)
        self._last_flush_at = self._clock()

    def _flush_if_due(self) -> None:
        if self._file is None:
            return
        now = self._clock()
        if now - self._last_flush_at < self._config.flush_interval_sec:
            return
        self._file.flush()
        self._last_flush_at = now


def run_raw_writer_loop(
    config: RawWriterConfig,
    raw_queue: Any,
    event_queue: Any,
    *,
    clock: Clock = time.monotonic,
    file_factory: FileFactory = _default_file_factory,
) -> None:
    """Write raw chunks from raw_queue until a None sentinel is received."""

    writer = RawWriter(config, clock=clock, file_factory=file_factory)
    try:
        while True:
            item = raw_queue.get()
            if item is None:
                break
            old_paths = writer.paths
            writer.write(item)
            if len(writer.paths) > len(old_paths):
                kind = 'opened' if not old_paths else 'rotated'
                _put_event(
                    event_queue,
                    RawWriterProcessEvent(
                        kind=kind,
                        message=str(writer.paths[-1]),
                        status=writer.status(),
                    ),
                )
        writer.finalize()
        _put_event(event_queue, RawWriterProcessEvent(kind='finalized', status=writer.status()))
    except Exception as e:
        _put_event(event_queue, RawWriterProcessEvent(kind='error', message=str(e), status=writer.status()))
        try:
            writer.finalize()
        except Exception as close_error:
            _put_event(
                event_queue,
                RawWriterProcessEvent(
                    kind='error',
                    message=f'close failed: {close_error}',
                    status=writer.status(),
                ),
            )


def run_raw_writer_process(config: RawWriterConfig, raw_queue: Any, event_queue: Any) -> None:
    """Process entrypoint for raw writer."""

    run_raw_writer_loop(config, raw_queue, event_queue)


def drain_raw_writer_events(event_queue: Any) -> list[RawWriterProcessEvent]:
    """Drain currently available raw writer events."""

    events: list[RawWriterProcessEvent] = []
    while True:
        try:
            events.append(event_queue.get_nowait())
        except Empty:
            return events
