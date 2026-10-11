# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Stream content identification from original parser input."""

from __future__ import annotations

import random
import struct
from queue import Queue
from typing import Any

import pytest
from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import InternalEvent, ParseBatch, ParseSummary, ReceivedChunk
from src.backend.analysis.stream_identification import (
    DEFAULT_IDENTIFICATION_RULES,
    IdentificationRules,
    StreamIdentity,
    StreamKind,
)
from src.backend.analysis.worker import run_analysis_loop, run_parser_loop
from src.backend.models import FRAME_HEADER_SIZE, BleLogSource, InternalSource

from tests.helpers import build_frame, internal_payload, snapshot_payload, xor_checksum

BOOT_TEXT = b"".join(
    b"\x1b[0;32mI (%d) boot: loading partition table entry %d\x1b[0m\r\n" % (index * 7, index) for index in range(12)
)
UNKNOWN_SOURCE = 0x55
# The decoder needs a whole header to reject a candidate, so it still holds this much text at EOF. That carry
# may be a cut-off frame: it is reported as carried bytes, not counted as data outside frames.
TEXT_EOF_CARRY = FRAME_HEADER_SIZE - 1


def _frame(payload: bytes, source: int = BleLogSource.HOST, sn: int = 0) -> bytes:
    return build_frame(payload, source, sn, xor_checksum)


def _regular_frames(count: int, start_sn: int = 0) -> bytes:
    return b"".join(_frame(b"\x00\x00\x00\x00log", BleLogSource.HOST, start_sn + sn) for sn in range(count))


def _identify(data: bytes, chunk_size: int = 4096, rules: IdentificationRules = DEFAULT_IDENTIFICATION_RULES) -> Any:
    parser = BleLogParser(identification=rules)
    for start in range(0, len(data), chunk_size):
        parser.feed(data[start : start + chunk_size], received_at_ms=1)
    return parser.finalize().identity


def _islands_in_binary(seed: int = 7, size: int = 3000) -> bytes:
    noise = bytearray(random.Random(seed).randbytes(size))
    for offset in range(0, size - 16, 97):
        noise[offset : offset + 12] = b"ASSERT line\n"
    return bytes(noise)


def test_no_input_is_distinct_from_unrecognized_input() -> None:
    assert _identify(b"").kind is StreamKind.NO_INPUT
    assert _identify(b"\x00\x01\x02").kind is StreamKind.UNRECOGNIZED


@pytest.mark.parametrize("chunk_size", [1, 7, 4096])
def test_persistent_plain_text_is_likely_text_and_chunking_does_not_change_the_result(chunk_size: int) -> None:
    identity = _identify(BOOT_TEXT * 4, chunk_size)

    assert identity.kind is StreamKind.LIKELY_TEXT
    assert identity == _identify(BOOT_TEXT * 4, 4096)
    assert identity.evidence.gap_bytes == len(BOOT_TEXT * 4) - TEXT_EOF_CARRY
    assert identity.evidence.window_bytes == len(BOOT_TEXT * 4)
    assert identity.evidence.window_line_breaks == 48
    assert identity.evidence.known_frames == 0


def test_text_below_the_byte_or_line_threshold_stays_unrecognized() -> None:
    assert _identify(b"I (1) boot: short line\r\n" * 3).kind is StreamKind.UNRECOGNIZED
    assert _identify(b"x" * 1024).kind is StreamKind.UNRECOGNIZED


def test_corrupt_binary_with_ascii_islands_is_not_text() -> None:
    data = _islands_in_binary()
    parser = BleLogParser(identification=DEFAULT_IDENTIFICATION_RULES)
    batch = parser.feed(data)
    summary = parser.finalize()

    assert batch.parsed_frames == 0
    assert summary.identity is not None
    assert summary.identity.kind is StreamKind.UNRECOGNIZED
    assert summary.identity.evidence.gap_bytes + summary.carried_bytes == len(data)


def test_three_known_source_frames_identify_ble_log_and_two_do_not() -> None:
    assert _identify(_regular_frames(2)).kind is StreamKind.UNRECOGNIZED
    assert _identify(_regular_frames(3)).kind is StreamKind.BLE_LOG


