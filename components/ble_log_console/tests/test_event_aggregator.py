# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import struct
from typing import cast

from ble_log_frame_decoder import (
    FLUSH,
    INIT,
    EnhancedStat,
    InternalLogBufferUtil,
    InternalLogEnhancedStat,
    InternalLogInfo,
    parse_snapshot,
)
from src.backend.analysis.aggregator import CaptureAggregator, frame_size_from_payload
from src.backend.analysis.parser_events import (
    EnhStatEvent,
    FinalStatEvent,
    FrameEvent,
    InternalEvent,
    ParseBatch,
    ParseSummary,
    RedirEvent,
)
from src.backend.models import FRAME_OVERHEAD, BleLogSource, FinalStatEntry, FirmwareCounterSource, InternalSource

from tests.helpers import snapshot_payload


def test_raw_bytes_are_recorded_from_reliable_path_not_parser_batch() -> None:
    aggregator = CaptureAggregator()
    aggregator.record_raw_bytes(120)
    batch = ParseBatch(raw_bytes=300, parsed_frames=0, consumed=300, carried_bytes=4, events=())

    update = aggregator.consume_parser_batch(batch)
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 0
    assert snapshot.stats.transport.rx_bytes == 120
    assert snapshot.parser_raw_bytes == 300
    assert snapshot.parser_frames == 0
    assert snapshot.parser_carried_bytes == 4


def test_regular_frame_updates_received_stats() -> None:
    aggregator = CaptureAggregator()
    payload = struct.pack("<I", 1234) + b"payload"
    frame_size = frame_size_from_payload(payload)

    update = aggregator.consume_events((FrameEvent(frame_size=frame_size, source_code=BleLogSource.HOST, frame_sn=7),))
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert snapshot.stats.transport.rx_frames == 1
    assert snapshot.stats.per_source_rx_bytes == {BleLogSource.HOST: frame_size}


def test_ll_frame_updates_received_stats() -> None:
    aggregator = CaptureAggregator()
    payload = b"\x00\x00" + struct.pack("<I", 555000) + b"ll"
    frame_size = frame_size_from_payload(payload)

    aggregator.consume_events((FrameEvent(frame_size=frame_size, source_code=BleLogSource.LL_TASK, frame_sn=1),))
    snapshot = aggregator.snapshot(1.0)

    assert snapshot.stats.per_source_rx_bytes == {BleLogSource.LL_TASK: frame_size}


def test_redir_event_updates_stats_and_returns_text() -> None:
    aggregator = CaptureAggregator()
    payload = b"console line\n"

    update = aggregator.consume_events(
        (
            RedirEvent(
                frame_size=frame_size_from_payload(payload),
                source_code=BleLogSource.REDIR,
                frame_sn=2,
                text="console line\n",
                received_at_ms=100,
            ),
        )
    )
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert update.redir_events[0].text == "console line\n"
    assert update.redir_events[0].received_at_ms == 100
    assert snapshot.stats.per_source_rx_bytes == {BleLogSource.REDIR: len(payload) + FRAME_OVERHEAD}


def test_internal_info_event_sets_version_and_is_forwarded() -> None:
    aggregator = CaptureAggregator()
    decoded = InternalLogInfo(log_os_ts=10, source=InternalSource.INFO, version=4)
    payload = struct.pack("<I", 10) + bytes([InternalSource.INFO.value, 4])

    update = aggregator.consume_events(
        (
            InternalEvent(
                frame_size=frame_size_from_payload(payload),
                int_src=InternalSource.INFO,
                decoded=decoded,
            ),
        )
    )
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert update.internal_frames[0].int_src == InternalSource.INFO
    assert cast(InternalLogInfo, update.internal_frames[0].decoded).version == 4
    assert snapshot.stats.transport.rx_frames == 1


def test_buf_util_internal_event_updates_buf_util_snapshot() -> None:
    aggregator = CaptureAggregator()
    decoded = InternalLogBufferUtil(
        log_os_ts=11,
        source=InternalSource.BUF_UTIL,
        lbm_id=0x21,
        trans_cnt=9,
        inflight_peak=3,
    )
    payload = struct.pack("<I", 11) + bytes([InternalSource.BUF_UTIL.value, 0x21, 9, 3])

    aggregator.consume_events(
        (
            InternalEvent(
                frame_size=frame_size_from_payload(payload),
                int_src=InternalSource.BUF_UTIL,
                decoded=decoded,
            ),
        )
    )
    snapshot = aggregator.snapshot(1.0)

    assert len(snapshot.buf_util_snapshots) == 1
    assert snapshot.buf_util_snapshots[0].lbm_id == 0x21
    assert snapshot.buf_util_snapshots[0].trans_cnt == 9
    assert snapshot.buf_util_snapshots[0].inflight_peak == 3


