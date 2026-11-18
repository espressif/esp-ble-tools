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
    InternalLogTimestamp,
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
    UndecodedEvent,
)
from src.backend.analysis.stream_identification import (
    NON_TEXT_BYTES,
    IdentificationRules,
    StreamEvidence,
    StreamIdentity,
    identify_stream,
    recorded_version,
    text_window_counts,
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

_KNOWN_SOURCES = frozenset(int(source) for source in BleLogSource)
_TAB_TO_SPACE = bytes.maketrans(b"\t", b" ")

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
    """Stateful streaming parser holding a persistent esp-blfd FrameDecoder.

    With ``identification`` rules the parser also owns the console-text view of
    the stream: it mirrors the decoder's unresolved tail so the bytes no frame
    claims can be shown as undecoded text, and it keeps the cumulative evidence
    that identifies what the stream carries. Without rules (transports that
    never carry console text) it emits frame events only.
    """

    def __init__(
        self,
        checksum_mode: ChecksumMode | None = None,
        *,
        identification: IdentificationRules | None = None,
    ) -> None:
        self._decoder = _decoder_for_mode(checksum_mode)
        self._rules = identification
        self._pending = b""
        self._text_open = False
        self._escape_held = False
        self._last_received_at_ms = 0
        self._gap_bytes = 0
        self._gap_bytes_after_ble = 0
        self._known_frames = 0
        self._identity_records = 0
        self._window = bytearray()

    def feed(self, chunk: bytes, *, received_at_ms: int | None = None) -> ParseBatch:
        """Parse one raw chunk; the decoder buffers any incomplete tail itself."""

        received_at_ms = time.time_ns() // 1_000_000 if received_at_ms is None else received_at_ms
        self._last_received_at_ms = received_at_ms
        before = self._decoder.stats
        buffered_before = before.buffered_bytes
        frames = self._decoder.feed(chunk)
        buffered_after = self._decoder.stats.buffered_bytes
        consumed = buffered_before + len(chunk) - buffered_after
        events: list[BleLogEvent] = []
        rules = self._rules
        if rules is None:
            for frame in frames:
                _append_frame_event(frame, events, received_at_ms)
        else:
            data = self._pending + chunk
            base_offset = before.bytes_received - buffered_before
            cursor = 0
            for frame in frames:
                start = frame.offset - base_offset
                self._take_gap(rules, data[cursor:start], received_at_ms, events, end=True)
                cursor = start + frame.size
                first_frame_event = len(events)
                _append_frame_event(frame, events, received_at_ms)
                self._observe_frame(frame, events[first_frame_event:])
            self._take_gap(rules, data[cursor:consumed], received_at_ms, events, end=False)
            # Mirror only the decoder's unresolved tail: a pending frame is never shown as text.
            self._pending = data[consumed:]
        return ParseBatch(
            raw_bytes=len(chunk),
            parsed_frames=len(frames),
            consumed=consumed,
            carried_bytes=buffered_after,
            events=tuple(events),
            identity=self._identity(),
        )

    def finalize(self) -> ParseSummary:
        """Return final parser totals and resolve the undecoded tail without reparsing raw data."""

        stats = self._decoder.finish()
        events: list[BleLogEvent] = []
        if self._rules is not None:
            # The carry may be a frame the recording cut off, so it is shown and read as text evidence but not
            # counted as data outside frames; the summary reports it as carried bytes.
            self._take_gap(self._rules, self._pending, self._last_received_at_ms, events, end=True, eof_carry=True)
            self._pending = b""
        return ParseSummary(
            raw_bytes=stats.bytes_received,
            parsed_frames=stats.frames_decoded,
            carried_bytes=stats.trailing_bytes,
            events=tuple(event for event in events if isinstance(event, UndecodedEvent)),
            identity=self._identity(),
        )

    def _take_gap(
        self,
        rules: IdentificationRules,
        gap: bytes,
        received_at_ms: int,
        events: list[BleLogEvent],
        *,
        end: bool,
        eof_carry: bool = False,
    ) -> None:
        """Account original undecoded bytes, then emit their display text and span end."""

        if gap:
            if not eof_carry:
                self._gap_bytes += len(gap)
                if rules.confirms_ble_log(self._known_frames, self._identity_records):
                    self._gap_bytes_after_ble += len(gap)
            self._window += gap
            overflow = len(self._window) - rules.window_bytes
            if overflow > 0:
                del self._window[:overflow]
            text = ("\x1b" if self._escape_held else "") + gap.translate(_TAB_TO_SPACE, NON_TEXT_BYTES).decode("ascii")
            self._escape_held = False
            if text.replace("\x1b", "") or (text and self._text_open):
                events.append(UndecodedEvent(text, received_at_ms))
                self._text_open = True
            elif text:
                # An ESC-only run may start a colored line that the next chunk continues; only its last ESC can.
                self._escape_held = True
        if end:
            # An ESC-only run that a frame or EOF ends shows nothing, so it opens no span.
            self._escape_held = False
            if self._text_open:
                events.append(UndecodedEvent("", received_at_ms, end=True))
                self._text_open = False

    def _observe_frame(self, frame: BleLogFrame, frame_events: list[BleLogEvent]) -> None:
        self._window.clear()
        if frame.payload and frame.source_code in _KNOWN_SOURCES:
            self._known_frames += 1
        for event in frame_events:
            if isinstance(event, InternalEvent) and (recorded_version(event.decoded) or 0) > 0:
                self._identity_records += 1

    def _identity(self) -> StreamIdentity | None:
        if self._rules is None:
            return None
        text_bytes, line_breaks = text_window_counts(self._window)
        evidence = StreamEvidence(
            received_bytes=self._decoder.stats.bytes_received,
            gap_bytes=self._gap_bytes,
            known_frames=self._known_frames,
            identity_records=self._identity_records,
            gap_bytes_after_ble=self._gap_bytes_after_ble,
            window_bytes=len(self._window),
            window_text_bytes=text_bytes,
            window_line_breaks=line_breaks,
        )
        return identify_stream(evidence, self._rules)


def _append_frame_event(frame: BleLogFrame, events: list[BleLogEvent], received_at_ms: int) -> None:
    frame_size = frame.size
    source_code = frame.source_code
    frame_sn = frame.sequence_number
    if source_code == BleLogSource.INTERNAL:
        events.extend(_decode_internal_events(frame_size, frame_sn, frame.payload))
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


def _decode_internal_events(frame_size: int, frame_sn: int, payload: bytes) -> list[BleLogEvent]:
    """Map one esp-blfd INTERNAL record onto the console's event model.

    Every decoded event carries the frame's SN, because INTERNAL frames take it
    from the same counter as regular frames: the gap tracker needs them to tell
    a consumed sequence number from a lost one. Two cases deliberately keep
    their SN out of the stream instead of guessing — a frame whose subtype is
    unreadable, and TASK_BINDING, which the firmware numbers from its own
    private counter. The legacy TIMESTAMP keep-alive feeds nothing the report
    shows, but it does consume an INTERNAL number, so it is decoded too.
    """

    if len(payload) < _MIN_INTERNAL_PAYLOAD_SIZE:
        return []
    try:
        int_src = InternalSource(payload[_INTERNAL_SUBTYPE_OFFSET])
    except ValueError:
        return []
    if int_src is InternalSource.TASK_BINDING:
        return []
    try:
        if int_src in (InternalSource.INIT_DONE, InternalSource.INFO, InternalSource.FLUSH):
            info = InternalLogInfo.from_payload(payload)
            if int_src is InternalSource.INIT_DONE and info.version == 0:
                return []
            return [InternalEvent(frame_size=frame_size, int_src=int_src, decoded=info, frame_sn=frame_sn)]
        if int_src is InternalSource.ENHANCED_STAT:
            stat = InternalLogEnhancedStat.from_payload(payload)
            return [EnhStatEvent(frame_size=frame_size, stat=stat, frame_sn=frame_sn)]
        if int_src is InternalSource.FINAL_STAT:
            final_stat = InternalLogFinalStat.from_payload(payload)
            return [
                FinalStatEvent(
                    frame_size=frame_size,
                    os_ts_ms=final_stat.log_os_ts,
                    entries=tuple(final_stat.entries),
                    frame_sn=frame_sn,
                )
            ]
        if int_src is InternalSource.BUF_UTIL:
            return [
                InternalEvent(
                    frame_size=frame_size,
                    int_src=int_src,
                    decoded=InternalLogBufferUtil.from_payload(payload),
                    frame_sn=frame_sn,
                )
            ]
        if int_src is InternalSource.TIMESTAMP:
            # Legacy keep-alive: it consumes an INTERNAL sequence number, so
            # dropping it would leave a hole the continuity check reads as a
            # lost frame. Nothing in the report shows its payload.
            return [
                InternalEvent(
                    frame_size=frame_size,
                    int_src=int_src,
                    decoded=InternalLogTimestamp.from_payload(payload),
                    frame_sn=frame_sn,
                )
            ]
        if int_src is InternalSource.VERSION_INFO:
            return [
                InternalEvent(
                    frame_size=frame_size,
                    int_src=int_src,
                    decoded=parse_version_info_payload(payload),
                    frame_sn=frame_sn,
                )
            ]
        if int_src is InternalSource.SNAPSHOT:
            return [
                InternalEvent(
                    frame_size=frame_size,
                    int_src=int_src,
                    decoded=parse_snapshot(payload),
                    frame_sn=frame_sn,
                )
            ]
    except ValueError:
        return []
    return []
