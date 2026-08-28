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

from src.backend.analysis.worker import run_analysis_loop
from src.backend.analysis.worker import run_analysis_process
from src.backend.analysis.worker import AggregatorProcessEvent
from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.io.worker import run_io_loop
from src.backend.io.worker import run_io_process
from src.backend.io.writer import Clock
from src.backend.io.writer import FileFactory
from src.backend.io.writer import WriterConfig
from src.backend.io.writer import WriterEvent
from src.backend.analysis.worker import ParserStatus
from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.io.reader import QUEUE_PUT_TIMEOUT_SEC
from src.backend.io.reader import ReaderCommand
from src.backend.io.reader import ReaderProcessEvent
from src.backend.models import TransportConfig
from src.backend.models import ChecksumMode
from src.backend.support.transport import TransportReader
from src.backend.support.transport import create_transport_reader

PARSE_QUEUE_SIZE = 512
# ui_queue still carries critical reader/writer status. Keep it unbounded by
# default until status events and lossy UI updates are split into separate lanes.
UI_QUEUE_SIZE = 0


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


def _drain_events(ui_queue: Any) -> list[Any]:
    events: list[Any] = []
    while True:
        try:
            events.append(ui_queue.get_nowait())
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
                WriterEvent,
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
        elif isinstance(event, WriterEvent):
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
    writer_config: WriterConfig,
    *,
    stop_requested: threading.Event | None = None,
    parse_queue_size: int = PARSE_QUEUE_SIZE,
    ui_queue_size: int = UI_QUEUE_SIZE,
    queue_put_timeout: float = QUEUE_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
    parser_checksum_mode: ChecksumMode | None = None,
    writer_clock: Clock | None = None,
    writer_file_factory: FileFactory | None = None,
) -> CapturePipelineResult:
    """Run the capture pipeline in-process for tests and local validation."""

    parse_queue: Queue[ReceivedChunk | None] = Queue(maxsize=parse_queue_size)
    raw_stats_queue: Queue[int | None] = Queue()
    ui_queue: Queue[Any] = Queue(maxsize=ui_queue_size)
    stop_requested = stop_requested or threading.Event()

    analysis_thread = threading.Thread(
        target=run_analysis_loop,
        args=(parse_queue, raw_stats_queue, ui_queue),
        kwargs={
            'bitrate': reader.bitrate_config,
            'checksum_mode': parser_checksum_mode,
        },
    )
    io_thread = threading.Thread(
        target=run_io_loop,
        args=(reader, writer_config, parse_queue, raw_stats_queue, ui_queue, stop_requested),
        kwargs={
            'queue_put_timeout': queue_put_timeout,
            'drain_rounds': drain_rounds,
            'writer_clock': writer_clock,
            'writer_file_factory': writer_file_factory,
        },
    )

    analysis_thread.start()
    io_thread.start()
    io_thread.join()
    analysis_thread.join()

    return _result_from_events(_drain_events(ui_queue))


class CapturePipeline:
    """Process-based BLE log capture pipeline."""

    def __init__(
        self,
        transport_config: TransportConfig,
        writer_config: WriterConfig,
        *,
        parse_queue_size: int = PARSE_QUEUE_SIZE,
        ui_queue_size: int = UI_QUEUE_SIZE,
        queue_put_timeout: float = QUEUE_PUT_TIMEOUT_SEC,
        drain_rounds: int = 10,
        parser_checksum_mode: ChecksumMode | None = None,
    ) -> None:
        self._transport_config = transport_config
        self._writer_config = writer_config
        self._parse_queue_size = parse_queue_size
        self._ui_queue_size = ui_queue_size
        self._queue_put_timeout = queue_put_timeout
        self._drain_rounds = drain_rounds
        self._parser_checksum_mode = parser_checksum_mode
        self._ctx = multiprocessing.get_context()
        self._parse_queue: Any | None = None
        self._raw_stats_queue: Any | None = None
        self._ui_queue: Any | None = None
        self._command_queue: Any | None = None
        self._stop_requested: Any | None = None
        self._io_process: Any | None = None
        self._analysis_process: Any | None = None
        self._result_events: list[Any] = []

    def start(self) -> None:
        if self._io_process is not None or self._analysis_process is not None:
            raise RuntimeError('capture pipeline is already started')

        self._parse_queue = self._ctx.Queue(maxsize=self._parse_queue_size)
        self._raw_stats_queue = self._ctx.Queue()
        self._ui_queue = self._ctx.Queue(maxsize=self._ui_queue_size)
        self._command_queue = self._ctx.Queue()
        self._stop_requested = self._ctx.Event()
        self._result_events = []
        bitrate = create_transport_reader(self._transport_config).bitrate_config

        self._analysis_process = self._ctx.Process(
            name='ble-log-analysis',
            target=run_analysis_process,
            args=(
                self._parse_queue,
                self._raw_stats_queue,
                self._ui_queue,
                bitrate,
                self._parser_checksum_mode,
            ),
        )
        self._io_process = self._ctx.Process(
            name='ble-log-io',
            target=run_io_process,
            args=(
                self._transport_config,
                self._writer_config,
                self._parse_queue,
                self._raw_stats_queue,
                self._ui_queue,
                self._stop_requested,
            ),
            kwargs={
                'command_queue': self._command_queue,
                'queue_put_timeout': self._queue_put_timeout,
                'drain_rounds': self._drain_rounds,
            },
        )

        self._analysis_process.start()
        self._io_process.start()

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
            for process in (self._io_process, self._analysis_process)
        )

    def drain_events(self) -> list[Any]:
        """Drain events for UI consumption without losing final result state."""

        if self._ui_queue is None:
            raise RuntimeError('capture pipeline is not started')
        events = _drain_events(self._ui_queue)
        self._result_events.extend(_events_for_result(events))
        return events

    def wait_with_events(self, timeout: float | None = None) -> tuple[list[Any], CapturePipelineResult]:
        if self._io_process is None or self._analysis_process is None or self._ui_queue is None:
            raise RuntimeError('capture pipeline is not started')

        self._io_process.join(timeout)
        if self._io_process.is_alive():
            self.stop()
            self._io_process.join(timeout)

        self._analysis_process.join(timeout)
        events = self.drain_events()
        result = _result_from_events(self._result_events)

        if self._io_process.is_alive() or self._analysis_process.is_alive():
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