def test_enh_stat_event_updates_loss() -> None:
    aggregator = CaptureAggregator()
    payload = struct.pack("<I", 12) + bytes([InternalSource.ENHANCED_STAT.value]) + b"\x00" * 17
    first = InternalLogEnhancedStat(
        log_os_ts=12,
        source=InternalSource.ENHANCED_STAT,
        enhanced_stat=EnhancedStat(
            log_source=BleLogSource.HOST,
            written_frame_cnt=10,
            lost_frame_cnt=0,
            written_bytes_cnt=1000,
            lost_bytes_cnt=0,
        ),
    )
    second = InternalLogEnhancedStat(
        log_os_ts=13,
        source=InternalSource.ENHANCED_STAT,
        enhanced_stat=EnhancedStat(
            log_source=BleLogSource.HOST,
            written_frame_cnt=20,
            lost_frame_cnt=2,
            written_bytes_cnt=2000,
            lost_bytes_cnt=128,
        ),
    )

    aggregator.consume_events((EnhStatEvent(frame_size=frame_size_from_payload(payload), stat=first),))
    update = aggregator.consume_events((EnhStatEvent(frame_size=frame_size_from_payload(payload), stat=second),))
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert update.internal_frames[0].int_src == InternalSource.ENHANCED_STAT
    assert snapshot.stats.loss.total_frames == 2
    assert snapshot.stats.loss.total_bytes == 128


def test_parser_summary_overwrites_final_parser_counters() -> None:
    aggregator = CaptureAggregator()
    aggregator.consume_parser_batch(ParseBatch(raw_bytes=10, parsed_frames=1, consumed=10, carried_bytes=0, events=()))

    aggregator.consume_parser_summary(ParseSummary(raw_bytes=42, parsed_frames=3, carried_bytes=5))

    assert aggregator.parser_raw_bytes == 42
    assert aggregator.parser_frames == 3
    assert aggregator.parser_carried_bytes == 5


def test_final_stat_closes_independent_capture_segments() -> None:
    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=4)
    aggregator.consume_events((InternalEvent(16, InternalSource.INIT_DONE, init),))
    final = FinalStatEvent(
        frame_size=169,
        os_ts_ms=1000,
        entries=(FinalStatEntry(BleLogSource.HOST, 2, 0, 200, 0),),
    )

    aggregator.consume_events(
        (
            FrameEvent(100, BleLogSource.HOST, 0),
            FrameEvent(100, BleLogSource.HOST, 1),
            final,
            FrameEvent(100, BleLogSource.HOST, 0),
            FrameEvent(100, BleLogSource.HOST, 1),
            final._replace(os_ts_ms=2000),
        )
    )
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=738, parsed_frames=7, carried_bytes=0))

    snapshot = aggregator.snapshot(1.0)
    assert snapshot.sequence.segments == 2
    assert snapshot.sequence.duplicate_frames == 0
    assert len(snapshot.capture_segments) == 2
    assert all(segment.complete for segment in snapshot.capture_segments)
    assert snapshot.capture_segments[0].received_frames == 2
    assert snapshot.capture_segments[0].firmware_written_bytes == 200
    assert snapshot.capture_firmware_written_bytes == 400
    assert aggregator.snapshot(1.0, include_segments=False).capture_segments == ()


def test_first_and_last_segments_are_marked_partial_without_boundaries() -> None:
    aggregator = CaptureAggregator()
    aggregator.consume_events((FrameEvent(100, BleLogSource.HOST, 7),))
    aggregator.consume_events(
        (
            FinalStatEvent(
                frame_size=169,
                os_ts_ms=1000,
                entries=(FinalStatEntry(BleLogSource.HOST, 10, 0, 1000, 0),),
            ),
            FrameEvent(100, BleLogSource.HOST, 0),
        )
    )
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=369, parsed_frames=3, carried_bytes=0))

    segments = aggregator.snapshot(1.0).capture_segments
    assert len(segments) == 2
    assert segments[0].final_stat_seen and not segments[0].complete
    assert not segments[1].final_stat_seen and not segments[1].complete


