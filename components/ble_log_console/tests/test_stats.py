# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from src.backend.models import BleLogSource
from src.backend.models import TransportBitrate
from src.backend.models import has_os_ts
from src.backend.support.stats import StatsAccumulator


def _set_uart_bitrate(stats: StatsAccumulator, baudrate: int = 3_000_000) -> None:
    stats.set_transport_bitrate(TransportBitrate(bits_per_payload_byte=10, wire_bits_per_sec=float(baudrate)))


class TestStatsAccumulator:
    def test_initial_state(self) -> None:
        stats = StatsAccumulator()
        snapshot = stats.snapshot(0.25)
        assert snapshot.transport.rx_bytes == 0
        assert snapshot.loss.total_frames == 0
        assert snapshot.loss.total_bytes == 0

    def test_record_bytes(self) -> None:
        stats = StatsAccumulator()
        stats.record_bytes(1024)
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.rx_bytes == 1024
        assert snapshot.transport.rx_bits_per_sec == 8192.0

    def test_record_bytes_with_uart_bitrate(self) -> None:
        stats = StatsAccumulator()
        _set_uart_bitrate(stats)
        stats.record_bytes(1024)
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.rx_bits_per_sec == 10240.0

    def test_record_frame(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame()
        stats.record_frame()
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.fps == 2.0

    def test_max_bps_tracked(self) -> None:
        stats = StatsAccumulator()
        stats.record_bytes(10000)
        stats.snapshot(1.0)
        stats.record_bytes(100)
        snap2 = stats.snapshot(1.0)
        assert snap2.transport.max_rx_bits_per_sec == 80000.0

    def _enh_stat_loss(
        self, stats: StatsAccumulator, src_code: int, lost_frames: int, lost_bytes: int
    ) -> tuple[int, int]:
        """Helper: call record_enh_stat with dummy written counters, return loss delta."""
        return stats.record_enh_stat(  # type: ignore[no-any-return]
            src_code=src_code,
            written_frames=0,
            lost_frames=lost_frames,
            written_bytes=0,
            lost_bytes=lost_bytes,
        )

    def test_firmware_loss_first_report_zero_delta(self) -> None:
        """First ENH_STAT initializes prev (delta=0); subsequent reports show delta."""
        stats = StatsAccumulator()
        new_frames, new_bytes = self._enh_stat_loss(stats, src_code=1, lost_frames=1000, lost_bytes=5000)
        assert new_frames == 0
        assert new_bytes == 0
        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 1000
        assert snapshot.loss.total_bytes == 5000

        new_frames, new_bytes = self._enh_stat_loss(stats, src_code=1, lost_frames=1003, lost_bytes=5128)
        assert new_frames == 3
        assert new_bytes == 128
        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 1003
        assert snapshot.loss.total_bytes == 5128

    def test_firmware_loss_incremental_returns(self) -> None:
        """Incremental return reflects per-report delta, not cumulative."""
        stats = StatsAccumulator()
        self._enh_stat_loss(stats, src_code=1, lost_frames=0, lost_bytes=0)

        new_frames, new_bytes = self._enh_stat_loss(stats, src_code=1, lost_frames=5, lost_bytes=200)
        assert new_frames == 5
        assert new_bytes == 200

        new_frames, new_bytes = self._enh_stat_loss(stats, src_code=1, lost_frames=8, lost_bytes=320)
        assert new_frames == 3
        assert new_bytes == 120

    def test_multi_source_firmware_loss(self) -> None:
        """Firmware loss tracked independently per source code."""
        stats = StatsAccumulator()
        self._enh_stat_loss(stats, src_code=1, lost_frames=100, lost_bytes=1000)
        self._enh_stat_loss(stats, src_code=2, lost_frames=50, lost_bytes=500)
        self._enh_stat_loss(stats, src_code=1, lost_frames=105, lost_bytes=1200)
        self._enh_stat_loss(stats, src_code=2, lost_frames=52, lost_bytes=580)
        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 157  # 100 + 50 + 5 + 2
        assert snapshot.loss.total_bytes == 1780  # 1000 + 500 + 200 + 80

    def test_firmware_loss_counter_reset(self) -> None:
        """Counter reset follows the latest firmware snapshot."""
        stats = StatsAccumulator()
        self._enh_stat_loss(stats, src_code=1, lost_frames=0, lost_bytes=0)
        self._enh_stat_loss(stats, src_code=1, lost_frames=100, lost_bytes=4000)

        new_frames, new_bytes = self._enh_stat_loss(stats, src_code=1, lost_frames=30, lost_bytes=1200)
        assert new_frames == 0
        assert new_bytes == 0

        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 30
        assert snapshot.loss.total_bytes == 1200

        new_frames, new_bytes = self._enh_stat_loss(stats, src_code=1, lost_frames=50, lost_bytes=2000)
        assert new_frames == 20
        assert new_bytes == 800
        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 50
        assert snapshot.loss.total_bytes == 2000

    def test_firmware_loss_multiple_resets(self) -> None:
        """Multiple resets follow the latest firmware snapshot."""
        stats = StatsAccumulator()
        self._enh_stat_loss(stats, src_code=1, lost_frames=0, lost_bytes=0)
        self._enh_stat_loss(stats, src_code=1, lost_frames=50, lost_bytes=2000)

        self._enh_stat_loss(stats, src_code=1, lost_frames=10, lost_bytes=400)
        self._enh_stat_loss(stats, src_code=1, lost_frames=30, lost_bytes=1200)

        self._enh_stat_loss(stats, src_code=1, lost_frames=5, lost_bytes=200)

        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 5
        assert snapshot.loss.total_bytes == 200

    def test_firmware_loss_uint32_overflow_follows_latest_snapshot(self) -> None:
        """uint32 counter wrap/reset follows the latest firmware snapshot."""
        stats = StatsAccumulator()
        self._enh_stat_loss(stats, src_code=1, lost_frames=0xFFFF_FF00, lost_bytes=0)

        new_frames, _ = self._enh_stat_loss(stats, src_code=1, lost_frames=50, lost_bytes=0)
        assert new_frames == 0

        snapshot = stats.snapshot(0.25)
        assert snapshot.loss.total_frames == 50


class TestRecordFrameWithSN:
    def test_backward_compatible_no_args(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame()
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.fps == 1.0

    def test_tracks_per_source_received(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        stats.record_frame(frame_size=200, src_code=1, frame_sn=1)
        stats.record_frame(frame_size=50, src_code=2, frame_sn=0)
        assert stats._per_source_received_frames[1] == 2
        assert stats._per_source_received_bytes[1] == 300
        assert stats._per_source_received_frames[2] == 1
        assert stats._per_source_received_bytes[2] == 50

    def test_sn_gap_tracked(self) -> None:
        stats = StatsAccumulator()
        stats.set_firmware_version(4)  # enable SN gap tracking (requires version >= 4)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        # SN=257 is beyond the reorder window (256), forcing SN=1 to be confirmed lost
        stats.record_frame(frame_size=100, src_code=1, frame_sn=257)
        assert stats._sn_gap.totals() == {1: 1}

    def test_no_sn_tracking_when_sn_negative(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=1, frame_sn=-1)
        assert 1 not in stats._per_source_received_frames
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.fps == 1.0

    def test_no_sn_tracking_when_src_zero(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=0, frame_sn=5)
        assert 0 not in stats._per_source_received_frames


class TestRecordEnhStat:
    def test_feeds_both_trackers(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=10, written_bytes=5000, lost_bytes=500)
        written = stats._fw_written.totals()
        assert written[1] == (100, 5000)
        loss = stats._fw_loss.per_source_totals()
        assert loss[1] == (10, 500)

    def test_returns_loss_delta(self) -> None:
        stats = StatsAccumulator()
        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        assert (d_f, d_b) == (0, 0)

        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=50, lost_frames=5, written_bytes=2500, lost_bytes=250)
        assert (d_f, d_b) == (5, 250)

    def test_torn_read_guard_rejects_implausible_written_bytes(self) -> None:
        stats = StatsAccumulator()
        baudrate = 3_000_000
        _set_uart_bitrate(stats, baudrate)
        max_delta = baudrate * 2 // 10
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=10, lost_frames=0, written_bytes=max_delta + 1, lost_bytes=0)
        assert (d_f, d_b) == (0, 0)
        assert stats._fw_written.totals()[1] == (0, 0)

    def test_torn_read_guard_rejects_implausible_lost_bytes(self) -> None:
        stats = StatsAccumulator()
        baudrate = 3_000_000
        _set_uart_bitrate(stats, baudrate)
        max_delta = baudrate * 2 // 10
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=10, lost_frames=5, written_bytes=500, lost_bytes=max_delta + 1)
        assert (d_f, d_b) == (0, 0)
        assert stats._fw_loss.per_source_totals()[1] == (0, 0)

    def test_torn_read_guard_accepts_plausible_delta(self) -> None:
        stats = StatsAccumulator()
        baudrate = 3_000_000
        _set_uart_bitrate(stats, baudrate)
        max_delta = baudrate * 2 // 10
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=10, lost_frames=2, written_bytes=max_delta, lost_bytes=100)
        assert d_f == 2
        assert d_b == 100

    def test_torn_read_recovery_uses_last_good_prev(self) -> None:
        stats = StatsAccumulator()
        baudrate = 3_000_000
        _set_uart_bitrate(stats, baudrate)
        max_delta = baudrate * 2 // 10
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=10, lost_frames=0, written_bytes=max_delta + 1, lost_bytes=0)
        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=20, lost_frames=3, written_bytes=1000, lost_bytes=150)
        assert d_f == 3
        assert d_b == 150


