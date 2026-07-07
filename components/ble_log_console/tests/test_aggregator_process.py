# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import struct
from queue import Empty
from queue import Queue

from src.backend.aggregator.worker import AggregatorProcessEvent
from src.backend.aggregator.worker import run_aggregator_loop
from src.backend.aggregator.event_aggregator import AggregatorSnapshot
from src.backend.aggregator.event_aggregator import AggregatorUpdate
from src.backend.aggregator.event_aggregator import frame_size_from_payload
from src.backend.parser.events import FrameEvent
from src.backend.parser.events import ParseBatch
from src.backend.parser.events import ParseSummary
from src.backend.parser.worker import ParserStatus
from src.backend.models import BleLogSource
from src.backend.models import ParsedFrame


class StepClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        if self.calls == 1:
            return 0.0
        return 0.3


def _events(event_queue: Queue[object]) -> list[object]:
    result: list[object] = []
    while True:
        try:
            result.append(event_queue.get_nowait())
        except Empty:
            return result


def test_aggregator_loop_emits_update_snapshot_and_finalized_status() -> None:
    parser_event_queue: Queue[object] = Queue()
    raw_stats_queue: Queue[int | None] = Queue()
    event_queue: Queue[object] = Queue()

    payload = struct.pack('<I', 1234) + b'payload'
    frame = ParsedFrame(
        source_code=BleLogSource.HOST,
        frame_sn=1,
        payload=payload,
        os_ts_ms=1234,
    )
    frame_event = FrameEvent(frame=frame, frame_size=frame_size_from_payload(payload))
    raw_stats_queue.put(len(payload) + 20)
    raw_stats_queue.put(None)
    parser_event_queue.put(
        ParseBatch(
            raw_bytes=len(payload) + 20,
            parsed_frames=1,
            consumed=len(payload) + 20,
            carried_bytes=0,
            events=(frame_event,),
        )
    )
    parser_event_queue.put(ParseSummary(raw_bytes=len(payload) + 20, parsed_frames=1, carried_bytes=0))

    run_aggregator_loop(parser_event_queue, raw_stats_queue, event_queue, snapshot_elapsed_sec=1.0)

    events = _events(event_queue)
    updates = [event for event in events if isinstance(event, AggregatorUpdate)]
    snapshots = [event for event in events if isinstance(event, AggregatorSnapshot)]
    statuses = [event for event in events if isinstance(event, AggregatorProcessEvent)]

    assert updates[0].frames_seen == 1
    assert snapshots[0].stats.transport.rx_bytes == len(payload) + 20
    assert snapshots[0].stats.transport.rx_frames == 1
    assert snapshots[0].parser_raw_bytes == len(payload) + 20
    assert snapshots[0].parser_frames == 1
    assert snapshots[0].parser_carried_bytes == 0
    assert statuses[-1].kind == 'finalized'


def test_aggregator_loop_merges_available_parse_batches_into_one_update() -> None:
    parser_event_queue: Queue[object] = Queue()
    raw_stats_queue: Queue[int | None] = Queue()
    event_queue: Queue[object] = Queue()

    payload = struct.pack('<I', 1234) + b'payload'
    frame1 = ParsedFrame(source_code=BleLogSource.HOST, frame_sn=1, payload=payload, os_ts_ms=1234)
    frame2 = ParsedFrame(source_code=BleLogSource.HOST, frame_sn=2, payload=payload, os_ts_ms=1234)
    raw_stats_queue.put((len(payload) + 20) * 2)
    raw_stats_queue.put(None)
    parser_event_queue.put(
        ParseBatch(
            raw_bytes=len(payload) + 20,
            parsed_frames=1,
            consumed=len(payload) + 20,
            carried_bytes=0,
            events=(FrameEvent(frame=frame1, frame_size=frame_size_from_payload(payload)),),
        )
    )
    parser_event_queue.put(
        ParseBatch(
            raw_bytes=len(payload) + 20,
            parsed_frames=1,
            consumed=len(payload) + 20,
            carried_bytes=0,
            events=(FrameEvent(frame=frame2, frame_size=frame_size_from_payload(payload)),),
        )
    )
    parser_event_queue.put(ParseSummary(raw_bytes=(len(payload) + 20) * 2, parsed_frames=2, carried_bytes=0))

    run_aggregator_loop(parser_event_queue, raw_stats_queue, event_queue, snapshot_elapsed_sec=1.0)

    updates = [event for event in _events(event_queue) if isinstance(event, AggregatorUpdate)]
    assert len(updates) == 1
    assert updates[0].frames_seen == 2


def test_aggregator_loop_emits_periodic_snapshot() -> None:
    parser_event_queue: Queue[object] = Queue()
    raw_stats_queue: Queue[int | None] = Queue()
    event_queue: Queue[object] = Queue()
    raw_stats_queue.put(100)
    raw_stats_queue.put(None)
    parser_event_queue.put(ParseSummary(raw_bytes=100, parsed_frames=0, carried_bytes=0))

    run_aggregator_loop(
        parser_event_queue,
        raw_stats_queue,
        event_queue,
        snapshot_interval_sec=0.25,
        clock=StepClock(),
    )

    snapshots = [event for event in _events(event_queue) if isinstance(event, AggregatorSnapshot)]
    assert len(snapshots) == 2
    assert snapshots[0].stats.transport.rx_bytes == 100
    assert snapshots[-1].parser_raw_bytes == 100


def test_aggregator_loop_forwards_parser_error_and_stops() -> None:
    parser_event_queue: Queue[object] = Queue()
    raw_stats_queue: Queue[int | None] = Queue()
    event_queue: Queue[object] = Queue()
    raw_stats_queue.put(None)
    parser_event_queue.put(ParserStatus(kind='error', message='parser failed'))

    run_aggregator_loop(parser_event_queue, raw_stats_queue, event_queue)

    events = _events(event_queue)
    parser_errors = [event for event in events if isinstance(event, ParserStatus)]
    statuses = [event for event in events if isinstance(event, AggregatorProcessEvent)]
    assert parser_errors[0].message == 'parser failed'
    assert statuses[-1].kind == 'stopped'
