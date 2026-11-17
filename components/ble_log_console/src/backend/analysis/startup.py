# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Observe already-decoded snapshots to locate a possible opening backlog.

This detects a reduction in backlog, not absolute device-to-host latency. Only
v8 periodic snapshots supply the clock and self-contained version anchor used
here. Other streams pass through unchanged. A decision is made once per opening.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ble_log_frame_decoder import INIT, PERIODIC, TS_VALID, BleLogFrame, Snapshot

from src.backend.analysis.parser_events import InternalEvent

STARTUP_MAX_SECONDS = 5.0
MIN_BACKLOG_SECONDS = 3.0
STABLE_INTERVALS = 2


@dataclass(frozen=True)
class StartupDecision:
    """Byte offset in the concatenated raw files; zero means no exclusion."""

    offset_bytes: int = 0
    reason: str = "No confirmed opening backlog"
    device_jump_sec: float = 0.0
    host_elapsed_sec: float = 0.0
    anchor_sn: int | None = None
    preserve_prefix: bool = False


@dataclass(frozen=True)
class _Anchor:
    offset: int
    sn: int
    count: int
    device_us: int
    received: float
    version: bytes


class StartupDetector:
    """Keep only clock/sequence evidence; never buffer or filter recording bytes."""

    def __init__(self, *, max_seconds: float = STARTUP_MAX_SECONDS) -> None:
        self._max_seconds = max_seconds
        self._bytes = 0
        self._started: float | None = None
        self._received = 0.0
        self._previous: _Anchor | None = None
        self._candidate: StartupDecision | None = None
        self._stable = 0
        self._preserve_prefix = False
        self.decision: StartupDecision | None = None

    @property
    def candidate(self) -> StartupDecision | None:
        """Current proposed boundary, or the final decision once observation ends."""
        return self.decision if self.decision is not None else self._candidate

    def begin_chunk(self, size: int, raw_offset: int | None, received: float | None) -> None:
        if self.decision is not None:
            return
        if raw_offset != self._bytes or received is None:
            self.decision = StartupDecision(reason="Receive provenance unavailable or discontinuous")
            return
        self._bytes += size
        self._received = received
        if self._started is None:
            self._started = received
        if received - self._started >= self._max_seconds:
            self.decision = StartupDecision(reason="Opening observation limit reached")

    def observe(self, frame: BleLogFrame, event: object) -> None:
        if self.decision is not None or frame.source_code != 0 or len(frame.payload) < 5:
            return
        subtype = frame.payload[4]
        if subtype == 9:
            # Keep task names in the raw file while evaluating a later snapshot interval.
            self._preserve_prefix = True
            return
        if subtype != 8:
            self.decision = StartupDecision(reason="Opening metadata requires the original prefix")
            return
        if not isinstance(event, InternalEvent) or not isinstance(event.decoded, Snapshot):
            self.decision = StartupDecision(reason="Invalid opening snapshot")
            return
        snapshot = event.decoded
        if snapshot.reason_flags & INIT:
            self.decision = StartupDecision(reason="Device initialization observed")
            return
        if not snapshot.reason_flags & PERIODIC:
            return
        if not snapshot.reason_flags & TS_VALID or snapshot.version_info[1] != 8:
            self.decision = StartupDecision(reason="Unsupported or invalid snapshot clock")
            return
        self.decision = self._observe(
            _Anchor(
                frame.offset,
                frame.sequence_number,
                snapshot.anchor_count,
                snapshot.esp_ts,
                self._received,
                snapshot.version_info,
            )
        )

    def _observe(self, anchor: _Anchor) -> StartupDecision | None:
        previous = self._previous
        self._previous = anchor
        if previous is None:
            return None
        host_delta = anchor.received - previous.received
        device_delta = (anchor.device_us - previous.device_us) / 1_000_000
        sn_delta = (anchor.sn - previous.sn) % (1 << 24)
        count_delta = (anchor.count - previous.count) % (1 << 24)
        if (
            host_delta < 0
            or device_delta <= 0
            or device_delta >= (1 << 31) / 1_000_000
            or not 0 < sn_delta < (1 << 23)
            or not 0 < count_delta < (1 << 23)
            or anchor.version != previous.version
        ):
            return StartupDecision(reason="Opening clock or sequence is ambiguous")

        if device_delta - host_delta >= MIN_BACKLOG_SECONDS and device_delta >= 4 * host_delta:
            if sn_delta <= 1 or count_delta <= 1:
                return StartupDecision(reason="Opening time jump lacks sequence evidence")
            self._candidate = StartupDecision(
                anchor.offset, "Opening backlog detected", device_delta, host_delta, anchor.sn
            )
            self._stable = 0
        elif host_delta > 0 and abs(device_delta - host_delta) <= max(0.25, device_delta * 0.35):
            self._stable += 1
            if self._stable >= STABLE_INTERVALS:
                return self._candidate or StartupDecision()
        else:
            self._stable = 0
        return None

    def finish(self) -> StartupDecision:
        decision = self.decision or StartupDecision(reason="Recording ended before opening was confirmed")
        return replace(decision, preserve_prefix=self._preserve_prefix)
