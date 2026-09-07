# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from src.backend.models import TransportBitrate


def test_transport_bitrate_default_spi_like_conversion() -> None:
    bitrate = TransportBitrate()

    assert bitrate.payload_bytes_to_wire_bits(128) == 1024
    assert bitrate.max_payload_bytes_per_sec is None


def test_transport_bitrate_uart_capacity_conversion() -> None:
    bitrate = TransportBitrate(bits_per_payload_byte=10, wire_bits_per_sec=3_000_000)

    assert bitrate.payload_bytes_to_wire_bits(128) == 1280
    assert bitrate.max_payload_bytes_per_sec == 300_000