class TestRecordFrameReturnsGap:
    def test_returns_zero_for_sequential_frames(self) -> None:
        stats = StatsAccumulator()
        stats.set_firmware_version(4)
        assert stats.record_frame(frame_size=100, src_code=1, frame_sn=0) == 0
        assert stats.record_frame(frame_size=100, src_code=1, frame_sn=1) == 0

    def test_returns_gap_count_for_large_jump(self) -> None:
        stats = StatsAccumulator()
        stats.set_firmware_version(4)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        gap = stats.record_frame(frame_size=100, src_code=1, frame_sn=300)
        assert gap > 0

    def test_returns_zero_when_no_sn_tracking(self) -> None:
        stats = StatsAccumulator()
        assert stats.record_frame(frame_size=100, src_code=1, frame_sn=-1) == 0
        assert stats.record_frame(frame_size=100, src_code=0, frame_sn=5) == 0

    def test_sn_gap_disabled_for_old_firmware(self) -> None:
        stats = StatsAccumulator()
        stats.set_firmware_version(3)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        gap = stats.record_frame(frame_size=100, src_code=1, frame_sn=300)
        assert gap == 0

    def test_sn_gap_disabled_by_default(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        gap = stats.record_frame(frame_size=100, src_code=1, frame_sn=300)
        assert gap == 0


class TestReset:
    def test_init_clears_firmware_preserves_console(self) -> None:
        stats = StatsAccumulator()
        stats.record_bytes(1000)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=50, lost_frames=5, written_bytes=2500, lost_bytes=250)
        stats.reset('init')

        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.rx_bytes == 1000
        assert snapshot.loss.total_frames == 0
        assert stats._per_source_received_frames == {1: 1}
        assert stats._per_source_received_bytes == {1: 100}
        assert stats._fw_written.totals() == {}

    def test_flush_resets_baselines_only(self) -> None:
        stats = StatsAccumulator()
        stats.record_bytes(1000)
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=50, lost_frames=5, written_bytes=2500, lost_bytes=250)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)

        stats.reset('flush')

        # Console-local data preserved
        snapshot = stats.snapshot(1.0)
        assert snapshot.transport.rx_bytes == 1000
        assert stats._per_source_received_bytes == {1: 100}

        # Loss latest snapshot preserved until the next ENH_STAT updates it.
        assert snapshot.loss.total_frames == 5

        # Next ENH_STAT re-baselines (first report = 0 delta)
        d_f, d_b = stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=10, written_bytes=5000, lost_bytes=500)
        assert (d_f, d_b) == (0, 0)


