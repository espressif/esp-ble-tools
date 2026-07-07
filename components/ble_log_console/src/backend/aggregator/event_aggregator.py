# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Aggregate parser events into console-facing statistics updates."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import cast

from src.backend.parser.events import BleLogEvent
from src.backend.parser.events import EnhStatEvent
from src.backend.parser.events import FrameEvent
from src.backend.parser.events import InternalEvent
from src.backend.parser.events import ParseBatch
from src.backend.parser.events import ParseSummary
from src.backend.parser.events import RedirEvent
from src.backend.models import BufUtilEntry
from src.backend.models import BufUtilResult
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import FrameStats
from src.backend.models import FunnelSnapshot
from src.backend.models import InfoResult
from src.backend.models import InternalDecoderResult
from src.backend.models import InternalSource
from src.backend.models import LL_TS_OFFSET
from src.backend.models import LL_TS_SIZE
from src.backend.models import LossType
from src.backend.models import ParsedFrame
from src.backend.models import TransportBitrate
from src.backend.models import has_os_ts
from src.backend.models import is_ll_source
from src.backend.models import resolve_source_name
from src.backend.support.stats import StatsAccumulator
from src.backend.support.stats import TrafficSpikeResult


@dataclass(frozen=True)
class InternalFrameUpdate:
    """Decoded INTERNAL frame forwarded to UI/log sinks."""

    int_src: InternalSource
    decoded: InternalDecoderResult


@dataclass(frozen=True)
class FrameLossUpdate:
    """Incremental loss notice derived from firmware statistics."""

    source_name: str
    loss_type: LossType
    lost_frames: int
    lost_bytes: int
    sn_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class AggregatorUpdate:
    """Incremental output produced after consuming parser events."""

    frames_seen: int = 0
    redir_texts: tuple[str, ...] = ()
    internal_frames: tuple[InternalFrameUpdate, ...] = ()
    frame_losses: tuple[FrameLossUpdate, ...] = ()
    traffic_spikes: tuple[TrafficSpikeResult, ...] = ()


@dataclass(frozen=True)
class AggregatorSnapshot:
    """Periodic snapshot of all console statistics owned by the aggregator."""

    stats: FrameStats
    funnel_snapshots: tuple[FunnelSnapshot, ...]
    buf_util_snapshots: tuple[BufUtilEntry, ...]
    captured_bytes: int
    parser_raw_bytes: int
    parser_frames: int
    parser_carried_bytes: int


