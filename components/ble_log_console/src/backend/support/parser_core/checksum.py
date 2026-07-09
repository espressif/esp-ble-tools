# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Checksum implementations matching BLE Log firmware (ble_log_util.c).

Two algorithms:
- sum_checksum: byte-by-byte sum
- xor_checksum: 32-bit word XOR matching firmware ble_log_fast_checksum()

The firmware's ror32 alignment compensation makes the XOR checksum
alignment-independent — simple word-by-word XOR produces the same result
regardless of the original buffer alignment.
"""

from __future__ import annotations

import struct
from typing import Any

try:
    from src.backend.support.parser_core import checksum_fast as _checksum_fast
except ImportError:
    _checksum_fast = None


def _resolve_range(data: Any, offset: int, length: int | None) -> tuple[int, int]:
    data_len = len(data)
    resolved_length = data_len - offset if length is None else length
    if offset < 0 or resolved_length < 0 or offset + resolved_length > data_len:
        raise ValueError('checksum range out of bounds')
    return offset, resolved_length


def sum_checksum(data: bytes) -> int:
    return sum_checksum_range(data, 0, len(data))


def sum_checksum_range(data: bytes, offset: int = 0, length: int | None = None) -> int:
    """Compute byte-sum checksum over a range in *data*."""

    offset, length = _resolve_range(data, offset, length)
    if _checksum_fast is not None:
        return int(_checksum_fast.sum_checksum_range(data, offset, length))
    return sum(memoryview(data)[offset : offset + length]) & 0xFFFFFFFF


def xor_checksum(data: bytes) -> int:
    """Compute XOR checksum matching firmware ble_log_fast_checksum().

    XORs consecutive 4-byte little-endian words. Partial last word is
    zero-padded. Alignment-independent due to firmware's ror32 compensation.
    """
    return xor_checksum_range(data, 0, len(data))


def xor_checksum_range(data: bytes, offset: int = 0, length: int | None = None) -> int:
    """Compute firmware fast XOR checksum over a range in *data*."""

    offset, length = _resolve_range(data, offset, length)
    if _checksum_fast is not None:
        return int(_checksum_fast.xor_checksum_range(data, offset, length))
    if length == 0:
        return 0

    checksum = 0
    full_end = offset + (length & ~3)
    end = offset + length
    for i in range(offset, full_end, 4):
        (word,) = struct.unpack_from('<I', data, i)
        checksum ^= word

    if full_end < end:
        word = 0
        shift = 0
        for i in range(full_end, end):
            word |= data[i] << shift
            shift += 8
        checksum ^= word

    return checksum & 0xFFFFFFFF


def _xor_checksum_legacy(data: bytes) -> int:
    """Legacy implementation kept for tests and local comparisons."""

    length = len(data)
    checksum = 0
    for i in range(0, length, 4):
        remaining = length - i
        if remaining >= 4:
            (word,) = struct.unpack_from('<I', data, i)
        else:
            chunk = data[i:] + b'\x00' * (4 - remaining)
            (word,) = struct.unpack('<I', chunk)

        checksum ^= word

    return checksum & 0xFFFFFFFF