def test_ambiguous_cross_segment_frame_is_retained_and_marked_uncertain() -> None:
    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=4)
    aggregator.consume_events((InternalEvent(16, InternalSource.INIT_DONE, init),))
    final = FinalStatEvent(
        frame_size=169,
        os_ts_ms=1000,
        entries=(FinalStatEntry(BleLogSource.HOST, 1000, 0, 100_000, 0),),
    )
    aggregator.consume_events((FrameEvent(100, BleLogSource.HOST, 998), final))

    aggregator.consume_events(
        (
            FrameEvent(100, BleLogSource.HOST, 0),
            FrameEvent(100, BleLogSource.HOST, 1),
            FrameEvent(100, BleLogSource.HOST, 998),
            FrameEvent(100, BleLogSource.HOST, 2),
            final._replace(os_ts_ms=2000, entries=(FinalStatEntry(BleLogSource.HOST, 3, 0, 300, 0),)),
        )
    )
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=738, parsed_frames=7, carried_bytes=0))

    sequence = aggregator.snapshot(1.0).sequence
    assert sequence.observed_frames == 5
    assert sequence.uncertain


def _snapshot_event(reason_flags: int, frame_sn: int) -> InternalEvent:
    payload = bytearray(snapshot_payload())
    struct.pack_into("<H", payload, 5, reason_flags)
    raw = bytes(payload)
    return InternalEvent(
        frame_size=frame_size_from_payload(raw),
        int_src=InternalSource.SNAPSHOT,
        decoded=parse_snapshot(raw),
        frame_sn=frame_sn,
    )


def test_init_done_sn_starts_the_new_epoch_before_it_is_recorded() -> None:
    """A non-empty old segment must be sealed before the INIT SN is recorded.

    Feeding the new instance's SN 0 into the old window counted it as a
    backward jump, so the sealed segment carried a permanent duplicate/uncertain
    mark into the capture total (review R2).
    """
    aggregator = CaptureAggregator()
    aggregator.consume_events(tuple(FrameEvent(100, BleLogSource.HOST, sn) for sn in (1000, 1001, 1002)))

    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=4)
    aggregator.consume_events((InternalEvent(16, InternalSource.INIT_DONE, init, frame_sn=0),))
    aggregator.consume_events(tuple(FrameEvent(100, BleLogSource.HOST, sn) for sn in (1, 2)))

    sequence = aggregator.snapshot(1.0).sequence

    assert not sequence.uncertain
    assert sequence.duplicate_frames == 0
    assert sequence.missing_frames == 0


def test_v8_init_snapshot_starts_a_new_epoch() -> None:
    """v8 marks the epoch on the SNAPSHOT's INIT flag, not on INIT_DONE (R5)."""
    aggregator = CaptureAggregator()
    aggregator.consume_events(tuple(FrameEvent(100, BleLogSource.HOST, sn) for sn in (1000, 1001, 1002)))

    aggregator.consume_events((_snapshot_event(INIT, 0),))

    sequence = aggregator.snapshot(1.0).sequence

    assert not sequence.uncertain
    assert sequence.duplicate_frames == 0
    assert sequence.missing_frames == 0


def test_flush_snapshot_does_not_cut_the_global_sn_window() -> None:
    """FLUSH only resets ENH baselines; the Global SN keeps running across it."""
    aggregator = CaptureAggregator()
    aggregator.consume_events(
        (
            FrameEvent(100, BleLogSource.HOST, 0),
            FrameEvent(100, BleLogSource.HOST, 1),
            _snapshot_event(FLUSH, 2),
            FrameEvent(100, BleLogSource.HOST, 3),
        )
    )

    sequence = aggregator.snapshot(1.0).sequence

    assert sequence.segments == 1
    assert sequence.missing_frames == 0
    assert not sequence.uncertain


def test_redir_private_sn_cannot_fill_a_core_gap() -> None:
    """REDIR numbers itself from redir->frame_sn, so it cannot fill a core hole (R1)."""
    aggregator = CaptureAggregator()
    aggregator.consume_events(
        (
            FrameEvent(100, BleLogSource.LL_TASK, 0),
            FrameEvent(100, BleLogSource.LL_TASK, 2),
            FrameEvent(100, BleLogSource.LL_TASK, 3),
            RedirEvent(20, BleLogSource.REDIR, 0, "text\n", 1),
            RedirEvent(20, BleLogSource.REDIR, 1, "text\n", 2),
        )
    )
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=420, parsed_frames=5, carried_bytes=0))

    sequence = aggregator.snapshot(1.0).sequence

    assert sequence.missing_frames == 1


