# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Public parse event model for BLE log capture pipelines."""

from __future__ import annotations

from typing import NamedTuple
from typing import TypeAlias

from src.backend.models import EnhStatResult
from src.backend.models import FinalStatEntry
from src.backend.models import InternalDecoderResult
from src.backend.models import InternalSource
from src.backend.models import SourceCode


class FrameEvent(NamedTuple):
    """Metadata for a parsed non-INTERNAL BLE log frame."""

    frame_size: int
    source_code: SourceCode
    frame_sn: int


class InternalEvent(NamedTuple):
    """Decoded INTERNAL frame metadata."""

    frame_size: int
    int_src: InternalSource
    decoded: InternalDecoderResult


class EnhStatEvent(NamedTuple):
    """Firmware ENH_STAT counters decoded from an INTERNAL frame."""

    frame_size: int
    stat: EnhStatResult


class FinalStatEvent(NamedTuple):
    """Terminal counters for one firmware flush interval."""

    frame_size: int
    os_ts_ms: int
    entries: tuple[FinalStatEntry, ...]


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


BleLogEvent: TypeAlias = FrameEvent | InternalEvent | EnhStatEvent | FinalStatEvent | RedirEvent


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


class ParseSummary(NamedTuple):
    """Final parser summary emitted when parse_queue receives None."""

    raw_bytes: int
    parsed_frames: int
    carried_bytes: int
