# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Identify what kind of byte stream a console-text transport is carrying.

The parser owns the mutable evidence; this module holds the immutable records
and the pure decision that turns evidence into a stream kind.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ble_log_frame_decoder import BleLogVersionInfo, InternalLogInfo, Snapshot, parse_snapshot_version_info

# Bytes a terminal text stream is made of: printable ASCII, tab, CR, LF and ESC
# (ESP-IDF colors its log lines with ANSI SGR sequences).
TEXT_BYTES = frozenset({0x09, 0x0A, 0x0D, 0x1B, *range(0x20, 0x7F)})
NON_TEXT_BYTES = bytes(byte for byte in range(256) if byte not in TEXT_BYTES)


class StreamKind(str, Enum):
    NO_INPUT = "no_input"
    UNRECOGNIZED = "unrecognized"
    LIKELY_TEXT = "likely_text"
    BLE_LOG = "ble_log"


@dataclass(frozen=True)
class IdentificationRules:
    """Conservative, tunable thresholds; policy defaults rather than measured guarantees.

    ``window_bytes`` bounds the recent run of original undecoded bytes the text
    decision reads. A valid frame empties that window, so disjoint corrupt
    regions never add up to a text stream.
    """

    window_bytes: int = 4096
    min_text_bytes: int = 256
    min_printable_ratio: float = 0.95
    min_text_lines: int = 2
    min_known_frames: int = 3
    min_identity_records: int = 1

    def __post_init__(self) -> None:
        for name in ("window_bytes", "min_text_bytes", "min_text_lines", "min_known_frames", "min_identity_records"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")
        ratio = self.min_printable_ratio
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio):
            raise ValueError(f"min_printable_ratio must be a finite number, got {ratio!r}")
        if not 0.0 <= ratio <= 1.0:
            raise ValueError(f"min_printable_ratio must be within [0, 1], got {ratio!r}")
        if self.min_text_bytes > self.window_bytes:
            raise ValueError(
                f"min_text_bytes ({self.min_text_bytes}) must not exceed window_bytes ({self.window_bytes})"
            )

    def confirms_ble_log(self, known_frames: int, identity_records: int) -> bool:
        return known_frames >= self.min_known_frames or identity_records >= self.min_identity_records


DEFAULT_IDENTIFICATION_RULES = IdentificationRules()


@dataclass(frozen=True)
class StreamEvidence:
    """Cumulative parser-input evidence; every count describes bytes the parser actually saw.

    ``gap_bytes`` counts original bytes the decoder skipped as belonging to no
    frame, before any display filtering. ``gap_bytes_after_ble`` is the part of
    them that arrived after the stream was identified as BLE Log. The decoder's
    unresolved tail at the end of input is not counted here (it may be a frame
    the recording cut off; the parse summary reports it as carried bytes), but
    it does enter the window. The ``window_*`` fields describe the recent
    undecoded run that the text decision reads.
    """

    received_bytes: int = 0
    gap_bytes: int = 0
    known_frames: int = 0
    identity_records: int = 0
    gap_bytes_after_ble: int = 0
    window_bytes: int = 0
    window_text_bytes: int = 0
    window_line_breaks: int = 0


@dataclass(frozen=True)
class StreamIdentity:
    kind: StreamKind
    evidence: StreamEvidence


def identify_stream(evidence: StreamEvidence, rules: IdentificationRules) -> StreamIdentity:
    """Classify cumulative evidence. BLE Log identity is sticky because its counters only grow."""

    if evidence.received_bytes == 0:
        kind = StreamKind.NO_INPUT
    elif rules.confirms_ble_log(evidence.known_frames, evidence.identity_records):
        kind = StreamKind.BLE_LOG
    elif (
        evidence.window_bytes >= rules.min_text_bytes
        and evidence.window_text_bytes >= rules.min_printable_ratio * evidence.window_bytes
        and evidence.window_line_breaks >= rules.min_text_lines
    ):
        kind = StreamKind.LIKELY_TEXT
    else:
        kind = StreamKind.UNRECOGNIZED
    return StreamIdentity(kind=kind, evidence=evidence)


def text_window_counts(window: bytes | bytearray) -> tuple[int, int]:
    """(text bytes, logical line breaks) of a window; CRLF counts as one break."""

    text_bytes = len(window.translate(None, NON_TEXT_BYTES))
    line_breaks = window.count(b"\n") + window.count(b"\r") - window.count(b"\r\n")
    return text_bytes, line_breaks


def recorded_version(decoded: object) -> int | None:
    """Firmware version an INTERNAL record carries, or None when it carries none."""

    try:
        if isinstance(decoded, Snapshot):
            return int(parse_snapshot_version_info(decoded).version)
        if isinstance(decoded, (BleLogVersionInfo, InternalLogInfo)):
            return int(decoded.version)
    except ValueError:
        # A SNAPSHOT can pass shape validation with a corrupt embedded block.
        return None
    return None
