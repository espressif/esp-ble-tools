# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""AggregatorProcess entrypoints for capture pipelines."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty
from typing import Any

from src.backend.aggregator.event_aggregator import AggregatorSnapshot
from src.backend.aggregator.event_aggregator import AggregatorUpdate
from src.backend.aggregator.event_aggregator import CaptureAggregator
from src.backend.parser.events import ParseBatch
from src.backend.parser.events import ParseSummary
from src.backend.parser.worker import ParserStatus
from src.backend.models import TransportBitrate


@dataclass(frozen=True)
class AggregatorProcessEvent:
    """Process-level aggregator status or error."""

    kind: str
    message: str = ''


Clock = Callable[[], float]
SNAPSHOT_INTERVAL_SEC = 0.25
AGGREGATOR_BATCH_MAX_ITEMS = 64


def _put_event(
    event_queue: Any,
    event: AggregatorUpdate | AggregatorSnapshot | AggregatorProcessEvent | ParserStatus,
) -> None:
    if event_queue is not None:
        event_queue.put(event)


def _merge_updates(updates: list[AggregatorUpdate]) -> AggregatorUpdate | None:
    if not updates:
        return None
    return AggregatorUpdate(
        frames_seen=sum(update.frames_seen for update in updates),
        redir_texts=tuple(text for update in updates for text in update.redir_texts),
        internal_frames=tuple(internal for update in updates for internal in update.internal_frames),
        frame_losses=tuple(loss for update in updates for loss in update.frame_losses),
        traffic_spikes=tuple(spike for update in updates for spike in update.traffic_spikes),
    )


def _put_merged_updates(event_queue: Any, updates: list[AggregatorUpdate]) -> None:
    merged = _merge_updates(updates)
    if merged is not None:
        _put_event(event_queue, merged)
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
    event_queue: Any,
    aggregator: CaptureAggregator,
    updates: list[AggregatorUpdate] | None = None,
) -> tuple[bool, bool]:
    if isinstance(item, ParseBatch):
        update = aggregator.consume_parser_batch(item)
        if updates is None:
            _put_event(event_queue, update)
        else:
            updates.append(update)
        return False, False
    if isinstance(item, ParseSummary):
        if updates is not None:
            _put_merged_updates(event_queue, updates)
        aggregator.consume_parser_summary(item)
        return True, True
    if isinstance(item, ParserStatus):
        if updates is not None:
            _put_merged_updates(event_queue, updates)
        _put_event(event_queue, item)
        return item.kind == 'error', False
    return False, False


def _consume_parser_event(parser_event_queue: Any, event_queue: Any, aggregator: CaptureAggregator) -> tuple[bool, bool]:
    updates: list[AggregatorUpdate] = []
    first_item = parser_event_queue.get_nowait()
    parser_done, parser_finalized = _handle_parser_item(first_item, event_queue, aggregator, updates)
    if parser_done:
        return parser_done, parser_finalized

    for _ in range(AGGREGATOR_BATCH_MAX_ITEMS - 1):
        try:
            item = parser_event_queue.get_nowait()
        except Empty:
            break
        parser_done, parser_finalized = _handle_parser_item(item, event_queue, aggregator, updates)
        if parser_done:
            return parser_done, parser_finalized

    _put_merged_updates(event_queue, updates)
    return parser_done, parser_finalized


def _consume_blocking_parser_event(
    parser_event_queue: Any,
    event_queue: Any,
    aggregator: CaptureAggregator,
    *,
    timeout: float | None = None,
) -> tuple[bool, bool]:
    updates: list[AggregatorUpdate] = []
    first_item = parser_event_queue.get() if timeout is None else parser_event_queue.get(timeout=timeout)
    parser_done, parser_finalized = _handle_parser_item(first_item, event_queue, aggregator, updates)
    if parser_done:
        return parser_done, parser_finalized

    for _ in range(AGGREGATOR_BATCH_MAX_ITEMS - 1):
        try:
            item = parser_event_queue.get_nowait()
        except Empty:
            break
        parser_done, parser_finalized = _handle_parser_item(item, event_queue, aggregator, updates)
        if parser_done:
            return parser_done, parser_finalized

    _put_merged_updates(event_queue, updates)
    return parser_done, parser_finalized


def run_aggregator_loop(
    parser_event_queue: Any,
    raw_stats_queue: Any,
    event_queue: Any,
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
        _put_event(event_queue, aggregator.snapshot(elapsed))
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
                    parser_done, parser_finalized = _consume_parser_event(parser_event_queue, event_queue, aggregator)
                    made_progress = True
                except Empty:
                    pass

            if not made_progress:
                if raw_done:
                    parser_done, parser_finalized = _consume_blocking_parser_event(
                        parser_event_queue, event_queue, aggregator
                    )
                elif parser_done:
                    raw_done = _handle_raw_item(raw_stats_queue.get(), aggregator)
                else:
                    try:
                        raw_done = _consume_raw_count(raw_stats_queue, aggregator)
                    except Empty:
                        try:
                            parser_done, parser_finalized = _consume_blocking_parser_event(
                                parser_event_queue, event_queue, aggregator, timeout=0.01
                            )
                        except Empty:
                            pass

            if snapshot_interval_sec > 0 and clock() - last_snapshot_at >= snapshot_interval_sec:
                emit_snapshot()

        emit_snapshot(snapshot_elapsed_sec)
        _put_event(event_queue, AggregatorProcessEvent(kind='finalized' if parser_finalized else 'stopped'))
    except Exception as e:
        _put_event(event_queue, AggregatorProcessEvent(kind='error', message=str(e)))


def run_aggregator_process(
    parser_event_queue: Any,
    raw_stats_queue: Any,
    event_queue: Any,
    bitrate: TransportBitrate | None = None,
) -> None:
    """Process entrypoint for capture event aggregation."""

    run_aggregator_loop(parser_event_queue, raw_stats_queue, event_queue, bitrate=bitrate)


def drain_aggregator_events(
    event_queue: Any,
) -> list[AggregatorUpdate | AggregatorSnapshot | AggregatorProcessEvent | ParserStatus]:
    """Drain currently available aggregator events."""

    events: list[AggregatorUpdate | AggregatorSnapshot | AggregatorProcessEvent | ParserStatus] = []
    while True:
        try:
            events.append(event_queue.get_nowait())
        except Empty:
            return events
