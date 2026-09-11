# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Thin composition of stats sub-modules into a single accumulator."""

from __future__ import annotations

from src.backend.models import BleLogSource
from src.backend.models import BufUtilEntry
from src.backend.models import FrameByteCount
from src.backend.models import FrameStats
from src.backend.models import FirmwareLossSummary
from src.backend.models import FunnelSnapshot
from src.backend.models import SequenceSummary
from src.backend.models import SequenceSourceSummary
from src.backend.models import SourceCode
from src.backend.models import ThroughputInfo
from src.backend.models import TransportBitrate
from src.backend.support.stats.buf_util import BufUtilTracker
from src.backend.support.stats.firmware_loss import FirmwareLossTracker
from src.backend.support.stats.firmware_written import FirmwareWrittenTracker
from src.backend.support.stats.sn_gap import SNGapTracker
from src.backend.support.stats.transport import TransportMetrics


class StatsAccumulator:
    def __init__(self) -> None:
        self._bitrate = TransportBitrate()
        self._transport = TransportMetrics()
        self._fw_loss = FirmwareLossTracker()
        self._fw_written = FirmwareWrittenTracker()
        self._sn_gap = SNGapTracker()
        self._sequence_total = SequenceSummary()
        self._buf_util = BufUtilTracker()
        self._per_source_received_frames: dict[SourceCode, int] = {}
        self._per_source_received_bytes: dict[SourceCode, int] = {}
        self._enh_stat_prev: dict[SourceCode, tuple[int, int, int, int]] = {}
        self._enh_zero_baseline = False
        self._capture_loss: dict[SourceCode, tuple[int, int]] = {}
        self._capture_written: dict[SourceCode, tuple[int, int]] = {}
        self._total_elapsed: float = 0.0
        self._prev_written: dict[SourceCode, tuple[int, int]] = {}

    def record_bytes(self, count: int) -> None:
        self._transport.record_bytes(count)

    def record_frame(self, frame_size: int = 0, src_code: int = 0, frame_sn: int = -1) -> int:
        """Record a received frame. Returns confirmed SN gap count (0 if SN tracking disabled)."""
        self._transport.record_frame()
        gap = 0
        if frame_sn >= 0 and src_code > 0:
            gap = self._sn_gap.record(src_code, frame_sn)
            self._per_source_received_frames[src_code] = self._per_source_received_frames.get(src_code, 0) + 1
            self._per_source_received_bytes[src_code] = self._per_source_received_bytes.get(src_code, 0) + frame_size
        return gap

    def record_frame_sn(self, src_code: SourceCode, frame_sn: int) -> int:
        """Record sequence number for an already-counted regular frame."""

        if frame_sn < 0 or src_code <= 0:
            return 0
        return self._sn_gap.record(src_code, frame_sn)

    @property
    def regular_frame_count(self) -> int:
        return sum(self._per_source_received_frames.values())

    def sequence_snapshot(self) -> SequenceSummary:
        return merge_sequence_summaries((self._sequence_total, self._sn_gap.snapshot()))

    def finalize_sequence(self) -> SequenceSummary:
        self.seal_sequence_segment()
        return self._sequence_total

    def seal_sequence_segment(self) -> SequenceSummary:
        """Close the current FINAL_STAT interval and start a fresh SN window."""

        summary = self._sn_gap.finalize()
        if summary.sources:
            self._sequence_total = merge_sequence_summaries((self._sequence_total, summary))
        self._sn_gap = SNGapTracker()
        return summary

    def capture_firmware_loss(self) -> tuple[FirmwareLossSummary, ...]:
        return tuple(
            FirmwareLossSummary(source=source, frames=frames, bytes=byte_count)
            for source, (frames, byte_count) in sorted(self._capture_loss.items())
            if frames > 0 or byte_count > 0
        )

    def capture_firmware_quality_bytes(self) -> tuple[int, int]:
        """Return comparable ENH written/lost byte deltas for regular sources."""

        written = sum(value[1] for source, value in self._capture_written.items() if source > 0)
        lost = sum(value[1] for source, value in self._capture_loss.items() if source > 0)
        return written, lost

    def record_regular_frame_summary(
        self,
        frame_count: int,
        per_source_frames: dict[SourceCode, int],
        per_source_bytes: dict[SourceCode, int],
    ) -> None:
        """Record a visible batch of regular parser frame counters."""

        if frame_count <= 0:
            return

        self._transport.record_frames(frame_count)
        for src_code, count in per_source_frames.items():
            self._per_source_received_frames[src_code] = self._per_source_received_frames.get(src_code, 0) + count
        for src_code, byte_count in per_source_bytes.items():
            self._per_source_received_bytes[src_code] = self._per_source_received_bytes.get(src_code, 0) + byte_count

    @property
    def frame_count(self) -> int:
        return self._transport.frame_count

    # -- Transport bitrate -------------------------------------------------------

    def set_transport_bitrate(self, bitrate: TransportBitrate) -> None:
        self._bitrate = bitrate
        self._transport.set_bitrate(bitrate)

    # -- Buffer utilization ------------------------------------------------------

    def record_buf_util(self, lbm_id: int, trans_cnt: int, inflight_peak: int) -> None:
        self._buf_util.record(lbm_id, trans_cnt, inflight_peak)

    def buf_util_snapshot(self) -> list[BufUtilEntry]:
        return self._buf_util.snapshot()  # type: ignore[no-any-return]

    # -- Firmware ENH_STAT -------------------------------------------------------

    def record_enh_stat(
        self,
        src_code: SourceCode,
        written_frames: int,
        lost_frames: int,
        written_bytes: int,
        lost_bytes: int,
    ) -> tuple[int, int]:
        """Record firmware ENH_STAT report. Returns (loss_delta_frames, loss_delta_bytes).

        Torn-read guard: discards reports where byte deltas exceed 2s of wire
        capacity (non-atomic enh_stat_t reads under concurrent ISR/task updates).
        """
        prev = self._enh_stat_prev.get(src_code)
        max_payload_bytes_per_sec = self._bitrate.max_payload_bytes_per_sec
        if prev is not None and max_payload_bytes_per_sec is not None:
            max_bytes_delta = int(max_payload_bytes_per_sec * 2)
            d_written_bytes = written_bytes - prev[2]
            d_lost_bytes = lost_bytes - prev[3]
            if d_written_bytes > max_bytes_delta or d_lost_bytes > max_bytes_delta:
                # Update prev to avoid cascading discards on next report
                self._enh_stat_prev[src_code] = (written_frames, lost_frames, written_bytes, lost_bytes)
                return (0, 0)

        self._enh_stat_prev[src_code] = (written_frames, lost_frames, written_bytes, lost_bytes)
        if prev is None and self._enh_zero_baseline:
            self._fw_written.record(src_code, 0, 0)
            self._fw_loss.record(src_code, 0, 0)
        new_written_frames, new_written_bytes = self._fw_written.record(src_code, written_frames, written_bytes)
        if new_written_frames > 0 or new_written_bytes > 0:
            old_frames, old_bytes = self._capture_written.get(src_code, (0, 0))
            self._capture_written[src_code] = (old_frames + new_written_frames, old_bytes + new_written_bytes)
        new_frames, new_bytes = self._fw_loss.record(src_code, lost_frames, lost_bytes)
        if new_frames > 0 or new_bytes > 0:
            old_frames, old_bytes = self._capture_loss.get(src_code, (0, 0))
            self._capture_loss[src_code] = (old_frames + new_frames, old_bytes + new_bytes)
        return new_frames, new_bytes

    # -- Reset -------------------------------------------------------------------

    def reset(self, reason: str) -> None:
        """Reset components by group.

        reason: "init" (INIT_DONE) or "flush" (FLUSH)
        """
        if reason == 'init':
            # INIT_DONE confirms a new firmware instance. FLUSH may be followed
            # by older asynchronously buffered frames, so it is not an SN cut.
            self.seal_sequence_segment()
            # ENH_STAT-coupled: full reset
            self._fw_loss.reset()
            self._fw_written.reset()
            self._enh_stat_prev.clear()
            self._enh_zero_baseline = True
            self._prev_written.clear()
            self._buf_util.reset()
        elif reason == 'flush':
            # ENH_STAT-coupled: reset baselines only
            self._fw_loss.reset_baselines()
            self._fw_written.reset_baselines()
            self._enh_stat_prev.clear()
            self._enh_zero_baseline = False
            # Console-local: preserve (no action)

    # -- Snapshots ---------------------------------------------------------------

    def snapshot(self, elapsed_sec: float) -> FrameStats:
        return FrameStats(
            transport=self._transport.harvest(elapsed_sec),
            loss=self._fw_loss.totals(),
            per_source_rx_bytes=(dict(self._per_source_received_bytes) if self._per_source_received_bytes else None),
        )

    def funnel_snapshot(self, elapsed_sec: float = 0.0) -> list[FunnelSnapshot]:
        """Build per-source funnel snapshots from all component data."""
        written_totals = self._fw_written.totals()
        loss_totals = self._fw_loss.per_source_totals()

        sources: set[int] = set()
        sources.update(written_totals)
        sources.update(loss_totals)
        sources.update(self._per_source_received_frames)

        # Exclude INTERNAL (src_code=0): its transport_loss is inherently
        # unknowable — if INTERNAL frames are lost, the ENH_STAT data inside
        # them never arrives, making the written-vs-received comparison circular.
        sources.discard(BleLogSource.INTERNAL)

        self._total_elapsed += elapsed_sec

        result: list[FunnelSnapshot] = []
        for src in sorted(sources):
            w_frames, w_bytes = written_totals.get(src, (0, 0))
            l_frames, l_bytes = loss_totals.get(src, (0, 0))
            r_frames = self._per_source_received_frames.get(src, 0)
            r_bytes = self._per_source_received_bytes.get(src, 0)

            produced = FrameByteCount(frames=w_frames + l_frames, bytes=w_bytes + l_bytes)
            written = FrameByteCount(frames=w_frames, bytes=w_bytes)
            received = FrameByteCount(frames=r_frames, bytes=r_bytes)
            buffer_loss = FrameByteCount(frames=l_frames, bytes=l_bytes)
            pw_frames, pw_bytes = self._prev_written.get(src, (0, 0))
            transport_loss = FrameByteCount(
                frames=max(0, pw_frames - r_frames),
                bytes=max(0, pw_bytes - r_bytes),
            )

            if self._total_elapsed > 0:
                tp_fps = r_frames / self._total_elapsed
                throughput_bits_per_sec = self._bitrate.payload_bytes_to_wire_bits(r_bytes) / self._total_elapsed
            else:
                tp_fps = 0.0
                throughput_bits_per_sec = 0.0

            result.append(
                FunnelSnapshot(
                    source=src,
                    produced=produced,
                    written=written,
                    received=received,
                    buffer_loss=buffer_loss,
                    transport_loss=transport_loss,
                    throughput=ThroughputInfo(
                        throughput_fps=tp_fps,
                        throughput_bits_per_sec=throughput_bits_per_sec,
                        peak_write_frames=0,
                        peak_write_bits_per_sec=0.0,
                        peak_window_ms=0,
                    ),
                )
            )

        self._prev_written = dict(written_totals)

        return result


def merge_sequence_summaries(summaries: tuple[SequenceSummary, ...]) -> SequenceSummary:
    merged: dict[SourceCode, SequenceSourceSummary] = {}
    for summary in summaries:
        for current in summary.sources:
            previous = merged.get(current.source)
            if previous is None:
                merged[current.source] = current
                continue
            merged[current.source] = SequenceSourceSummary(
                source=current.source,
                observed_frames=previous.observed_frames + current.observed_frames,
                first_sn=previous.first_sn,
                last_sn=current.last_sn,
                missing_frames=previous.missing_frames + current.missing_frames,
                segments=previous.segments + current.segments,
                late_frames=previous.late_frames + current.late_frames,
                duplicate_frames=previous.duplicate_frames + current.duplicate_frames,
                wraps=previous.wraps + current.wraps,
                uncertain=previous.uncertain or current.uncertain,
            )
    return SequenceSummary(tuple(merged[source] for source in sorted(merged)))
