# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from src.backend.models import TransportBitrate
from src.backend.stats.transport import TransportMetrics


class TestTransportMetrics:
    def test_initial_harvest(self) -> None:
        t = TransportMetrics()
        snap = t.harvest(1.0)
        assert snap.rx_bytes == 0
        assert snap.rx_bits_per_sec == 0.0
        assert snap.fps == 0.0

    def test_record_bytes(self) -> None:
        t = TransportMetrics()
        t.record_bytes(1024)
        snap = t.harvest(1.0)
        assert snap.rx_bytes == 1024
        assert snap.rx_bits_per_sec == 8192.0

    def test_uart_bitrate_conversion(self) -> None:
        t = TransportMetrics()
        t.set_bitrate(TransportBitrate(bits_per_payload_byte=10, wire_bits_per_sec=3_000_000))
        t.record_bytes(1024)
        snap = t.harvest(1.0)
        assert snap.rx_bits_per_sec == 10240.0

    def test_record_frame(self) -> None:
        t = TransportMetrics()
        t.record_frame()
        t.record_frame()
        snap = t.harvest(1.0)
        assert snap.fps == 2.0

    def test_max_bps_persists(self) -> None:
        t = TransportMetrics()
        t.record_bytes(10000)
        t.harvest(1.0)
        t.record_bytes(100)
        snap = t.harvest(1.0)
        assert snap.max_rx_bits_per_sec == 80000.0

    def test_zero_elapsed(self) -> None:
        t = TransportMetrics()
        t.record_bytes(100)
        snap = t.harvest(0.0)
        assert snap.rx_bits_per_sec == 0.0
        assert snap.fps == 0.0

    def test_delta_resets_between_harvests(self) -> None:
        t = TransportMetrics()
        t.record_bytes(1000)
        t.harvest(1.0)
        snap = t.harvest(1.0)
        assert snap.rx_bits_per_sec == 0.0
        assert snap.rx_bytes == 1000
