# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""BLE log parser facade backed by the esp-blfd frame decoder."""

from __future__ import annotations

import time
from typing import cast

from ble_log_frame_decoder import BleLogFrame
from ble_log_frame_decoder import FrameDecoder
from ble_log_frame_decoder import FrameFormat

from src.backend.analysis.parser_events import BleLogEvent
from src.backend.analysis.parser_events import EnhStatEvent
from src.backend.analysis.parser_events import FrameEvent
from src.backend.analysis.parser_events import FinalStatEvent
from src.backend.analysis.parser_events import InternalEvent
from src.backend.analysis.parser_events import ParseBatch
from src.backend.analysis.parser_events import ParseChunkResult
from src.backend.analysis.parser_events import ParseSummary
from src.backend.analysis.parser_events import RedirEvent
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import MAX_FRAME_SIZE
from src.backend.models import BleLogSource
from src.backend.models import ChecksumAlgorithm
from src.backend.models import ChecksumMode
from src.backend.models import ChecksumScope
from src.backend.models import EnhStatResult
from src.backend.models import FinalStatResult
from src.backend.models import InfoResult
from src.backend.models import InternalSource
from src.backend.support.parser_core.internal_decoder import decode_internal_frame

DEFAULT_CHECKSUM_MODE = ChecksumMode(ChecksumAlgorithm.XOR, ChecksumScope.FULL)

# esp-blfd sanity-caps candidate frames at max_frame_size; without a cap it
# would treat oversized payload lengths as valid frame candidates. 2058 keeps
# the historical 2048-byte payload sanity bound from the hand-written parser.
MAX_DECODER_FRAME_SIZE = FRAME_OVERHEAD + MAX_FRAME_SIZE

# The decoder's checksum covers the whole frame (header + payload), which
# matches ChecksumScope.FULL. HEADER_ONLY checksums were probed by the legacy
# parser but are not produced by firmware and are unsupported by esp-blfd.
_FORMAT_BY_MODE: dict[tuple[ChecksumAlgorithm, ChecksumScope], FrameFormat] = {
    (ChecksumAlgorithm.XOR, ChecksumScope.FULL): FrameFormat.BLE_LOG_V2_XOR32,
    (ChecksumAlgorithm.SUM, ChecksumScope.FULL): FrameFormat.BLE_LOG_V2_SUM32,
}


def _decoder_for_mode(checksum_mode: ChecksumMode | None) -> FrameDecoder:
    """Build an esp-blfd decoder for a console checksum mode (or the default)."""

    resolved = checksum_mode or DEFAULT_CHECKSUM_MODE
    try:
        frame_format = _FORMAT_BY_MODE[(resolved.algorithm, resolved.scope)]
    except KeyError:
        raise ValueError(
            f'unsupported checksum mode {resolved}: esp-blfd covers '
            'XOR/FULL (v2 xor32) and SUM/FULL (v2 sum32)'
        ) from None
    return FrameDecoder(format=frame_format, max_frame_size=MAX_DECODER_FRAME_SIZE)


def parse_ble_log_chunk(
    data: bytes,
    checksum_mode: ChecksumMode | None = None,
    *,
    received_at_ms: int | None = None,
) -> ParseChunkResult:
    """Parse *data* and return events plus the safe-to-discard byte count."""

    received_at_ms = time.time_ns() // 1_000_000 if received_at_ms is None else received_at_ms
    decoder = _decoder_for_mode(checksum_mode)
    frames = decoder.feed(data)
    events: list[BleLogEvent] = []
    for frame in frames:
        _append_frame_event(frame, events, received_at_ms)

    buffered_bytes = decoder.stats.buffered_bytes
    return ParseChunkResult(
        events=tuple(events),
        parsed_frames=len(frames),
        consumed=len(data) - buffered_bytes,
    )


class BleLogParser:
    """Stateful streaming parser holding a persistent esp-blfd FrameDecoder."""

    def __init__(self, checksum_mode: ChecksumMode | None = None) -> None:
        self._decoder = _decoder_for_mode(checksum_mode)

    def feed(self, chunk: bytes, *, received_at_ms: int | None = None) -> ParseBatch:
        """Parse one raw chunk; the decoder buffers any incomplete tail itself."""

        received_at_ms = time.time_ns() // 1_000_000 if received_at_ms is None else received_at_ms
        buffered_before = self._decoder.stats.buffered_bytes
        frames = self._decoder.feed(chunk)
        buffered_after = self._decoder.stats.buffered_bytes
        events: list[BleLogEvent] = []
        for frame in frames:
            _append_frame_event(frame, events, received_at_ms)
        return ParseBatch(
            raw_bytes=len(chunk),
            parsed_frames=len(frames),
            consumed=buffered_before + len(chunk) - buffered_after,
            carried_bytes=buffered_after,
            events=tuple(events),
        )

    def finalize(self) -> ParseSummary:
        """Return final parser totals without reparsing raw data."""

        stats = self._decoder.finish()
        return ParseSummary(
            raw_bytes=stats.bytes_received,
            parsed_frames=stats.frames_decoded,
            carried_bytes=stats.trailing_bytes,
        )


def _append_frame_event(frame: BleLogFrame, events: list[BleLogEvent], received_at_ms: int) -> None:
    frame_size = frame.size
    source_code = frame.source_code
    frame_sn = frame.sequence_number
    if source_code == BleLogSource.INTERNAL:
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
        if int_src == InternalSource.FINAL_STAT:
            final_stat = cast(FinalStatResult, decoded)
            events.append(
                FinalStatEvent(
                    frame_size=frame_size,
                    os_ts_ms=final_stat['os_ts_ms'],
                    entries=final_stat['entries'],
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

    if source_code == BleLogSource.REDIR:
        events.append(
            RedirEvent(
                frame_size=frame_size,
                source_code=source_code,
                frame_sn=frame_sn,
                text=frame.payload.decode('ascii', errors='replace'),
                received_at_ms=received_at_ms,
            )
        )
        return

    events.append(FrameEvent(frame_size=frame_size, source_code=source_code, frame_sn=frame_sn))
