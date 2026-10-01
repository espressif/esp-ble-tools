# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Transport tests against a real tty: a POSIX pty, no hardware.

The mocked tests in ``test_uart_transport.py`` and
``test_spi_usb_bridge_transport.py`` prove the argument plumbing and can assert
that ``exclusive=True`` is attempted first. They cannot prove what the kernel
does with it. A pty is a real tty, so these tests take the same open / read /
close path as a physical port: a genuine ``flock`` refusal, genuine byte
delivery, a genuine read timeout.

Not covered here, because a pty does not emulate it: DTR/RTS modem lines
(``reset_target`` raises ``ENOTTY`` on a pty) and USB enumeration. Those still
need a real device.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import serial
from src.backend.models import TransportMode
from src.backend.support.transport import TransportReader
from src.backend.support.transport.spi_usb_bridge_transport import SPI_USB_RX_BUFFER_SIZE, SpiUsbBridgeCdcTransport
from src.backend.support.transport.uart_transport import UART_BLOCK_SIZE, UART_READ_TIMEOUT, UartTransport

pty = pytest.importorskip("pty", reason="POSIX-only virtual terminal; Windows has no pty module")

# A pty has no physical baud rate, so any value pyserial accepts works — except
# that macOS termios has no B3000000 and would route the request through the
# IOSSIOSPEED ioctl, which a pty does not implement (ENOTTY). 115200 is a
# standard speed on every POSIX termios, so both platforms stay on the plain
# tcsetattr path. Passing 3_000_000 to the constructor stays covered by the
# mocked transport tests.
PTY_BAUDRATE = 115_200


@dataclass(frozen=True)
class PtyPort:
    """Slave end of an open pty pair, plus the master end used to feed bytes."""

    master_fd: int
    path: str

    def feed(self, data: bytes) -> None:
        os.write(self.master_fd, data)


@pytest.fixture
def pty_port() -> Iterator[PtyPort]:
    master_fd, slave_fd = pty.openpty()
    try:
        yield PtyPort(master_fd=master_fd, path=os.ttyname(slave_fd))
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def _read_exactly(reader: TransportReader, size: int) -> bytes:
    """pyserial may return short reads; accumulate until size or the timeout."""
    received = b""
    while len(received) < size:
        block = reader.read(size - len(received))
        if not block:
            break
        received += block
    return received


def test_uart_open_falls_back_when_port_is_exclusively_locked(pty_port: PtyPort) -> None:
    holder = serial.Serial(pty_port.path, baudrate=PTY_BAUDRATE, timeout=0.1, exclusive=True)
    reader = UartTransport(pty_port.path, PTY_BAUDRATE)
    try:
        # Precondition: the lock is real, so UartTransport's first attempt fails
        # and its fallback to a plain open is what makes the test pass.
        with pytest.raises(serial.SerialException, match="Could not exclusively lock"):
            serial.Serial(pty_port.path, baudrate=PTY_BAUDRATE, timeout=0.1, exclusive=True)

        reader.open()

        assert reader.status().opened is True
        assert reader.status().last_error is None
        pty_port.feed(b"uart")
        assert _read_exactly(reader, 4) == b"uart"
    finally:
        reader.close()
        holder.close()


def test_uart_read_uses_the_real_kernel_timeout(pty_port: PtyPort) -> None:
    reader = UartTransport(pty_port.path, PTY_BAUDRATE)
    reader.open()
    try:
        assert reader.block_size == UART_BLOCK_SIZE
        assert reader.status().healthy is True

        # A read on an empty port must block for the configured timeout. Assert
        # a lower bound only, so scheduler jitter cannot flake the test.
        started = time.monotonic()
        assert reader.read() == b""
        assert time.monotonic() - started >= UART_READ_TIMEOUT / 2

        pty_port.feed(b"ble-log")
        assert _read_exactly(reader, 7) == b"ble-log"

        status = reader.status()
        assert status.rx_bytes == 7
        assert status.rx_chunks >= 1
    finally:
        reader.close()


def test_cdc_reader_opens_reads_and_closes_on_a_real_port(pty_port: PtyPort) -> None:
    reader = SpiUsbBridgeCdcTransport(pty_port.path, PTY_BAUDRATE)
    assert reader.status().opened is False

    reader.open()
    try:
        assert reader.block_size == SPI_USB_RX_BUFFER_SIZE
        assert reader.mode is TransportMode.SPI_USB_BRIDGE
        assert reader.status().opened is True
        assert reader.status().display_name.endswith(pty_port.path)

        pty_port.feed(b"cdc")
        assert _read_exactly(reader, 3) == b"cdc"
    finally:
        reader.close()

    assert reader.status().opened is False
    assert reader.status().rx_bytes == 3
