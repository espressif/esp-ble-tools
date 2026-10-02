# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Aggregate parser events into console-facing statistics updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from ble_log_frame_decoder import (
    INIT,
    BleLogVersionInfo,
    InternalLogBufferUtil,
    InternalSource,
    Snapshot,
    parse_snapshot_version_info,
)

from src.backend.analysis.parser_events import (
    BleLogEvent,
    EnhStatEvent,
    FinalStatEvent,
    FrameEvent,
    InternalEvent,
    ParseBatch,
    ParseSummary,
    RedirEvent,
)
from src.backend.models import (
    FRAME_OVERHEAD,
    BufUtilEntry,
    CaptureSegmentSummary,
    FirmwareLossSummary,
    FrameStats,
    FunnelSnapshot,
    InternalDecoderResult,
    InternalLogInfo,
    SequenceSummary,
    TransportBitrate,
)
from src.backend.support.stats import StatsAccumulator

# Firmware records that prove which counter owns frame numbers. The two
# protocol generations barely overlap in what they write, so the record itself
# is the evidence: protocol 8 numbers every frame from one counter and writes
# SNAPSHOT/VERSION_INFO/TASK_BINDING, while protocol <= 7 numbers each source
# from its own counter and writes the other records. The version number is only
# reported alongside, never used to pick the contract.
_GLOBAL_COUNTER_SOURCES = frozenset({InternalSource.SNAPSHOT, InternalSource.VERSION_INFO, InternalSource.TASK_BINDING})


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
    sequence: SequenceSummary = field(default_factory=SequenceSummary)
    capture_firmware_loss: tuple[FirmwareLossSummary, ...] = ()
    capture_firmware_written_bytes: int = 0
    capture_firmware_lost_bytes: int = 0
    capture_segments: tuple[CaptureSegmentSummary, ...] = ()
    firmware_version: int | None = None
    firmware_contract_known: bool = True


