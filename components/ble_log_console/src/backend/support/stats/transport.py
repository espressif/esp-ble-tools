# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Transport-layer metrics: RX bytes, throughput, and frame rate."""

from src.backend.models import TransportSnapshot
from src.backend.models import TransportBitrate


class TransportMetrics:
    """Tracks cumulative RX bytes and frame count with delta-based rate snapshots."""

    def __init__(self) -> None:
        self._bitrate = TransportBitrate()
        self._rx_bytes = 0
        self._rx_bytes_snapshot = 0
        self._frame_count = 0
        self._frame_count_snapshot = 0
        self._max_rx_bits_per_sec = 0.0

    def set_bitrate(self, bitrate: TransportBitrate) -> None:
        self._bitrate = bitrate

    def record_bytes(self, count: int) -> None:
        self._rx_bytes += count

    def record_frame(self) -> None:
        self._frame_count += 1

    def record_frames(self, count: int) -> None:
        self._frame_count += count

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def harvest(self, elapsed_sec: float) -> TransportSnapshot:
        """Compute rates from deltas since last harvest, update max, and reset deltas."""
        rx_delta = self._rx_bytes - self._rx_bytes_snapshot
        frame_delta = self._frame_count - self._frame_count_snapshot

        rx_bits_per_sec = (
            self._bitrate.payload_bytes_to_wire_bits(rx_delta) / elapsed_sec if elapsed_sec > 0 else 0.0
        )
        fps = frame_delta / elapsed_sec if elapsed_sec > 0 else 0.0

        if rx_bits_per_sec > self._max_rx_bits_per_sec:
            self._max_rx_bits_per_sec = rx_bits_per_sec

        self._rx_bytes_snapshot = self._rx_bytes
        self._frame_count_snapshot = self._frame_count

        return TransportSnapshot(
            rx_bytes=self._rx_bytes,
            rx_frames=self._frame_count,
            rx_bits_per_sec=rx_bits_per_sec,
            max_rx_bits_per_sec=self._max_rx_bits_per_sec,
            fps=fps,
        )
