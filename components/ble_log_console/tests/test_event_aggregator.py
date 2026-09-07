# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import struct
from typing import cast

from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.aggregator import frame_size_from_payload
from src.backend.analysis.parser_events import EnhStatEvent
from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import InternalEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.parser_events import RedirEvent
from src.backend.models import BleLogSource
from src.backend.models import BufUtilResult
from src.backend.models import EnhStatResult
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import InfoResult
from src.backend.models import InternalSource
from src.backend.models import LossType


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
    payload = struct.pack('<I', 1234) + b'payload'
    frame_size = frame_size_from_payload(payload)

    update = aggregator.consume_events(
        (FrameEvent(frame_size=frame_size, source_code=BleLogSource.HOST, frame_sn=7),)
    )
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert snapshot.stats.transport.rx_frames == 1
    assert snapshot.stats.per_source_rx_bytes == {BleLogSource.HOST: frame_size}


def test_ll_frame_updates_received_stats() -> None:
    aggregator = CaptureAggregator()
    payload = b'\x00\x00' + struct.pack('<I', 555000) + b'll'
    frame_size = frame_size_from_payload(payload)

    aggregator.consume_events(
        (FrameEvent(frame_size=frame_size, source_code=BleLogSource.LL_TASK, frame_sn=1),)
    )
    snapshot = aggregator.snapshot(1.0)

    assert snapshot.stats.per_source_rx_bytes == {BleLogSource.LL_TASK: frame_size}


def test_redir_event_updates_stats_and_returns_text() -> None:
    aggregator = CaptureAggregator()
    payload = b'console line\n'

    update = aggregator.consume_events(
        (
            RedirEvent(
                frame_size=frame_size_from_payload(payload),
                source_code=BleLogSource.REDIR,
                frame_sn=2,
                text='console line\n',
                received_at_ms=100,
            ),
        )
    )
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert update.redir_events[0].text == 'console line\n'
    assert update.redir_events[0].received_at_ms == 100
    assert snapshot.stats.per_source_rx_bytes == {BleLogSource.REDIR: len(payload) + FRAME_OVERHEAD}


def test_internal_info_event_sets_version_and_is_forwarded() -> None:
    aggregator = CaptureAggregator()
    decoded = InfoResult(int_src=InternalSource.INFO, version=4, os_ts_ms=10)
    payload = struct.pack('<I', 10) + bytes([InternalSource.INFO, 4])

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
    assert cast(InfoResult, update.internal_frames[0].decoded)['version'] == 4
    assert snapshot.stats.transport.rx_frames == 1


def test_buf_util_internal_event_updates_buf_util_snapshot() -> None:
    aggregator = CaptureAggregator()
    decoded = BufUtilResult(
        int_src=InternalSource.BUF_UTIL,
        lbm_id=0x21,
        pool=2,
        index=1,
        trans_cnt=9,
        inflight_peak=3,
        os_ts_ms=11,
    )
    payload = struct.pack('<I', 11) + bytes([InternalSource.BUF_UTIL, 0x21, 9, 3])

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


def test_enh_stat_event_updates_loss_and_emits_loss_update() -> None:
    aggregator = CaptureAggregator()
    payload = struct.pack('<I', 12) + bytes([InternalSource.ENH_STAT]) + b'\x00' * 17
    first = EnhStatResult(
        int_src=InternalSource.ENH_STAT,
        src_code=BleLogSource.HOST,
        written_frame_cnt=10,
        lost_frame_cnt=0,
        written_bytes_cnt=1000,
        lost_bytes_cnt=0,
        os_ts_ms=12,
    )
    second = EnhStatResult(
        int_src=InternalSource.ENH_STAT,
        src_code=BleLogSource.HOST,
        written_frame_cnt=20,
        lost_frame_cnt=2,
        written_bytes_cnt=2000,
        lost_bytes_cnt=128,
        os_ts_ms=13,
    )

    aggregator.consume_events((EnhStatEvent(frame_size=frame_size_from_payload(payload), stat=first),))
    update = aggregator.consume_events((EnhStatEvent(frame_size=frame_size_from_payload(payload), stat=second),))
    snapshot = aggregator.snapshot(1.0)

    assert update.frames_seen == 1
    assert update.internal_frames[0].int_src == InternalSource.ENH_STAT
    assert len(update.frame_losses) == 1
    assert update.frame_losses[0].source_name == 'HOST'
    assert update.frame_losses[0].loss_type == LossType.BUFFER
    assert update.frame_losses[0].lost_frames == 2
    assert update.frame_losses[0].lost_bytes == 128
    assert snapshot.stats.loss.total_frames == 2
    assert snapshot.stats.loss.total_bytes == 128


def test_parser_summary_overwrites_final_parser_counters() -> None:
    aggregator = CaptureAggregator()
    aggregator.consume_parser_batch(ParseBatch(raw_bytes=10, parsed_frames=1, consumed=10, carried_bytes=0, events=()))

    aggregator.consume_parser_summary(ParseSummary(raw_bytes=42, parsed_frames=3, carried_bytes=5))

    assert aggregator.parser_raw_bytes == 42
    assert aggregator.parser_frames == 3
    assert aggregator.parser_carried_bytes == 5