class CaptureAggregator:
    """Consume BLE log parser events and update shared statistics components.

    The reliable raw byte count is intentionally fed through record_raw_bytes().
    ParseBatch.raw_bytes only tells us what the best-effort parser has seen.
    """

    def __init__(self, bitrate: TransportBitrate | None = None) -> None:
        self._stats = StatsAccumulator()
        if bitrate is not None:
            self._stats.set_transport_bitrate(bitrate)
        self._captured_bytes = 0
        self._parser_raw_bytes = 0
        self._parser_frames = 0
        self._parser_carried_bytes = 0

    @property
    def captured_bytes(self) -> int:
        return self._captured_bytes

    @property
    def parser_raw_bytes(self) -> int:
        return self._parser_raw_bytes

    @property
    def parser_frames(self) -> int:
        return self._parser_frames

    @property
    def parser_carried_bytes(self) -> int:
        return self._parser_carried_bytes

    @property
    def frame_count(self) -> int:
        return self._stats.frame_count

    def set_transport_bitrate(self, bitrate: TransportBitrate) -> None:
        self._stats.set_transport_bitrate(bitrate)

    def record_raw_bytes(self, count: int) -> None:
        """Record bytes from the reliable capture path."""

        if count <= 0:
            return
        self._captured_bytes += count
        self._stats.record_bytes(count)

    def consume_parser_batch(self, batch: ParseBatch) -> AggregatorUpdate:
        """Consume one parser batch without treating parser bytes as saved bytes."""

        self._parser_raw_bytes += batch.raw_bytes
        self._parser_frames += batch.parsed_frames
        self._parser_carried_bytes = batch.carried_bytes
        return self.consume_events(batch.events)

    def consume_parser_summary(self, summary: ParseSummary) -> None:
        """Store final parser counters emitted on parser shutdown."""

        self._parser_raw_bytes = summary.raw_bytes
        self._parser_frames = summary.parsed_frames
        self._parser_carried_bytes = summary.carried_bytes

    def consume_events(self, events: tuple[BleLogEvent, ...]) -> AggregatorUpdate:
        """Consume parsed BLE log events and return UI/log-friendly updates."""

        frame_count_before = self._stats.frame_count
        redir_texts: list[str] = []
        internal_frames: list[InternalFrameUpdate] = []
        frame_losses: list[FrameLossUpdate] = []

        for event in events:
            if isinstance(event, RedirEvent):
                self._record_regular_frame(event.frame, event.frame_size, wall_ms=event.wall_ms)
                redir_texts.append(event.text)
            elif isinstance(event, FrameEvent):
                self._record_regular_frame(event.frame, event.frame_size)
            elif isinstance(event, EnhStatEvent):
                self._record_internal_frame(event.frame_size)
                internal_frames.append(InternalFrameUpdate(int_src=InternalSource.ENH_STAT, decoded=event.stat))
                self._record_enh_stat(event, frame_losses)
            elif isinstance(event, InternalEvent):
                self._record_internal_frame(event.frame_size)
                internal_frames.append(InternalFrameUpdate(int_src=event.int_src, decoded=event.decoded))
                self._record_internal_effect(event)

        traffic_spike = self._stats.check_traffic()
        traffic_spikes = () if traffic_spike is None else (traffic_spike,)
        return AggregatorUpdate(
            frames_seen=self._stats.frame_count - frame_count_before,
            redir_texts=tuple(redir_texts),
            internal_frames=tuple(internal_frames),
            frame_losses=tuple(frame_losses),
            traffic_spikes=traffic_spikes,
        )

    def snapshot(self, elapsed_sec: float) -> AggregatorSnapshot:
        """Harvest periodic stats for UI/log sinks."""

        return AggregatorSnapshot(
            stats=self._stats.snapshot(elapsed_sec),
            funnel_snapshots=tuple(self._stats.funnel_snapshot(elapsed_sec)),
            buf_util_snapshots=tuple(self._stats.buf_util_snapshot()),
            captured_bytes=self._captured_bytes,
            parser_raw_bytes=self._parser_raw_bytes,
            parser_frames=self._parser_frames,
            parser_carried_bytes=self._parser_carried_bytes,
        )

    def _record_regular_frame(self, frame: ParsedFrame, frame_size: int, *, wall_ms: int | None = None) -> None:
        self._stats.record_frame(frame_size, frame.source_code, frame.frame_sn)
        self._stats.record_frame_traffic(frame_size, frame.source_code)

        if has_os_ts(frame.source_code):
            self._stats.record_frame_ts(frame.os_ts_ms, frame_size, frame.source_code)
        elif is_ll_source(frame.source_code) and len(frame.payload) >= LL_TS_OFFSET + LL_TS_SIZE:
            (lc_ts_us,) = struct.unpack_from('<I', frame.payload, LL_TS_OFFSET)
            self._stats.record_ll_frame_ts(lc_ts_us, frame_size, frame.source_code)
        elif wall_ms is not None:
            self._stats.record_frame_wall_ts(wall_ms, frame_size, frame.source_code)

    def _record_internal_frame(self, frame_size: int) -> None:
        # INTERNAL frames count for transport FPS, but not per-source SN tracking.
        self._stats.record_frame(frame_size=frame_size)

    def _record_internal_effect(self, event: InternalEvent) -> None:
        if event.int_src in (InternalSource.INIT_DONE, InternalSource.INFO):
            info = cast(InfoResult, event.decoded)
            self._stats.set_firmware_version(info['version'])
        if event.int_src == InternalSource.INIT_DONE:
            self._stats.reset('init')
        elif event.int_src == InternalSource.FLUSH:
            self._stats.reset('flush')
        elif event.int_src == InternalSource.BUF_UTIL:
            buf = cast(BufUtilResult, event.decoded)
            self._stats.record_buf_util(
                lbm_id=buf['lbm_id'],
                trans_cnt=buf['trans_cnt'],
                inflight_peak=buf['inflight_peak'],
            )

    def _record_enh_stat(self, event: EnhStatEvent, frame_losses: list[FrameLossUpdate]) -> None:
        stat = event.stat
        new_frames, new_bytes = self._stats.record_enh_stat(
            src_code=stat['src_code'],
            written_frames=stat['written_frame_cnt'],
            lost_frames=stat['lost_frame_cnt'],
            written_bytes=stat['written_bytes_cnt'],
            lost_bytes=stat['lost_bytes_cnt'],
        )
        if new_frames > 0:
            frame_losses.append(
                FrameLossUpdate(
                    source_name=resolve_source_name(stat['src_code']),
                    loss_type=LossType.BUFFER,
                    lost_frames=new_frames,
                    lost_bytes=new_bytes,
                )
            )


def frame_size_from_payload(payload: bytes) -> int:
    """Return the BLE log wire frame size for a payload."""

    return len(payload) + FRAME_OVERHEAD
