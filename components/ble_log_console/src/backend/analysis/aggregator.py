# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Aggregate parser events into console-facing statistics updates."""

from __future__ import annotations

from dataclasses import dataclass, field

from ble_log_frame_decoder import (
    INIT,
    FirmwareSnapshot,
    InternalLogBufferUtil,
    InternalSource,
    Snapshot,
)
from ble_log_frame_decoder.checking import CheckResult

from src.backend.analysis.parser_events import (
    BleLogEvent,
    ConsoleEvent,
    EnhStatEvent,
    FrameEvent,
    HciLogEvent,
    HostLogEvent,
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
    FirmwareLossSummary,
    FrameByteCount,
    FrameStats,
    FunnelSnapshot,
    InternalDecoderResult,
    LossSnapshot,
    SequenceSourceSummary,
    SequenceSummary,
    ThroughputInfo,
    TransportBitrate,
)
from src.backend.support.stats.buf_util import BufUtilTracker
from src.backend.support.stats.transport import TransportMetrics

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
    capture_firmware_lost_bytes: int | None = 0
    capture_segments: tuple[CaptureSegmentSummary, ...] = ()
    firmware_version: int | None = None
    firmware_contract_known: bool = True
    stream_identity: StreamIdentity | None = None
    integrity: CheckResult | None = None
    firmware: FirmwareSnapshot | None = None


class CaptureAggregator:
    """Console measurements and presentation; Core owns protocol accounting."""

    def __init__(self, bitrate: TransportBitrate | None = None) -> None:
        self._transport = TransportMetrics()
        self._bitrate = bitrate or TransportBitrate()
        self._transport.set_bitrate(self._bitrate)
        self._buf_util = BufUtilTracker()
        self._received: dict[int, tuple[int, int]] = {}
        self._elapsed = 0.0
        self._captured_bytes = self._parser_raw_bytes = self._parser_frames = self._parser_carried_bytes = 0
        self._firmware: FirmwareSnapshot | None = None
        self._integrity: CheckResult | None = None
        self._firmware_version: int | None = None
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
        return self._transport.frame_count

    def set_transport_bitrate(self, bitrate: TransportBitrate) -> None:
        self._bitrate = bitrate
        self._transport.set_bitrate(bitrate)

    def record_raw_bytes(self, count: int) -> None:
        if count > 0:
            self._captured_bytes += count
            self._transport.record_bytes(count)

    def consume_parser_batch(self, batch: ParseBatch) -> AggregatorUpdate:
        self._parser_raw_bytes += batch.raw_bytes
        self._parser_frames += batch.parsed_frames
        self._parser_carried_bytes = batch.carried_bytes
        self._stream_identity = batch.identity
        self._firmware = batch.firmware
        return self.consume_events(batch.events)

    def consume_parser_summary(self, summary: ParseSummary) -> None:
        self._parser_raw_bytes = summary.raw_bytes
        self._parser_frames = summary.parsed_frames
        self._parser_carried_bytes = summary.carried_bytes
        self._stream_identity = summary.identity
        self._firmware = summary.firmware
        self._integrity = summary.integrity

    def consume_events(self, events: tuple[BleLogEvent, ...]) -> AggregatorUpdate:
        before = self.frame_count
        console = []
        internal = []
        for event in events:
            if isinstance(event, (UndecodedEvent, HostLogEvent, HciLogEvent)):
                console.append(event)
                continue
            self._transport.record_frame()
            if isinstance(event, (FrameEvent, RedirEvent)):
                frames, size = self._received.get(event.source_code, (0, 0))
                self._received[event.source_code] = frames + 1, size + event.frame_size
                if isinstance(event, RedirEvent):
                    console.append(event)
            elif isinstance(event, EnhStatEvent):
                internal.append(InternalFrameUpdate(InternalSource.ENHANCED_STAT, event.stat))
            elif isinstance(event, InternalEvent):
                internal.append(InternalFrameUpdate(event.int_src, event.decoded))
                version = recorded_version(event.decoded)
                if version is not None:
                    self._firmware_version = version
                if event.int_src == InternalSource.INIT_DONE or (
                    isinstance(event.decoded, Snapshot) and event.decoded.reason_flags & INIT
                ):
                    self._buf_util.reset()
                if isinstance(event.decoded, InternalLogBufferUtil):
                    buf = event.decoded
                    self._buf_util.record(buf.lbm_id, buf.trans_cnt, buf.inflight_peak)
        return AggregatorUpdate(self.frame_count - before, tuple(console), tuple(internal))

    def snapshot(self, elapsed_sec: float, *, include_segments: bool = True) -> AggregatorSnapshot:
        self._elapsed += max(0, elapsed_sec)
        firmware = self._firmware.sources if self._firmware is not None else ()
        latest = {row.source: row.latest for row in firmware}
        funnels = []
        for source in sorted(set(latest) | set(self._received)):
            counters = latest.get(source)
            written = (
                FrameByteCount(counters.written_frame_cnt, counters.written_bytes_cnt)
                if counters
                else FrameByteCount(0, 0)
            )
            lost = (
                FrameByteCount(counters.lost_frame_cnt, counters.lost_bytes_cnt)
                if counters
                else FrameByteCount(0, None)
            )
            frames, size = self._received.get(source, (0, 0))
            funnels.append(
                FunnelSnapshot(
                    source=source,
                    produced=FrameByteCount(
                        written.frames + lost.frames, None if lost.bytes is None else written.bytes + lost.bytes
                    ),
                    written=written,
                    received=FrameByteCount(frames, size),
                    buffer_loss=lost,
                    transport_loss=FrameByteCount(0, None),
                    throughput=ThroughputInfo(
                        frames / self._elapsed if self._elapsed else 0,
                        self._bitrate.payload_bytes_to_wire_bits(size) / self._elapsed if self._elapsed else 0,
                        0,
                        0.0,
                        0,
                    ),
                )
            )
        loss = tuple(
            FirmwareLossSummary(
                row.source,
                row.observed.lost_frame_cnt,
                row.observed.lost_bytes_cnt,
                row.observed.written_frame_cnt,
                row.observed.written_bytes_cnt,
            )
            for row in firmware
        )
        lost_bytes = None if any(row.bytes is None for row in loss) else sum(row.bytes for row in loss)
        return AggregatorSnapshot(
            stats=FrameStats(
                transport=self._transport.harvest(elapsed_sec),
                loss=LossSnapshot(sum(row.frames for row in loss), lost_bytes),
                per_source_rx_bytes={source: size for source, (_, size) in self._received.items()} or None,
            ),
            funnel_snapshots=tuple(funnels),
            buf_util_snapshots=tuple(self._buf_util.snapshot()),
            captured_bytes=self._captured_bytes,
            parser_raw_bytes=self._parser_raw_bytes,
            parser_frames=self._parser_frames,
            parser_carried_bytes=self._parser_carried_bytes,
            regular_frames=sum(frames for source, (frames, _) in self._received.items() if source > 0),
            sequence=sequence_summary(self._integrity),
            capture_firmware_loss=loss,
            capture_firmware_written_bytes=sum(row.written_bytes for row in loss),
            capture_firmware_lost_bytes=lost_bytes,
            firmware_version=self._firmware_version,
            firmware_contract_known=self._firmware_version is not None
            or (
                self._integrity is not None
                and any(row.protocol != "unknown" for row in self._integrity.checked_intervals)
            ),
            stream_identity=self._stream_identity,
            integrity=self._integrity,
            firmware=self._firmware,
        )


