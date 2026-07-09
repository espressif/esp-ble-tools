# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""BLE log parser facade and function-style chunk parser."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

from src.backend.analysis.parser_events import BleLogEvent
from src.backend.analysis.parser_events import EnhStatEvent
from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import InternalEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseChunkResult
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.parser_events import RedirEvent
from src.backend.support.parser_core.frame_parser import FrameParser
from src.backend.support.parser_core.internal_decoder import decode_internal_frame
from src.backend.support.parser_core.checksum import sum_checksum_range
from src.backend.support.parser_core.checksum import xor_checksum_range
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import MAX_FRAME_SIZE
from src.backend.models import BleLogSource
from src.backend.models import ChecksumAlgorithm
from src.backend.models import ChecksumMode
from src.backend.models import ChecksumScope
from src.backend.models import EnhStatResult
from src.backend.models import InfoResult
from src.backend.models import InternalSource
from src.backend.models import ParsedFrame

_MIN_FRAME_SIZE = FRAME_OVERHEAD + 1
_MAX_CARRY_BYTES = FRAME_OVERHEAD + MAX_FRAME_SIZE - 1
DEFAULT_CHECKSUM_MODE = ChecksumMode(ChecksumAlgorithm.XOR, ChecksumScope.FULL)


ChecksumRange = Callable[[bytes, int, int], int]


def _resolve_checksum_mode(mode: ChecksumMode | None) -> tuple[ChecksumMode, ChecksumRange]:
    resolved = mode or DEFAULT_CHECKSUM_MODE
    if resolved.algorithm == ChecksumAlgorithm.XOR:
        return resolved, xor_checksum_range
    return resolved, sum_checksum_range


def parse_ble_log_chunk(data: bytes, checksum_mode: ChecksumMode | None = None) -> ParseChunkResult:
    """Parse *data* and return events plus the safe-to-discard byte count."""

    events: list[BleLogEvent] = []
    parsed_frames = 0
    pointer = 0
    last_complete_frame_end = 0
    data_len = len(data)
    parser = FrameParser()
    mode, checksum_fn = _resolve_checksum_mode(checksum_mode)

    while pointer <= data_len - _MIN_FRAME_SIZE:
        result = parser._try_parse_at(data, pointer, checksum_fn, mode.scope)  # noqa: SLF001
        if result is None:
            pointer += 1
            continue

        frame, next_offset = result
        parsed_frames += 1
        _append_frame_event(frame, events)
        pointer = next_offset
        last_complete_frame_end = next_offset

    consumed = last_complete_frame_end
    if data_len > _MAX_CARRY_BYTES:
        consumed = max(consumed, data_len - _MAX_CARRY_BYTES)

    return ParseChunkResult(
        events=tuple(events),
        parsed_frames=parsed_frames,
        consumed=consumed,
    )


class BleLogParser:
    """Stateful local adapter around the function-style parser contract."""

    def __init__(self, checksum_mode: ChecksumMode | None = None) -> None:
        self._checksum_mode = checksum_mode or DEFAULT_CHECKSUM_MODE
        self._carry = b''
        self._raw_bytes = 0
        self._parsed_frames = 0

    def feed(self, chunk: bytes) -> ParseBatch:
        """Parse one raw chunk while preserving unconsumed tail bytes locally."""

        self._raw_bytes += len(chunk)
        data = self._carry + chunk
        result = parse_ble_log_chunk(data, checksum_mode=self._checksum_mode)
        self._carry = data[result.consumed :]
        self._parsed_frames += result.parsed_frames
        return ParseBatch(
            raw_bytes=len(chunk),
            parsed_frames=result.parsed_frames,
            consumed=result.consumed,
            carried_bytes=len(self._carry),
            events=result.events,
        )

    def finalize(self) -> ParseSummary:
        """Return final parser totals without reparsing raw data."""

        return ParseSummary(
            raw_bytes=self._raw_bytes,
            parsed_frames=self._parsed_frames,
            carried_bytes=len(self._carry),
        )


def _append_frame_event(frame: ParsedFrame, events: list[BleLogEvent]) -> None:
    frame_size = len(frame.payload) + FRAME_OVERHEAD
    if frame.source_code == BleLogSource.INTERNAL:
        decoded = decode_internal_frame(frame.payload)
        if decoded is None:
            return
        int_src = decoded['int_src']
        if int_src == InternalSource.INIT_DONE:
            info = cast(InfoResult, decoded)
            if info['version'] == 0:
                return
        if int_src == InternalSource.ENH_STAT:
            events.append(
                EnhStatEvent(
                    frame_size=frame_size,
                    stat=cast(EnhStatResult, decoded),
                )
            )
            return
        events.append(
            InternalEvent(
                frame_size=frame_size,
                int_src=int_src,
                decoded=decoded,
            )
        )
        return

    if frame.source_code == BleLogSource.REDIR:
        events.append(
            RedirEvent(
                frame_size=frame_size,
                source_code=frame.source_code,
                frame_sn=frame.frame_sn,
                text=frame.payload.decode('ascii', errors='replace'),
                wall_ms=int(time.perf_counter() * 1000) & 0xFFFFFFFF,
            )
        )
        return

    events.append(FrameEvent(frame_size=frame_size, source_code=frame.source_code, frame_sn=frame.frame_sn))
