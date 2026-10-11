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

import serial

from src.backend.models import TransportBitrate
from src.backend.support.transport.base import TransportMode, TransportStatus

# pyserial reports a held port as SerialException carrying the flock()/CreateFile
# errno, plus the text "Could not exclusively lock port ...". That is a refusal
# by another owner, not a platform limitation.
_LOCK_REFUSAL_ERRNOS = frozenset(
    value
    for value in (errno.EACCES, getattr(errno, "EAGAIN", None), getattr(errno, "EBUSY", None))
    if value is not None
)
_LOCK_REFUSAL_TEXT = ("exclusively lock", "resource temporarily unavailable", "device or resource busy")


def _is_lock_refusal(error: Exception) -> bool:
    """Whether an exclusive open failed because the port is already held."""

    if getattr(error, "errno", None) in _LOCK_REFUSAL_ERRNOS:
        return True
    text = str(error).lower()
    return any(marker in text for marker in _LOCK_REFUSAL_TEXT)


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
            except (ValueError, serial.SerialException) as error:
                if _is_lock_refusal(error):
                    # A plain open would succeed and split the byte stream
                    # between two readers, so propagate the refusal instead.
                    raise
                # The platform cannot express exclusive access; retry without
                # the flag. A real open error surfaces unchanged from there.
        return self._open_handle(exclusive=False)

    def _open_handle(self, *, exclusive: bool) -> serial.Serial:
        """Open one pyserial handle; subclasses override how the handle is prepared."""
        if exclusive:
            return serial.Serial(self._port, baudrate=self._baudrate, timeout=self.timeout, exclusive=True)
        return serial.Serial(self._port, baudrate=self._baudrate, timeout=self.timeout)

    def _open_error(self, error: Exception) -> Exception:
        """Exception to raise from ``open``. Default: the original one."""
        return error
