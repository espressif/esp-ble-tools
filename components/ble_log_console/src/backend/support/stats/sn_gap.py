# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Sliding receive window over firmware frame sequence streams.

Which frames share a stream depends on the firmware's counter ownership, and
the tracker models both contracts in the field:

- Protocol 8 numbers regular frames and INTERNAL snapshots from one counter
  (``g_frame_sn``), so they form a single stream: a per-source window would
  count every other source's frames as its own loss. REDIR (``redir->frame_sn``)
  and TASK_BINDING (``g_task_binding_sn``) keep private counters; REDIR is
  tracked separately from the shared stream, TASK_BINDING never reaches the
  tracker at all.
- Protocol <= 7 numbers every source from its own counter
  (``stat_mgr_ctx[src]->frame_sn``), so each source is a stream of its own and
  one loss in one source says nothing about another.

``per_source`` selects the contract, and ``StatsAccumulator`` picks it from the
firmware records the capture produced. Frames are only declared lost when the
receive window advances past their SN without them being received, tolerating
out-of-order delivery up to REORDER_WINDOW frames.
"""

from dataclasses import dataclass, field, replace

from src.backend.models import SequenceSourceSummary, SequenceSummary, SourceCode

SN_MAX = 1 << 24  # 24-bit SN space
REORDER_WINDOW = 256  # receive window size
MAX_GAP_RANGES = 4096
MAX_TRUSTED_FORWARD_GAP = 500


@dataclass
class _Stream:
    """Receive window and counters of one sequence stream."""

    base: int
    highest: int
    first: int | None
    last: int | None
    received: set[int] = field(default_factory=set)
    missing: list[tuple[int, int]] = field(default_factory=list)
    gap_accum: int = 0
    observed: int = 0
    segments: int = 1
    late: int = 0
    duplicates: int = 0
    wraps: int = 0
    uncertain: bool = False


class SNGapTracker:
    """Tracks SN continuity over one window per sequence stream."""

    def __init__(self, *, max_gap_ranges: int = MAX_GAP_RANGES, per_source: bool = False) -> None:
        self._max_gap_ranges = max_gap_ranges
        self._per_source = per_source
        self._streams: dict[int, _Stream] = {}
        self._unverified = False
        self._source_observed: dict[SourceCode, int] = {}
        self._source_first: dict[SourceCode, int] = {}
        self._source_last: dict[SourceCode, int] = {}

    def record(self, frame_sn: int, source: SourceCode = 0) -> int:
        """Record a received frame SN and return newly confirmed gap count.

        ``source`` tallies which source was observed (0 is INTERNAL) and, in
        per-source mode, selects the stream the frame belongs to. In shared
        counter mode every frame recorded on one tracker numbers itself from the
        same counter, so the source never scopes the gap math.
        """
        self._source_observed[source] = self._source_observed.get(source, 0) + 1
        self._source_first.setdefault(source, frame_sn)
        self._source_last[source] = frame_sn

        group = self._group(source)
        stream = self._streams.get(group)
        if stream is None:
            self._start_segment(group, frame_sn)
            return 0
        stream.observed += 1

        frame_abs = self._unwrap(frame_sn, stream.highest)
        dist = frame_abs - stream.base

        if frame_abs > stream.highest:
            if frame_abs - stream.highest > MAX_TRUSTED_FORWARD_GAP:
                stream.uncertain = True
            previous_wrap = stream.highest // SN_MAX
            stream.highest = frame_abs
            stream.last = frame_sn
            stream.wraps += frame_abs // SN_MAX - previous_wrap

        if 0 <= dist < REORDER_WINDOW:
            # Within receive window: mark received, advance base
            if frame_abs in stream.received:
                stream.duplicates += 1
                return 0
            stream.received.add(frame_abs)
            return self._advance(group)

        if dist >= REORDER_WINDOW:
            # Beyond window: expire old slots as confirmed gaps
            new_base = frame_abs - REORDER_WINDOW + 1
            gaps = self._expire_to(group, new_base)
            stream.received.add(frame_abs)
            self._advance(group)
            return gaps

        # Behind the window: reconcile a confirmed gap or count a duplicate.
        if self._fill_missing(group, frame_abs):
            stream.late += 1
        else:
            stream.duplicates += 1
            if stream.highest - frame_abs > MAX_TRUSTED_FORWARD_GAP:
                stream.uncertain = True
        return 0

    def last_observed(self, source: SourceCode) -> int | None:
        """Raw SN of the newest frame recorded for this source, if any."""

        return self._source_last.get(source)

    def totals(self) -> dict[SourceCode, int]:
        """Return frames observed per source."""

        return dict(self._source_observed)

    def finalize(self) -> SequenceSummary:
        """Seal pending holes through the highest observed SN and summarize."""

        self._seal()
        return self._summary()

    def snapshot(self) -> SequenceSummary:
        """Return confirmed gaps without sealing the reorder window."""

        return self._summary()

    def set_per_source(self, per_source: bool) -> None:
        """Re-key the windows to the firmware counter contract.

        Frames already accounted under the other contract cannot be re-keyed, so
        such windows are dropped and the summary is marked unverified: an
        admitted unknown beats a number derived from the wrong grouping.
        Observation counts survive, because they do not depend on the grouping.
        """

        if per_source == self._per_source:
            return
        self._per_source = per_source
        if self._streams:
            # Frames already sit in windows keyed the other way and cannot be
            # re-keyed, so the capture's continuity is no longer verifiable.
            self._unverified = True
        self._streams.clear()

    def reset(self) -> None:
        """Reset tracker state."""

        self.__init__(max_gap_ranges=self._max_gap_ranges, per_source=self._per_source)

    def _group(self, source: SourceCode) -> int:
        """Stream key of a source: the source itself, or the one shared stream."""

        return source if self._per_source else 0

    def _start_segment(self, key: int, frame_sn: int) -> _Stream:
        stream = _Stream(base=frame_sn + 1, highest=frame_sn, first=frame_sn, last=frame_sn, observed=1)
        self._streams[key] = stream
        return stream

    def _seal(self) -> None:
        for key in tuple(self._streams):
            self._expire_to(key, self._streams[key].highest + 1)

    def _summary(self) -> SequenceSummary:
        if self._per_source:
            sources = tuple(self._source_entry(source) for source in sorted(self._source_observed))
            return SequenceSummary(
                observed_frames=sum(entry.observed_frames for entry in sources),
                missing_frames=sum(entry.missing_frames for entry in sources),
                segments=sum(entry.segments for entry in sources),
                late_frames=sum(entry.late_frames for entry in sources),
                duplicate_frames=sum(entry.duplicate_frames for entry in sources),
                wraps=sum(entry.wraps for entry in sources),
                uncertain=self._unverified or any(entry.uncertain for entry in sources),
                per_source=True,
                sources=sources,
            )

        stream = self._streams.get(0)
        return SequenceSummary(
            observed_frames=stream.observed if stream else 0,
            first_sn=stream.first if stream else None,
            last_sn=stream.last if stream else None,
            missing_frames=stream.gap_accum if stream else 0,
            segments=stream.segments if stream else 0,
            late_frames=stream.late if stream else 0,
            duplicate_frames=stream.duplicates if stream else 0,
            wraps=stream.wraps if stream else 0,
            uncertain=self._unverified or (stream.uncertain if stream else False),
            sources=tuple(self._observation(source) for source in sorted(self._source_observed)),
        )

    def _observation(self, source: SourceCode) -> SequenceSourceSummary:
        """What a shared counter makes visible: observations, not stream bounds."""

        return SequenceSourceSummary(
            source=source,
            observed_frames=self._source_observed[source],
            first_sn=self._source_first[source],
            last_sn=self._source_last[source],
        )

    def _source_entry(self, source: SourceCode) -> SequenceSourceSummary:
        """Continuity counters of the source's own stream.

        A source can be observed without a stream: a contract switch drops the
        windows it cannot re-key, and the observation counts survive it. Such a
        source reports what it observed with its continuity marked unverified
        rather than inventing counters for a window that no longer exists.
        """

        stream = self._streams.get(self._group(source))
        if stream is None:
            return replace(self._observation(source), uncertain=True)
        return SequenceSourceSummary(
            source=source,
            observed_frames=stream.observed,
            first_sn=stream.first,
            last_sn=stream.last,
            missing_frames=stream.gap_accum,
            segments=stream.segments,
            late_frames=stream.late,
            duplicate_frames=stream.duplicates,
            wraps=stream.wraps,
            uncertain=self._unverified or stream.uncertain,
        )

    def _unwrap(self, frame_sn: int, reference: int) -> int:
        """Map a raw 24-bit SN to the nearest epoch around reference."""
        candidate = reference - reference % SN_MAX + frame_sn
        if candidate - reference >= SN_MAX // 2:
            candidate -= SN_MAX
        elif reference - candidate > SN_MAX // 2:
            candidate += SN_MAX
        return candidate

    def _advance(self, key: int) -> int:
        """Advance base past continuous received SNs."""
        stream = self._streams[key]
        while stream.base in stream.received:
            stream.received.discard(stream.base)
            stream.base += 1
        return 0

    def _expire_to(self, key: int, new_base: int) -> int:
        """Advance base to new_base, counting unreceived SNs as confirmed gaps."""
        stream = self._streams[key]
        expired_slots = new_base - stream.base
        if expired_slots <= 0:
            return 0
        expired_received = {frame_sn for frame_sn in stream.received if frame_sn < new_base}
        gaps = expired_slots - len(expired_received)
        cursor = stream.base
        for frame_abs in sorted(expired_received):
            if cursor < frame_abs:
                self._remember_missing(key, cursor, frame_abs - 1)
            cursor = frame_abs + 1
        if cursor < new_base:
            self._remember_missing(key, cursor, new_base - 1)
        stream.received.difference_update(expired_received)
        stream.base = new_base
        stream.gap_accum += gaps
        return gaps

    def _remember_missing(self, key: int, start: int, end: int) -> None:
        stream = self._streams[key]
        if start > end or stream.uncertain:
            return
        if stream.missing and stream.missing[-1][1] + 1 >= start:
            stream.missing[-1] = (stream.missing[-1][0], max(stream.missing[-1][1], end))
        else:
            stream.missing.append((start, end))
        if len(stream.missing) > self._max_gap_ranges:
            # hint: cap the sparse evidence; an interval tree is only worth it if
            # real captures exceed this range count.
            stream.missing.clear()
            stream.uncertain = True

    def _fill_missing(self, key: int, frame_abs: int) -> bool:
        stream = self._streams[key]
        if stream.uncertain:
            return False
        for index in range(len(stream.missing) - 1, -1, -1):
            start, end = stream.missing[index]
            if frame_abs > end:
                return False
            if frame_abs < start:
                continue
            if start == end:
                stream.missing.pop(index)
            elif frame_abs == start:
                stream.missing[index] = (start + 1, end)
            elif frame_abs == end:
                stream.missing[index] = (start, end - 1)
            else:
                stream.missing[index : index + 1] = [(start, frame_abs - 1), (frame_abs + 1, end)]
                if len(stream.missing) > self._max_gap_ranges:
                    stream.missing.clear()
                    stream.uncertain = True
            stream.gap_accum -= 1
            return True
        return False
