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
from src.backend.support.transport.base import TransportMode, TransportProvider
from src.backend.support.transport.serial_reader import SerialReader

VENDOR_ID = 0x303A
PRODUCT_ID = 0x1001
MODE_LABEL = "USJ"

USJ_BLOCK_SIZE = 64 * 1024
USJ_READ_TIMEOUT = 0.1


def _is_usj_port(port: object) -> bool:
    return getattr(port, "vid", None) == VENDOR_ID and getattr(port, "pid", None) == PRODUCT_ID


def list_usj_ports() -> list[tuple[str, str]]:
    """Enumerate USB Serial/JTAG ports as (label, serial device) pairs."""
    return [
        (f"{MODE_LABEL}  {port.device}", str(port.device))
        for port in serial.tools.list_ports.comports()
        if _is_usj_port(port)
    ]


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

    def list_options(self) -> list[tuple[str, str]]:
        return list_usj_ports()

    def create_reader(self, config: TransportConfig) -> UsjTransport:
        return UsjTransport(config.port, config.baudrate)


PROVIDER: TransportProvider = UsjTransportProvider()
