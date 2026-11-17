# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""USB Serial/JTAG (USJ) transport for BLE log byte streams.

The chip's built-in USB Serial/JTAG controller enumerates as a CDC-ACM port
with VID:PID 303A:1001 and carries the same frame stream as UART. On that
controller DTR/RTS drive the chip's reset and boot-mode logic: RTS asserted
while DTR is released resets the chip. Opening follows esp-idf-monitor's
no-reset sequence. pyserial asserts DTR and then RTS while opening, which
matches what Linux CDC-ACM asserts on open; RTS is then released before DTR,
so the lines never pass through the reset combination. Nothing writes the
lines afterwards. The operating system, its driver and the USB host may
still change the lines on their own; only a physical check can show whether
a given host resets the chip.
"""

from __future__ import annotations

import errno

import serial
import serial.tools.list_ports

from src.backend.models import TransportBitrate, TransportConfig
from src.backend.support.transport.base import (
    PortScan,
    TransportMode,
    TransportProvider,
)
from src.backend.support.transport.serial_reader import SerialReader, serial_port_issue

VENDOR_ID = 0x303A
PRODUCT_ID = 0x1001
MODE_LABEL = "USJ"

USJ_BLOCK_SIZE = 64 * 1024
USJ_READ_TIMEOUT = 0.1


def _is_usj_port(port: object) -> bool:
    return getattr(port, "vid", None) == VENDOR_ID and getattr(port, "pid", None) == PRODUCT_ID


def scan_usj_ports() -> PortScan:
    """Enumerate USB Serial/JTAG ports, keeping unusable ports visible.

    A port that is present but cannot be opened by this user becomes a
    ``PortIssue`` instead of disappearing from the list, the same way the SPI
    Bridge reports a device it cannot open.
    """
    scan = PortScan()
    for port in serial.tools.list_ports.comports():
        if not _is_usj_port(port):
            continue
        device = str(port.device)
        issue = serial_port_issue(device, MODE_LABEL)
        if issue is not None:
            scan.issues.append(issue)
            continue
        scan.options.append((f"{MODE_LABEL}  {device}", device))
    return scan


class UsjTransport(SerialReader):
    mode = TransportMode.USJ
    block_size = USJ_BLOCK_SIZE
    timeout = USJ_READ_TIMEOUT
    open_exclusive = True
    not_open_message = "USJ transport is not open"

    @property
    def display_name(self) -> str:
        return f"{MODE_LABEL} {self._port}"

    @property
    def bitrate_config(self) -> TransportBitrate:
        """No wire bitrate: the baud rate setting does not clock a USB link."""
        return TransportBitrate()

    def _open_handle(self, *, exclusive: bool) -> serial.Serial:
        handle = super()._open_handle(exclusive=exclusive)
        try:
            handle.rts = False
            # Windows usbser.sys sends an RTS change only with a DTR update (esptool/esp-idf-monitor workaround).
            handle.dtr = True
            handle.dtr = False
        except OSError as error:
            # Like pyserial's own open: a tty without modem lines (a pty) refuses these ioctls.
            if error.errno not in (errno.EINVAL, errno.ENOTTY):
                handle.close()
                raise OSError(error.errno, f"could not release DTR/RTS on {self._port}: {error.strerror}") from error
        return handle


class UsjTransportProvider:
    @property
    def label(self) -> str:
        """The mode name in the launch screen, matching the CLI's ``--mode usj``."""

        return MODE_LABEL

    @property
    def mode(self) -> TransportMode:
        return TransportMode.USJ

    def scan_ports(self) -> PortScan:
        return scan_usj_ports()

    def create_reader(self, config: TransportConfig) -> UsjTransport:
        return UsjTransport(config.port, config.baudrate)


PROVIDER: TransportProvider = UsjTransportProvider()
