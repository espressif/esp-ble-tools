# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Deliver contiguous recording bytes to the Core artifact writer."""

from dataclasses import dataclass
from pathlib import Path

from ble_log_frame_decoder import FrameDecoder, FrameFormat
from ble_log_frame_decoder.analysis.recording import RecordingExport
from ble_log_frame_decoder.checking.protocol import FRAME_CANDIDATE_POLICIES

from src.backend.analysis.parser_events import ReceivedChunk, ReceivedEnd
from src.backend.models import ChecksumAlgorithm, ChecksumMode


@dataclass(frozen=True)
class RecordingProducts:
    paths: tuple[Path, ...] = ()
    error: str | None = None


class RecordingProductWriter:
    def __init__(self, path: Path, database: Path | None, checksum: ChecksumMode | None):
        self.path, self.database, self.checksum = path, database, checksum
        self.export: RecordingExport | None = None
        self.offset = 0
        self.error: str | None = None

    def _feed(self, data: bytes) -> None:
        if self.export is None:
            decoder = None
            if self.checksum and self.checksum.algorithm == ChecksumAlgorithm.SUM:
                decoder = FrameDecoder(
                    FrameFormat.BLE_LOG_V2_SUM32, max_frame_size=4106, candidate_policies=FRAME_CANDIDATE_POLICIES
                )
            self.export = RecordingExport(self.path, database=self.database, decoder=decoder)
        self.export.feed(data)
        self.offset += len(data)

    def _catch_up(self, paths: tuple[Path, ...], limit: int) -> None:
        part_start = 0
        for path in paths:
            if self.offset >= limit:
                break
            size = path.stat().st_size
            if part_start + size > self.offset:
                with path.open("rb") as file:
                    file.seek(self.offset - part_start)
                    part_end = min(part_start + size, limit)
                    while self.offset < part_end:
                        data = file.read(min(256 * 1024, part_end - self.offset))
                        if not data:
                            raise OSError("Saved recording part ended before its reported size")
                        self._feed(data)
            part_start += size

    def receive(self, chunk: ReceivedChunk) -> None:
        if self.error or chunk.raw_offset is None:
            return
        try:
            if chunk.saved_paths and self.offset < chunk.raw_offset:
                self._catch_up(chunk.saved_paths, chunk.raw_offset)
            if self.offset == chunk.raw_offset:
                self._feed(chunk.data)
        except Exception as exc:
            self.error = str(exc)
            self.close()

    def finish(self, end: ReceivedEnd | None) -> RecordingProducts:
        try:
            if self.error is not None:
                return RecordingProducts(error=self.error)
            if end is None or not end.raw_complete:
                return RecordingProducts(error="Raw recording coverage could not be confirmed")
            if self.offset < end.raw_bytes:
                self._catch_up(end.raw_paths, end.raw_bytes)
            if self.offset != end.raw_bytes:
                return RecordingProducts(error="Saved parts do not cover the announced recording size")
            return RecordingProducts(self.export.finish() if self.export else ())
        except Exception as exc:
            return RecordingProducts(error=str(exc))
        finally:
            self.close()

    def close(self):
        if self.export is not None:
            self.export.close()