def test_unknown_source_frames_are_decoded_but_never_identify_ble_log() -> None:
    data = b"".join(_frame(b"\x00\x00\x00\x00raw", UNKNOWN_SOURCE, sn) for sn in range(10))
    parser = BleLogParser(identification=DEFAULT_IDENTIFICATION_RULES)

    batch = parser.feed(data)

    assert batch.parsed_frames == 10
    assert batch.identity is not None
    assert batch.identity.kind is StreamKind.UNRECOGNIZED
    assert batch.identity.evidence.known_frames == 0


def test_empty_known_source_frames_do_not_identify_ble_log() -> None:
    assert _identify(b"".join(_frame(b"", BleLogSource.HOST, sn) for sn in range(5))).kind is StreamKind.UNRECOGNIZED


def test_one_valid_snapshot_identifies_ble_log_without_regular_frames() -> None:
    identity = _identify(_frame(snapshot_payload(), BleLogSource.INTERNAL))

    assert identity.kind is StreamKind.BLE_LOG
    assert identity.evidence.identity_records == 1


@pytest.mark.parametrize(
    "payload",
    [
        snapshot_payload(version_block=b"\x00" * 58),
        internal_payload(0, InternalSource.INFO, b"\x00"),
        internal_payload(0, InternalSource.TIMESTAMP, b"\x00" * 13),
    ],
    ids=["snapshot-unreadable-version", "info-version-zero", "timestamp"],
)
def test_decoded_internal_records_without_a_readable_nonzero_version_are_not_identity(payload: bytes) -> None:
    parser = BleLogParser(identification=DEFAULT_IDENTIFICATION_RULES)
    batch = parser.feed(_frame(payload, BleLogSource.INTERNAL))

    assert [type(event) for event in batch.events] == [InternalEvent]
    assert batch.identity is not None
    assert batch.identity.evidence.identity_records == 0
    assert batch.identity.evidence.known_frames == 1
    assert batch.identity.kind is StreamKind.UNRECOGNIZED


def test_info_record_with_a_nonzero_version_is_identity() -> None:
    identity = _identify(_frame(internal_payload(0, InternalSource.INFO, b"\x03"), BleLogSource.INTERNAL))

    assert identity.evidence.identity_records == 1
    assert identity.kind is StreamKind.BLE_LOG


def test_startup_text_then_ble_log_becomes_ble_log_and_keeps_the_text_as_pre_identification_gap() -> None:
    parser = BleLogParser(identification=DEFAULT_IDENTIFICATION_RULES)
    text = parser.feed(BOOT_TEXT * 2).identity
    ble = parser.feed(_regular_frames(3)).identity

    assert text is not None and text.kind is StreamKind.LIKELY_TEXT
    assert ble is not None and ble.kind is StreamKind.BLE_LOG
    assert ble.evidence.gap_bytes == len(BOOT_TEXT * 2)
    assert ble.evidence.gap_bytes_after_ble == 0


def test_redir_text_is_inside_ble_log_not_plain_text() -> None:
    data = b"".join(_frame(b"I (1) app: redirected line\r\n", BleLogSource.REDIR, sn) for sn in range(40))

    identity = _identify(data)

    assert identity.kind is StreamKind.BLE_LOG
    assert identity.evidence.gap_bytes == 0


def test_quiet_or_later_text_never_turns_ble_log_back_into_text() -> None:
    parser = BleLogParser(identification=DEFAULT_IDENTIFICATION_RULES)
    parser.feed(_regular_frames(3))
    quiet = parser.feed(b"").identity
    later = parser.feed(BOOT_TEXT * 4).identity
    summary = parser.finalize()
    final = summary.identity

    for identity in (quiet, later, final):
        assert identity is not None and identity.kind is StreamKind.BLE_LOG
    assert final is not None
    assert summary.carried_bytes == TEXT_EOF_CARRY
    assert final.evidence.gap_bytes_after_ble == len(BOOT_TEXT * 4) - TEXT_EOF_CARRY


def test_a_frame_empties_the_window_so_separate_text_runs_do_not_add_up() -> None:
    run = BOOT_TEXT[:200]
    data = b"".join(run + _frame(b"\x00\x00\x00\x00raw", UNKNOWN_SOURCE, sn) for sn in range(6)) + run

    identity = _identify(data)

    assert identity.evidence.gap_bytes == 7 * len(run) - TEXT_EOF_CARRY
    assert identity.kind is StreamKind.UNRECOGNIZED


