# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Combined parser + aggregator process entrypoints."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty
from queue import Queue
from typing import Any

from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.analysis.aggregator import AggregatorUpdate
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseSummary
from src.backend.models import ChecksumMode
from src.backend.models import TransportBitrate

PARSER_BATCH_MAX_CHUNKS = 16
PARSER_BATCH_MAX_BYTES = 1024 * 1024

ANALYSIS_QUEUE_SIZE = 256
ANALYSIS_JOIN_TIMEOUT_SEC = 1.0

SNAPSHOT_INTERVAL_SEC = 0.25
AGGREGATOR_BATCH_MAX_ITEMS = 64

Clock = Callable[[], float]


@dataclass(frozen=True)
class ParserStatus:
    """Parser status or error."""

    kind: str
    message: str = ''


@dataclass(frozen=True)
class AggregatorProcessEvent:
    """Aggregator status or error."""

    kind: str
    message: str = ''


def _put_parser_event(output_queue: Any, event: ParseBatch | ParseSummary | ParserStatus) -> None:
    if output_queue is not None:
        output_queue.put(event)


def _put_analysis_event(
    ui_queue: Any,
    event: AggregatorUpdate | AggregatorSnapshot | AggregatorProcessEvent | ParserStatus,
) -> None:
    if ui_queue is not None:
        ui_queue.put(event)


def run_parser_loop(
    parse_queue: Any,
    output_queue: Any,
    *,
    checksum_mode: ChecksumMode | None = None,
) -> None:
    """Parse raw chunks from parse_queue until a None sentinel is received."""

    parser = BleLogParser(checksum_mode=checksum_mode)
    try:
        while True:
            item = parse_queue.get()
            if item is None:
                break
            chunks: list[bytes] = []
            total_bytes = 0
            stop_after_batch = False

            if item:
                chunks.append(item)
                total_bytes += len(item)

            while len(chunks) < PARSER_BATCH_MAX_CHUNKS and total_bytes < PARSER_BATCH_MAX_BYTES:
                try:
                    next_item = parse_queue.get_nowait()
                except Empty:
                    break
                if next_item is None:
                    stop_after_batch = True
                    break
                if not next_item:
                    continue
                chunks.append(next_item)
                total_bytes += len(next_item)

            if chunks:
                _put_parser_event(output_queue, parser.feed(b''.join(chunks)))
            if stop_after_batch:
                break
        _put_parser_event(output_queue, parser.finalize())
    except Exception as e:
        _put_parser_event(output_queue, ParserStatus(kind='error', message=str(e)))


def drain_parser_events(output_queue: Any) -> list[ParseBatch | ParseSummary | ParserStatus]:
    """Drain currently available parser events."""

    events: list[ParseBatch | ParseSummary | ParserStatus] = []
    while True:
        try:
            events.append(output_queue.get_nowait())
        except Empty:
            return events


def _merge_updates(updates: list[AggregatorUpdate]) -> AggregatorUpdate | None:
    if not updates:
        return None
    return AggregatorUpdate(
        frames_seen=sum(update.frames_seen for update in updates),
        redir_texts=tuple(text for update in updates for text in update.redir_texts),
        internal_frames=tuple(internal for update in updates for internal in update.internal_frames),
        frame_losses=tuple(loss for update in updates for loss in update.frame_losses),
    )


def _put_merged_updates(ui_queue: Any, updates: list[AggregatorUpdate]) -> None:
    merged = _merge_updates(updates)
    if merged is not None:
        _put_analysis_event(ui_queue, merged)
        updates.clear()


def _handle_raw_item(item: Any, aggregator: CaptureAggregator) -> bool:
    if item is None:
        return True
    aggregator.record_raw_bytes(int(item))
    return False


def _consume_raw_count(raw_stats_queue: Any, aggregator: CaptureAggregator) -> bool:
    return _handle_raw_item(raw_stats_queue.get_nowait(), aggregator)


def _handle_parser_item(
    item: Any,
    ui_queue: Any,
    aggregator: CaptureAggregator,
    updates: list[AggregatorUpdate] | None = None,
) -> tuple[bool, bool]:
    if isinstance(item, ParseBatch):
        update = aggregator.consume_parser_batch(item)
        if updates is None:
            _put_analysis_event(ui_queue, update)
        else:
            updates.append(update)
        return False, False
    if isinstance(item, ParseSummary):
        if updates is not None:
            _put_merged_updates(ui_queue, updates)
        aggregator.consume_parser_summary(item)
        return True, True
    if isinstance(item, ParserStatus):
        if updates is not None:
            _put_merged_updates(ui_queue, updates)
        _put_analysis_event(ui_queue, item)
        return item.kind == 'error', False
    return False, False


def _consume_parser_event(parser_event_queue: Any, ui_queue: Any, aggregator: CaptureAggregator) -> tuple[bool, bool]:
    updates: list[AggregatorUpdate] = []
    first_item = parser_event_queue.get_nowait()
    parser_done, parser_finalized = _handle_parser_item(first_item, ui_queue, aggregator, updates)
    if parser_done:
        return parser_done, parser_finalized

    for _ in range(AGGREGATOR_BATCH_MAX_ITEMS - 1):
        try:
            item = parser_event_queue.get_nowait()
        except Empty:
            break
        parser_done, parser_finalized = _handle_parser_item(item, ui_queue, aggregator, updates)
        if parser_done:
            return parser_done, parser_finalized

    _put_merged_updates(ui_queue, updates)
    return parser_done, parser_finalized


