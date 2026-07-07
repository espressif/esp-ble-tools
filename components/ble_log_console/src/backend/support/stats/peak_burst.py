# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Sliding-window peak write burst tracker.

Tracks the densest burst of log writes within a configurable time window
over chip-side timestamps.  A single instance handles one clock domain
(os_ts or lc_ts); the accumulator holds two instances.

The window uses millisecond-resolution timestamps.  Because log writes
happen at microsecond frequency, many frames share the same ms timestamp.
Instead of computing an inaccurate fps, we count frames and bytes within
the densest window.
"""

from collections import deque

from src.backend.models import PeakBurstSnapshot
from src.backend.models import SourceCode
from src.backend.models import SourcePeakWrite

# Sliding window width in chip timestamp space (milliseconds).
WRITE_RATE_WINDOW_MS = 10
MAX_PEAK_WINDOW_ENTRIES = 4096

_UINT32_MAX = 0xFFFF_FFFF
_UINT32_HALF = _UINT32_MAX // 2

# Type alias for a single window entry: (ts_ms, frame_size, src_code)
_WindowEntry = tuple[int, int, SourceCode]


def _ts_delta_ms(newer: int, older: int) -> int:
    """Compute forward delta between two uint32 timestamps, handling wraparound."""
    diff = (newer - older) & _UINT32_MAX
    if diff > _UINT32_HALF:
        return -1
    return diff


class PeakBurstTracker:
    """Sliding-window peak frame burst over a timestamp stream."""

    def __init__(
        self,
        window_ms: int = WRITE_RATE_WINDOW_MS,
        max_entries: int = MAX_PEAK_WINDOW_ENTRIES,
    ) -> None:
        self._window: deque[_WindowEntry] = deque()
        self._window_ms = window_ms
        self._max_entries = max_entries
        self._current_per_source: dict[SourceCode, SourcePeakWrite] = {}
        self._per_source_peak: dict[SourceCode, SourcePeakWrite] = {}
        self._max_per_source_peak: dict[SourceCode, SourcePeakWrite] = {}

    def _add_current(self, frame_size: int, src_code: SourceCode) -> None:
        current = self._current_per_source.get(src_code)
        if current is None:
            self._current_per_source[src_code] = SourcePeakWrite(peak_frames=1, peak_bytes=frame_size)
            return
        self._current_per_source[src_code] = SourcePeakWrite(
            peak_frames=current.peak_frames + 1,
            peak_bytes=current.peak_bytes + frame_size,
        )

    def _remove_current(self, frame_size: int, src_code: SourceCode) -> None:
        current = self._current_per_source[src_code]
        next_frames = current.peak_frames - 1
        if next_frames <= 0:
            del self._current_per_source[src_code]
            return
        self._current_per_source[src_code] = SourcePeakWrite(
            peak_frames=next_frames,
            peak_bytes=current.peak_bytes - frame_size,
        )

    def _drop_oldest(self) -> None:
        _, old_frame_size, old_src_code = self._window.popleft()
        self._remove_current(old_frame_size, old_src_code)

    def _update_peak(self, src_code: SourceCode) -> None:
        current = self._current_per_source.get(src_code)
        if current is None:
            return
        existing = self._per_source_peak.get(src_code)
        if existing is None or current.peak_frames > existing.peak_frames:
            self._per_source_peak[src_code] = current

    def record(self, ts_ms: int, frame_size: int, src_code: SourceCode) -> None:
        """Record a frame timestamp for peak burst calculation."""
        entry: _WindowEntry = (ts_ms, frame_size, src_code)
        self._window.append(entry)
        self._add_current(frame_size, src_code)

        while len(self._window) > 1:
            delta = _ts_delta_ms(ts_ms, self._window[0][0])
            if delta < 0:
                self._window.clear()
                self._window.append(entry)
                self._current_per_source = {src_code: SourcePeakWrite(peak_frames=1, peak_bytes=frame_size)}
                break
            if delta < self._window_ms:
                break
            self._drop_oldest()

        while len(self._window) > self._max_entries:
            self._drop_oldest()

        self._update_peak(src_code)

    def harvest(self) -> PeakBurstSnapshot:
        """Take current-period peaks, update all-time max, reset current period."""
        per_source = self._per_source_peak if self._per_source_peak else None

        for src, sp in self._per_source_peak.items():
            existing = self._max_per_source_peak.get(src)
            if existing is None or sp.peak_frames > existing.peak_frames:
                self._max_per_source_peak[src] = sp

        self._per_source_peak = {}

        max_per_source = dict(self._max_per_source_peak) if self._max_per_source_peak else None

        return PeakBurstSnapshot(
            per_source=per_source,
            max_per_source=max_per_source,
        )

    def max_peaks(self) -> dict[SourceCode, SourcePeakWrite]:
        """Return all-time max peaks per source (non-destructive, no reset)."""
        return dict(self._max_per_source_peak)
