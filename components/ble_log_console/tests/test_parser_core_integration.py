# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Core ownership through Console's real parser, aggregator and process messages."""

import pickle
from queue import Queue

import pytest
from ble_log_frame_decoder import ParserSession
from rich.console import Console
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import ParseBatch, ParseSummary, ReceivedChunk
from src.backend.analysis.worker import run_parser_loop
from src.frontend.capture_report import _firmware_source_rates
from src.frontend.stats_screen import _build_firmware_table

from tests.helpers import build_frame, enh_stat_payload, snapshot_payload, version_info_payload, xor_checksum


def frame(payload, source=0, sn=0):
    return build_frame(payload, source, sn, xor_checksum)


@pytest.mark.parametrize("chunk_size", [1, 7, 65536])
def test_live_and_final_firmware_observed_counts_are_core_owned(chunk_size):
    data = b"".join(
        [
            frame(version_info_payload(0, version=6)),
            frame(enh_stat_payload(1, 5, 100, 10, 10000, 1000), sn=1),
            frame(enh_stat_payload(2, 5, 110, 11, 11000, 1100), sn=2),
        ]
    )
    parser, aggregator = BleLogParser(), CaptureAggregator()
    with ParserSession(firmware_stats=True) as reference:
        for i in range(0, len(data), chunk_size):
            chunk = data[i : i + chunk_size]
            reference.feed(chunk)
            batch = pickle.loads(pickle.dumps(parser.feed(chunk)))
            aggregator.consume_parser_batch(batch)
        live = aggregator.snapshot(1)
        assert live.firmware == reference.snapshot().firmware
        row = live.capture_firmware_loss[0]
        assert (row.written_bytes, row.bytes, row.written_frames, row.frames) == (1000, 100, 10, 1)
        assert live.funnel_snapshots[0].written.bytes == 11000
        assert live.funnel_snapshots[0].buffer_loss.bytes == 1100
        aggregator.consume_parser_summary(pickle.loads(pickle.dumps(parser.finalize())))
        final = aggregator.snapshot(0)
        expected = reference.finish()
        assert final.integrity.to_dict() == expected.integrity.to_dict()
        assert final.firmware == expected.firmware
        assert final.capture_firmware_loss == live.capture_firmware_loss


def test_v8_unknown_lost_bytes_survive_to_ui_and_rate():
    parser, aggregator = BleLogParser(), CaptureAggregator()
    aggregator.consume_parser_batch(parser.feed(frame(snapshot_payload())))
    aggregator.consume_parser_summary(parser.finalize())
    snapshot = aggregator.snapshot(1)
    assert snapshot.capture_firmware_loss
    assert all(row.bytes is None for row in snapshot.capture_firmware_loss)
    assert snapshot.capture_firmware_lost_bytes is None
    assert _firmware_source_rates(snapshot.capture_firmware_loss) == ()
    console = Console(record=True, width=160)
    console.print(_build_firmware_table(list(snapshot.funnel_snapshots)))
    assert "Unknown" in console.export_text() or "未知" in console.export_text()


def test_worker_batch_merge_keeps_firmware_and_final_integrity():
    incoming, outgoing = Queue(), Queue()
    incoming.put(ReceivedChunk(frame(enh_stat_payload(1, 5, 10, 0, 100, 0)), 0))
    incoming.put(ReceivedChunk(frame(enh_stat_payload(2, 5, 20, 1, 200, 10), sn=1), 1))
    incoming.put(None)
    run_parser_loop(incoming, outgoing)
    events = []
    while not outgoing.empty():
        events.append(outgoing.get_nowait())
    batches = [event for event in events if isinstance(event, ParseBatch)]
    summaries = [event for event in events if isinstance(event, ParseSummary)]
    assert batches[-1].firmware.sources[0].observed.written_bytes_cnt == 100
    assert summaries[0].firmware == batches[-1].firmware
    assert summaries[0].integrity is not None


def test_unknown_frame_is_preserved_without_aborting_following_valid_frames():
    parser = BleLogParser()
    batch = parser.feed(frame(b"unknown", 99) + frame(version_info_payload(1, version=6), sn=1))
    assert batch.parsed_frames == 2
    assert batch.events[0].source_code == 99
    result = parser.finalize()
    assert result.parsed_frames == 2
    assert any("outside the Checker protocol contract" in note for note in result.integrity.notes)


def test_v8_snapshot_contains_version_and_uses_global_sn():
    parser, aggregator = BleLogParser(), CaptureAggregator()
    data = b"".join(
        [
            frame(b"data", source=2, sn=0),
            frame(b"data", source=3, sn=1),
            frame(snapshot_payload(reason_flags=0b1010), sn=2),
            frame(b"data", source=2, sn=3),
            frame(b"data", source=3, sn=4),
        ]
    )
    aggregator.consume_parser_batch(parser.feed(data))
    aggregator.consume_parser_summary(parser.finalize())
    snapshot = aggregator.snapshot(1)
    assert snapshot.sequence.missing_frames == 0
    assert not snapshot.sequence.per_source


def test_sum32_unknown_frames_keep_wire_order():
    from src.backend.models import ChecksumAlgorithm, ChecksumMode, ChecksumScope

    from tests.helpers import sum_checksum

    parser = BleLogParser(ChecksumMode(ChecksumAlgorithm.SUM, ChecksumScope.FULL))
    batch = parser.feed(b"".join(build_frame(b"data", source, i, sum_checksum) for i, source in enumerate((2, 99, 3))))
    from src.backend.analysis.parser_events import FrameEvent

    assert [event.source_code for event in batch.events if isinstance(event, FrameEvent)] == [2, 99, 3]
    assert parser.finalize().parsed_frames == 3


def test_reboot_keeps_recording_totals_and_reception_but_resets_latest_counters():
    from tests.helpers import internal_payload

    parser, aggregator = BleLogParser(), CaptureAggregator()
    payloads = [
        internal_payload(1, 0, b"\x04"),
        enh_stat_payload(2, 5, 10, 1, 1000, 100),
        internal_payload(3, 0, b"\x04"),
        enh_stat_payload(4, 5, 20, 2, 2000, 200),
    ]
    for sn, payload in enumerate(payloads):
        raw = frame(payload, sn=sn)
        aggregator.record_raw_bytes(len(raw))
        aggregator.consume_parser_batch(parser.feed(raw))
    aggregator.consume_parser_summary(parser.finalize())
    final = aggregator.snapshot(1)
    assert final.stats.transport.rx_frames == 4
    assert final.stats.transport.rx_bytes == final.parser_raw_bytes
    assert final.capture_firmware_written_bytes == 3000
    assert final.capture_firmware_lost_bytes == 300
    assert final.funnel_snapshots[0].written.bytes == 2000
    assert final.firmware.epoch == 2
