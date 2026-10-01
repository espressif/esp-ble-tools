# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from src.backend.support.stats.sn_gap import SN_MAX, SNGapTracker

LL_TASK = 2
ENCODE = 7
INTERNAL = 0


class TestSNGapTracker:
    def setup_method(self) -> None:
        self.tracker = SNGapTracker()

    # --- Baseline ---
    def test_first_frame_establishes_baseline(self) -> None:
        assert self.tracker.record(42) == 0
        assert self.tracker.finalize().missing_frames == 0

    # --- In-order ---
    def test_sequential_no_gap(self) -> None:
        self.tracker.record(0)
        assert self.tracker.record(1) == 0
        assert self.tracker.record(2) == 0

    # --- One stream shared by every source ---
    def test_sources_share_one_sequence_space(self) -> None:
        """A per-source window counts the other sources' frames as own loss."""
        for frame_sn in range(100):
            self.tracker.record(frame_sn, LL_TASK if frame_sn % 2 else ENCODE)

        summary = self.tracker.finalize()

        assert summary.observed_frames == 100
        assert summary.missing_frames == 0

    def test_skipping_a_number_is_loss_whatever_source_took_it(self) -> None:
        """A source that stops transmitting does not make its last SN lost."""
        self.tracker.record(0, LL_TASK)
        self.tracker.record(1, INTERNAL)  # snapshot frame consumes SN 1
        self.tracker.record(2, ENCODE)

        summary = self.tracker.finalize()

        assert summary.missing_frames == 0
        assert summary.observed_frames == 3

    def test_source_tallies_are_observations_not_gap_scopes(self) -> None:
        self.tracker.record(0, LL_TASK)
        self.tracker.record(1, ENCODE)

        summary = self.tracker.finalize()

        assert [(source.source, source.observed_frames) for source in summary.sources] == [
            (LL_TASK, 1),
            (ENCODE, 1),
        ]
        assert summary.observed_frames == 2

    # --- Simple reorder (within window) ---
    def test_reorder_no_false_gap(self) -> None:
        """SN=8 arrives before SN=5,6,7 — no gaps should be counted."""
        self.tracker.record(5)  # baseline → window_base=6
        assert self.tracker.record(8) == 0  # within window, NOT a gap
        assert self.tracker.record(6) == 0  # late fill
        assert self.tracker.record(7) == 0  # late fill

        summary = self.tracker.finalize()

        assert summary.missing_frames == 0
        assert summary.last_sn == 8

    # --- Confirmed loss ---
    def test_loss_confirmed_when_window_expires(self) -> None:
        """Frame beyond window forces expiry of unreceived SNs."""
        self.tracker.record(0)  # baseline → base=1
        # SN=1 never arrives; jump to SN=257 (beyond window of 256)
        gaps = self.tracker.record(257)
        assert gaps > 0  # SN=1 expired as confirmed loss
        assert self.tracker.finalize().missing_frames > 0

    def test_large_forward_gap_is_counted_without_walking_every_sn(self) -> None:
        self.tracker.record(0)
        self.tracker.record(1_000_000)

        assert self.tracker.finalize().missing_frames == 999_999

    # --- Late arrival behind window ---
    def test_late_arrival_ignored(self) -> None:
        self.tracker.record(0)
        self.tracker.record(257)  # force window advance past 0
        assert self.tracker.record(1) == 0  # too late, ignored

    # --- Ambiguous reset/old data ---
    def test_large_backward_jump_is_not_guessed_as_a_reset(self) -> None:
        self.tracker.record(1000)
        self.tracker.record(5)

        assert self.tracker.finalize().uncertain

    # --- Reset method ---
    def test_reset_clears_all(self) -> None:
        self.tracker.record(10)
        self.tracker.reset()
        # After reset, next frame establishes new baseline
        assert self.tracker.record(0) == 0
        assert self.tracker.finalize().observed_frames == 1

    def test_finalize_seals_pending_gaps_through_highest_observed_sn(self) -> None:
        self.tracker.record(5)
        self.tracker.record(8)

        summary = self.tracker.finalize()

        assert summary.first_sn == 5
        assert summary.last_sn == 8
        assert summary.observed_frames == 2
        assert summary.missing_frames == 2
        assert summary.segments == 1

    def test_finalize_does_not_infer_frames_after_last_observed_sn(self) -> None:
        self.tracker.record(42)

        assert self.tracker.finalize().missing_frames == 0

    def test_very_late_frames_reconcile_confirmed_gaps(self) -> None:
        late = (100, 500)
        for frame_sn in range(1000):
            if frame_sn not in late:
                self.tracker.record(frame_sn)
        for frame_sn in late:
            self.tracker.record(frame_sn)

        summary = self.tracker.finalize()

        assert summary.missing_frames == 0
        assert summary.segments == 1
        assert summary.last_sn == 999
        assert summary.late_frames == 2

    def test_sparse_gap_evidence_is_bounded(self) -> None:
        tracker = SNGapTracker(max_gap_ranges=1)
        for frame_sn in range(1000):
            if frame_sn not in (100, 500):
                tracker.record(frame_sn)

        assert tracker.finalize().uncertain

    # --- Wraparound ---
    def test_wraparound(self) -> None:
        self.tracker.record(SN_MAX - 2)  # base = SN_MAX-1
        assert self.tracker.record(SN_MAX - 1) == 0
        assert self.tracker.record(0) == 0  # wraps to 0
        assert self.tracker.record(1) == 0

        summary = self.tracker.finalize()

        assert summary.wraps == 1
        assert summary.missing_frames == 0
