# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Opening evidence is observed during normal parsing without delaying output."""

import struct

import pytest
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.analysis.startup import StartupDetector

from tests.helpers import build_frame, snapshot_payload, xor_checksum


def snapshot(seconds: float, sn: int, anchor: int, *, reason: int = 10, os_ms: int | None = None) -> bytes:
    esp_us = round(seconds * 1_000_000) % (1 << 32)
    payload = bytearray(snapshot_payload(esp_us, reason_flags=reason))
    payload[7:10] = anchor.to_bytes(3, "little")
    struct.pack_into("<II", payload, 73, esp_us, (round(seconds * 1000) if os_ms is None else os_ms) % (1 << 32))
    return build_frame(bytes(payload), 0, sn, xor_checksum)


def chunks(*, stale: bool = True, clock_origin: int = 0) -> list[ReceivedChunk]:
    rows = [
        (10, 100, 10, 0.0),
        (70 if stale else 11, 300 if stale else 101, 70 if stale else 11, 0.1 if stale else 1.0),
    ]
    rows += [(71 if stale else 12, 301 if stale else 102, 71 if stale else 12, 1.1 if stale else 2.0)]
    rows += [(72 if stale else 13, 302 if stale else 103, 72 if stale else 13, 2.1 if stale else 3.0)]
    result = []
    offset = 0
    for device, sn, anchor, host in rows:
        data = snapshot(clock_origin + device, sn, anchor)
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
    "condition", ["host_pause", "reset", "wrap", "metadata", "input_gap", "short", "invalid_clock"]
)
def test_ambiguous_or_context_dependent_prefix_is_not_selected(condition):
    items = chunks()
    if condition == "host_pause":
        items = [c._replace(received_monotonic=c.received_monotonic + (60 if i else 0)) for i, c in enumerate(items)]
    elif condition == "reset":
        items[1] = items[1]._replace(data=snapshot(70, 300, 70, reason=11))
    elif condition == "wrap":
        items[0] = items[0]._replace(data=snapshot(4000, 100, 10, os_ms=10_000))
    elif condition == "metadata":
        binding = build_frame(struct.pack("<IB", 1, 3) + b"metadata", 0, 0, xor_checksum)
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


def test_replaced_candidate_uses_the_later_live_check():
    parser = BleLogParser()
    rows = [(10, 100, 10, 0.0), (70, 300, 70, 0.1), (130, 500, 130, 0.2), (131, 501, 131, 1.2), (132, 502, 132, 2.2)]
    offset = 0
    selected_offset = 0
    for i, (device, sn, count, host) in enumerate(rows):
        if i == 2:
            selected_offset = offset
        data = snapshot(device, sn, count)
        parser.feed(data, received_monotonic=host, raw_offset=offset)
        offset += len(data)
    parser.finalize()
    assert parser.opening_quality.offset_bytes == selected_offset
    assert parser.opening_quality.snapshot.parser_frames == 3
    assert parser.opening_quality.snapshot.sequence.missing_frames == 0
    parser.close()


def test_rejected_candidate_releases_checker_resources():
    parser = BleLogParser()
    items = chunks()
    for c in items[:2]:
        parser.feed(c.data, received_monotonic=c.received_monotonic, raw_offset=c.raw_offset)
    checker = parser._opening_checker._checker
    archive = checker.archive_path
    c = items[2]
    parser.feed(snapshot(71, 301, 71, reason=11), received_monotonic=c.received_monotonic, raw_offset=c.raw_offset)
    parser.finalize()
    assert parser.opening_quality is None
    assert not archive.exists()
    parser.close()


def test_selected_check_retains_unknown_frame_warning():
    parser = BleLogParser()
    items = chunks()
    for c in items:
        parser.feed(c.data, received_monotonic=c.received_monotonic, raw_offset=c.raw_offset)
    unknown = build_frame(b"unknown source", 63, 303, xor_checksum)
    parser.feed(unknown, raw_offset=sum(len(c.data) for c in items), received_monotonic=2.2)
    parser.finalize()
    assert parser.opening_quality.snapshot.sequence.uncertain
    parser.close()