def test_a_gap_between_flush_and_final_stat_stays_in_the_segment() -> None:
    """A legacy flush is not the segment boundary; its FINAL_STAT is.

    v6.1 writes FLUSH, then drains, then its FINAL_STAT from the old counters, and
    only then resets them. Sealing at the FLUSH record would cut the window the
    FINAL_STAT still belongs to and report the gap inside it as zero.
    """
    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=5)
    flush = InternalLogInfo(log_os_ts=1, source=InternalSource.FLUSH, version=5)
    aggregator.consume_events(
        (
            InternalEvent(16, InternalSource.INIT_DONE, init, frame_sn=0),
            FrameEvent(100, BleLogSource.HOST, 0),
            FrameEvent(100, BleLogSource.HOST, 1),
            InternalEvent(16, InternalSource.FLUSH, flush, frame_sn=1),
            # INTERNAL frame number 2 never arrived.
            FinalStatEvent(
                frame_size=169, os_ts_ms=1000, entries=(FinalStatEntry(BleLogSource.HOST, 2, 0, 200, 0),), frame_sn=3
            ),
        )
    )

    snapshot = aggregator.snapshot(1.0)

    assert snapshot.sequence.missing_frames == 1
    assert snapshot.capture_segments[0].sequence_missing_frames == 1


def test_frames_without_a_firmware_record_leave_the_contract_unproven() -> None:
    aggregator = CaptureAggregator()
    aggregator.consume_events((FrameEvent(100, BleLogSource.HOST, 0), FrameEvent(100, BleLogSource.HOST, 1)))

    assert aggregator.snapshot(1.0).firmware_contract_known is False


def test_a_firmware_record_proves_the_contract() -> None:
    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=5)
    aggregator.consume_events(
        (
            FrameEvent(100, BleLogSource.HOST, 0),
            InternalEvent(16, InternalSource.INIT_DONE, init, frame_sn=1),
        )
    )

    snapshot = aggregator.snapshot(1.0)

    assert snapshot.firmware_contract_known is True
    assert snapshot.firmware_version == 5


def _enh_stat_event(
    os_ts: int, written_frames: int, lost_frames: int, written_bytes: int, lost_bytes: int
) -> EnhStatEvent:
    payload = struct.pack("<I", os_ts) + bytes([InternalSource.ENHANCED_STAT.value]) + b"\x00" * 17
    return EnhStatEvent(
        frame_size=frame_size_from_payload(payload),
        stat=InternalLogEnhancedStat(
            log_os_ts=os_ts,
            source=InternalSource.ENHANCED_STAT,
            enhanced_stat=EnhancedStat(
                log_source=BleLogSource.HOST,
                written_frame_cnt=written_frames,
                lost_frame_cnt=lost_frames,
                written_bytes_cnt=written_bytes,
                lost_bytes_cnt=lost_bytes,
            ),
        ),
    )


def test_segment_without_a_known_start_reports_its_own_enh_stat_loss() -> None:
    """A capture attached mid-interval never saw the interval start.

    FINAL_STAT has no baseline that segment could be read against, so its own
    ENH_STAT deltas are the loss evidence; the capture total is the sum over the
    segments instead of a separate whole-capture number.
    """

    aggregator = CaptureAggregator()
    aggregator.consume_events(
        (
            _enh_stat_event(1, written_frames=10, lost_frames=0, written_bytes=1000, lost_bytes=0),
            FrameEvent(100, BleLogSource.HOST, 0),
            _enh_stat_event(2, written_frames=20, lost_frames=2, written_bytes=2000, lost_bytes=128),
        )
    )
    final = FinalStatEvent(
        frame_size=169,
        os_ts_ms=3000,
        entries=(FinalStatEntry(BleLogSource.HOST, 3, 5, 300, 500),),
    )
    aggregator.consume_events((FrameEvent(100, BleLogSource.HOST, 1), final))
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=738, parsed_frames=3, carried_bytes=0))

    snapshot = aggregator.snapshot(1.0)

    assert not snapshot.capture_segments[0].complete
    assert snapshot.capture_segments[0].firmware_counters is FirmwareCounterSource.ENH_STAT
    assert snapshot.capture_segments[0].firmware_lost_frames == 2
    # The segment's own ENH_STAT deltas are in the total; its FINAL_STAT entry is not.
    assert snapshot.capture_firmware_written_bytes == 1000
    assert snapshot.capture_firmware_lost_bytes == 128
    assert snapshot.capture_firmware_loss[0].frames == 2


