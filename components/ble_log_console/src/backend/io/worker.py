# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Combined reader + writer process entrypoints."""

from __future__ import annotations

from queue import Full
from typing import Any

from src.backend.models import TransportConfig
from src.backend.io.reader import QUEUE_PUT_TIMEOUT_SEC
from src.backend.io.reader import ReaderProcessEvent
from src.backend.io.reader import StopSignal
from src.backend.io.reader import run_reader_loop
from src.backend.io.writer import Clock
from src.backend.io.writer import FileFactory
from src.backend.io.writer import AsyncBatchWriter
from src.backend.io.writer import WriterConfig
from src.backend.support.transport import TransportReader
from src.backend.support.transport import create_transport_reader


def _put_stop_sentinel(queue: Any, timeout: float) -> None:
    try:
        queue.put(None, timeout=timeout)
    except Full:
        pass


def run_io_loop(
    reader: TransportReader,
    writer_config: WriterConfig,
    parse_queue: Any,
    raw_stats_queue: Any,
    ui_queue: Any,
    stop_requested: StopSignal,
    *,
    command_queue: Any | None = None,
    queue_put_timeout: float = QUEUE_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
    writer_clock: Clock | None = None,
    writer_file_factory: FileFactory | None = None,
) -> None:
    """Run transport reader and raw writer in one IO loop."""

    writer_kwargs: dict[str, Any] = {}
    if writer_clock is not None:
        writer_kwargs['clock'] = writer_clock
    if writer_file_factory is not None:
        writer_kwargs['file_factory'] = writer_file_factory
    writer = AsyncBatchWriter(writer_config, ui_queue, **writer_kwargs)
    writer.start()

    run_reader_loop(
        reader,
        writer,
        parse_queue,
        ui_queue,
        stop_requested,
        raw_stats_queue=raw_stats_queue,
        command_queue=command_queue,
        queue_put_timeout=queue_put_timeout,
        drain_rounds=drain_rounds,
    )


def run_io_process(
    transport_config: TransportConfig,
    writer_config: WriterConfig,
    parse_queue: Any,
    raw_stats_queue: Any,
    ui_queue: Any,
    stop_requested: StopSignal,
    *,
    command_queue: Any | None = None,
    queue_put_timeout: float = QUEUE_PUT_TIMEOUT_SEC,
    drain_rounds: int = 10,
) -> None:
    """Process entrypoint for combined BLE log IO."""

    try:
        reader = create_transport_reader(transport_config)
        run_io_loop(
            reader,
            writer_config,
            parse_queue,
            raw_stats_queue,
            ui_queue,
            stop_requested,
            command_queue=command_queue,
            queue_put_timeout=queue_put_timeout,
            drain_rounds=drain_rounds,
        )
    except Exception as e:
        ui_queue.put(ReaderProcessEvent(kind='error', message=str(e)))
        _put_stop_sentinel(parse_queue, QUEUE_PUT_TIMEOUT_SEC)
        _put_stop_sentinel(raw_stats_queue, QUEUE_PUT_TIMEOUT_SEC)