def _consume_blocking_parser_event(
    parser_event_queue: Any,
    ui_queue: Any,
    aggregator: CaptureAggregator,
    *,
    timeout: float | None = None,
) -> tuple[bool, bool]:
    updates: list[AggregatorUpdate] = []
    first_item = parser_event_queue.get() if timeout is None else parser_event_queue.get(timeout=timeout)
    parser_done, parser_finalized = _handle_parser_item(first_item, ui_queue, aggregator, updates)
    if parser_done:
        return parser_done, parser_finalized

    for _ in range(AGGREGATOR_BATCH_MAX_ITEMS - 1):
        try:
            item = parser_event_queue.get_nowait()
        except Empty:
            break
        parser_done, parser_finalized = _handle_parser_item(item, ui_queue, aggregator, updates)
        if parser_done:
            return parser_done, parser_finalized

    _put_merged_updates(ui_queue, updates)
    return parser_done, parser_finalized


def run_aggregator_loop(
    parser_event_queue: Any,
    raw_stats_queue: Any,
    ui_queue: Any,
    *,
    bitrate: TransportBitrate | None = None,
    snapshot_interval_sec: float = SNAPSHOT_INTERVAL_SEC,
    snapshot_elapsed_sec: float | None = None,
    clock: Clock = time.monotonic,
) -> None:
    """Aggregate parser batches and raw byte counters until both streams end."""

    aggregator = CaptureAggregator(bitrate)
    parser_done = False
    raw_done = raw_stats_queue is None
    parser_finalized = False
    last_snapshot_at = clock()

    def emit_snapshot(force_elapsed: float | None = None) -> None:
        nonlocal last_snapshot_at
        now = clock()
        elapsed = force_elapsed if force_elapsed is not None else now - last_snapshot_at
        _put_analysis_event(ui_queue, aggregator.snapshot(elapsed))
        last_snapshot_at = now

    try:
        while not (parser_done and raw_done):
            made_progress = False

            if not raw_done:
                try:
                    raw_done = _consume_raw_count(raw_stats_queue, aggregator)
                    made_progress = True
                except Empty:
                    pass

            if not parser_done:
                try:
                    parser_done, parser_finalized = _consume_parser_event(parser_event_queue, ui_queue, aggregator)
                    made_progress = True
                except Empty:
                    pass

            if not made_progress:
                if raw_done:
                    parser_done, parser_finalized = _consume_blocking_parser_event(
                        parser_event_queue,
                        ui_queue,
                        aggregator,
                    )
                elif parser_done:
                    raw_done = _handle_raw_item(raw_stats_queue.get(), aggregator)
                else:
                    try:
                        raw_done = _consume_raw_count(raw_stats_queue, aggregator)
                    except Empty:
                        try:
                            parser_done, parser_finalized = _consume_blocking_parser_event(
                                parser_event_queue,
                                ui_queue,
                                aggregator,
                                timeout=0.01,
                            )
                        except Empty:
                            pass

            if snapshot_interval_sec > 0 and clock() - last_snapshot_at >= snapshot_interval_sec:
                emit_snapshot()

        emit_snapshot(snapshot_elapsed_sec)
        _put_analysis_event(ui_queue, AggregatorProcessEvent(kind='finalized' if parser_finalized else 'stopped'))
    except Exception as e:
        _put_analysis_event(ui_queue, AggregatorProcessEvent(kind='error', message=str(e)))


def drain_aggregator_events(
    ui_queue: Any,
) -> list[AggregatorUpdate | AggregatorSnapshot | AggregatorProcessEvent | ParserStatus]:
    """Drain currently available aggregator events."""

    events: list[AggregatorUpdate | AggregatorSnapshot | AggregatorProcessEvent | ParserStatus] = []
    while True:
        try:
            events.append(ui_queue.get_nowait())
        except Empty:
            return events


def run_analysis_loop(
    parse_queue: Any,
    raw_stats_queue: Any,
    ui_queue: Any,
    *,
    bitrate: TransportBitrate | None = None,
    checksum_mode: ChecksumMode | None = None,
    analysis_queue_size: int = ANALYSIS_QUEUE_SIZE,
) -> None:
    """Run parser and aggregator in one process, connected by a thread queue."""

    analysis_queue: Queue[Any] = Queue(maxsize=analysis_queue_size)
    parser_thread = threading.Thread(
        name='ble-log-parser-thread',
        target=run_parser_loop,
        args=(parse_queue, analysis_queue),
        kwargs={
            'checksum_mode': checksum_mode,
        },
        daemon=True,
    )

    parser_thread.start()
    try:
        run_aggregator_loop(
            analysis_queue,
            raw_stats_queue,
            ui_queue,
            bitrate=bitrate,
        )
    finally:
        parser_thread.join(ANALYSIS_JOIN_TIMEOUT_SEC)


def run_analysis_process(
    parse_queue: Any,
    raw_stats_queue: Any,
    ui_queue: Any,
    bitrate: TransportBitrate | None = None,
    checksum_mode: ChecksumMode | None = None,
) -> None:
    """Process entrypoint for combined BLE log analysis."""

    run_analysis_loop(
        parse_queue,
        raw_stats_queue,
        ui_queue,
        bitrate=bitrate,
        checksum_mode=checksum_mode,
    )
