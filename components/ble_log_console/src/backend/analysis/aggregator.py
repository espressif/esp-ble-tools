# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Aggregate parser events into console-facing statistics updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.backend.analysis.parser_events import BleLogEvent
from src.backend.analysis.parser_events import EnhStatEvent
from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import FinalStatEvent
from src.backend.analysis.parser_events import InternalEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.parser_events import RedirEvent
from src.backend.models import BufUtilEntry
from src.backend.models import BufUtilResult
from src.backend.models import CaptureSegmentSummary
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import FrameStats
from src.backend.models import FirmwareLossSummary
from src.backend.models import FunnelSnapshot
from src.backend.models import InternalDecoderResult
from src.backend.models import InternalSource
from src.backend.models import SequenceSummary
from src.backend.models import TransportBitrate
from src.backend.support.stats import StatsAccumulator
from src.backend.support.stats.accumulator import merge_sequence_summaries


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
    capture_segments: tuple[CaptureSegmentSummary, ...] = ()


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
        self._segments: list[CaptureSegmentSummary] = []
        self._segment_regular_frames = 0
        self._segment_regular_bytes = 0
        self._segment_start_known = False
        self._final_stat_seen = False
        self._final_written_bytes = 0
        self._final_loss: dict[int, tuple[int, int]] = {}
        self._complete_sequence = SequenceSummary()

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
        self._close_pending_segment()

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
            if event_type in (RedirEvent, FrameEvent):
                frame_size = event.frame_size
                regular_frame_count += 1
                src_code = event.source_code
                frame_sn = event.frame_sn
                self._segment_regular_frames += 1
                self._segment_regular_bytes += frame_size
                if frame_sn >= 0 and src_code > 0:
                    per_source_frames[src_code] = per_source_frames.get(src_code, 0) + 1
                    per_source_bytes[src_code] = per_source_bytes.get(src_code, 0) + frame_size
                    stats.record_frame_sn(src_code, frame_sn)
                if event_type is RedirEvent:
                    redir_events.append(event)
            elif event_type is EnhStatEvent:
                flush_regular_frames()
                self._record_internal_frame(event.frame_size)
                internal_frames.append(InternalFrameUpdate(int_src=InternalSource.ENH_STAT, decoded=event.stat))
                self._record_enh_stat(event)
            elif event_type is FinalStatEvent:
                flush_regular_frames()
                self._record_internal_frame(event.frame_size)
                self._close_final_stat_segment(event)
            elif event_type is InternalEvent:
                flush_regular_frames()
                self._record_internal_frame(event.frame_size)
                if event.int_src == InternalSource.INIT_DONE:
                    self._close_pending_segment()
                    self._segment_start_known = True
                internal_frames.append(InternalFrameUpdate(int_src=event.int_src, decoded=event.decoded))
                self._record_internal_effect(event)

        flush_regular_frames()
        return AggregatorUpdate(
            frames_seen=self._stats.frame_count - frame_count_before,
            redir_events=tuple(redir_events),
            internal_frames=tuple(internal_frames),
        )

    def snapshot(self, elapsed_sec: float, *, include_segments: bool = True) -> AggregatorSnapshot:
        """Harvest periodic stats for UI/log sinks."""

        if self._final_stat_seen:
            firmware_written_bytes = self._final_written_bytes
            firmware_lost_bytes = sum(value[1] for value in self._final_loss.values())
            firmware_loss = tuple(
                FirmwareLossSummary(source=source, frames=frames, bytes=byte_count)
                for source, (frames, byte_count) in sorted(self._final_loss.items())
                if frames or byte_count
            )
        else:
            firmware_written_bytes, firmware_lost_bytes = self._stats.capture_firmware_quality_bytes()
            firmware_loss = self._stats.capture_firmware_loss()
        sequence = (
            self._complete_sequence
            if self._final_stat_seen
            else self._stats.sequence_snapshot()
        )
        return AggregatorSnapshot(
            stats=self._stats.snapshot(elapsed_sec),
            funnel_snapshots=tuple(self._stats.funnel_snapshot(elapsed_sec)),
            buf_util_snapshots=tuple(self._stats.buf_util_snapshot()),
            captured_bytes=self._captured_bytes,
            parser_raw_bytes=self._parser_raw_bytes,
            parser_frames=self._parser_frames,
            parser_carried_bytes=self._parser_carried_bytes,
            regular_frames=self._stats.regular_frame_count,
            sequence=sequence,
            capture_firmware_loss=firmware_loss,
            capture_firmware_written_bytes=firmware_written_bytes,
            capture_firmware_lost_bytes=firmware_lost_bytes,
            capture_segments=tuple(self._segments) if include_segments else (),
        )

    def _record_internal_frame(self, frame_size: int) -> None:
        # INTERNAL frames count for transport FPS, but not per-source SN tracking.
        self._stats.record_frame(frame_size=frame_size)

    def _record_internal_effect(self, event: InternalEvent) -> None:
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

    def _close_final_stat_segment(self, event: FinalStatEvent) -> None:
        self._final_stat_seen = True
        sequence = self._stats.seal_sequence_segment()
        entries = tuple(entry for entry in event.entries if entry.source_code > 0)
        segment = CaptureSegmentSummary(
            index=len(self._segments) + 1,
            complete=self._segment_start_known,
            final_stat_seen=True,
            received_frames=self._segment_regular_frames,
            received_bytes=self._segment_regular_bytes,
            firmware_written_frames=sum(entry.written_frame_cnt for entry in entries),
            firmware_written_bytes=sum(entry.written_bytes_cnt for entry in entries),
            firmware_lost_frames=sum(entry.failed_frame_cnt for entry in entries),
            firmware_lost_bytes=sum(entry.failed_bytes_cnt for entry in entries),
            sequence_missing_frames=sequence.total_missing_frames,
            sequence_uncertain=sequence.uncertain,
        )
        self._segments.append(segment)
        if segment.complete:
            self._complete_sequence = merge_sequence_summaries((self._complete_sequence, sequence))
            for entry in entries:
                self._final_written_bytes += entry.written_bytes_cnt
                lost_frames, lost_bytes = self._final_loss.get(entry.source_code, (0, 0))
                self._final_loss[entry.source_code] = (
                    lost_frames + entry.failed_frame_cnt,
                    lost_bytes + entry.failed_bytes_cnt,
                )
        self._segment_regular_frames = 0
        self._segment_regular_bytes = 0
        self._segment_start_known = True

    def _close_pending_segment(self) -> None:
        sequence = self._stats.seal_sequence_segment()
        if not self._segment_regular_frames and not sequence.sources:
            return
        self._segments.append(
            CaptureSegmentSummary(
                index=len(self._segments) + 1,
                complete=False,
                final_stat_seen=False,
                received_frames=self._segment_regular_frames,
                received_bytes=self._segment_regular_bytes,
                firmware_written_frames=0,
                firmware_written_bytes=0,
                firmware_lost_frames=0,
                firmware_lost_bytes=0,
                sequence_missing_frames=sequence.total_missing_frames,
                sequence_uncertain=sequence.uncertain,
            )
        )
        self._segment_regular_frames = 0
        self._segment_regular_bytes = 0



def frame_size_from_payload(payload: bytes) -> int:
    """Return the BLE log wire frame size for a payload."""

    return len(payload) + FRAME_OVERHEAD
