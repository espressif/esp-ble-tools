# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from queue import Empty
from queue import Queue

from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.worker import run_parser_loop
from src.backend.support.parser_core.checksum import xor_checksum
from src.backend.models import BleLogSource

from tests.helpers import build_frame


def _make_frame(payload: bytes, src: int, sn: int) -> bytes:
    return build_frame(payload, src, sn, xor_checksum, checksum_scope_full=True)  # type: ignore[no-any-return]


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
    parse_queue: Queue[bytes | None] = Queue()
    output_queue: Queue[object] = Queue()
    parse_queue.put(_sync_frames())
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
    parse_queue: Queue[bytes | None] = Queue()
    output_queue: Queue[object] = Queue()
    frames = _sync_frames()
    parse_queue.put(frames[:10])
    parse_queue.put(frames[10:])
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
    parse_queue: Queue[bytes | None] = Queue()
    output_queue: Queue[object] = Queue()
    parse_queue.put(b'')
    parse_queue.put(None)

    run_parser_loop(parse_queue, output_queue)

    events = _events(output_queue)
    assert len(events) == 1
    assert isinstance(events[0], ParseSummary)
    assert events[0].raw_bytes == 0
