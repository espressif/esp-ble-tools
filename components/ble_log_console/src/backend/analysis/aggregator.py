# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Aggregate parser events into console-facing statistics updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.backend.analysis.parser_events import BleLogEvent
from src.backend.analysis.parser_events import EnhStatEvent
from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import InternalEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.parser_events import RedirEvent
from src.backend.models import BufUtilEntry
from src.backend.models import BufUtilResult
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import FrameStats
from src.backend.models import FirmwareLossSummary
from src.backend.models import FunnelSnapshot
from src.backend.models import InfoResult
from src.backend.models import InternalDecoderResult
from src.backend.models import InternalSource
from src.backend.models import SequenceSummary
from src.backend.models import TransportBitrate
from src.backend.support.stats import StatsAccumulator


@dataclass(frozen=True)
class InternalFrameUpdate:
    """Decoded INTERNAL frame forwarded to UI/log sinks."""

    int_src: InternalSource
    decoded: InternalDecoderResult


@dataclass(frozen=True)
class AggregatorUpdate:
    """Incremental output produced after consuming parser events."""

    frames_seen: int = 0
    redir_events: tuple[RedirEvent, ...] = ()
    internal_frames: tuple[InternalFrameUpdate, ...] = ()


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
    regular_frames: int = 0
    sequence: SequenceSummary = SequenceSummary()
    capture_firmware_loss: tuple[FirmwareLossSummary, ...] = ()
    capture_firmware_written_bytes: int = 0
    capture_firmware_lost_bytes: int = 0


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
        self._stats.finalize_sequence()

    def consume_events(self, events: tuple[BleLogEvent, ...]) -> AggregatorUpdate:
        """Consume parsed BLE log events and return UI/log-friendly updates."""

        frame_count_before = self._stats.frame_count
        regular_frame_count = 0
        per_source_frames: dict[int, int] = {}
        per_source_bytes: dict[int, int] = {}
        redir_events: list[RedirEvent] = []
        internal_frames: list[InternalFrameUpdate] = []
        stats = self._stats

        def flush_regular_frames() -> None:
            nonlocal regular_frame_count
            if regular_frame_count:
                stats.record_regular_frame_summary(regular_frame_count, per_source_frames, per_source_bytes)
                regular_frame_count = 0
                per_source_frames.clear()
                per_source_bytes.clear()

        for event in events:
            event_type = type(event)
            if event_type is RedirEvent:
                frame_size = event.frame_size
                regular_frame_count += 1
                src_code = event.source_code
                frame_sn = event.frame_sn
                if frame_sn >= 0 and src_code > 0:
                    per_source_frames[src_code] = per_source_frames.get(src_code, 0) + 1
                    per_source_bytes[src_code] = per_source_bytes.get(src_code, 0) + frame_size
                    stats.record_frame_sn(src_code, frame_sn)
                redir_events.append(event)
            elif event_type is FrameEvent:
                frame_size = event.frame_size
                regular_frame_count += 1
                src_code = event.source_code
                frame_sn = event.frame_sn
                if frame_sn >= 0 and src_code > 0:
                    per_source_frames[src_code] = per_source_frames.get(src_code, 0) + 1
                    per_source_bytes[src_code] = per_source_bytes.get(src_code, 0) + frame_size
                    stats.record_frame_sn(src_code, frame_sn)
            elif event_type is EnhStatEvent:
                flush_regular_frames()
                self._record_internal_frame(event.frame_size)
                internal_frames.append(InternalFrameUpdate(int_src=InternalSource.ENH_STAT, decoded=event.stat))
                self._record_enh_stat(event)
            elif event_type is InternalEvent:
                flush_regular_frames()
                self._record_internal_frame(event.frame_size)
                internal_frames.append(InternalFrameUpdate(int_src=event.int_src, decoded=event.decoded))
                self._record_internal_effect(event)

        flush_regular_frames()
        return AggregatorUpdate(
            frames_seen=self._stats.frame_count - frame_count_before,
            redir_events=tuple(redir_events),
            internal_frames=tuple(internal_frames),
        )

    def snapshot(self, elapsed_sec: float) -> AggregatorSnapshot:
        """Harvest periodic stats for UI/log sinks."""

        firmware_written_bytes, firmware_lost_bytes = self._stats.capture_firmware_quality_bytes()
        return AggregatorSnapshot(
            stats=self._stats.snapshot(elapsed_sec),
            funnel_snapshots=tuple(self._stats.funnel_snapshot(elapsed_sec)),
            buf_util_snapshots=tuple(self._stats.buf_util_snapshot()),
            captured_bytes=self._captured_bytes,
            parser_raw_bytes=self._parser_raw_bytes,
            parser_frames=self._parser_frames,
            parser_carried_bytes=self._parser_carried_bytes,
            regular_frames=self._stats.regular_frame_count,
            sequence=self._stats.sequence_snapshot(),
            capture_firmware_loss=self._stats.capture_firmware_loss(),
            capture_firmware_written_bytes=firmware_written_bytes,
            capture_firmware_lost_bytes=firmware_lost_bytes,
        )

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

    def _record_enh_stat(self, event: EnhStatEvent) -> None:
        stat = event.stat
        self._stats.record_enh_stat(
            src_code=stat['src_code'],
            written_frames=stat['written_frame_cnt'],
            lost_frames=stat['lost_frame_cnt'],
            written_bytes=stat['written_bytes_cnt'],
            lost_bytes=stat['lost_bytes_cnt'],
        )


def frame_size_from_payload(payload: bytes) -> int:
    """Return the BLE log wire frame size for a payload."""

    return len(payload) + FRAME_OVERHEAD
