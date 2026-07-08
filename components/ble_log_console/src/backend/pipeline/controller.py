# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Minimal capture pipeline controller."""

from __future__ import annotations

import multiprocessing
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from queue import Queue
from typing import Any

from src.backend.aggregator.worker import AggregatorProcessEvent
from src.backend.aggregator.worker import run_aggregator_loop
from src.backend.aggregator.worker import run_aggregator_process
from src.backend.aggregator.event_aggregator import AggregatorSnapshot
from src.backend.writer.raw_writer import Clock
from src.backend.writer.raw_writer import FileFactory
from src.backend.writer.raw_writer import RawWriterConfig
from src.backend.writer.raw_writer import RawWriterProcessEvent
from src.backend.writer.raw_writer import run_raw_writer_loop
from src.backend.writer.raw_writer import run_raw_writer_process
from src.backend.parser.worker import ParserStatus
from src.backend.parser.worker import run_parser_loop
from src.backend.parser.worker import run_parser_process
from src.backend.reader.worker import ReaderCommand
from src.backend.reader.worker import ReaderProcessEvent
from src.backend.reader.worker import run_reader_loop
from src.backend.reader.worker import run_reader_process
from src.backend.models import TransportConfig
from src.backend.support.transport import TransportReader
from src.backend.support.transport import create_transport_reader

RAW_QUEUE_SIZE = 4096
PARSE_QUEUE_SIZE = 0
RAW_PUT_TIMEOUT_SEC = 5.0


@dataclass(frozen=True)
class CapturePipelineResult:
    """Final result of a minimal capture pipeline run."""

    raw_paths: tuple[Path, ...]
    reader_error: str | None
    writer_error: str | None
    parser_error: str | None
    aggregator_error: str | None
    parse_backlog: bool
    raw_bytes: int
    parser_raw_bytes: int
    parser_frames: int
    parser_carried_bytes: int
    completed: bool
    parse_dropped_chunks: int = 0
    parse_dropped_bytes: int = 0
    parser_lag_bytes: int = 0


def _drain_events(event_queue: Any) -> list[Any]:
    events: list[Any] = []
    while True:
        try:
            events.append(event_queue.get_nowait())
        except Empty:
            return events


def _events_for_result(events: list[Any]) -> list[Any]:
    return [
        event
        for event in events
        if isinstance(
            event,
            (
                ReaderProcessEvent,
                RawWriterProcessEvent,
                ParserStatus,
                AggregatorSnapshot,
                AggregatorProcessEvent,
            ),
        )
    ]


def _result_from_events(events: list[Any]) -> CapturePipelineResult:
    raw_paths: tuple[Path, ...] = ()
    reader_error: str | None = None
    writer_error: str | None = None
    parser_error: str | None = None
    aggregator_error: str | None = None
    parse_backlog = False
    raw_bytes = 0
    parser_raw_bytes = 0
    parser_frames = 0
    parser_carried_bytes = 0
    parse_dropped_chunks = 0
    parse_dropped_bytes = 0
    writer_finalized = False
    aggregator_finalized = False

    for event in events:
        if isinstance(event, ReaderProcessEvent):
            if event.kind == 'error' and reader_error is None:
                reader_error = event.message
            elif event.kind == 'parse_backlog':
                parse_backlog = True
            elif event.kind == 'parse_backlog_summary':
                parse_backlog = True
            parse_dropped_chunks = max(parse_dropped_chunks, event.parse_dropped_chunks)
            parse_dropped_bytes = max(parse_dropped_bytes, event.parse_dropped_bytes)
        elif isinstance(event, RawWriterProcessEvent):
            if event.status is not None:
                raw_paths = event.status.paths
                raw_bytes = event.status.bytes_written
            if event.kind == 'error' and writer_error is None:
                writer_error = event.message
            elif event.kind == 'finalized':
                writer_finalized = True
        elif isinstance(event, ParserStatus):
            if event.kind == 'error' and parser_error is None:
                parser_error = event.message
        elif isinstance(event, AggregatorSnapshot):
            parser_raw_bytes = event.parser_raw_bytes
            parser_frames = event.parser_frames
            parser_carried_bytes = event.parser_carried_bytes
        elif isinstance(event, AggregatorProcessEvent):
            if event.kind == 'error' and aggregator_error is None:
                aggregator_error = event.message
            elif event.kind == 'finalized':
                aggregator_finalized = True

    completed = (
        reader_error is None
        and writer_error is None
        and parser_error is None
        and aggregator_error is None
        and writer_finalized
        and aggregator_finalized
    )
    parser_lag_bytes = max(0, raw_bytes - parser_raw_bytes)
    return CapturePipelineResult(
        raw_paths=raw_paths,
        reader_error=reader_error,
        writer_error=writer_error,
        parser_error=parser_error,
        aggregator_error=aggregator_error,
        parse_backlog=parse_backlog,
        raw_bytes=raw_bytes,
        parser_raw_bytes=parser_raw_bytes,
        parser_frames=parser_frames,
        parser_carried_bytes=parser_carried_bytes,
        completed=completed,
        parse_dropped_chunks=parse_dropped_chunks,
        parse_dropped_bytes=parse_dropped_bytes,
        parser_lag_bytes=parser_lag_bytes,
    )


