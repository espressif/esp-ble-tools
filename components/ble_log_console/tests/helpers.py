# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import struct
from collections.abc import Callable


def sum_checksum(data: bytes) -> int:
    return sum(data) & 0xFFFFFFFF


def xor_checksum(data: bytes) -> int:
    checksum = 0
    for offset in range(0, len(data), 4):
        checksum ^= int.from_bytes(data[offset : offset + 4], 'little')
    return checksum & 0xFFFFFFFF


def build_frame_header(payload_len: int, source_code: int, frame_sn: int) -> bytes:
    """Build a 6-byte BLE Log frame header."""
    frame_meta = (source_code & 0xFF) | (frame_sn << 8)
    return struct.pack('<HI', payload_len, frame_meta)


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
    return header + payload + struct.pack('<I', checksum_val)
