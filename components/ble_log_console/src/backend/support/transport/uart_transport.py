# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""UART implementation of the BLE log transport interface."""

from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports

from src.backend.models import TransportBitrate
from src.backend.models import TransportConfig
from src.backend.support.transport.base import TransportMode
from src.backend.support.transport.base import TransportProvider
from src.backend.support.transport.serial_reader import SerialReader


UART_BITS_PER_BYTE = 10

UART_READ_TIMEOUT = 0.1
UART_BLOCK_SIZE = 50 * 1024


def list_serial_ports() -> list[str]:
    ports = serial.tools.list_ports.comports()
    devices = [port.device for port in ports]
    if sys.platform.startswith('linux'):
        return [device for device in devices if device.startswith(('/dev/ttyUSB', '/dev/ttyACM'))]
    return devices


def validate_uart_port(port: str) -> str | None:
    """Validate port exists and is accessible. Returns error message or None if valid."""
    available = list_serial_ports()
    if port not in available:
        return f"UART port '{port}' not found. Available: {available}"
    return None


class UartTransport(SerialReader):
    mode = TransportMode.UART
    block_size = UART_BLOCK_SIZE
    timeout = UART_READ_TIMEOUT
    open_exclusive = True
    not_open_message = 'UART transport is not open'

    @property
    def display_name(self) -> str:
        return f'UART {self._port} @ {self._baudrate}'

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate(
            bits_per_payload_byte=UART_BITS_PER_BYTE,
            wire_bits_per_sec=float(self._baudrate),
        )

    def reset_target(self) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        self._serial.dtr = False
        self._serial.rts = True
        time.sleep(0.1)
        self._serial.rts = False
        return True


def list_uart_options() -> list[tuple[str, str]]:
    return [(port, port) for port in list_serial_ports()]


class UartTransportProvider:

    @property
    def label(self) -> str:
        return 'UART'

    @property
    def mode(self) -> TransportMode:
        return TransportMode.UART

    def list_options(self) -> list[tuple[str, str]]:
        return list_uart_options()

    def create_reader(self, config: TransportConfig) -> UartTransport:
        return UartTransport(config.port, config.baudrate)


PROVIDER: TransportProvider = UartTransportProvider()