def run_capture_pipeline_inprocess(
    reader: TransportReader,
    raw_writer_config: RawWriterConfig,
    *,
    stop_requested: threading.Event | None = None,
    raw_queue_size: int = RAW_QUEUE_SIZE,
    parse_queue_size: int = PARSE_QUEUE_SIZE,
    raw_put_timeout: float = RAW_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
    writer_clock: Clock | None = None,
    writer_file_factory: FileFactory | None = None,
) -> CapturePipelineResult:
    """Run the capture pipeline in-process for tests and local validation."""

    raw_queue: Queue[bytes | None] = Queue(maxsize=raw_queue_size)
    # Parser can lag behind raw capture. Keep it unbounded by default so live
    # parsing catches up instead of dropping chunks; raw_queue remains bounded
    # because raw writer backpressure is capture-critical.
    parse_queue: Queue[bytes | None] = Queue(maxsize=parse_queue_size)
    parser_event_queue: Queue[Any] = Queue()
    raw_stats_queue: Queue[int | None] = Queue()
    event_queue: Queue[Any] = Queue()
    stop_requested = stop_requested or threading.Event()

    writer_kwargs: dict[str, Any] = {}
    if writer_clock is not None:
        writer_kwargs['clock'] = writer_clock
    if writer_file_factory is not None:
        writer_kwargs['file_factory'] = writer_file_factory

    writer_thread = threading.Thread(
        target=run_raw_writer_loop,
        args=(raw_writer_config, raw_queue, event_queue),
        kwargs=writer_kwargs,
    )
    parser_thread = threading.Thread(
        target=run_parser_loop,
        args=(parse_queue, parser_event_queue),
    )
    aggregator_thread = threading.Thread(
        target=run_aggregator_loop,
        args=(parser_event_queue, raw_stats_queue, event_queue),
        kwargs={'bitrate': reader.bitrate_config},
    )
    reader_thread = threading.Thread(
        target=run_reader_loop,
        args=(reader, raw_queue, parse_queue, event_queue, stop_requested),
        kwargs={
            'raw_stats_queue': raw_stats_queue,
            'raw_put_timeout': raw_put_timeout,
            'drain_rounds': drain_rounds,
        },
    )

    writer_thread.start()
    parser_thread.start()
    aggregator_thread.start()
    reader_thread.start()
    reader_thread.join()
    writer_thread.join()
    parser_thread.join()
    aggregator_thread.join()

    return _result_from_events(_drain_events(event_queue))


