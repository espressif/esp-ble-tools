# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from src.backend.models import SourceCode


class FirmwareWrittenTracker:
    def __init__(self) -> None:
        self._frames_prev: dict[SourceCode, int] = {}
        self._bytes_prev: dict[SourceCode, int] = {}
        self._frames_latest: dict[SourceCode, int] = {}
        self._bytes_latest: dict[SourceCode, int] = {}

    def record(self, src_code: SourceCode, written_frames: int, written_bytes: int) -> tuple[int, int]:
        if src_code not in self._frames_prev:
            self._frames_prev[src_code] = written_frames
            self._bytes_prev[src_code] = written_bytes
            self._frames_latest[src_code] = written_frames
            self._bytes_latest[src_code] = written_bytes
            return (0, 0)

        prev_frames = self._frames_prev[src_code]
        prev_bytes = self._bytes_prev[src_code]
        d_frames = written_frames - prev_frames
        d_bytes = written_bytes - prev_bytes

        self._frames_prev[src_code] = written_frames
        self._bytes_prev[src_code] = written_bytes
        self._frames_latest[src_code] = written_frames
        self._bytes_latest[src_code] = written_bytes

        if d_frames < 0 or d_bytes < 0:
            return (0, 0)

        return (d_frames, d_bytes)

    def totals(self) -> dict[SourceCode, tuple[int, int]]:
        return {src: (self._frames_latest[src], self._bytes_latest[src]) for src in self._frames_latest}

    def reset(self) -> None:
        self._frames_prev.clear()
        self._bytes_prev.clear()
        self._frames_latest.clear()
        self._bytes_latest.clear()

    def reset_baselines(self) -> None:
        self._frames_prev.clear()
        self._bytes_prev.clear()
