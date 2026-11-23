# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Observe already-decoded snapshots to locate a possible opening backlog.

This detects a reduction in backlog, not absolute device-to-host latency. Only
v8 periodic snapshots supply the clock and self-contained version anchor used
here. Other streams pass through unchanged. A decision is made once per opening.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise

from ble_log_frame_decoder import (
    INIT,
    PERIODIC,
    TS_VALID,
    BleLogFrame,
    Snapshot,
    is_snapshot,
    is_task_binding,
    parse_snapshot,
)

STARTUP_MAX_SECONDS = 5.0
STARTUP_MAX_BYTES = 2 * 1024 * 1024
MIN_BACKLOG_SECONDS = 3.0
STABLE_INTERVALS = 2
CLOCK_MODULUS = 1 << 32
OS_TICK_TOLERANCE_US = 100_000


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
    os_ms: int
    received: float
    version: bytes


def _device_elapsed_sec(previous: _Anchor, current: _Anchor) -> float | None:
    delta_us = current.device_us - previous.device_us
    os_delta_ms = (current.os_ms - previous.os_ms) % CLOCK_MODULUS
    if os_delta_ms >= CLOCK_MODULUS // 2:
        return None
    os_delta_us = os_delta_ms * 1000
    if 0 < delta_us < CLOCK_MODULUS // 2 and os_delta_us < CLOCK_MODULUS // 2:
        return delta_us / 1_000_000

    # The same snapshot samples ESP microseconds and tick-quantized OS milliseconds.
    # Select the ESP wrap count nearest the independent OS elapsed time.
    wraps = (os_delta_us - delta_us + CLOCK_MODULUS // 2) // CLOCK_MODULUS
    elapsed_us = delta_us + wraps * CLOCK_MODULUS
    if os_delta_ms == 0 or elapsed_us <= 0 or abs(elapsed_us - os_delta_us) > OS_TICK_TOLERANCE_US:
        return None
    return elapsed_us / 1_000_000


class StartupDetector:
    """Keep only clock/sequence evidence; never buffer or filter recording bytes."""

    def __init__(self, *, max_seconds: float = STARTUP_MAX_SECONDS) -> None:
        self._max_seconds = max_seconds
        self._bytes = 0
        self._started: float | None = None
        self._received = 0.0
        self._previous: _Anchor | None = None
        self._candidate: StartupDecision | None = None
        self._opening_rows: list[tuple[int, int]] = []
        self._fresh_sn: int | None = None
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
        if self._bytes > STARTUP_MAX_BYTES or received - self._started >= self._max_seconds:
            self._opening_rows.clear()
            self.decision = StartupDecision(reason="Opening observation limit reached")

    def observe(self, frame: BleLogFrame, snapshot: Snapshot | None = None) -> None:
        if self.decision is not None:
            self._opening_rows.clear()
            return
        if frame.source_code == 0 and is_task_binding(frame.payload):
            self._preserve_prefix = True
            return
        if frame.source_code == 8:
            # REDIR has its own sequence. Its position cannot prove a cut.
            self.decision = StartupDecision(reason="Opening metadata requires the original prefix")
            return
        if frame.source_code not in range(8):
            self.decision = StartupDecision(reason="Opening clock or sequence is ambiguous")
            return
        if self._fresh_sn is not None and (frame.sequence_number - self._fresh_sn) % (1 << 24) >= (1 << 23):
            self.decision = StartupDecision(reason="Opening clock or sequence is ambiguous")
            return
        self._opening_rows.append((frame.sequence_number, frame.offset))
        if frame.source_code != 0:
            return
        if not is_snapshot(frame.payload):
            self.decision = StartupDecision(reason="Opening metadata requires the original prefix")
            return
        snapshot = snapshot or parse_snapshot(frame.payload)
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
                snapshot.os_ts,
                self._received,
                snapshot.version_info,
            )
        )

        if self.decision is not None:
            self._opening_rows.clear()

    def _fresh_start(self, previous: _Anchor, anchor: _Anchor) -> tuple[int, int] | None:
        # A single hole must separate two contiguous SN ranges in wire order.
        # A second hole or old data interleaved with new makes a byte cut unsafe.
        ring = 1 << 24
        span = (anchor.sn - previous.sn) % ring
        rows = [((sn - previous.sn) % ring, offset) for sn, offset in self._opening_rows if offset >= previous.offset]
        values = sorted({sn for sn, _ in rows})
        gaps = [right for left, right in pairwise(values) if right - left > 1]
        if len(gaps) != 1 or values[-1] != span:
            return None
        boundary = gaps[0]
        first = next(i for i, (sn, _) in enumerate(rows) if sn >= boundary)
        if any(sn < boundary for sn, _ in rows[first:]):
            return None
        fresh_sn = (previous.sn + boundary) % ring
        if any((sn - fresh_sn) % ring < ring // 2 for sn, offset in self._opening_rows if offset < previous.offset):
            return None
        return rows[first][1], fresh_sn

    def _observe(self, anchor: _Anchor) -> StartupDecision | None:
        previous = self._previous
        self._previous = anchor
        if previous is None:
            return None
        host_delta = anchor.received - previous.received
        device_delta = _device_elapsed_sec(previous, anchor)
        sn_delta = (anchor.sn - previous.sn) % (1 << 24)
        count_delta = (anchor.count - previous.count) % (1 << 24)
        if (
            host_delta < 0
            or device_delta is None
            or not 0 < sn_delta < (1 << 23)
            or not 0 < count_delta < (1 << 23)
            or anchor.version != previous.version
        ):
            return StartupDecision(reason="Opening clock or sequence is ambiguous")

        if device_delta - host_delta >= MIN_BACKLOG_SECONDS and device_delta >= 4 * host_delta:
            if sn_delta <= 1 or count_delta <= 1:
                return StartupDecision(reason="Opening time jump lacks sequence evidence")
            start = self._fresh_start(previous, anchor)
            if start is None:
                return StartupDecision(reason="Opening clock or sequence is ambiguous")
            offset, self._fresh_sn = start
            self._candidate = StartupDecision(offset, "Opening backlog detected", device_delta, host_delta, anchor.sn)
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
