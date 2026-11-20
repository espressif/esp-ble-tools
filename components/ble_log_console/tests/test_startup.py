# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Opening evidence is observed during normal parsing without delaying output."""

import struct

import pytest
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.analysis.startup import StartupDetector

from tests.helpers import build_frame, snapshot_payload, xor_checksum


def snapshot(seconds: float, sn: int, anchor: int, *, reason: int = 10) -> bytes:
    payload = bytearray(snapshot_payload(int(seconds * 1_000_000), reason_flags=reason))
    payload[7:10] = anchor.to_bytes(3, "little")
    struct.pack_into("<I", payload, 73, int(seconds * 1_000_000))
    return build_frame(bytes(payload), 0, sn, xor_checksum)


def chunks(*, stale: bool = True) -> list[ReceivedChunk]:
    rows = [
        (10, 100, 10, 0.0),
        (70 if stale else 11, 300 if stale else 101, 70 if stale else 11, 0.1 if stale else 1.0),
    ]
    rows += [(71 if stale else 12, 301 if stale else 102, 71 if stale else 12, 1.1 if stale else 2.0)]
    rows += [(72 if stale else 13, 302 if stale else 103, 72 if stale else 13, 2.1 if stale else 3.0)]
    result = []
    offset = 0
    for device, sn, anchor, host in rows:
        data = snapshot(device, sn, anchor)
        result.append(ReceivedChunk(data, int(host * 1000), host, offset))
        offset += len(data)
    return result


def parse_items(items):
    parser = BleLogParser()
    batches = [
        parser.feed(
            c.data,
            received_at_ms=c.received_at_ms,
            received_monotonic=c.received_monotonic,
            raw_offset=c.raw_offset,
        )
        for c in items
    ]
    return parser.startup.finish(), batches


def test_existing_parser_reports_frames_immediately_while_observing_startup():
    parser = BleLogParser()
    items = chunks()
    for i, c in enumerate(items):
        batch = parser.feed(c.data, received_monotonic=c.received_monotonic, raw_offset=c.raw_offset)
        assert batch.parsed_frames == 1
        assert batch.raw_bytes == len(c.data)
        if i < 3:
            assert parser.startup.decision is None
    decision = parser.startup.finish()
    assert decision.offset_bytes == len(items[0].data)
    assert decision.device_jump_sec == 60
    assert decision.anchor_sn == 300
    assert parser.finalize().parsed_frames == 4


def test_normal_start_and_mid_recording_gap_are_never_trimmed():
    items = chunks(stale=False)
    items.append(ReceivedChunk(snapshot(80, 900, 80), 4000, 4.0, sum(len(c.data) for c in items)))
    decision, batches = parse_items(items)
    assert decision.offset_bytes == 0
    assert sum(b.parsed_frames for b in batches) == 5


@pytest.mark.parametrize(
    "condition", ["host_pause", "reset", "wrap", "bindings", "input_gap", "short", "invalid_clock"]
)
def test_ambiguous_or_context_dependent_prefix_is_not_selected(condition):
    items = chunks()
    if condition == "host_pause":
        items = [c._replace(received_monotonic=c.received_monotonic + (60 if i else 0)) for i, c in enumerate(items)]
    elif condition == "reset":
        items[1] = items[1]._replace(data=snapshot(70, 300, 70, reason=11))
    elif condition == "wrap":
        items[0] = items[0]._replace(data=snapshot(4000, 100, 10))
    elif condition == "bindings":
        binding = build_frame(struct.pack("<IB", 1, 9) + b"binding", 0, 0, xor_checksum)
        items = [ReceivedChunk(binding, 0, 0.0, 0)] + [
            c._replace(raw_offset=c.raw_offset + len(binding)) for c in items
        ]
    elif condition == "input_gap":
        items = [c._replace(raw_offset=c.raw_offset + (20 if i else 0)) for i, c in enumerate(items)]
    elif condition == "short":
        items = items[:3]
    elif condition == "invalid_clock":
        items[1] = items[1]._replace(data=snapshot(70, 300, 70, reason=2))
    decision, batches = parse_items(items)
    assert decision.offset_bytes == 0
    assert sum(b.raw_bytes for b in batches) == sum(len(c.data) for c in items)


def test_frame_split_across_receive_chunks_records_exact_raw_offset():
    items = chunks()
    first, second = items[:2]
    items[:2] = [
        first._replace(data=first.data + second.data[:17]),
        second._replace(data=second.data[17:], raw_offset=second.raw_offset + 17),
    ]
    decision, batches = parse_items(items)
    assert decision.offset_bytes == len(first.data)
    assert sum(b.parsed_frames for b in batches) == 4


def test_observation_budget_does_not_filter_data():
    parser = BleLogParser()
    parser.startup = StartupDetector(max_seconds=0.05)
    c, following = chunks()[:2]
    assert parser.feed(c.data, raw_offset=0, received_monotonic=0).parsed_frames == 1
    assert parser.feed(following.data, raw_offset=len(c.data), received_monotonic=0.1).parsed_frames == 1
    assert parser.startup.finish().offset_bytes == 0


def test_sequence_gaps_without_time_compression_are_retained():
    items = chunks(stale=False)
    items[1] = items[1]._replace(data=snapshot(11, 1000, 11))
    items[2] = items[2]._replace(data=snapshot(12, 1001, 12))
    items[3] = items[3]._replace(data=snapshot(13, 1002, 13))
    decision, _ = parse_items(items)
    assert decision.offset_bytes == 0


def test_wall_clock_adjustment_does_not_change_the_startup_decision():
    items = [c._replace(received_at_ms=-i * 100_000) for i, c in enumerate(chunks())]
    decision, _ = parse_items(items)
    assert decision.offset_bytes == len(items[0].data)
