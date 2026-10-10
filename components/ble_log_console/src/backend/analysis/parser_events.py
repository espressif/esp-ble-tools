# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Public parse event model for BLE log capture pipelines."""

from __future__ import annotations

from typing import NamedTuple, TypeAlias

from src.backend.analysis.stream_identification import StreamIdentity
from src.backend.models import (
    FinalStatEntry,
    InternalDecoderResult,
    InternalLogEnhancedStat,
    InternalSource,
    SourceCode,
)


class FrameEvent(NamedTuple):
    """Metadata for a parsed non-INTERNAL BLE log frame."""

    frame_size: int
    source_code: SourceCode
    frame_sn: int


class InternalEvent(NamedTuple):
    """Decoded INTERNAL frame metadata.

    ``frame_sn`` is the frame's slot in the shared sequence stream, or -1 when
    the producer did not supply one (the gap tracker ignores those).
    """

    frame_size: int
    int_src: InternalSource
    decoded: InternalDecoderResult
    frame_sn: int = -1


class EnhStatEvent(NamedTuple):
    """Firmware ENH_STAT counters decoded from an INTERNAL frame."""

    frame_size: int
    stat: InternalLogEnhancedStat
    frame_sn: int = -1


class FinalStatEvent(NamedTuple):
    """Terminal counters for one firmware flush interval."""

    frame_size: int
    os_ts_ms: int
    entries: tuple[FinalStatEntry, ...]
    frame_sn: int = -1


class RedirEvent(NamedTuple):
    """Metadata and text for a parsed REDIR frame."""

    frame_size: int
    source_code: SourceCode
    frame_sn: int
    text: str
    received_at_ms: int


class ReceivedChunk(NamedTuple):
    """Raw transport bytes with their computer receive time."""

    data: bytes
    received_at_ms: int


class UndecodedEvent(NamedTuple):
    """Display text from bytes no frame claimed, or the end of that undecoded span.

    It never counts as a frame; ``RedirEvent`` is the text carried inside valid
    BLE Log frames.
    """

    text: str
    received_at_ms: int
    end: bool = False


BleLogEvent: TypeAlias = FrameEvent | InternalEvent | EnhStatEvent | FinalStatEvent | RedirEvent | UndecodedEvent
ConsoleEvent: TypeAlias = RedirEvent | UndecodedEvent


class ParseChunkResult(NamedTuple):
    """Function-style parser result for one input buffer."""

    events: tuple[BleLogEvent, ...]
    parsed_frames: int
    consumed: int  # Safe-to-discard prefix length.


class ParseBatch(NamedTuple):
    """Batch of parser events produced from one or more raw input chunks."""

    raw_bytes: int
    parsed_frames: int
    consumed: int  # Bytes retired from prior carry plus this batch.
    carried_bytes: int  # Bytes retained for the next batch.
    events: tuple[BleLogEvent, ...]
    identity: StreamIdentity | None = None  # Cumulative; None when the transport carries no console text.


class ParseSummary(NamedTuple):
    """Final parser summary emitted when parse_queue receives None."""

    raw_bytes: int
    parsed_frames: int
    carried_bytes: int
    events: tuple[UndecodedEvent, ...] = ()  # Undecoded tail resolved at end of input.
    identity: StreamIdentity | None = None
