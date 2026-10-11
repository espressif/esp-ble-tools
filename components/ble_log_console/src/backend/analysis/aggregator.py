# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Aggregate parser events into console-facing statistics updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from ble_log_frame_decoder import (
    INIT,
    InternalLogBufferUtil,
    InternalSource,
    Snapshot,
)

from src.backend.analysis.parser_events import (
    BleLogEvent,
    ConsoleEvent,
    EnhStatEvent,
    FinalStatEvent,
    FrameEvent,
    InternalEvent,
    ParseBatch,
    ParseSummary,
    RedirEvent,
    UndecodedEvent,
)
from src.backend.analysis.stream_identification import StreamIdentity, recorded_version
from src.backend.models import (
    FRAME_OVERHEAD,
    BufUtilEntry,
    CaptureSegmentSummary,
    FinalStatEntry,
    FirmwareCounterSource,
    FirmwareLossSummary,
    FrameStats,
    FunnelSnapshot,
    InternalDecoderResult,
    SequenceSummary,
    TransportBitrate,
)
from src.backend.support.stats import StatsAccumulator

# Protocol 8 shares one counter; legacy firmware numbers each source separately.
# Most record subtypes identify the contract, but VERSION_INFO is shared with
# protocol 6: its decoded version must identify that legacy record before the
# first contract is frozen. Other VERSION_INFO keeps the global default.
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
    console_events: tuple[ConsoleEvent, ...] = ()  # REDIR and undecoded text in stream order.
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
    stream_identity: StreamIdentity | None = None


def _accumulate(target: dict[int, tuple[int, int]], source: int, delta: tuple[int, int]) -> None:
    """Add one (frames, bytes) delta to a per-source total in place."""

    frames, byte_count = delta
    if not frames and not byte_count:
        return
    old_frames, old_bytes = target.get(source, (0, 0))
    target[source] = (old_frames + frames, old_bytes + byte_count)


