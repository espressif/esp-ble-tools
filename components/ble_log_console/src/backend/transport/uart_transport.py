# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""UART implementation of the BLE log transport interface."""

from __future__ import annotations

import time

import serial
import serial.tools.list_ports

from src.backend.models import TransportConfig
from src.backend.models import TransportBitrate
from src.backend.transport.base import TransportMode
from src.backend.transport.base import TransportProvider


UART_BITS_PER_BYTE = 10

UART_READ_TIMEOUT = 0.1
UART_BLOCK_SIZE = 50 * 1024

def list_serial_ports() -> list[str]:
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]


def validate_uart_port(port: str) -> str | None:
    """Validate port exists and is accessible. Returns error message or None if valid."""
    available = list_serial_ports()
    if port not in available:
        return f"UART port '{port}' not found. Available: {available}"
    return None


def open_serial(port: str, baudrate: int) -> serial.Serial:
    try:
        return serial.Serial(port, baudrate=baudrate, timeout=UART_READ_TIMEOUT, exclusive=True)
    except (ValueError, serial.SerialException):
        return serial.Serial(port, baudrate=baudrate, timeout=UART_READ_TIMEOUT)


class UartTransport:
    def __init__(self, port: str, baudrate: int) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial: serial.Serial = open_serial(port, baudrate)

    @property
    def display_name(self) -> str:
        return f'UART {self._port} @ {self._baudrate}'

    @property
    def block_size(self) -> int:
        return UART_BLOCK_SIZE

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate(
            bits_per_payload_byte=UART_BITS_PER_BYTE,
            wire_bits_per_sec=float(self._baudrate),
        )

    def read(self, size: int | None = None) -> bytes:
        return self._serial.read(size or self.block_size)  # type: ignore[no-any-return]

    def close(self) -> None:
        self._serial.close()

    def reset_target(self) -> bool:
        if not self._serial.is_open:
            return False
        self._serial.dtr = False
        self._serial.rts = True
        time.sleep(0.1)
        self._serial.rts = False
        return True


def list_uart_options() -> list[tuple[str, str]]:
    return [(port, port) for port in list_serial_ports()]


def open_uart_transport(port: str, baudrate: int) -> UartTransport:
    return UartTransport(port, baudrate)


class UartTransportProvider:

    @property
    def label(self) -> str:
        return 'UART'

    @property
    def mode(self) -> TransportMode:
        return TransportMode.UART

    def list_options(self) -> list[tuple[str, str]]:
        return list_uart_options()

    def open(self, config: TransportConfig) -> UartTransport:
        return open_uart_transport(config.port, config.baudrate)


PROVIDER: TransportProvider = UartTransportProvider()
