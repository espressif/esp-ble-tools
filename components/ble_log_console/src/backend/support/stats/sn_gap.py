# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Sliding receive window gap tracker for per-source frame sequence numbers.

Frames are only declared lost when the receive window advances past their SN
without them being received, tolerating out-of-order delivery up to
REORDER_WINDOW frames.
"""

from src.backend.models import SourceCode
from src.backend.models import SequenceSourceSummary
from src.backend.models import SequenceSummary

SN_MAX = 1 << 24  # 24-bit SN space
REORDER_WINDOW = 256  # receive window size
MAX_GAP_RANGES = 4096
MAX_TRUSTED_FORWARD_GAP = 500


class SNGapTracker:
    """Tracks per-source gaps without retaining every observed SN."""

    def __init__(self, *, max_gap_ranges: int = MAX_GAP_RANGES) -> None:
        self._max_gap_ranges = max_gap_ranges
        self._window_base: dict[SourceCode, int] = {}
        self._received: dict[SourceCode, set[int]] = {}
        self._highest: dict[SourceCode, int] = {}
        self._missing: dict[SourceCode, list[tuple[int, int]]] = {}
        self._gap_accum: dict[SourceCode, int] = {}
        self._observed: dict[SourceCode, int] = {}
        self._first: dict[SourceCode, int] = {}
        self._last: dict[SourceCode, int] = {}
        self._segments: dict[SourceCode, int] = {}
        self._late: dict[SourceCode, int] = {}
        self._duplicates: dict[SourceCode, int] = {}
        self._wraps: dict[SourceCode, int] = {}
        self._uncertain: set[SourceCode] = set()

    def record(self, src_code: SourceCode, frame_sn: int) -> int:
        """Record a received frame SN and return newly confirmed gap count.

        Returns the number of SNs confirmed lost by this call (0 for in-order
        or reordered frames within the window).
        """
        if src_code not in self._window_base:
            self._start_segment(src_code, frame_sn)
            return 0

        frame_abs = self._unwrap(frame_sn, self._highest[src_code])
        dist = frame_abs - self._window_base[src_code]

        self._observed[src_code] += 1
        if frame_abs > self._highest[src_code]:
            if frame_abs - self._highest[src_code] > MAX_TRUSTED_FORWARD_GAP:
                self._uncertain.add(src_code)
            previous_wrap = self._highest[src_code] // SN_MAX
            self._highest[src_code] = frame_abs
            self._last[src_code] = frame_sn
            self._wraps[src_code] += frame_abs // SN_MAX - previous_wrap

        if 0 <= dist < REORDER_WINDOW:
            # Within receive window: mark received, advance base
            if frame_abs in self._received[src_code]:
                self._duplicates[src_code] += 1
                return 0
            self._received[src_code].add(frame_abs)
            return self._advance(src_code)

        if dist >= REORDER_WINDOW:
            # Beyond window: expire old slots as confirmed gaps
            new_base = frame_abs - REORDER_WINDOW + 1
            gaps = self._expire_to(src_code, new_base)
            self._received[src_code].add(frame_abs)
            self._advance(src_code)
            return gaps

        # Behind the window: reconcile a confirmed gap or count a duplicate.
        if self._fill_missing(src_code, frame_abs):
            self._late[src_code] += 1
        else:
            self._duplicates[src_code] += 1
            if self._highest[src_code] - frame_abs > MAX_TRUSTED_FORWARD_GAP:
                self._uncertain.add(src_code)
        return 0

    def totals(self) -> dict[SourceCode, int]:
        """Return cumulative confirmed gap count per source."""
        return dict(self._gap_accum)

    def start_new_segment(self) -> None:
        """Seal active ranges while retaining capture-local totals."""

        for src_code in tuple(self._window_base):
            self._seal_source(src_code)
        self._window_base.clear()
        self._received.clear()
        self._highest.clear()
        self._missing.clear()

    def finalize(self) -> SequenceSummary:
        """Seal pending holes through each highest observed SN and summarize."""

        self.start_new_segment()
        return SequenceSummary(
            sources=tuple(
                SequenceSourceSummary(
                    source=src_code,
                    observed_frames=self._observed[src_code],
                    first_sn=self._first[src_code],
                    last_sn=self._last[src_code],
                    missing_frames=self._gap_accum.get(src_code, 0),
                    segments=self._segments[src_code],
                    late_frames=self._late[src_code],
                    duplicate_frames=self._duplicates[src_code],
                    wraps=self._wraps[src_code],
                    uncertain=src_code in self._uncertain,
                )
                for src_code in sorted(self._observed)
            )
        )

    def snapshot(self) -> SequenceSummary:
        """Return confirmed gaps without sealing the reorder window."""

        return SequenceSummary(
            sources=tuple(
                SequenceSourceSummary(
                    source=src_code,
                    observed_frames=self._observed[src_code],
                    first_sn=self._first[src_code],
                    last_sn=self._last[src_code],
                    missing_frames=self._gap_accum.get(src_code, 0),
                    segments=self._segments[src_code],
                    late_frames=self._late[src_code],
                    duplicate_frames=self._duplicates[src_code],
                    wraps=self._wraps[src_code],
                    uncertain=src_code in self._uncertain,
                )
                for src_code in sorted(self._observed)
            )
        )

    def reset(self, src_code: SourceCode | None = None) -> None:
        """Reset tracker state.

        If src_code is None, resets all sources.
        Otherwise resets only the specified source.
        """
        if src_code is None:
            self._window_base.clear()
            self._received.clear()
            self._highest.clear()
            self._missing.clear()
            self._gap_accum.clear()
            self._observed.clear()
            self._first.clear()
            self._last.clear()
            self._segments.clear()
            self._late.clear()
            self._duplicates.clear()
            self._wraps.clear()
            self._uncertain.clear()
        else:
            self._window_base.pop(src_code, None)
            self._received.pop(src_code, None)
            self._highest.pop(src_code, None)
            self._missing.pop(src_code, None)
            self._gap_accum.pop(src_code, None)
            self._observed.pop(src_code, None)
            self._first.pop(src_code, None)
            self._last.pop(src_code, None)
            self._segments.pop(src_code, None)
            self._late.pop(src_code, None)
            self._duplicates.pop(src_code, None)
            self._wraps.pop(src_code, None)
            self._uncertain.discard(src_code)

    def _start_segment(self, src_code: SourceCode, frame_sn: int) -> None:
        self._window_base[src_code] = frame_sn + 1
        self._received[src_code] = set()
        self._highest[src_code] = frame_sn
        self._missing[src_code] = []
        self._gap_accum.setdefault(src_code, 0)
        self._observed[src_code] = self._observed.get(src_code, 0) + 1
        self._first.setdefault(src_code, frame_sn)
        self._last[src_code] = frame_sn
        self._segments[src_code] = self._segments.get(src_code, 0) + 1
        self._late.setdefault(src_code, 0)
        self._duplicates.setdefault(src_code, 0)
        self._wraps.setdefault(src_code, 0)

    def _seal_source(self, src_code: SourceCode) -> None:
        new_base = self._highest[src_code] + 1
        self._expire_to(src_code, new_base)

    def _unwrap(self, frame_sn: int, reference: int) -> int:
        """Map a raw 24-bit SN to the nearest epoch around reference."""
        candidate = reference - reference % SN_MAX + frame_sn
        if candidate - reference >= SN_MAX // 2:
            candidate -= SN_MAX
        elif reference - candidate > SN_MAX // 2:
            candidate += SN_MAX
        return candidate

    def _advance(self, src_code: SourceCode) -> int:
        """Advance base past continuous received SNs."""
        while self._window_base[src_code] in self._received[src_code]:
            self._received[src_code].discard(self._window_base[src_code])
            self._window_base[src_code] += 1
        return 0

    def _expire_to(self, src_code: SourceCode, new_base: int) -> int:
        """Advance base to new_base, counting unreceived SNs as confirmed gaps."""
        old_base = self._window_base[src_code]
        expired_slots = new_base - old_base
        if expired_slots <= 0:
            return 0
        expired_received = {frame_sn for frame_sn in self._received[src_code] if frame_sn < new_base}
        gaps = expired_slots - len(expired_received)
        cursor = old_base
        for frame_abs in sorted(expired_received):
            if cursor < frame_abs:
                self._remember_missing(src_code, cursor, frame_abs - 1)
            cursor = frame_abs + 1
        if cursor < new_base:
            self._remember_missing(src_code, cursor, new_base - 1)
        self._received[src_code].difference_update(expired_received)
        self._window_base[src_code] = new_base
        self._gap_accum[src_code] += gaps
        return gaps

    def _remember_missing(self, src_code: SourceCode, start: int, end: int) -> None:
        if start > end or src_code in self._uncertain:
            return
        ranges = self._missing[src_code]
        if ranges and ranges[-1][1] + 1 >= start:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
        if len(ranges) > self._max_gap_ranges:
            # ponytail: cap sparse evidence; an interval tree is only justified if real captures exceed this.
            ranges.clear()
            self._uncertain.add(src_code)

    def _fill_missing(self, src_code: SourceCode, frame_abs: int) -> bool:
        if src_code in self._uncertain:
            return False
        ranges = self._missing[src_code]
        for index in range(len(ranges) - 1, -1, -1):
            start, end = ranges[index]
            if frame_abs > end:
                return False
            if frame_abs < start:
                continue
            if start == end:
                ranges.pop(index)
            elif frame_abs == start:
                ranges[index] = (start + 1, end)
            elif frame_abs == end:
                ranges[index] = (start, end - 1)
            else:
                ranges[index : index + 1] = [(start, frame_abs - 1), (frame_abs + 1, end)]
                if len(ranges) > self._max_gap_ranges:
                    ranges.clear()
                    self._uncertain.add(src_code)
            self._gap_accum[src_code] -= 1
            return True
        return False
