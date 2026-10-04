# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import errno
import struct
import threading
from collections.abc import Callable
from enum import Enum

from src.backend.models import BleLogSource, InternalSource, TransportBitrate, TransportMode
from src.backend.support.transport.base import TransportStatus


def sum_checksum(data: bytes) -> int:
    return sum(data) & 0xFFFFFFFF


def xor_checksum(data: bytes) -> int:
    checksum = 0
    for offset in range(0, len(data), 4):
        checksum ^= int.from_bytes(data[offset : offset + 4], "little")
    return checksum & 0xFFFFFFFF


def _int_value(value: int | Enum) -> int:
    return int(value.value) if isinstance(value, Enum) else int(value)


def internal_payload(os_ts: int, int_src: int | Enum, sub_payload: bytes) -> bytes:
    """Build an INTERNAL frame payload: os_ts, subtype byte, then the subtype body."""
    return struct.pack("<I", os_ts) + bytes([_int_value(int_src)]) + sub_payload


def final_stat_payload(
    os_ts: int,
    host: tuple[int, int, int, int],
    internal: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> bytes:
    """Canonical FINAL_STAT payload: one 17-byte entry per source code 0..8."""
    payload = struct.pack("<IBB", os_ts, _int_value(InternalSource.FINAL_STAT), 9)
    for source in range(9):
        if source == _int_value(BleLogSource.HOST):
            counts = host
        elif source == _int_value(BleLogSource.INTERNAL):
            counts = internal
        else:
            counts = (0, 0, 0, 0)
        payload += struct.pack("<BIIII", source, *counts)
    return payload


def enh_stat_payload(
    os_ts: int,
    source: int | Enum,
    written_frames: int,
    lost_frames: int,
    written_bytes: int,
    lost_bytes: int,
) -> bytes:
    """ENH_STAT payload: one source's cumulative write/loss counters."""
    return internal_payload(
        os_ts,
        InternalSource.ENHANCED_STAT,
        struct.pack("<BIIII", _int_value(source), written_frames, lost_frames, written_bytes, lost_bytes),
    )


def version_info_payload(os_ts: int, chip_model: int = 13, chip_revision: int = 302) -> bytes:
    """VERSION_INFO payload. The chip identity is what the status bar surfaces."""
    return struct.pack(
        "<IBB12s10s10s10s10sHH",
        os_ts,
        _int_value(InternalSource.VERSION_INFO),
        8,
        b"a" * 12,
        b"b" * 10,
        b"c" * 10,
        b"d" * 10,
        b"e" * 10,
        chip_model,
        chip_revision,
    )


def snapshot_payload(
    os_ts: int = 0x1234,
    chip_model: int = 13,
    chip_revision: int = 302,
    *,
    reason_flags: int = 0b1011,
    version_block: bytes | None = None,
) -> bytes:
    """SNAPSHOT payload. The embedded VERSION_INFO block drops its timestamp.

    `reason_flags` defaults to the firmware's init snapshot (PERIODIC, TS_VALID
    and INIT); pass `reason_flags=0b1010` for a periodic one that keeps the
    sequence window running. Pass `version_block` to substitute a 58-byte block
    the console cannot interpret.
    """
    stats = b"".join(struct.pack("<III", 5 + source, source, 50 + source) for source in range(7))
    block = version_block if version_block is not None else version_info_payload(os_ts, chip_model, chip_revision)[4:]
    body = (
        struct.pack("<H", reason_flags)
        + (0x0201).to_bytes(3, "little")
        + block
        + struct.pack("<BIII", 2, 0x1111, 0x2222, 0x3333)
        + struct.pack("<BBBB", 7, 1, 2, 3)
        + stats
    )
    return struct.pack("<I", os_ts) + bytes([_int_value(InternalSource.SNAPSHOT)]) + body


def build_frame_header(payload_len: int, source_code: int, frame_sn: int) -> bytes:
    """Build a 6-byte BLE Log frame header."""
    frame_meta = (source_code & 0xFF) | (frame_sn << 8)
    return struct.pack("<HI", payload_len, frame_meta)


def build_frame(
    payload: bytes,
    source_code: int,
    frame_sn: int,
    checksum_fn: Callable[[bytes], int],
) -> bytes:
    """Build a complete BLE Log frame with header, payload, and checksum.

    Args:
        payload: Frame payload bytes (should include 4B os_ts prefix if applicable)
        source_code: BLE Log source code stored in the low byte of frame_meta
        frame_sn: 24-bit sequence number
        checksum_fn: Function(data: bytes) -> int
    """
    header = build_frame_header(len(payload), source_code, frame_sn)
    checksum_val = checksum_fn(header + payload)
    return header + payload + struct.pack("<I", checksum_val)


class BytesReader:
    """Feed a fixed byte stream through the capture pipeline in-process.

    Stops the capture when the stream ends, so a scenario can replay bytes
    without a transport or a child process.
    """

    def __init__(self, data: bytes, stop_event: threading.Event, *, block_size: int = 64 * 1024) -> None:
        self._data = data
        self._stop_event = stop_event
        self._block_size = block_size
        self._offset = 0
        self.opened = False
        self.rx_bytes = 0
        self.rx_chunks = 0

    @property
    def display_name(self) -> str:
        return "byte replay"

    @property
    def block_size(self) -> int:
        return self._block_size

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate()

    def open(self) -> None:
        self.opened = True

    def read(self, size: int | None = None) -> bytes:
        block = self._data[self._offset : self._offset + self._block_size]
        self._offset += len(block)
        if not block:
            self._stop_event.set()
            return b""
        self.rx_bytes += len(block)
        self.rx_chunks += 1
        return block

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        return []

    def close(self) -> None:
        self.opened = False

    def reset_target(self) -> bool:
        return False

    def status(self) -> TransportStatus:
        return TransportStatus(
            mode=TransportMode.USB_OUTPUT,
            display_name=self.display_name,
            opened=self.opened,
            healthy=self.opened,
            rx_bytes=self.rx_bytes,
            rx_chunks=self.rx_chunks,
        )


class SerialHandleStub:
    """Enough of a pyserial handle to observe DTR/RTS writes."""

    def __init__(self, *, reject_dtr: bool = False) -> None:
        self.is_open = True
        self.dtr_writes: list[bool] = []
        self.rts_writes: list[bool] = []
        self._dtr = False
        self._reject_dtr = reject_dtr

    @property
    def dtr(self) -> bool:
        return self._dtr

    @dtr.setter
    def dtr(self, value: bool) -> None:
        if self._reject_dtr:
            raise OSError(errno.ENOTTY, "Inappropriate ioctl for device")
        self._dtr = value
        self.dtr_writes.append(value)

    @property
    def rts(self) -> bool:
        return False

    @rts.setter
    def rts(self, value: bool) -> None:
        self.rts_writes.append(value)

    def close(self) -> None:
        self.is_open = False
