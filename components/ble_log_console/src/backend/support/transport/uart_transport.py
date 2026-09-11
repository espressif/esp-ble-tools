# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""UART implementation of the BLE log transport interface."""

from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports

from src.backend.models import TransportConfig
from src.backend.models import TransportBitrate
from src.backend.support.transport.base import TransportMode
from src.backend.support.transport.base import TransportProvider
from src.backend.support.transport.base import TransportStatus


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


def open_serial(port: str, baudrate: int) -> serial.Serial:
    try:
        return serial.Serial(port, baudrate=baudrate, timeout=UART_READ_TIMEOUT, exclusive=True)
    except (ValueError, serial.SerialException):
        return serial.Serial(port, baudrate=baudrate, timeout=UART_READ_TIMEOUT)


class UartTransport:
    def __init__(self, port: str, baudrate: int) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial: serial.Serial | None = None
        self._rx_bytes = 0
        self._rx_chunks = 0
        self._last_error: str | None = None

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

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        try:
            self._serial = open_serial(self._port, self._baudrate)
            self._last_error = None
        except Exception as e:
            self._last_error = str(e)
            raise

    def read(self, size: int | None = None) -> bytes:
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError('UART transport is not open')
        block = self._serial.read(size or self.block_size)  # type: ignore[no-any-return]
        if block:
            self._rx_bytes += len(block)
            self._rx_chunks += 1
        return block

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        blocks: list[bytes] = []
        for _ in range(max_rounds):
            block = self.read()
            if not block:
                break
            blocks.append(block)
        return blocks

    def close(self) -> None:
        if self._serial is None:
            return
        self._serial.close()

    def reset_target(self) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        self._serial.dtr = False
        self._serial.rts = True
        time.sleep(0.1)
        self._serial.rts = False
        return True

    def status(self) -> TransportStatus:
        opened = self._serial is not None and self._serial.is_open
        return TransportStatus(
            mode=TransportMode.UART,
            display_name=self.display_name,
            opened=opened,
            healthy=opened and self._last_error is None,
            rx_bytes=self._rx_bytes,
            rx_chunks=self._rx_chunks,
            last_error=self._last_error,
        )


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
