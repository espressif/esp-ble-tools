# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Reader loop for BLE log IO pipelines."""

from __future__ import annotations

import time
from dataclasses import dataclass
from queue import Empty
from queue import Full
from typing import Any
from typing import Callable
from typing import Protocol

from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.support.transport import TransportReader
from src.backend.support.transport import TransportStatus
from src.backend.io.writer import Clock
from src.backend.io.writer import WriterEvent
from src.backend.io.writer import WriterStatus

QUEUE_PUT_TIMEOUT_SEC = 5.0
RAW_STATS_INTERVAL_SEC = 0.25
WallClockMs = Callable[[], int]


def _wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class ReaderProcessEvent:
    """Status or error emitted by the reader loop."""

    kind: str
    message: str = ''
    status: TransportStatus | None = None
    parse_dropped_chunks: int = 0
    parse_dropped_bytes: int = 0


@dataclass(frozen=True)
class ReaderCommand:
    """Command sent from the controller to the live reader."""

    kind: str


class StopSignal(Protocol):
    def is_set(self) -> bool:
        ...


class WriterSink(Protocol):
    emits_events: bool

    @property
    def paths(self) -> tuple[Any, ...]:
        ...

    def status(self) -> WriterStatus:
        ...

    def write(self, block: bytes, *, timeout: float | None = None) -> None:
        ...

    def finalize(self) -> None:
        ...


def _put_event(ui_queue: Any, event: ReaderProcessEvent | WriterEvent) -> None:
    if ui_queue is not None:
        ui_queue.put(event)


def _put_parse(parse_queue: Any, item: ReceivedChunk | None) -> bool:
    try:
        parse_queue.put(item, block=False)
    except Full:
        return False
    return True


def _put_parse_sentinel(parse_queue: Any, timeout: float) -> bool:
    try:
        parse_queue.put(None, timeout=timeout)
    except Full:
        return False
    return True


def _put_raw_stats(raw_stats_queue: Any, count: int) -> None:
    if raw_stats_queue is None or count <= 0:
        return
    try:
        raw_stats_queue.put(count, block=False)
    except Full:
        pass


def _put_raw_stats_sentinel(raw_stats_queue: Any) -> None:
    if raw_stats_queue is None:
        return
    try:
        raw_stats_queue.put(None, block=False)
    except Full:
        pass


class RawStatsBatcher:
    """Batch reliable raw byte counters before sending them to analysis."""

    def __init__(
        self,
        raw_stats_queue: Any,
        *,
        interval_sec: float = RAW_STATS_INTERVAL_SEC,
        clock: Clock = time.monotonic,
    ) -> None:
        self._raw_stats_queue = raw_stats_queue
        self._interval_sec = interval_sec
        self._clock = clock
        self._pending_bytes = 0
        self._last_emit_at = self._clock()

    def record(self, byte_count: int) -> None:
        if byte_count <= 0:
            return
        self._pending_bytes += byte_count
        now = self._clock()
        if now - self._last_emit_at >= self._interval_sec:
            self.flush(now=now)

    def flush(self, *, now: float | None = None) -> None:
        if self._pending_bytes <= 0:
            return
        _put_raw_stats(self._raw_stats_queue, self._pending_bytes)
        self._pending_bytes = 0
        self._last_emit_at = self._clock() if now is None else now

    def close(self) -> None:
        self.flush()
        _put_raw_stats_sentinel(self._raw_stats_queue)


def _handle_reader_command(reader: TransportReader, ui_queue: Any, command: Any) -> None:
    kind = command.kind if isinstance(command, ReaderCommand) else str(command)
    if kind != 'reset_target':
        _put_event(ui_queue, ReaderProcessEvent(kind='error', message=f'unknown reader command: {kind}'))
        return

    try:
        reset_done = reader.reset_target()
    except Exception as e:
        _put_event(ui_queue, ReaderProcessEvent(kind='reset_error', message=str(e), status=reader.status()))
        return

    if reset_done:
        _put_event(
            ui_queue,
            ReaderProcessEvent(kind='reset_done', message='Chip reset triggered', status=reader.status()),
        )
    else:
        _put_event(
            ui_queue,
            ReaderProcessEvent(
                kind='reset_unsupported',
                message='Reset is not supported by this transport',
                status=reader.status(),
            ),
        )


def _drain_reader_commands(reader: TransportReader, ui_queue: Any, command_queue: Any | None) -> None:
    if command_queue is None:
        return
    while True:
        try:
            command = command_queue.get_nowait()
        except Empty:
            return
        _handle_reader_command(reader, ui_queue, command)


def _write_block(writer: WriterSink, block: bytes, ui_queue: Any, *, timeout: float) -> None:
    old_paths = writer.paths
    writer.write(block, timeout=timeout)
    if not writer.emits_events and len(writer.paths) > len(old_paths):
        kind = 'opened' if not old_paths else 'rotated'
        _put_event(
            ui_queue,
            WriterEvent(
                kind=kind,
                message=str(writer.paths[-1]),
                status=writer.status(),
            ),
        )