class CapturePipeline:
    """Minimal process-based reader -> raw writer pipeline."""

    def __init__(
        self,
        transport_config: TransportConfig,
        raw_writer_config: RawWriterConfig,
        *,
        raw_queue_size: int = RAW_QUEUE_SIZE,
        parse_queue_size: int = PARSE_QUEUE_SIZE,
        raw_put_timeout: float = RAW_PUT_TIMEOUT_SEC,
        drain_rounds: int = 10,
    ) -> None:
        self._transport_config = transport_config
        self._raw_writer_config = raw_writer_config
        self._raw_queue_size = raw_queue_size
        # Parser can lag behind raw capture. Keep it unbounded by default so
        # live parsing catches up instead of dropping chunks.
        self._parse_queue_size = parse_queue_size
        self._raw_put_timeout = raw_put_timeout
        self._drain_rounds = drain_rounds
        self._ctx = multiprocessing.get_context()
        self._raw_queue: Any | None = None
        self._parse_queue: Any | None = None
        self._parser_event_queue: Any | None = None
        self._raw_stats_queue: Any | None = None
        self._event_queue: Any | None = None
        self._command_queue: Any | None = None
        self._stop_requested: Any | None = None
        self._reader_process: Any | None = None
        self._writer_process: Any | None = None
        self._parser_process: Any | None = None
        self._aggregator_process: Any | None = None
        self._result_events: list[Any] = []

    def start(self) -> None:
        if (
            self._reader_process is not None
            or self._writer_process is not None
            or self._parser_process is not None
            or self._aggregator_process is not None
        ):
            raise RuntimeError('capture pipeline is already started')

        self._raw_queue = self._ctx.Queue(maxsize=self._raw_queue_size)
        self._parse_queue = self._ctx.Queue(maxsize=self._parse_queue_size)
        self._parser_event_queue = self._ctx.Queue()
        self._raw_stats_queue = self._ctx.Queue()
        self._event_queue = self._ctx.Queue()
        self._command_queue = self._ctx.Queue()
        self._stop_requested = self._ctx.Event()
        self._result_events = []
        bitrate = create_transport_reader(self._transport_config).bitrate_config

        self._writer_process = self._ctx.Process(
            target=run_raw_writer_process,
            args=(self._raw_writer_config, self._raw_queue, self._event_queue),
        )
        self._parser_process = self._ctx.Process(
            target=run_parser_process,
            args=(self._parse_queue, self._parser_event_queue),
        )
        self._aggregator_process = self._ctx.Process(
            target=run_aggregator_process,
            args=(self._parser_event_queue, self._raw_stats_queue, self._event_queue, bitrate),
        )
        self._reader_process = self._ctx.Process(
            target=run_reader_process,
            args=(
                self._transport_config,
                self._raw_queue,
                self._parse_queue,
                self._event_queue,
                self._stop_requested,
            ),
            kwargs={
                'raw_stats_queue': self._raw_stats_queue,
                'command_queue': self._command_queue,
                'raw_put_timeout': self._raw_put_timeout,
                'drain_rounds': self._drain_rounds,
            },
        )

        self._writer_process.start()
        self._parser_process.start()
        self._aggregator_process.start()
        self._reader_process.start()

    def stop(self) -> None:
        if self._stop_requested is not None:
            self._stop_requested.set()

    def reset_target(self) -> None:
        if self._command_queue is None:
            raise RuntimeError('capture pipeline is not started')
        self._command_queue.put(ReaderCommand(kind='reset_target'))

    def is_alive(self) -> bool:
        return any(
            process is not None and process.is_alive()
            for process in (
                self._reader_process,
                self._writer_process,
                self._parser_process,
                self._aggregator_process,
            )
        )

    def drain_events(self) -> list[Any]:
        """Drain events for UI consumption without losing final result state."""

        if self._event_queue is None:
            raise RuntimeError('capture pipeline is not started')
        events = _drain_events(self._event_queue)
        self._result_events.extend(_events_for_result(events))
        return events

    def wait_with_events(self, timeout: float | None = None) -> tuple[list[Any], CapturePipelineResult]:
        if (
            self._reader_process is None
            or self._writer_process is None
            or self._parser_process is None
            or self._aggregator_process is None
            or self._event_queue is None
        ):
            raise RuntimeError('capture pipeline is not started')

        self._reader_process.join(timeout)
        if self._reader_process.is_alive():
            self.stop()
            self._reader_process.join(timeout)

        self._writer_process.join(timeout)
        self._parser_process.join(timeout)
        self._aggregator_process.join(timeout)
        events = self.drain_events()
        result = _result_from_events(self._result_events)

        if (
            self._reader_process.is_alive()
            or self._writer_process.is_alive()
            or self._parser_process.is_alive()
            or self._aggregator_process.is_alive()
        ):
            return (
                events,
                CapturePipelineResult(
                    raw_paths=result.raw_paths,
                    reader_error=result.reader_error or 'capture pipeline did not stop before timeout',
                    writer_error=result.writer_error,
                    parser_error=result.parser_error,
                    aggregator_error=result.aggregator_error,
                    parse_backlog=result.parse_backlog,
                    raw_bytes=result.raw_bytes,
                    parser_raw_bytes=result.parser_raw_bytes,
                    parser_frames=result.parser_frames,
                    parser_carried_bytes=result.parser_carried_bytes,
                    completed=False,
                    parse_dropped_chunks=result.parse_dropped_chunks,
                    parse_dropped_bytes=result.parse_dropped_bytes,
                    parser_lag_bytes=result.parser_lag_bytes,
                ),
            )
        return events, result

    def wait(self, timeout: float | None = None) -> CapturePipelineResult:
        _, result = self.wait_with_events(timeout)
        return result