def sequence_summary(result: CheckResult | None) -> SequenceSummary:
    """Map selected Checker ranges without inventing coverage outside them."""
    if result is None:
        return SequenceSummary(uncertain=True)
    intervals = result.checked_intervals
    duplicates = sum(row.duplicate_frames for row in intervals)
    sources = []
    for source in sorted({source for row in intervals for source in row.received}):
        rows = [row for row in intervals if source in row.received]
        ranges = [row.source_sn_ranges[source] for row in rows if source in row.source_sn_ranges]
        sources.append(
            SequenceSourceSummary(
                source=source,
                observed_frames=sum(row.received[source].frames for row in rows),
                first_sn=ranges[0][0] if ranges else None,
                last_sn=ranges[-1][1] if ranges else None,
                missing_frames=sum(
                    end - start + 1 for row in rows for start, end in row.source_missing_ranges.get(source, [])
                ),
                segments=len(rows),
                uncertain=any(row.status != "reported" or row.details_truncated for row in rows),
            )
        )
    return SequenceSummary(
        observed_frames=sum(row.received_unique_sn_count or 0 for row in intervals) + duplicates,
        missing_frames=sum(row.missing_sn_count for row in intervals),
        segments=len(intervals),
        late_frames=sum(row.late_frames for row in intervals),
        duplicate_frames=duplicates,
        uncertain=result.conclusion == "indeterminate"
        or any(note.startswith("Console retained") for note in result.notes),
        per_source=any(row.protocol not in ("snapshot", "unknown") for row in intervals),
        sources=tuple(sources),
    )


def frame_size_from_payload(payload: bytes) -> int:
    return len(payload) + FRAME_OVERHEAD
