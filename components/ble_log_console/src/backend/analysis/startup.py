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
    BleLogSource,
    Snapshot,
    is_snapshot,
    is_task_binding,
    parse_snapshot,
)

STARTUP_MAX_SECONDS = 5.0
STARTUP_MAX_BYTES = 2 * 1024 * 1024
MIN_BACKLOG_SECONDS = 3.0
MIN_FIRST_READ_GAP_SECONDS = 0.5
STABLE_INTERVALS = 2
SN_MODULUS = 1 << 24
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
        self._first_read_end = 0
        self._first_read_clocks: dict[int, int] = {}
        self._received = 0.0
        self._previous: _Anchor | None = None
        self._candidate: StartupDecision | None = None
        self._opening_rows: list[tuple[int, int]] = []
        self._fresh_sn: int | None = None
        self._fresh_span = 0
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
            self._first_read_end = self._bytes
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
        if self._fresh_sn is not None and (frame.sequence_number - self._fresh_sn) % SN_MODULUS >= self._fresh_span:
            self.decision = StartupDecision(reason="Opening clock or sequence is ambiguous")
            return
        self._opening_rows.append((frame.sequence_number, frame.offset))
        if frame.source_code != 0:
            if (
                self._bytes == self._first_read_end
                and frame.source_code in (BleLogSource.CUSTOM, BleLogSource.HOST, BleLogSource.HCI, BleLogSource.ENCODE)
                and len(frame.payload) >= 4
            ):
                # Public v8 writers prepend ESP microseconds. LL payloads use a different clock.
                self._first_read_clocks[frame.offset] = int.from_bytes(frame.payload[:4], "little")
            return
        if not is_snapshot(frame.payload):
            self.decision = StartupDecision(reason="Opening metadata requires the original prefix")
            return
        snapshot = snapshot or parse_snapshot(frame.payload)
        if self._bytes == self._first_read_end:
            self._first_read_clocks[frame.offset] = snapshot.esp_ts
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

    def _fresh_start(self, previous: _Anchor, anchor: _Anchor) -> tuple[int, int, int] | None:
        # A run starts wherever its predecessor on the 24-bit ring is absent.
        # The snapshot and the FIFO offsets identify which run is fresh, even after many wraps.
        rows = self._opening_rows
        values = {sn for sn, _ in rows}
        starts = sorted(sn for sn in values if (sn - 1) % SN_MODULUS not in values)
        if len(starts) != 2:
            return None
        low, high = starts
        fresh, old = (low, high) if low <= anchor.sn < high else (high, low)
        span = (old - fresh) % SN_MODULUS
        if (previous.sn - fresh) % SN_MODULUS < span:
            return None

        # A large modular jump alone could be a late frame. Require a neighbour in both runs.
        if (anchor.sn - previous.sn) % SN_MODULUS >= SN_MODULUS // 2 and (
            (old + 1) % SN_MODULUS not in values or (fresh + 1) % SN_MODULUS not in values
        ):
            return None

        first = None
        for i, (sn, _) in enumerate(rows):
            if (sn - fresh) % SN_MODULUS < span:
                if first is None:
                    first = i
            elif first is not None:
                return None
        assert first is not None  # The confirming snapshot belongs to the fresh run.
        offset = rows[first][1]
        del rows[:first]  # A subsequent time jump can replace this candidate.
        return offset, fresh, min(span, SN_MODULUS // 2)

    def _first_read_start(self, previous: _Anchor, anchor: _Anchor, host_delta: float) -> tuple[int, int, int] | None:
        # A fragmented FIFO prefix can end within one periodic snapshot interval.
        # Find the uninterrupted sequence ending at the confirming snapshot.
        rows = self._opening_rows
        first = len(rows) - 1
        while first and (rows[first][0] - rows[first - 1][0]) % SN_MODULUS == 1:
            first -= 1
        if not first or first == len(rows) - 1:
            return None
        fresh, offset = rows[first]
        _, before = rows[first - 1]
        if not previous.offset <= before < offset < self._first_read_end:
            return None

        # Corroborate the gap locally using timestamps from the first read.
        # The fresh frame's age at the next snapshot must fit host elapsed time.
        old_clock = self._first_read_clocks.get(before)
        fresh_clock = next(
            (self._first_read_clocks[pos] for _, pos in rows[first:] if pos in self._first_read_clocks), None
        )
        if old_clock is None or fresh_clock is None:
            return None
        jump = (fresh_clock - old_clock) % CLOCK_MODULUS / 1_000_000
        remaining = (anchor.device_us - fresh_clock) % CLOCK_MODULUS / 1_000_000
        interval = (anchor.device_us - previous.device_us) % CLOCK_MODULUS / 1_000_000
        if not MIN_FIRST_READ_GAP_SECONDS <= jump <= interval or remaining > host_delta + 0.25:
            return None

        # A reverse or half-ring jump requires the independent long-gap proof.
        origin = rows[0][0]
        distances = [(sn - origin) % SN_MODULUS for sn, _ in rows[: first + 1]]
        if distances[-1] >= SN_MODULUS // 2 or any(b <= a for a, b in pairwise(distances)):
            return None
        del rows[:first]
        return offset, fresh, SN_MODULUS // 2

    def _observe(self, anchor: _Anchor) -> StartupDecision | None:
        previous = self._previous
        self._previous = anchor
        if previous is None:
            return None
        host_delta = anchor.received - previous.received
        device_delta = _device_elapsed_sec(previous, anchor)
        sn_delta = (anchor.sn - previous.sn) % SN_MODULUS
        count_delta = (anchor.count - previous.count) % (1 << 24)
        if (
            host_delta < 0
            or device_delta is None
            or not 0 < count_delta < (1 << 23)
            or anchor.version != previous.version
        ):
            return StartupDecision(reason="Opening clock or sequence is ambiguous")

        long_jump = device_delta - host_delta >= MIN_BACKLOG_SECONDS and device_delta >= 4 * host_delta
        first_read_jump = (
            self._candidate is None
            and previous.offset < self._first_read_end
            and count_delta > 1
            and device_delta - host_delta >= MIN_FIRST_READ_GAP_SECONDS
            and device_delta >= 2 * host_delta
        )
        if long_jump or first_read_jump:
            if sn_delta <= 1 or count_delta <= 1:
                return StartupDecision(reason="Opening time jump lacks sequence evidence")
            os_delta_ms = (anchor.os_ms - previous.os_ms) % CLOCK_MODULUS
            if abs(device_delta * 1_000_000 - os_delta_ms * 1000) > OS_TICK_TOLERANCE_US:
                return StartupDecision(reason="Opening clock or sequence is ambiguous")
            start = self._fresh_start(previous, anchor) if long_jump else None
            if start is None and first_read_jump:
                start = self._first_read_start(previous, anchor, host_delta)
            if start is None and not long_jump:
                self._stable = 0
                return None
            if start is None:
                return StartupDecision(reason="Opening time jump has no clear frame boundary")
            offset, self._fresh_sn, self._fresh_span = start
            self._candidate = StartupDecision(offset, "Opening backlog detected", device_delta, host_delta, anchor.sn)
            self._stable = 0
        elif not 0 < sn_delta < SN_MODULUS // 2:
            return StartupDecision(reason="Opening clock or sequence is ambiguous")
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
