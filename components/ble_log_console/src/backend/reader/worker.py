# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""ReaderProcess entrypoints for capture pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty
from queue import Full
from typing import Any
from typing import Protocol

from src.backend.models import TransportConfig
from src.backend.support.transport import TransportReader
from src.backend.support.transport import TransportStatus
from src.backend.support.transport import create_transport_reader

RAW_PUT_TIMEOUT_SEC = 5.0


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


def _put_event(event_queue: Any, event: ReaderProcessEvent) -> None:
    if event_queue is not None:
        event_queue.put(event)


def _put_raw(raw_queue: Any, item: bytes | None, timeout: float) -> bool:
    try:
        raw_queue.put(item, timeout=timeout)
    except Full:
        return False
    return True


def _put_parse(parse_queue: Any, item: bytes | None) -> bool:
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
    if raw_stats_queue is None:
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


def _handle_reader_command(reader: TransportReader, event_queue: Any, command: Any) -> None:
    kind = command.kind if isinstance(command, ReaderCommand) else str(command)
    if kind != 'reset_target':
        _put_event(event_queue, ReaderProcessEvent(kind='error', message=f'unknown reader command: {kind}'))
        return

    try:
        reset_done = reader.reset_target()
    except Exception as e:
        _put_event(event_queue, ReaderProcessEvent(kind='reset_error', message=str(e), status=reader.status()))
        return

    if reset_done:
        _put_event(
            event_queue,
            ReaderProcessEvent(kind='reset_done', message='Chip reset triggered', status=reader.status()),
        )
    else:
        _put_event(
            event_queue,
            ReaderProcessEvent(
                kind='reset_unsupported',
                message='Reset is not supported by this transport',
                status=reader.status(),
            ),
        )


def _drain_reader_commands(reader: TransportReader, event_queue: Any, command_queue: Any | None) -> None:
    if command_queue is None:
        return
    while True:
        try:
            command = command_queue.get_nowait()
        except Empty:
            return
        _handle_reader_command(reader, event_queue, command)


def run_reader_loop(
    reader: TransportReader,
    raw_queue: Any,
    parse_queue: Any,
    event_queue: Any,
    stop_requested: StopSignal,
    *,
    raw_stats_queue: Any | None = None,
    command_queue: Any | None = None,
    raw_put_timeout: float = RAW_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
) -> None:
    """Run a TransportReader and fan out raw chunks to writer/parser queues.

    The raw queue is authoritative. If it cannot accept bytes within
    ``raw_put_timeout``, capture is failed because raw preservation is at risk.
    The parse queue is best-effort; a full parse queue marks backlog but does
    not stop raw saving.
    """

    opened = False
    parse_backlog_reported = False
    raw_backpressure = False
    parse_dropped_chunks = 0
    parse_dropped_bytes = 0

    def report_parse_backlog(message: str) -> None:
        nonlocal parse_backlog_reported
        if parse_backlog_reported:
            return
        parse_backlog_reported = True
        _put_event(
            event_queue,
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

    try:
        reader.open()
        opened = True
        _put_event(event_queue, ReaderProcessEvent(kind='opened', status=reader.status()))

        while not stop_requested.is_set():
            _drain_reader_commands(reader, event_queue, command_queue)
            block = reader.read()
            if not block:
                continue

            if not _put_raw(raw_queue, block, raw_put_timeout):
                raw_backpressure = True
                _put_event(
                    event_queue,
                    ReaderProcessEvent(
                        kind='error',
                        message='raw_queue full; raw writer is not keeping up',
                        status=reader.status(),
                    ),
                )
                break

            _put_raw_stats(raw_stats_queue, len(block))

            parse_put_ok = _put_parse(parse_queue, block)
            if not parse_put_ok:
                record_parse_drop(
                    block,
                    (
                        'Realtime parser fell behind; raw capture continues, '
                        'live stats may be incomplete.'
                    ),
                )

        if opened and stop_requested.is_set() and not raw_backpressure:
            for block in reader.drain(drain_rounds):
                if not _put_raw(raw_queue, block, raw_put_timeout):
                    raw_backpressure = True
                    _put_event(
                        event_queue,
                        ReaderProcessEvent(
                            kind='error',
                            message='raw_queue full while draining transport',
                            status=reader.status(),
                        ),
                    )
                    break
                _put_raw_stats(raw_stats_queue, len(block))
                parse_put_ok = _put_parse(parse_queue, block)
                if not parse_put_ok:
                    record_parse_drop(
                        block,
                        (
                            'Realtime parser fell behind while draining transport; '
                            'raw capture continues, live stats may be incomplete.'
                        ),
                    )
    except Exception as e:
        _put_event(event_queue, ReaderProcessEvent(kind='error', message=str(e)))
    finally:
        try:
            reader.close()
        except Exception as e:
            _put_event(event_queue, ReaderProcessEvent(kind='error', message=f'close failed: {e}'))

        _put_raw(raw_queue, None, raw_put_timeout)
        _put_raw_stats_sentinel(raw_stats_queue)
        if not _put_parse_sentinel(parse_queue, raw_put_timeout) and not parse_backlog_reported:
            report_parse_backlog(
                (
                    'Realtime parser queue stayed full during shutdown; '
                    'raw capture continues, final live stats may be incomplete.'
                )
            )
        if parse_dropped_chunks:
            _put_event(
                event_queue,
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
        _put_event(event_queue, ReaderProcessEvent(kind='stopped', status=reader.status()))


def run_reader_process(
    config: TransportConfig,
    raw_queue: Any,
    parse_queue: Any,
    event_queue: Any,
    stop_requested: StopSignal,
    *,
    raw_stats_queue: Any | None = None,
    command_queue: Any | None = None,
    raw_put_timeout: float = RAW_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
) -> None:
    """Create and run a transport reader inside ReaderProcess."""

    reader = create_transport_reader(config)
    run_reader_loop(
        reader,
        raw_queue,
        parse_queue,
        event_queue,
        stop_requested,
        raw_stats_queue=raw_stats_queue,
        command_queue=command_queue,
        raw_put_timeout=raw_put_timeout,
        drain_rounds=drain_rounds,
    )