def test_duplicate_final_stat_is_not_counted_twice() -> None:
    """INTERNAL frames have no SN dedup behind them.

    The same FINAL_STAT delivered twice describes one interval. The repeat must
    not add a second segment, a second set of counters, or its SN to the window
    the first arrival already closed — hence the real parser's frame_sn here.
    """

    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=4)
    final = FinalStatEvent(
        frame_size=169,
        os_ts_ms=1000,
        entries=(FinalStatEntry(BleLogSource.HOST, 2, 1, 200, 50),),
        frame_sn=100,
    )
    aggregator.consume_events(
        (InternalEvent(16, InternalSource.INIT_DONE, init), FrameEvent(100, BleLogSource.HOST, 0), final, final)
    )
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=200, parsed_frames=3, carried_bytes=0))

    snapshot = aggregator.snapshot(1.0)

    assert len(snapshot.capture_segments) == 1
    assert snapshot.capture_firmware_written_bytes == 200
    assert snapshot.capture_firmware_lost_bytes == 50
    assert snapshot.capture_firmware_loss[0].frames == 1
    # SN 0 and the FINAL_STAT's own SN 100: the repeat is not a third frame.
    assert snapshot.sequence.observed_frames == 2


def test_the_same_final_stat_in_a_new_epoch_is_a_new_interval() -> None:
    """The dedup identity is scoped to the SN epoch that recorded it.

    Two firmware instances can report the same timestamp and the same counters.
    That is a second interval, not a repeat of the first one, so both must be
    counted.
    """

    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=4)
    final = FinalStatEvent(
        frame_size=169,
        os_ts_ms=1000,
        entries=(FinalStatEntry(BleLogSource.HOST, 200, 50, 2000, 500),),
        frame_sn=100,
    )
    aggregator.consume_events(
        (
            InternalEvent(16, InternalSource.INIT_DONE, init),
            final,
            InternalEvent(16, InternalSource.INIT_DONE, init),
            final,
        )
    )

    snapshot = aggregator.snapshot(1.0)

    assert len(snapshot.capture_segments) == 2
    assert snapshot.capture_firmware_written_bytes == 4000
    assert snapshot.capture_firmware_lost_bytes == 1000


def test_internal_final_stat_entry_is_kept_for_its_own_score() -> None:
    """A legacy FINAL_STAT carries an INTERNAL entry like every other source.

    Dropping it would leave INTERNAL loss unscored; merging it into the customer
    rows would score it as customer data.
    """

    aggregator = CaptureAggregator()
    init = InternalLogInfo(log_os_ts=0, source=InternalSource.INIT_DONE, version=4)
    final = FinalStatEvent(
        frame_size=169,
        os_ts_ms=1000,
        entries=(
            FinalStatEntry(BleLogSource.LL_TASK, 100, 0, 10_000, 0),
            FinalStatEntry(BleLogSource.INTERNAL, 900, 100, 90_000, 10_000),
        ),
        frame_sn=100,
    )
    aggregator.consume_events((InternalEvent(16, InternalSource.INIT_DONE, init), final))
    aggregator.consume_parser_summary(ParseSummary(raw_bytes=200, parsed_frames=2, carried_bytes=0))

    snapshot = aggregator.snapshot(1.0)

    rows = {int(row.source): row for row in snapshot.capture_firmware_loss}
    assert rows[int(BleLogSource.INTERNAL)].frames == 100
    assert rows[int(BleLogSource.INTERNAL)].written_bytes == 90_000
    # A source that lost nothing still gets a row: it is the 0% data point that
    # lets the capture's rate be a number instead of "not enough data".
    assert rows[int(BleLogSource.LL_TASK)].frames == 0
    assert rows[int(BleLogSource.LL_TASK)].written_bytes == 10_000
    assert snapshot.capture_firmware_written_bytes == 100_000
    assert snapshot.capture_firmware_lost_bytes == 10_000