def test_recent_window_lets_text_after_a_binary_burst_be_recognized() -> None:
    data = random.Random(3).randbytes(8000).replace(b"\x00", b"\x01") + BOOT_TEXT * 8

    identity = _identify(data)

    assert identity.evidence.window_bytes == DEFAULT_IDENTIFICATION_RULES.window_bytes
    assert identity.kind is StreamKind.LIKELY_TEXT


def test_custom_rules_change_the_decision() -> None:
    short = b"ok\r\nok\r\n"
    assert _identify(short).kind is StreamKind.UNRECOGNIZED
    rules = IdentificationRules(window_bytes=64, min_text_bytes=8, min_text_lines=2)
    assert _identify(short, rules=rules).kind is StreamKind.LIKELY_TEXT


@pytest.mark.parametrize(
    "overrides",
    [
        {"window_bytes": 0},
        {"min_text_bytes": -1},
        {"min_text_lines": 0},
        {"min_known_frames": 0},
        {"min_identity_records": 0},
        {"window_bytes": 1.5},
        {"min_printable_ratio": 1.01},
        {"min_printable_ratio": -0.1},
        {"min_printable_ratio": float("nan")},
        {"min_printable_ratio": float("inf")},
        {"window_bytes": 128, "min_text_bytes": 256},
    ],
)
def test_invalid_rules_are_rejected_at_construction(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        IdentificationRules(**overrides)


def test_parser_without_rules_keeps_no_identity_and_no_text() -> None:
    parser = BleLogParser()
    batch = parser.feed(BOOT_TEXT + _regular_frames(3))
    summary = parser.finalize()

    assert batch.identity is None and summary.identity is None
    assert summary.events == ()
    assert all(type(event).__name__ == "FrameEvent" for event in batch.events)


def _run_parser_loop(chunks: list[bytes]) -> list[ParseBatch | ParseSummary]:
    incoming: Queue[Any] = Queue()
    outgoing: Queue[Any] = Queue()
    for chunk in chunks:
        incoming.put(ReceivedChunk(chunk, 1))
    incoming.put(None)
    run_parser_loop(incoming, outgoing, identification=DEFAULT_IDENTIFICATION_RULES)
    items = []
    while not outgoing.empty():
        items.append(outgoing.get_nowait())
    return items


def test_worker_batching_and_eof_carry_the_same_identity_as_direct_parsing() -> None:
    data = BOOT_TEXT * 3 + _regular_frames(5) + b"\xfe" * 40 + BOOT_TEXT
    chunks = [data[start : start + 13] for start in range(0, len(data), 13)]
    expected = _identify(data)

    items = _run_parser_loop(chunks)

    batches = [item for item in items if isinstance(item, ParseBatch)]
    summary = items[-1]
    assert isinstance(summary, ParseSummary)
    assert len(batches) < len(chunks)
    assert summary.identity == expected
    seen = 0
    for batch in batches:
        seen += batch.raw_bytes
        assert batch.identity is not None
        assert batch.identity.evidence.received_bytes == seen


def test_analysis_loop_final_snapshot_carries_the_parser_identity() -> None:
    data = struct.pack("<I", 0) + BOOT_TEXT * 2 + _frame(snapshot_payload(), BleLogSource.INTERNAL)
    incoming: Queue[Any] = Queue()
    counts: Queue[Any] = Queue()
    outgoing: Queue[Any] = Queue()
    for start in range(0, len(data), 64):
        incoming.put(ReceivedChunk(data[start : start + 64], 1))
    incoming.put(None)
    counts.put(len(data))
    counts.put(None)

    run_analysis_loop(incoming, counts, outgoing, identification=DEFAULT_IDENTIFICATION_RULES)

    snapshots = []
    while not outgoing.empty():
        event = outgoing.get_nowait()
        if isinstance(event, AggregatorSnapshot):
            snapshots.append(event)
    final = snapshots[-1].stream_identity
    assert isinstance(final, StreamIdentity)
    assert final == _identify(data)
    assert final.kind is StreamKind.BLE_LOG
    assert snapshots[-1].regular_frames == 0
