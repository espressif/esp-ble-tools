# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Shared pyserial plumbing for BLE log transports.

Every transport that receives its bytes from a serial port (UART, USB-SPI
bridge CDC, USB Output, USB Serial/JTAG) differs only in identity, tuning and error text; the
open/read/drain/close/status cycle and the rx counters are the same. Subclasses
parameterize the difference and may override ``reset_target``.
"""

from __future__ import annotations

import errno
import os
import sys

import serial

from src.backend.models import TransportBitrate
from src.backend.support.transport.base import PortIssue, PortIssueKind, TransportMode, TransportStatus
from src.i18n import tr


def serial_port_issue(device: str, label: str) -> PortIssue | None:
    """Check tty permissions without opening a port or changing its modem lines."""
    # COM names are not filesystem paths; Windows access is checked when opening.
    if sys.platform != "win32" and not os.access(device, os.R_OK | os.W_OK):
        return PortIssue(kind=PortIssueKind.PERMISSION_DENIED, port=device, label=label)
    return None


def serial_open_hint(error: Exception) -> str | None:
    """An action the user can take for the errnos this port actually fails with."""
    if sys.platform == "win32":
        return tr(
            "On Windows, close other applications using this COM port and check "
            "Ports (COM & LPT) in Device Manager. Reconnect the device and refresh the port list."
        )
    errno_value = getattr(error, "errno", None)
    text = str(error).lower()

    if errno_value == errno.EACCES or "permission denied" in text:
        return tr(
            "Permission denied. On Linux, add your user to the dialout group "
            "(or install a udev rule for this device) and open the port again."
        )
    if errno_value in (errno.EBUSY, getattr(errno, "EAGAIN", None)) or "busy" in text or "exclusively lock" in text:
        return tr("The port is busy. Stop ModemManager or whatever else holds it, then open the port again.")
    if errno_value in (errno.ENOENT, getattr(errno, "ENXIO", None)) or "no such file" in text:
        return tr("The device is no longer present. Re-plug the DUT (or press its reset button) and refresh the ports.")
    return None


class SerialReader:
    """Openable reader backed by one pyserial handle.

    A reader owns the device handle. In the process-based capture pipeline it
    must be created and opened inside ReaderProcess, not passed across process
    boundaries.
    """

    mode: TransportMode
    block_size: int
    timeout: float
    open_exclusive: bool = False
    not_open_message: str = "Serial transport is not open"

    def __init__(self, port: str, baudrate: int) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial: serial.Serial | None = None
        self._rx_bytes = 0
        self._rx_chunks = 0
        self._last_error: str | None = None

    @property
    def display_name(self) -> str:
        raise NotImplementedError

    @property
    def bitrate_config(self) -> TransportBitrate:
        raise NotImplementedError

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        try:
            self._serial = self._open_serial()
        except Exception as error:
            self._last_error = str(error)
            wrapped = self._open_error(error)
            if wrapped is error:
                raise
            raise wrapped from error
        self._last_error = None

    def read(self, size: int | None = None) -> bytes:
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError(self.not_open_message)
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
        return False

    def status(self) -> TransportStatus:
        opened = self._serial is not None and self._serial.is_open
        return TransportStatus(
            mode=self.mode,
            display_name=self.display_name,
            opened=opened,
            healthy=opened and self._last_error is None,
            rx_bytes=self._rx_bytes,
            rx_chunks=self._rx_chunks,
            last_error=self._last_error,
        )

    def _open_serial(self) -> serial.Serial:
        if self.open_exclusive:
            try:
                return self._open_handle(exclusive=True)
            except ValueError as error:
                # Windows always opens exclusively; real port/control-line failures must not retry.
                message = str(error).lower()
                unsupported = "exclusive" in message and ("not supported" in message or "unsupported" in message)
                if sys.platform == "win32" or not unsupported:
                    raise
        return self._open_handle(exclusive=False)

    def _open_handle(self, *, exclusive: bool) -> serial.Serial:
        """Open one pyserial handle; subclasses override how the handle is prepared."""
        if exclusive:
            return serial.Serial(self._port, baudrate=self._baudrate, timeout=self.timeout, exclusive=True)
        return serial.Serial(self._port, baudrate=self._baudrate, timeout=self.timeout)

    def _open_error(self, error: Exception) -> Exception:
        """Preserve serial exception types while adding Windows recovery guidance."""
        if sys.platform == "win32" and isinstance(error, serial.SerialException):
            message = tr("Failed to open {port}: {error}", port=self._port, error=error)
            return serial.SerialException(f"{message}\n{serial_open_hint(error)}")
        return error
