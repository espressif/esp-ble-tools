# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Thin composition of stats sub-modules into a single accumulator."""

from __future__ import annotations

from typing import NamedTuple

from src.backend.models import (
    BleLogSource,
    BufUtilEntry,
    FrameByteCount,
    FrameStats,
    FunnelSnapshot,
    SequenceSourceSummary,
    SequenceSummary,
    SourceCode,
    ThroughputInfo,
    TransportBitrate,
)
from src.backend.support.stats.buf_util import BufUtilTracker
from src.backend.support.stats.firmware_loss import FirmwareLossTracker
from src.backend.support.stats.firmware_written import FirmwareWrittenTracker
from src.backend.support.stats.sn_gap import SNGapTracker
from src.backend.support.stats.transport import TransportMetrics


class EnhStatDelta(NamedTuple):
    """Deltas accepted from one ENH_STAT report; all zero when the guard drops it."""

    written_frames: int
    written_bytes: int
    lost_frames: int
    lost_bytes: int


# Frames kept for a replay while the firmware's counter contract is not proven.
# The log only has to outlast the gap between attaching to a running device and
# its first record (about a second); past it the frames cannot be re-grouped and
# a disagreeing record marks the result unverified instead.
SN_REPLAY_LIMIT = 65536


class StatsAccumulator:
    def __init__(self) -> None:
        self._bitrate = TransportBitrate()
        self._transport = TransportMetrics()
        self._fw_loss = FirmwareLossTracker()
        self._fw_written = FirmwareWrittenTracker()
        # The counter contract is only proven once the firmware writes a record
        # that identifies it (see set_sequence_model). Frames are accounted under
        # the default until then and logged, so a proven contract can re-group
        # them; the default matches the current firmware's shared counter.
        self._sn_per_source = False
        self._sn_contract_known = False
        self._sn_reset_pending = False
        self._sn_replay_log: list[tuple[SourceCode, int]] = []
        self._sn_replay_lost = False
        self._sn_gap = SNGapTracker(per_source=self._sn_per_source)
        # REDIR numbers frames from its own firmware counter
        # (ble_log_redir.c: `redir->frame_sn`), so its numbers must never fill
        # a gap in the stream shared by regular frames and snapshots.
        self._redir_sn_gap = SNGapTracker(per_source=self._sn_per_source)
        self._sequence_total = SequenceSummary()
        self._buf_util = BufUtilTracker()
        self._per_source_received_frames: dict[SourceCode, int] = {}
        self._per_source_received_bytes: dict[SourceCode, int] = {}
        self._enh_stat_prev: dict[SourceCode, tuple[int, int, int, int]] = {}
        self._enh_zero_baseline = False
        self._total_elapsed: float = 0.0
        self._prev_written: dict[SourceCode, tuple[int, int]] = {}

    def record_bytes(self, count: int) -> None:
        self._transport.record_bytes(count)

    def record_frame(self, frame_size: int = 0, src_code: int = 0, frame_sn: int = -1) -> int:
        """Record a received frame. Returns confirmed SN gap count (0 if SN tracking disabled)."""
        self._transport.record_frame()
        gap = 0
        if frame_sn >= 0 and src_code > 0:
            gap = self.record_frame_sn(src_code, frame_sn)
            self._per_source_received_frames[src_code] = self._per_source_received_frames.get(src_code, 0) + 1
            self._per_source_received_bytes[src_code] = self._per_source_received_bytes.get(src_code, 0) + frame_size
        return gap

    def record_frame_sn(self, src_code: SourceCode, frame_sn: int) -> int:
        """Record the sequence number of one transmitted frame.

        Called for regular frames and for the INTERNAL frames that share the
        global counter, plus for REDIR frames, whose number comes from a
        private counter. The trackers keep the counters apart and the
        capture-level summary merges them; src_code tallies which source was
        observed and, per the firmware contract, selects the stream.
        """

        if frame_sn < 0:
            return 0
        if not self._sn_contract_known:
            if len(self._sn_replay_log) < SN_REPLAY_LIMIT:
                self._sn_replay_log.append((src_code, frame_sn))
            else:
                self._sn_replay_lost = True
        return self._record_sn(src_code, frame_sn)

    def set_sequence_model(self, per_source: bool) -> None:
        """Adopt the counter contract the firmware's records prove.

        The frames recorded before the contract was proven are replayed under
        it, in stream order, so both contracts are accounted exactly. A capture
        that outran SN_REPLAY_LIMIT cannot be rebuilt; its windows are dropped
        and the continuity reported unverified rather than recomputed wrong.
        """

        if self._sn_contract_known:
            return
        self._sn_contract_known = True
        if per_source == self._sn_per_source:
            self._sn_replay_log.clear()
            return
        self._sn_per_source = per_source
        if self._sn_replay_lost:
            self._sn_gap.set_per_source(per_source)
            self._redir_sn_gap.set_per_source(per_source)
            self._sn_replay_log.clear()
            return
        self._sn_gap, self._redir_sn_gap = self._new_trackers()
        for src_code, frame_sn in self._sn_replay_log:
            self._record_sn(src_code, frame_sn)
        self._sn_replay_log.clear()

    @property
    def regular_frame_count(self) -> int:
        return sum(self._per_source_received_frames.values())

    def expect_flushed_restart(self) -> None:
        """Note that the firmware may restart its counters right after a FLUSH.

        A legacy flush zeroes every source's counter (``ble_log_lbm_reset_stats``
        in v6.0.1/v6.1), so the frames that follow start each source's numbering
        over. The restart is the boundary, not the record: a v5 flush writes its
        FINAL_STAT after the flush record with old-counter numbers, and a failed
        flush resets nothing at all. Sealing on the record would cut a window
        that is still running and hide what happens inside it.
        """

        if self._sn_per_source:
            self._sn_reset_pending = True

    def sequence_snapshot(self) -> SequenceSummary:
        return merge_sequence_summaries((self._sequence_total, self._sn_gap.snapshot(), self._redir_sn_gap.snapshot()))

    def finalize_sequence(self) -> SequenceSummary:
        self.seal_sequence_segment()
        return self._sequence_total

    def seal_sequence_segment(self) -> SequenceSummary:
        """Close the current FINAL_STAT interval and start fresh SN windows.

        A seal follows the firmware record that proved the contract, so the
        replay log has served its purpose and starts empty for the next segment.
        """

        self._sn_replay_log.clear()
        self._sn_replay_lost = False
        self._sn_reset_pending = False
        summary = merge_sequence_summaries((self._sn_gap.finalize(), self._redir_sn_gap.finalize()))
        if summary.sources:
            self._sequence_total = merge_sequence_summaries((self._sequence_total, summary))
        self._sn_gap, self._redir_sn_gap = self._new_trackers()
        return summary

    def _new_trackers(self) -> tuple[SNGapTracker, SNGapTracker]:
        return (
            SNGapTracker(per_source=self._sn_per_source),
            SNGapTracker(per_source=self._sn_per_source),
        )

    def _record_sn(self, src_code: SourceCode, frame_sn: int) -> int:
        if self._sn_reset_pending and self._restarted(src_code, frame_sn):
            # The counters really did start over: close the old window before
            # this frame opens the new one.
            self.seal_sequence_segment()
        if self._sn_per_source or src_code != BleLogSource.REDIR:
            return self._sn_gap.record(frame_sn, src_code)
        return self._redir_sn_gap.record(frame_sn, src_code)

    def _restarted(self, src_code: SourceCode, frame_sn: int) -> bool:
        """Whether this number goes backwards for the source that sent it."""

        previous = self._sn_gap.last_observed(src_code)
        return previous is not None and frame_sn < previous

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
    ) -> EnhStatDelta:
        """Record firmware ENH_STAT report. Returns the deltas that were accepted.

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
                return EnhStatDelta(0, 0, 0, 0)

        self._enh_stat_prev[src_code] = (written_frames, lost_frames, written_bytes, lost_bytes)
        if prev is None and self._enh_zero_baseline:
            self._fw_written.record(src_code, 0, 0)
            self._fw_loss.record(src_code, 0, 0)
        new_written_frames, new_written_bytes = self._fw_written.record(src_code, written_frames, written_bytes)
        new_frames, new_bytes = self._fw_loss.record(src_code, lost_frames, lost_bytes)
        return EnhStatDelta(new_written_frames, new_written_bytes, new_frames, new_bytes)

    # -- Reset -------------------------------------------------------------------

    def reset(self, reason: str) -> None:
        """Reset components by group.

        reason: "init" (INIT_DONE) or "flush" (FLUSH)
        """
        if reason == "init":
            # INIT_DONE confirms a new firmware instance. FLUSH may be followed
            # by older asynchronously buffered frames, so it is not an SN cut.
            self.seal_sequence_segment()  # ENH_STAT-coupled: full reset
            self._fw_loss.reset()
            self._fw_written.reset()
            self._enh_stat_prev.clear()
            self._enh_zero_baseline = True
            self._prev_written.clear()
            self._buf_util.reset()
        elif reason == "flush":
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
    """Merge per-stream and per-segment summaries into one capture-level view.

    The merge sums continuity counters, but no single SN range describes the
    result: it spans several streams (the shared counter plus REDIR's private
    one) and several firmware segments, so the range stays on the per-source
    entries instead.
    """

    merged: dict[SourceCode, SequenceSourceSummary] = {}
    observed = 0
    missing = 0
    segments = 0
    late = 0
    duplicates = 0
    wraps = 0
    uncertain = False
    per_source = False
    for summary in summaries:
        observed += summary.observed_frames
        missing += summary.missing_frames
        segments += summary.segments
        late += summary.late_frames
        duplicates += summary.duplicate_frames
        wraps += summary.wraps
        uncertain = uncertain or summary.uncertain
        per_source = per_source or summary.per_source
        for current in summary.sources:
            previous = merged.get(current.source)
            if previous is None:
                merged[current.source] = current
                continue
            merged[current.source] = SequenceSourceSummary(
                source=current.source,
                observed_frames=previous.observed_frames + current.observed_frames,
                first_sn=previous.first_sn if previous.first_sn is not None else current.first_sn,
                last_sn=current.last_sn if current.last_sn is not None else previous.last_sn,
                missing_frames=previous.missing_frames + current.missing_frames,
                segments=previous.segments + current.segments,
                late_frames=previous.late_frames + current.late_frames,
                duplicate_frames=previous.duplicate_frames + current.duplicate_frames,
                wraps=previous.wraps + current.wraps,
                uncertain=previous.uncertain or current.uncertain,
            )
    return SequenceSummary(
        observed_frames=observed,
        missing_frames=missing,
        segments=segments,
        late_frames=late,
        duplicate_frames=duplicates,
        wraps=wraps,
        uncertain=uncertain,
        per_source=per_source,
        sources=tuple(merged[source] for source in sorted(merged)),
    )
