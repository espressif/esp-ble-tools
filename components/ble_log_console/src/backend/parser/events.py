# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Public parse event model for BLE log capture pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from src.backend.models import EnhStatResult
from src.backend.models import InternalDecoderResult
from src.backend.models import InternalSource
from src.backend.models import ParsedFrame


@dataclass(frozen=True)
class FrameEvent:
    """A parsed non-INTERNAL BLE log frame."""

    frame: ParsedFrame
    frame_size: int


@dataclass(frozen=True)
class InternalEvent:
    """A parsed and decoded INTERNAL frame."""

    frame: ParsedFrame
    frame_size: int
    int_src: InternalSource
    decoded: InternalDecoderResult


@dataclass(frozen=True)
class EnhStatEvent:
    """Firmware ENH_STAT counters decoded from an INTERNAL frame."""

    frame: ParsedFrame
    frame_size: int
    stat: EnhStatResult


@dataclass(frozen=True)
class RedirEvent:
    """A parsed REDIR frame payload decoded for console/log sinks."""

    frame: ParsedFrame
    frame_size: int
    text: str
    wall_ms: int


BleLogEvent: TypeAlias = FrameEvent | InternalEvent | EnhStatEvent | RedirEvent


@dataclass(frozen=True)
class ParseChunkResult:
    """Function-style parser result for one input buffer."""

    events: tuple[BleLogEvent, ...]
    parsed_frames: int
    consumed: int


@dataclass(frozen=True)
class ParseBatch:
    """Batch of parser events produced from one raw input chunk."""

    raw_bytes: int
    parsed_frames: int
    consumed: int
    carried_bytes: int
    events: tuple[BleLogEvent, ...]


@dataclass(frozen=True)
class ParseSummary:
    """Final parser summary emitted when parse_queue receives None."""

    raw_bytes: int
    parsed_frames: int
    carried_bytes: int
