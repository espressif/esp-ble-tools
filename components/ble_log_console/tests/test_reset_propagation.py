# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Reset propagation matrix tests.

Verifies that reset("init") and reset("flush") dispatch correctly per the spec:

| Group            | Components                              | INIT_DONE    | FLUSH                              |
|------------------|-----------------------------------------|--------------|------------------------------------|
| SN-coupled       | SNGapTracker                            | new segment  | preserved                          |
| ENH_STAT-coupled | FirmwareLossTracker, FirmwareWritten    | full reset   | reset baselines, keep latest snapshot |
| Console-local    | TransportMetrics, per_source_received,  | preserve     | preserve                           |
|                  | throughput cache                        |              |                                    |
"""

from src.backend.support.stats import StatsAccumulator


class TestResetPropagation:
    """Verify reset("init") and reset("flush") dispatch correctly per the spec."""

    def _populate(self, stats: StatsAccumulator) -> None:
        """Feed data into all components so we can verify what gets reset."""
        # Transport (console-local)
        stats.record_bytes(1000)
        stats.record_frame(100, 1, 10)  # frame_size=100, src=1, sn=10
        stats.record_frame(100, 1, 11)
        # ENH_STAT (firmware-coupled)
        stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=5, written_bytes=5000, lost_bytes=250
        )
        stats.record_enh_stat(
            src_code=1, written_frames=200, lost_frames=10, written_bytes=10000, lost_bytes=500
        )

    # === INIT_DONE Tests ===

    def test_init_resets_sn_gap(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(100, 1, 0)
        stats.record_frame(100, 1, 1)
        stats.reset('init')
        stats.record_frame(100, 1, 100)
        funnel = stats.funnel_snapshot()
        for snap in funnel:
            if snap.source == 1:
                assert snap.received.frames == 3

    def test_init_resets_firmware_loss(self) -> None:
        stats = StatsAccumulator()
        self._populate(stats)
        stats.reset('init')
        # INIT_DONE is a trusted zero baseline, so the first report belongs
        # to this capture instead of being discarded as historical loss.
        stats.record_enh_stat(1, 50, 3, 2500, 150)
        funnel = stats.funnel_snapshot()
        for snap in funnel:
            if snap.source == 1:
                assert snap.buffer_loss.frames == 3  # first report absolute value
        capture_loss = stats.capture_firmware_loss()
        assert capture_loss[0].frames == 8
        assert capture_loss[0].bytes == 400

    def test_init_resets_firmware_written(self) -> None:
        stats = StatsAccumulator()
        self._populate(stats)
        stats.reset('init')
        stats.record_enh_stat(1, 50, 0, 2500, 0)
        funnel = stats.funnel_snapshot()
        for snap in funnel:
            if snap.source == 1:
                assert snap.written.frames == 50  # first report absolute value

    def test_init_preserves_transport_metrics(self) -> None:
        stats = StatsAccumulator()
        stats.record_bytes(5000)
        stats.record_frame()
        stats.reset('init')
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.rx_bytes == 5000
        assert snapshot.transport.fps == 1.0

    def test_init_preserves_per_source_received(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(100, 1, 0)
        stats.reset('init')
        funnel = stats.funnel_snapshot()
        assert len(funnel) == 1
        assert funnel[0].received.frames == 1

    # === FLUSH Tests ===

    def test_flush_preserves_sn_tracking(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(100, 1, 0)
        stats.record_frame(100, 1, 1)
        stats.reset('flush')
        stats.record_frame(100, 1, 0)

        sequence = stats.finalize_sequence().sources[0]
        assert sequence.missing_frames == 0
        assert sequence.segments == 1
        assert sequence.duplicate_frames == 1

    def test_flush_updates_firmware_loss_to_latest_snapshot(self) -> None:
        stats = StatsAccumulator()
        # Build up some loss: baseline then delta
        stats.record_enh_stat(1, 100, 5, 5000, 250)
        stats.record_enh_stat(1, 200, 10, 10000, 500)
        # Now flush
        stats.reset('flush')
        # Next report re-establishes baseline (no additional delta)
        stats.record_enh_stat(1, 50, 3, 2500, 150)
        funnel = stats.funnel_snapshot()
        for snap in funnel:
            if snap.source == 1:
                assert snap.buffer_loss.frames == 3

    def test_flush_updates_firmware_written_to_latest_snapshot(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(1, 100, 0, 5000, 0)
        stats.record_enh_stat(1, 200, 0, 10000, 0)
        stats.reset('flush')
        stats.record_enh_stat(1, 50, 0, 2500, 0)
        funnel = stats.funnel_snapshot()
        for snap in funnel:
            if snap.source == 1:
                assert snap.written.frames == 50

    def test_flush_preserves_transport_metrics(self) -> None:
        stats = StatsAccumulator()
        stats.record_bytes(5000)
        stats.record_frame()
        stats.reset('flush')
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.rx_bytes == 5000  # preserved

    def test_flush_preserves_per_source_received(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(100, 1, 0)
        stats.record_frame(100, 1, 1)
        stats.reset('flush')
        funnel = stats.funnel_snapshot()
        for snap in funnel:
            if snap.source == 1:
                assert snap.received.frames == 2  # preserved