class TestFunnelSnapshot:
    def test_empty(self) -> None:
        stats = StatsAccumulator()
        assert stats.funnel_snapshot() == []

    def test_single_source_full_data(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=10, written_bytes=5000, lost_bytes=500)
        stats.record_frame(frame_size=80, src_code=1, frame_sn=0)
        stats.record_frame(frame_size=80, src_code=1, frame_sn=1)

        stats.funnel_snapshot()  # establishes prev_written baseline
        funnels = stats.funnel_snapshot()
        assert len(funnels) == 1
        f = funnels[0]
        assert f.source == 1
        assert f.written.frames == 100
        assert f.written.bytes == 5000
        assert f.buffer_loss.frames == 10
        assert f.buffer_loss.bytes == 500
        assert f.produced.frames == 110
        assert f.produced.bytes == 5500
        assert f.received.frames == 2
        assert f.received.bytes == 160
        assert f.transport_loss.frames == 98
        assert f.transport_loss.bytes == 4840

    def test_transport_loss_zero_on_first_snapshot(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=0, written_bytes=5000, lost_bytes=0)
        stats.record_frame(frame_size=80, src_code=1, frame_sn=0)
        funnels = stats.funnel_snapshot()
        assert funnels[0].transport_loss.frames == 0

    def test_transport_loss_stable_after_written_jump(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=50, lost_frames=0, written_bytes=2500, lost_bytes=0)
        for i in range(50):
            stats.record_frame(frame_size=50, src_code=1, frame_sn=i)
        stats.funnel_snapshot()  # prev_written = {1: (50, 2500)}
        stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=0, written_bytes=5000, lost_bytes=0)
        for i in range(49):
            stats.record_frame(frame_size=50, src_code=1, frame_sn=50 + i)
        funnels = stats.funnel_snapshot()
        assert funnels[0].transport_loss.frames == 0

    def test_multi_source(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=2, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=50, lost_frames=5, written_bytes=2500, lost_bytes=250)
        stats.record_enh_stat(
            src_code=2, written_frames=30, lost_frames=2, written_bytes=1500, lost_bytes=100)
        funnels = stats.funnel_snapshot()
        assert len(funnels) == 2
        assert funnels[0].source == 1
        assert funnels[1].source == 2
        assert funnels[0].written.frames == 50
        assert funnels[1].written.frames == 30

    def test_throughput_lifetime_average(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=1)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=2)
        funnels = stats.funnel_snapshot(elapsed_sec=1.0)
        assert funnels[0].throughput.throughput_fps == 3.0
        assert funnels[0].throughput.throughput_bits_per_sec == 2400.0

    def test_throughput_accumulates_across_snapshots(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        stats.record_frame(frame_size=100, src_code=1, frame_sn=1)
        stats.funnel_snapshot(elapsed_sec=1.0)
        stats.record_frame(frame_size=200, src_code=1, frame_sn=2)
        funnels = stats.funnel_snapshot(elapsed_sec=1.0)
        assert funnels[0].throughput.throughput_fps == 1.5
        assert funnels[0].throughput.throughput_bits_per_sec == 1600.0

    def test_throughput_zero_without_elapsed(self) -> None:
        stats = StatsAccumulator()
        stats.record_frame(frame_size=100, src_code=1, frame_sn=0)
        funnels = stats.funnel_snapshot()
        assert funnels[0].throughput.throughput_fps == 0.0
        assert funnels[0].throughput.throughput_bits_per_sec == 0.0


class TestFunnelExcludesInternal:
    def test_internal_only_returns_empty(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=0, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=0, written_frames=50, lost_frames=0, written_bytes=2500, lost_bytes=0)
        funnels = stats.funnel_snapshot()
        assert funnels == []

    def test_internal_excluded_alongside_others(self) -> None:
        stats = StatsAccumulator()
        stats.record_enh_stat(
            src_code=0, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=0, written_frames=50, lost_frames=0, written_bytes=2500, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=0, lost_frames=0, written_bytes=0, lost_bytes=0)
        stats.record_enh_stat(
            src_code=1, written_frames=100, lost_frames=0, written_bytes=5000, lost_bytes=0)
        funnels = stats.funnel_snapshot()
        assert len(funnels) == 1
        assert funnels[0].source == 1


class TestHasOsTs:
    def test_sources_with_os_ts(self) -> None:
        assert has_os_ts(BleLogSource.INTERNAL) is True
        assert has_os_ts(BleLogSource.CUSTOM) is True
        assert has_os_ts(BleLogSource.HOST) is True
        assert has_os_ts(BleLogSource.HCI) is True
        assert has_os_ts(BleLogSource.ENCODE) is True

    def test_sources_without_os_ts(self) -> None:
        assert has_os_ts(BleLogSource.LL_TASK) is False
        assert has_os_ts(BleLogSource.LL_HCI) is False
        assert has_os_ts(BleLogSource.LL_ISR) is False
        assert has_os_ts(BleLogSource.REDIR) is False
