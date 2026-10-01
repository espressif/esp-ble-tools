# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""BLE log parser facade backed by the esp-blfd frame decoder."""

from __future__ import annotations

import time

from ble_log_frame_decoder import (
    BleLogFrame,
    FrameDecoder,
    FrameFormat,
    InternalLogBufferUtil,
    InternalLogEnhancedStat,
    InternalLogFinalStat,
    InternalLogInfo,
    parse_snapshot,
    parse_version_info_payload,
)

from src.backend.analysis.parser_events import (
    BleLogEvent,
    EnhStatEvent,
    FinalStatEvent,
    FrameEvent,
    InternalEvent,
    ParseBatch,
    ParseChunkResult,
    ParseSummary,
    RedirEvent,
)
from src.backend.models import (
    FRAME_OVERHEAD,
    MAX_FRAME_SIZE,
    BleLogSource,
    ChecksumAlgorithm,
    ChecksumMode,
    ChecksumScope,
    InternalSource,
)

DEFAULT_CHECKSUM_MODE = ChecksumMode(ChecksumAlgorithm.XOR, ChecksumScope.FULL)

# INTERNAL payload: [4B os_ts][1B int_src_code][sub-payload]
_INTERNAL_SUBTYPE_OFFSET = 4
_MIN_INTERNAL_PAYLOAD_SIZE = _INTERNAL_SUBTYPE_OFFSET + 1

# esp-blfd sanity-caps candidate frames at max_frame_size; without a cap it
# would treat oversized payload lengths as valid frame candidates. 2058 is the
# legacy 2048-byte payload sanity bound plus frame overhead.
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
            f"unsupported checksum mode {resolved}: esp-blfd covers XOR/FULL (v2 xor32) and SUM/FULL (v2 sum32)"
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
        events.extend(_decode_internal_events(frame_size, frame.payload))
        return

    if source_code == BleLogSource.REDIR:
        events.append(
            RedirEvent(
                frame_size=frame_size,
                source_code=source_code,
                frame_sn=frame_sn,
                text=frame.payload.decode("ascii", errors="replace"),
                received_at_ms=received_at_ms,
            )
        )
        return

    events.append(FrameEvent(frame_size=frame_size, source_code=source_code, frame_sn=frame_sn))


def _decode_internal_events(frame_size: int, payload: bytes) -> list[BleLogEvent]:
    """Map one esp-blfd INTERNAL record onto the console's event model.

    Malformed payloads and the TIMESTAMP keep-alive are dropped, matching the
    previous hand-written decoder.  TASK_BINDING is decoded by esp-blfd but not
    consumed here yet (compressed-log task names are a separate work item).
    """

    if len(payload) < _MIN_INTERNAL_PAYLOAD_SIZE:
        return []
    try:
        int_src = InternalSource(payload[_INTERNAL_SUBTYPE_OFFSET])
    except ValueError:
        return []
    try:
        if int_src in (InternalSource.INIT_DONE, InternalSource.INFO, InternalSource.FLUSH):
            info = InternalLogInfo.from_payload(payload)
            if int_src is InternalSource.INIT_DONE and info.version == 0:
                return []
            return [InternalEvent(frame_size=frame_size, int_src=int_src, decoded=info)]
        if int_src is InternalSource.ENHANCED_STAT:
            return [EnhStatEvent(frame_size=frame_size, stat=InternalLogEnhancedStat.from_payload(payload))]
        if int_src is InternalSource.FINAL_STAT:
            final_stat = InternalLogFinalStat.from_payload(payload)
            return [
                FinalStatEvent(
                    frame_size=frame_size,
                    os_ts_ms=final_stat.log_os_ts,
                    entries=tuple(final_stat.entries),
                )
            ]
        if int_src is InternalSource.BUF_UTIL:
            return [
                InternalEvent(
                    frame_size=frame_size,
                    int_src=int_src,
                    decoded=InternalLogBufferUtil.from_payload(payload),
                )
            ]
        if int_src is InternalSource.VERSION_INFO:
            return [
                InternalEvent(
                    frame_size=frame_size,
                    int_src=int_src,
                    decoded=parse_version_info_payload(payload),
                )
            ]
        if int_src is InternalSource.SNAPSHOT:
            return [InternalEvent(frame_size=frame_size, int_src=int_src, decoded=parse_snapshot(payload))]
    except ValueError:
        return []
    return []