def _recorded_version(decoded: InternalDecoderResult) -> int | None:
    """Firmware version a record carries, or None when it carries none."""

    try:
        if isinstance(decoded, Snapshot):
            return int(parse_snapshot_version_info(decoded).version)
        if isinstance(decoded, (BleLogVersionInfo, InternalLogInfo)):
            return int(decoded.version)
    except ValueError:
        # A SNAPSHOT can pass shape validation with a corrupt embedded block.
        return None
    return None


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
        self._firmware_version: int | None = None
        self._firmware_contract_known = False

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
                self._observe_firmware(per_source=True)
                self._record_internal_frame(event.frame_size, event.frame_sn)
                internal_frames.append(InternalFrameUpdate(int_src=InternalSource.ENHANCED_STAT, decoded=event.stat))
                self._record_enh_stat(event)
            elif event_type is FinalStatEvent:
                flush_regular_frames()
                self._observe_firmware(per_source=True)
                self._record_internal_frame(event.frame_size, event.frame_sn)
                self._close_final_stat_segment(event)
            elif event_type is InternalEvent:
                flush_regular_frames()
                # Before sealing or feeding this frame's SN: a protocol 8 record
                # re-keys the windows, and the frames already accounted under
                # the other contract must not enter the segment they precede.
                self._observe_firmware(
                    per_source=event.int_src not in _GLOBAL_COUNTER_SOURCES,
                    version=_recorded_version(event.decoded),
                )
                if self._starts_new_sn_epoch(event):
                    # Cut the old segment over before feeding this frame's SN:
                    # the marker belongs to the new firmware instance, not to
                    # the window it replaces.
                    self._close_pending_segment()
                    self._segment_start_known = True
                internal_frames.append(InternalFrameUpdate(int_src=event.int_src, decoded=event.decoded))
                self._record_internal_effect(event)
                self._record_internal_frame(event.frame_size, event.frame_sn)
                if event.int_src == InternalSource.FLUSH:
                    # The record itself belongs to the interval it closes; a
                    # legacy firmware restarts its counters only afterwards (and
                    # v5 does it past its FINAL_STAT), so the seal waits for the
                    # restart instead of cutting here.
                    self._stats.expect_flushed_restart()

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
        # Sequence continuity spans every sealed window plus the live one: a
        # segment whose FINAL_STAT never arrived still holds real gaps, and
        # dropping it would report a clean capture while the segment table shows
        # missing frames.
        sequence = self._stats.sequence_snapshot()
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
            firmware_version=self._firmware_version,
            firmware_contract_known=self._firmware_contract_known,
        )

    def _observe_firmware(self, *, per_source: bool, version: int | None = None) -> None:
        """Adopt the SN contract the firmware's records prove."""

        if version is not None and self._firmware_version is None:
            self._firmware_version = version
        if self._firmware_contract_known:
            return
        self._firmware_contract_known = True
        self._stats.set_sequence_model(per_source)

    def _record_internal_frame(self, frame_size: int, frame_sn: int = -1) -> None:
        # INTERNAL frames count for transport FPS and share the global SN stream
        # with regular frames, but never for per-source byte accounting.
        self._stats.record_frame(frame_size=frame_size)
        self._stats.record_frame_sn(0, frame_sn)

    def _record_internal_effect(self, event: InternalEvent) -> None:
        if self._starts_new_sn_epoch(event):
            self._stats.reset("init")
        elif event.int_src == InternalSource.FLUSH:
            self._stats.reset("flush")
        elif event.int_src == InternalSource.BUF_UTIL:
            buf = cast(InternalLogBufferUtil, event.decoded)
            self._stats.record_buf_util(
                lbm_id=buf.lbm_id,
                trans_cnt=buf.trans_cnt,
                inflight_peak=buf.inflight_peak,
            )

    def _starts_new_sn_epoch(self, event: InternalEvent) -> bool:
        """Whether this INTERNAL frame begins a new firmware instance's SN epoch.

        INIT_DONE is the v4 marker. v8 marks it on a SNAPSHOT's reason_flags
        instead; a FLUSH snapshot only resets ENH baselines and the Global SN
        keeps running across it, so it must not cut the window.
        """
        if event.int_src == InternalSource.INIT_DONE:
            return True
        decoded = event.decoded
        return (
            event.int_src == InternalSource.SNAPSHOT
            and isinstance(decoded, Snapshot)
            and bool(decoded.reason_flags & INIT)
        )

    def _record_enh_stat(self, event: EnhStatEvent) -> None:
        stat = event.stat.enhanced_stat
        self._stats.record_enh_stat(
            src_code=int(stat.log_source),
            written_frames=stat.written_frame_cnt,
            lost_frames=stat.lost_frame_cnt,
            written_bytes=stat.written_bytes_cnt,
            lost_bytes=stat.lost_bytes_cnt,
        )

    def _close_final_stat_segment(self, event: FinalStatEvent) -> None:
        self._final_stat_seen = True
        sequence = self._stats.seal_sequence_segment()
        entries = tuple(entry for entry in event.entries if int(entry.log_source) > 0)
        segment = CaptureSegmentSummary(
            index=len(self._segments) + 1,
            complete=self._segment_start_known,
            final_stat_seen=True,
            received_frames=self._segment_regular_frames,
            received_bytes=self._segment_regular_bytes,
            firmware_written_frames=sum(entry.written_frame_cnt for entry in entries),
            firmware_written_bytes=sum(entry.written_bytes_cnt for entry in entries),
            firmware_lost_frames=sum(entry.lost_frame_cnt for entry in entries),
            firmware_lost_bytes=sum(entry.lost_bytes_cnt for entry in entries),
            sequence_missing_frames=sequence.missing_frames,
            sequence_uncertain=sequence.uncertain,
        )
        self._segments.append(segment)
        # Firmware counters only make sense for a segment that saw its FINAL_STAT;
        # the sequence window is sealed either way and stays in the capture total.
        if segment.complete:
            for entry in entries:
                self._final_written_bytes += entry.written_bytes_cnt
                lost_frames, lost_bytes = self._final_loss.get(int(entry.log_source), (0, 0))
                self._final_loss[int(entry.log_source)] = (
                    lost_frames + entry.lost_frame_cnt,
                    lost_bytes + entry.lost_bytes_cnt,
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
                sequence_missing_frames=sequence.missing_frames,
                sequence_uncertain=sequence.uncertain,
            )
        )
        self._segment_regular_frames = 0
        self._segment_regular_bytes = 0


def frame_size_from_payload(payload: bytes) -> int:
    """Return the BLE log wire frame size for a payload."""

    return len(payload) + FRAME_OVERHEAD
