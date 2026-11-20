# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Check an opening candidate from frames decoded by the live parser."""

from dataclasses import dataclass

from ble_log_frame_decoder import BleLogFrame, FrameView, is_valid_internal_candidate
from ble_log_frame_decoder.analysis.firmware import FirmwareStats
from ble_log_frame_decoder.checking import LogChecker

from src.backend.analysis.aggregator import AggregatorSnapshot, CaptureAggregator
from src.backend.analysis.parser_events import BleLogEvent, ParseSummary


@dataclass(frozen=True)
class OpeningQuality:
    offset_bytes: int
    snapshot: AggregatorSnapshot | None = None
    error: str | None = None


class OpeningChecker:
    """Keep only Checker windows and counters; do not retain or decode raw bytes."""

    def __init__(self, offset: int) -> None:
        self.offset = offset
        self._aggregator = CaptureAggregator()
        self._firmware = FirmwareStats()
        self._frames = 0
        self._unchecked = 0
        self._error: str | None = None
        self._checker = None
        try:
            self._checker = LogChecker()
        except Exception as error:
            self._error = str(error)

    def feed(self, frame: BleLogFrame, events: tuple[BleLogEvent, ...]) -> None:
        if self._error is not None:
            return
        try:
            checked = 0 <= frame.source_code <= 8 and (
                frame.source_code != 0 or is_valid_internal_candidate(frame.payload)
            )
            if checked:
                with memoryview(frame.payload) as payload:
                    view = FrameView(frame.source_code, frame.sequence_number, frame.offset + 6, len(payload), payload)
                    self._checker.feed(view)
                    self._firmware.feed(view)
            else:
                self._unchecked += 1
            self._frames += 1
            self._aggregator.consume_events(events)
        except Exception as error:
            self._error = str(error)
            self.close()

    def finish(self, raw_bytes: int, carried_bytes: int) -> OpeningQuality:
        try:
            if self._error is not None:
                return OpeningQuality(self.offset, error=self._error)
            integrity = self._checker.finish()
            if self._unchecked:
                integrity.notes.append(
                    f"Console retained {self._unchecked} frame(s) outside the Checker protocol contract."
                )
            size = raw_bytes - self.offset
            self._aggregator.record_raw_bytes(size)
            self._aggregator.consume_parser_summary(
                ParseSummary(size, self._frames, carried_bytes, firmware=self._firmware.snapshot(), integrity=integrity)
            )
            return OpeningQuality(self.offset, self._aggregator.snapshot(0))
        except Exception as error:
            return OpeningQuality(self.offset, error=str(error))
        finally:
            self.close()

    def close(self) -> None:
        if self._checker is not None:
            self._checker.close()
