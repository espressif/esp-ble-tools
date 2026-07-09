# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Writer loop entrypoints for capture pipelines."""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import IO

CAPTURE_PART_MAX_BYTES = 200 * 1024 * 1024
FLUSH_INTERVAL_SEC = 1.0
RAW_FILE_BUFFER_BYTES = 4 * 1024 * 1024
WRITER_QUEUE_BLOCKS = 4096
WRITER_BATCH_BYTES = 512 * 1024
WRITER_BATCH_TIMEOUT_SEC = 0.005


@dataclass(frozen=True)
class WriterConfig:
    """Configuration for raw binary capture output."""

    base_path: Path
    part_max_bytes: int = CAPTURE_PART_MAX_BYTES
    flush_interval_sec: float = FLUSH_INTERVAL_SEC


@dataclass(frozen=True)
class WriterStatus:
    """Status emitted by the writer."""

    base_path: Path
    paths: tuple[Path, ...]
    bytes_written: int
    chunks_written: int
    current_part: int
    finalized: bool
    last_error: str | None = None


@dataclass(frozen=True)
class WriterEvent:
    """Status or error emitted by the writer loop."""

    kind: str
    message: str = ''
    status: WriterStatus | None = None


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


def _put_event(ui_queue: Any, event: WriterEvent) -> None:
    if ui_queue is not None:
        ui_queue.put(event)


def _put_path_events(ui_queue: Any, old_paths: tuple[Path, ...], writer: Any) -> None:
    new_paths = writer.paths[len(old_paths) :]
    for index, path in enumerate(new_paths):
        kind = 'opened' if not old_paths and index == 0 else 'rotated'
        _put_event(
            ui_queue,
            WriterEvent(
                kind=kind,
                message=str(path),
                status=writer.status(),
            ),
        )


class Writer:
    """Write raw byte chunks to rotated capture files without dropping chunks."""

    emits_events = False

    def __init__(
        self,
        config: WriterConfig,
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

    def status(self) -> WriterStatus:
        return WriterStatus(
            base_path=self._config.base_path,
            paths=tuple(self._paths),
            bytes_written=self._bytes_written,
            chunks_written=self._chunks_written,
            current_part=self._current_part,
            finalized=self._finalized,
            last_error=self._last_error,
        )

    def write(self, block: bytes, *, timeout: float | None = None) -> None:
        del timeout
        if self._finalized:
            raise RuntimeError('writer is already finalized')
        if not block:
            return

        try:
            self._ensure_open()
            offset = 0
            block_size = len(block)
            while offset < block_size:
                self._rotate_if_needed()
                if self._file is None:
                    raise RuntimeError('writer failed to open output file')

                if self._config.part_max_bytes > 0:
                    part_remaining = self._config.part_max_bytes - self._current_part_bytes
                    if part_remaining <= 0:
                        continue
                    write_size = min(block_size - offset, part_remaining)
                else:
                    write_size = block_size - offset

                self._file.write(block[offset : offset + write_size])
                self._bytes_written += write_size
                self._current_part_bytes += write_size
                offset += write_size

            self._chunks_written += 1
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


class AsyncBatchWriter:
    """Decouple transport reading from file writes with a bounded thread queue."""

    emits_events = True

    def __init__(
        self,
        config: WriterConfig,
        ui_queue: Any,
        *,
        queue_max_blocks: int = WRITER_QUEUE_BLOCKS,
        batch_max_bytes: int = WRITER_BATCH_BYTES,
        batch_timeout_sec: float = WRITER_BATCH_TIMEOUT_SEC,
        clock: Clock = time.monotonic,
        file_factory: FileFactory = _default_file_factory,
    ) -> None:
        self._writer = Writer(config, clock=clock, file_factory=file_factory)
        self._ui_queue = ui_queue
        self._queue_max_blocks = queue_max_blocks
        self._batch_max_bytes = batch_max_bytes
        self._batch_timeout_sec = batch_timeout_sec
        self._closed = False
        self._started = False
        self._error: BaseException | None = None
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=self._queue_max_blocks)
        self._thread = threading.Thread(name='ble-log-writer-thread', target=self._run_writer)

    @property
    def paths(self) -> tuple[Path, ...]:
        return self._writer.paths

    def status(self) -> WriterStatus:
        status = self._writer.status()
        if self._error is None or status.last_error:
            return status
        return WriterStatus(
            base_path=status.base_path,
            paths=status.paths,
            bytes_written=status.bytes_written,
            chunks_written=status.chunks_written,
            current_part=status.current_part,
            finalized=status.finalized,
            last_error=str(self._error),
        )

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def write(self, block: bytes, *, timeout: float | None = None) -> None:
        """Queue one raw block for background file writing.

        The block is never silently dropped. If the bounded writer queue cannot
        accept it before ``timeout``, the caller gets a clear backpressure error.
        """

        if not block:
            return
        if not self._started:
            raise RuntimeError('async writer is not started')

        self._raise_if_unavailable()
        try:
            self._queue.put(block, timeout=timeout)
        except queue.Full as e:
            raise TimeoutError('writer queue full; disk writer is not keeping up') from e
        self._raise_if_unavailable()

    def finalize(self) -> None:
        if not self._started:
            self._writer.finalize()
            _put_event(self._ui_queue, WriterEvent(kind='finalized', status=self.status()))
            return
        self._closed = True
        while self._thread.is_alive():
            try:
                self._queue.put(None, timeout=0.1)
                break
            except queue.Full:
                if self._error is not None:
                    break
        self._thread.join()

    def _raise_if_unavailable(self) -> None:
        if self._error is not None:
            raise RuntimeError(str(self._error))
        if self._closed:
            raise RuntimeError('writer is already finalized')

    def _pop_batch(self) -> tuple[list[bytes], bool]:
        first = self._queue.get()
        if first is None:
            return [], True

        batch: list[bytes] = []
        batch.append(first)
        batch_bytes = len(first)
        saw_sentinel = False
        deadline = time.monotonic() + self._batch_timeout_sec
        while batch_bytes < self._batch_max_bytes:
            if self._batch_timeout_sec <= 0:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break

            if item is None:
                saw_sentinel = True
                break
            batch.append(item)
            batch_bytes += len(item)

        return batch, saw_sentinel

    def _set_error(self, error: BaseException) -> None:
        self._error = error

    def _run_writer(self) -> None:
        failed = False
        try:
            while True:
                batch, saw_sentinel = self._pop_batch()
                if not batch:
                    if saw_sentinel:
                        break
                    continue

                block = batch[0] if len(batch) == 1 else b''.join(batch)
                old_paths = self._writer.paths
                self._writer.write(block)
                _put_path_events(self._ui_queue, old_paths, self)
                if saw_sentinel:
                    break
        except Exception as e:
            failed = True
            self._set_error(e)
            _put_event(self._ui_queue, WriterEvent(kind='error', message=str(e), status=self.status()))
        finally:
            try:
                self._writer.finalize()
                if not failed:
                    _put_event(self._ui_queue, WriterEvent(kind='finalized', status=self.status()))
            except Exception as close_error:
                self._set_error(close_error)
                _put_event(
                    self._ui_queue,
                    WriterEvent(
                        kind='error',
                        message=f'close failed: {close_error}',
                        status=self.status(),
                    ),
                )