def _finalize_writer(writer: WriterSink, ui_queue: Any, *, emit_finalized: bool) -> None:
    try:
        writer.finalize()
    except Exception as e:
        _put_event(ui_queue, WriterEvent(kind='error', message=f'close failed: {e}', status=writer.status()))
        return
    if emit_finalized and not writer.emits_events:
        _put_event(ui_queue, WriterEvent(kind='finalized', status=writer.status()))


def run_reader_loop(
    reader: TransportReader,
    writer: WriterSink,
    parse_queue: Any,
    ui_queue: Any,
    stop_requested: StopSignal,
    *,
    raw_stats_queue: Any | None = None,
    command_queue: Any | None = None,
    queue_put_timeout: float = QUEUE_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
    raw_stats_interval_sec: float = RAW_STATS_INTERVAL_SEC,
    clock: Clock = time.monotonic,
    wall_clock_ms: WallClockMs = _wall_clock_ms,
) -> None:
    """Read transport blocks, enqueue raw bytes for saving, then feed parser.

    Raw preservation is authoritative: a block is handed to the parser only
    after it has been accepted by the writer sink. Parser input remains
    best-effort. Reliable raw byte counters are batched before crossing into
    analysis.
    """

    opened = False
    parse_backlog_reported = False
    writer_failed = False
    parse_dropped_chunks = 0
    parse_dropped_bytes = 0
    raw_stats = RawStatsBatcher(raw_stats_queue, interval_sec=raw_stats_interval_sec, clock=clock)

    def report_parse_backlog(message: str) -> None:
        nonlocal parse_backlog_reported
        if parse_backlog_reported:
            return
        parse_backlog_reported = True
        _put_event(
            ui_queue,
            ReaderProcessEvent(
                kind='parse_backlog',
                message=message,
                status=reader.status(),
                parse_dropped_chunks=parse_dropped_chunks,
                parse_dropped_bytes=parse_dropped_bytes,
            ),
        )

    def record_parse_drop(block: bytes, message: str) -> None:
        nonlocal parse_dropped_chunks, parse_dropped_bytes
        parse_dropped_chunks += 1
        parse_dropped_bytes += len(block)
        report_parse_backlog(message)

    def handle_block(block: bytes, received_at_ms: int) -> bool:
        nonlocal writer_failed
        try:
            _write_block(writer, block, ui_queue, timeout=queue_put_timeout)
        except Exception as e:
            writer_failed = True
            _put_event(ui_queue, WriterEvent(kind='error', message=str(e), status=writer.status()))
            return False

        raw_stats.record(len(block))
        if not _put_parse(parse_queue, ReceivedChunk(block, received_at_ms)):
            record_parse_drop(
                block,
                (
                    'Realtime parser fell behind; raw capture continues, '
                    'live stats may be incomplete.'
                ),
            )
        return True

    try:
        reader.open()
        opened = True
        _put_event(ui_queue, ReaderProcessEvent(kind='opened', status=reader.status()))

        while not stop_requested.is_set():
            _drain_reader_commands(reader, ui_queue, command_queue)
            block = reader.read()
            if not block:
                continue
            received_at_ms = wall_clock_ms()
            if not handle_block(block, received_at_ms):
                break

        if opened and stop_requested.is_set() and not writer_failed:
            for block in reader.drain(drain_rounds):
                if not handle_block(block, wall_clock_ms()):
                    break
    except Exception as e:
        _put_event(ui_queue, ReaderProcessEvent(kind='error', message=str(e)))
    finally:
        try:
            reader.close()
        except Exception as e:
            _put_event(ui_queue, ReaderProcessEvent(kind='error', message=f'close failed: {e}'))

        raw_stats.close()
        if not _put_parse_sentinel(parse_queue, queue_put_timeout) and not parse_backlog_reported:
            report_parse_backlog(
                (
                    'Realtime parser queue stayed full during shutdown; '
                    'raw capture continues, final live stats may be incomplete.'
                )
            )
        _finalize_writer(writer, ui_queue, emit_finalized=not writer_failed)
        if parse_dropped_chunks:
            _put_event(
                ui_queue,
                ReaderProcessEvent(
                    kind='parse_backlog_summary',
                    message=(
                        'Realtime parser skipped '
                        f'{parse_dropped_chunks} chunks ({parse_dropped_bytes} bytes); '
                        'raw capture saved them, live stats are incomplete.'
                    ),
                    status=reader.status(),
                    parse_dropped_chunks=parse_dropped_chunks,
                    parse_dropped_bytes=parse_dropped_bytes,
                ),
            )
        _put_event(ui_queue, ReaderProcessEvent(kind='stopped', status=reader.status()))