def _totals(totals: dict[int, tuple[int, int]]) -> tuple[int, int]:
    """(frames, bytes) summed across the sources of a per-source total."""

    return sum(frames for frames, _ in totals.values()), sum(byte_count for _, byte_count in totals.values())


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
        self._final_written: dict[int, tuple[int, int]] = {}
        self._final_loss: dict[int, tuple[int, int]] = {}
        # Firmware loss accrues per segment from ENH_STAT deltas. A segment that
        # closes with FINAL_STAT replaces its own accrual with that interval's
        # terminal totals, so no interval is ever counted from both sources.
        self._segment_enh_written: dict[int, tuple[int, int]] = {}
        self._segment_enh_loss: dict[int, tuple[int, int]] = {}
        self._partial_written: dict[int, tuple[int, int]] = {}
        self._partial_loss: dict[int, tuple[int, int]] = {}
        self._last_final_stat: tuple[int, tuple[FinalStatEntry, ...]] | None = None
        self._firmware_version: int | None = None
        self._firmware_contract_known = False
        self._stream_identity: StreamIdentity | None = None

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
        self._stream_identity = batch.identity
        return self.consume_events(batch.events)

    def consume_parser_summary(self, summary: ParseSummary) -> None:
        """Store final parser counters emitted on parser shutdown."""

        self._parser_raw_bytes = summary.raw_bytes
        self._parser_frames = summary.parsed_frames
        self._parser_carried_bytes = summary.carried_bytes
        self._stream_identity = summary.identity
        self._close_pending_segment()

    def consume_events(self, events: tuple[BleLogEvent, ...]) -> AggregatorUpdate:
        """Consume parsed BLE log events and return UI/log-friendly updates."""

        frame_count_before = self._stats.frame_count
        regular_frame_count = 0
        per_source_frames: dict[int, int] = {}
        per_source_bytes: dict[int, int] = {}
        console_events: list[ConsoleEvent] = []
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
            if event_type is UndecodedEvent:
                console_events.append(event)
            elif event_type in (RedirEvent, FrameEvent):
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
                    console_events.append(event)
            elif event_type is EnhStatEvent:
                flush_regular_frames()
                self._observe_firmware(per_source=True)
                self._record_internal_frame(event.frame_size, event.frame_sn)
                internal_frames.append(InternalFrameUpdate(int_src=InternalSource.ENHANCED_STAT, decoded=event.stat))
                self._record_enh_stat(event)
            elif event_type is FinalStatEvent:
                flush_regular_frames()
                if self._is_duplicate_final_stat(event):
                    # The same record delivered twice: the transport still carried
                    # the bytes, but its SN and its interval were already
                    # accounted for by the first arrival.
                    self._stats.record_frame(frame_size=event.frame_size)
                    continue
                self._observe_firmware(per_source=True)
                self._record_internal_frame(event.frame_size, event.frame_sn)
                self._close_final_stat_segment(event)
            elif event_type is InternalEvent:
                flush_regular_frames()
                # Decide the contract before sealing or feeding this frame's SN,
                # so replay can regroup earlier frames before a segment boundary.
                version = recorded_version(event.decoded)
                per_source = event.int_src not in _GLOBAL_COUNTER_SOURCES
                if event.int_src == InternalSource.VERSION_INFO and version == 6:
                    per_source = True
                self._observe_firmware(per_source=per_source, version=version)
                if self._starts_new_sn_epoch(event):
                    # Cut the old segment over before feeding this frame's SN:
                    # the marker belongs to the new firmware instance, not to
                    # the window it replaces.
                    self._close_pending_segment()
                    self._segment_start_known = True
                    # The dedup identity is scoped to the epoch that recorded
                    # it. A later instance can report the same timestamp and
                    # the same counters, and that is a new interval rather
                    # than a repeat of the previous one.
                    self._last_final_stat = None
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
            console_events=tuple(console_events),
            internal_frames=tuple(internal_frames),
        )

    def snapshot(self, elapsed_sec: float, *, include_segments: bool = True) -> AggregatorSnapshot:
        """Harvest periodic stats for UI/log sinks."""

        # Every segment contributes its own evidence, and the live window is a
        # segment that has not been sealed yet: complete segments report their
        # FINAL_STAT interval totals, the rest report accrued ENH_STAT deltas.
        # Counters stay per source, so each source is scored on its own loss rate.
        firmware_written, firmware_loss_totals = self._firmware_totals()
        # One row per source that reported any counter, including the ones that
        # lost nothing: the rate is scored per source, so a source with written
        # frames and no loss is a 0% data point rather than a missing one.
        # Which of these rows count as observed loss is the report's decision.
        firmware_loss = tuple(
            FirmwareLossSummary(
                source=source,
                frames=firmware_loss_totals.get(source, (0, 0))[0],
                bytes=firmware_loss_totals.get(source, (0, 0))[1],
                written_frames=firmware_written.get(source, (0, 0))[0],
                written_bytes=firmware_written.get(source, (0, 0))[1],
            )
            for source in sorted(set(firmware_written) | set(firmware_loss_totals))
        )
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
            capture_firmware_written_bytes=_totals(firmware_written)[1],
            capture_firmware_lost_bytes=_totals(firmware_loss_totals)[1],
            capture_segments=tuple(self._segments) if include_segments else (),
            firmware_version=self._firmware_version,
            firmware_contract_known=self._firmware_contract_known,
            stream_identity=self._stream_identity,
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
        source = int(stat.log_source)
        delta = self._stats.record_enh_stat(
            src_code=source,
            written_frames=stat.written_frame_cnt,
            lost_frames=stat.lost_frame_cnt,
            written_bytes=stat.written_bytes_cnt,
            lost_bytes=stat.lost_bytes_cnt,
        )
        # Accrued for the current segment; a FINAL_STAT closing it replaces this
        # accrual with the interval's own totals (see _close_final_stat_segment).
        _accumulate(self._segment_enh_written, source, (delta.written_frames, delta.written_bytes))
        _accumulate(self._segment_enh_loss, source, (delta.lost_frames, delta.lost_bytes))

    def _take_segment_enh_totals(self) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
        """Take the ENH_STAT accrual of the segment that is being sealed."""

        written, loss = self._segment_enh_written, self._segment_enh_loss
        self._segment_enh_written = {}
        self._segment_enh_loss = {}
        return written, loss

    def _firmware_totals(self) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
        """Per-source written and lost counters of every segment, sealed or live."""

        written = dict(self._final_written)
        loss = dict(self._final_loss)
        for source, delta in self._partial_written.items():
            _accumulate(written, source, delta)
        for source, delta in self._partial_loss.items():
            _accumulate(loss, source, delta)
        for source, delta in self._segment_enh_written.items():
            _accumulate(written, source, delta)
        for source, delta in self._segment_enh_loss.items():
            _accumulate(loss, source, delta)
        return written, loss

    def _final_stat_identity(self, event: FinalStatEvent) -> tuple[int, tuple[FinalStatEntry, ...]]:
        """What makes two FINAL_STAT arrivals the same record: its own content."""

        return event.os_ts_ms, tuple(event.entries)

    def _is_duplicate_final_stat(self, event: FinalStatEvent) -> bool:
        """Whether this arrival repeats the record already accounted for.

        The transport can deliver the same bytes twice. The record carries its
        own firmware timestamp and every counter, so a repeat is recognised by
        content, with no timing assumption. The comparison is against the most
        recent identity of the current SN epoch: a replay separated from its
        original by another FINAL_STAT is not recognised, and a repeat that
        arrives after a new epoch has begun belongs to that epoch.
        """

        return self._last_final_stat is not None and self._last_final_stat == self._final_stat_identity(event)

    def _close_final_stat_segment(self, event: FinalStatEvent) -> None:
        # INTERNAL (source 0) is a source like any other here: its loss is scored
        # on its own row instead of being dropped or merged into customer data.
        entries = tuple(event.entries)
        self._last_final_stat = self._final_stat_identity(event)
        sequence = self._stats.seal_sequence_segment()
        enh_written, enh_loss = self._take_segment_enh_totals()
        if self._segment_start_known:
            # The segment covers the whole interval, so its terminal counters are
            # the authority for it.
            firmware_written = _totals(
                {int(entry.log_source): (entry.written_frame_cnt, entry.written_bytes_cnt) for entry in entries}
            )
            firmware_lost = _totals(
                {int(entry.log_source): (entry.lost_frame_cnt, entry.lost_bytes_cnt) for entry in entries}
            )
            counters = FirmwareCounterSource.FINAL_STAT
            for entry in entries:
                source = int(entry.log_source)
                _accumulate(self._final_written, source, (entry.written_frame_cnt, entry.written_bytes_cnt))
                _accumulate(self._final_loss, source, (entry.lost_frame_cnt, entry.lost_bytes_cnt))
        else:
            # The capture never saw this interval start, so FINAL_STAT has no
            # baseline to be read against; the segment's OWN ENH_STAT deltas are
            # the evidence, exactly as for a segment that has no FINAL_STAT.
            firmware_written = _totals(enh_written)
            firmware_lost = _totals(enh_loss)
            counters = FirmwareCounterSource.ENH_STAT if (enh_written or enh_loss) else FirmwareCounterSource.NONE
            for source, delta in enh_written.items():
                _accumulate(self._partial_written, source, delta)
            for source, delta in enh_loss.items():
                _accumulate(self._partial_loss, source, delta)
        self._segments.append(
            CaptureSegmentSummary(
                index=len(self._segments) + 1,
                complete=self._segment_start_known,
                final_stat_seen=True,
                received_frames=self._segment_regular_frames,
                received_bytes=self._segment_regular_bytes,
                firmware_written_frames=firmware_written[0],
                firmware_written_bytes=firmware_written[1],
                firmware_lost_frames=firmware_lost[0],
                firmware_lost_bytes=firmware_lost[1],
                sequence_missing_frames=sequence.missing_frames,
                sequence_uncertain=sequence.uncertain,
                firmware_counters=counters,
            )
        )
        self._segment_regular_frames = 0
        self._segment_regular_bytes = 0
        self._segment_start_known = True

    def _close_pending_segment(self) -> None:
        sequence = self._stats.seal_sequence_segment()
        if not self._segment_regular_frames and not sequence.sources:
            return
        enh_written, enh_loss = self._take_segment_enh_totals()
        firmware_written = _totals(enh_written)
        firmware_lost = _totals(enh_loss)
        for source, delta in enh_written.items():
            _accumulate(self._partial_written, source, delta)
        for source, delta in enh_loss.items():
            _accumulate(self._partial_loss, source, delta)
        self._segments.append(
            CaptureSegmentSummary(
                index=len(self._segments) + 1,
                complete=False,
                final_stat_seen=False,
                received_frames=self._segment_regular_frames,
                received_bytes=self._segment_regular_bytes,
                firmware_written_frames=firmware_written[0],
                firmware_written_bytes=firmware_written[1],
                firmware_lost_frames=firmware_lost[0],
                firmware_lost_bytes=firmware_lost[1],
                sequence_missing_frames=sequence.missing_frames,
                sequence_uncertain=sequence.uncertain,
                firmware_counters=(
                    FirmwareCounterSource.ENH_STAT if (enh_written or enh_loss) else FirmwareCounterSource.NONE
                ),
            )
        )
        self._segment_regular_frames = 0
        self._segment_regular_bytes = 0


def frame_size_from_payload(payload: bytes) -> int:
    """Return the BLE log wire frame size for a payload."""

    return len(payload) + FRAME_OVERHEAD
