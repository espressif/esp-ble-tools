# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from queue import Empty
from queue import Queue
from threading import Thread

from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.analysis.parser_events import RedirEvent
from src.backend.analysis.worker import AggregatorProcessEvent
from src.backend.analysis.worker import ParserStatus
from src.backend.analysis.worker import run_analysis_loop
from src.backend.analysis.worker import run_parser_loop
from src.backend.models import BleLogSource
from src.backend.models import ChecksumAlgorithm
from src.backend.models import ChecksumMode
from src.backend.models import ChecksumScope

from tests.helpers import build_frame
from tests.helpers import xor_checksum


def _make_frame(payload: bytes, src: int, sn: int) -> bytes:
    return build_frame(payload, src, sn, xor_checksum)


def _sync_frames() -> bytes:
    payload = b'\x00\x00\x00\x00data'
    return b''.join(_make_frame(payload, src=BleLogSource.HOST, sn=sn) for sn in range(3))


def _events(output_queue: Queue[object]) -> list[object]:
    result: list[object] = []
    while True:
        try:
            result.append(output_queue.get_nowait())
        except Empty:
            return result


def test_parser_loop_emits_batches_and_final_summary() -> None:
    parse_queue: Queue[ReceivedChunk | None] = Queue()
    output_queue: Queue[object] = Queue()
    parse_queue.put(ReceivedChunk(_sync_frames(), 100))
    parse_queue.put(None)

    run_parser_loop(parse_queue, output_queue)

    events = _events(output_queue)
    batch = events[0]
    final = events[1]
    assert isinstance(batch, ParseBatch)
    assert batch.parsed_frames == 3
    assert len([event for event in batch.events if isinstance(event, FrameEvent)]) == 3
    assert isinstance(final, ParseSummary)
    assert final.parsed_frames == 3


def test_parser_loop_batches_available_chunks_before_feed() -> None:
    parse_queue: Queue[ReceivedChunk | None] = Queue()
    output_queue: Queue[object] = Queue()
    frames = _sync_frames()
    parse_queue.put(ReceivedChunk(frames[:10], 100))
    parse_queue.put(ReceivedChunk(frames[10:], 200))
    parse_queue.put(None)

    run_parser_loop(parse_queue, output_queue)

    events = _events(output_queue)
    batches = [event for event in events if isinstance(event, ParseBatch)]
    final = events[-1]
    assert len(batches) == 1
    assert batches[0].raw_bytes == len(frames)
    assert batches[0].parsed_frames == 3
    assert isinstance(final, ParseSummary)
    assert final.raw_bytes == len(frames)
    assert final.parsed_frames == 3


def test_parser_loop_ignores_empty_chunks() -> None:
    parse_queue: Queue[ReceivedChunk | None] = Queue()
    output_queue: Queue[object] = Queue()
    parse_queue.put(ReceivedChunk(b'', 100))
    parse_queue.put(None)

    run_parser_loop(parse_queue, output_queue)

    events = _events(output_queue)
    assert len(events) == 1
    assert isinstance(events[0], ParseSummary)
    assert events[0].raw_bytes == 0


def test_parser_loop_reports_unsupported_checksum_mode() -> None:
    parse_queue: Queue[bytes | None] = Queue()
    output_queue: Queue[object] = Queue()

    run_parser_loop(
        parse_queue,
        output_queue,
        checksum_mode=ChecksumMode(ChecksumAlgorithm.XOR, ChecksumScope.HEADER_ONLY),
    )

    events = _events(output_queue)
    assert len(events) == 1
    assert isinstance(events[0], ParserStatus)
    assert events[0].kind == 'error'
    assert 'unsupported checksum mode' in events[0].message


def test_analysis_loop_exits_after_unsupported_checksum_mode() -> None:
    parse_queue: Queue[bytes | None] = Queue()
    raw_stats_queue: Queue[int | None] = Queue()
    output_queue: Queue[object] = Queue()
    parse_queue.put(None)
    raw_stats_queue.put(None)
    thread = Thread(
        target=run_analysis_loop,
        args=(parse_queue, raw_stats_queue, output_queue),
        kwargs={
            'checksum_mode': ChecksumMode(ChecksumAlgorithm.XOR, ChecksumScope.HEADER_ONLY),
        },
        daemon=True,
    )

    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive()
    events = _events(output_queue)
    assert any(isinstance(event, ParserStatus) and event.kind == 'error' for event in events)
    assert any(isinstance(event, AggregatorProcessEvent) and event.kind == 'stopped' for event in events)


def test_parser_loop_uses_timestamp_of_buffer_that_completes_redir_frame() -> None:
    parse_queue: Queue[ReceivedChunk | None] = Queue()
    output_queue: Queue[object] = Queue()
    frame = _make_frame(b'console line\n', src=BleLogSource.REDIR, sn=0)
    split = len(frame) // 2
    parse_queue.put(ReceivedChunk(frame[:split], 100))
    parse_queue.put(ReceivedChunk(frame[split:], 200))
    parse_queue.put(None)

    run_parser_loop(parse_queue, output_queue)

    redir_events = [
        event
        for batch in _events(output_queue)
        if isinstance(batch, ParseBatch)
        for event in batch.events
        if isinstance(event, RedirEvent)
    ]
    assert redir_events[0].received_at_ms == 200