@pytest.mark.parametrize("gap", [4045, 8640])
def test_long_opening_gap_uses_both_device_clocks(gap):
    parser = BleLogParser()
    offset = 0
    for device, sn, count, host in [
        (3665.872059, 7691582, 244184, 0.0),
        (3665.872059 + gap, 15047084, 244184 + gap, 0.1),
        (3666.872059 + gap, 15048945, 244185 + gap, 1.1),
        (3667.872059 + gap, 15050660, 244186 + gap, 2.1),
    ]:
        data = snapshot(device, sn, count)
        parser.feed(data, raw_offset=offset, received_monotonic=host)
        offset += len(data)
    decision = parser.startup.finish()
    assert decision.anchor_sn == 15047084
    assert decision.device_jump_sec == gap
    parser.close()


def test_normal_stream_across_both_clock_wraps_keeps_full_recording():
    # At 2**32 ms both the 32-bit millisecond and microsecond clocks wrap.
    items = chunks(stale=False, clock_origin=4_294_956)
    decision, _ = parse_items(items)
    assert decision.offset_bytes == 0
    assert decision.reason == "No confirmed opening backlog"


@pytest.mark.parametrize(
    "sn, count, reason",
    [
        (99, 4055, "Opening time jump has no clear frame boundary"),
        (5000, 9, "Opening clock or sequence is ambiguous"),
        (5000, 11, "Opening time jump lacks sequence evidence"),
    ],
)
def test_wrapped_time_jump_still_needs_distinct_runs_and_anchor_gap(sn, count, reason):
    items = chunks(clock_origin=4250)
    items[1] = items[1]._replace(data=snapshot(4260 + 4045, sn, count))
    decision, _ = parse_items(items[:2])
    assert decision.offset_bytes == 0
    assert decision.reason == reason


@pytest.mark.parametrize("sequence,host_clock", [([11, 90, 12], True), ([11, 50, 90], True), ([11, 90], False)])
def test_ambiguous_packet_boundary_or_missing_receive_time_preserves_prefix(sequence, host_clock):
    blocks = [snapshot(1, 10, 1)]
    blocks.extend(build_frame(struct.pack("<IB", sn, 1) + b"pkt", 6, sn, xor_checksum) for sn in sequence)
    blocks.extend(snapshot(second, sn, second) for sn, second in [(91, 61), (92, 62), (93, 63)])
    parser = BleLogParser()
    try:
        offset = 0
        for i, block in enumerate(blocks):
            received = max(0.0, i - len(sequence) - 1.0) if host_clock else None
            parser.feed(block, received_monotonic=received, raw_offset=offset)
            offset += len(block)
        assert parser.startup.finish().offset_bytes == 0
    finally:
        parser.close()


@pytest.mark.parametrize("case", ["only_snapshots", "clock_disagreement", "steady_clock", "late_old_packet"])
def test_reverse_sequence_jump_alone_cannot_select_a_boundary(case):
    old, new = 6_428_621, 2_733_463
    gap = 1 if case == "steady_clock" else 60

    def packet(sn):
        return build_frame(struct.pack("<IB", 1, 4) + b"pkt", 6, sn, xor_checksum)

    first = snapshot(10, old, 10)
    second = snapshot(10 + gap, new, 10 + gap, os_ms=11_000 if case == "clock_disagreement" else None)
    if case != "only_snapshots":
        first += packet(old + 1)
        second = packet(new - 1) + second
    if case == "late_old_packet":
        second += packet(old)
    blocks = [first, second, snapshot(11 + gap, new + 1, 11 + gap), snapshot(12 + gap, new + 2, 12 + gap)]
    parser = BleLogParser()
    try:
        offset = 0
        for data, received in zip(blocks, (0.0, 0.1, 1.1, 2.1)):
            parser.feed(data, received_monotonic=received, raw_offset=offset)
            offset += len(data)
        assert parser.startup.finish().offset_bytes == 0
        assert parser.finalize().raw_bytes == offset
    finally:
        parser.close()


def test_consecutive_sequence_wrap_is_not_an_opening_boundary():
    parser = BleLogParser()
    try:
        offset = 0
        for sn, seconds, received in [(0xFFFFFE, 10, 0), (0xFFFFFF, 70, 0.1), (0, 71, 1.1), (1, 72, 2.1)]:
            data = snapshot(seconds, sn, seconds)
            parser.feed(data, received_monotonic=received, raw_offset=offset)
            offset += len(data)
        assert parser.startup.finish().offset_bytes == 0
    finally:
        parser.close()
