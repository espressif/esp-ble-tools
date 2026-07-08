# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from queue import Queue
from threading import Event
from typing import IO

from src.backend.aggregator.event_aggregator import AggregatorUpdate
from src.backend.aggregator.event_aggregator import AggregatorSnapshot
from src.backend.pipeline.controller import run_capture_pipeline_inprocess
from src.backend.pipeline.controller import CapturePipeline
from src.backend.pipeline.controller import _result_from_events
from src.backend.reader.worker import ReaderProcessEvent
from src.backend.writer.raw_writer import RawWriterConfig
from src.backend.writer.raw_writer import RawWriterProcessEvent
from src.backend.writer.raw_writer import RawWriterStatus
from src.backend.support.parser_core.checksum import sum_checksum
from src.backend.models import BleLogSource
from src.backend.models import FrameStats
from src.backend.models import TransportConfig
from src.backend.models import TransportBitrate
from src.backend.models import TransportMode
from src.backend.support.transport import TransportStatus

from tests.helpers import build_frame


def _make_frame(payload: bytes, src: int, sn: int) -> bytes:
    return build_frame(payload, src, sn, sum_checksum, checksum_scope_full=True)  # type: ignore[no-any-return]


def _sync_frames(src: int = BleLogSource.HOST) -> bytes:
    payload = b'\x00\x00\x00\x00data'
    return b''.join(_make_frame(payload, src=src, sn=sn) for sn in range(3))


class FakeReader:
    def __init__(
        self,
        blocks: list[bytes],
        stop_event: Event,
        *,
        drain_blocks: list[bytes] | None = None,
        fail_after_blocks: bool = False,
    ) -> None:
        self.blocks = list(blocks)
        self.drain_blocks = list(drain_blocks or [])
        self.stop_event = stop_event
        self.fail_after_blocks = fail_after_blocks
        self.failed = False
        self.opened = False
        self.rx_bytes = 0
        self.rx_chunks = 0

    @property
    def display_name(self) -> str:
        return 'fake reader'

    @property
    def block_size(self) -> int:
        return 64

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate()

    def open(self) -> None:
        self.opened = True

    def read(self, size: int | None = None) -> bytes:
        if self.blocks:
            block = self.blocks.pop(0)
            self.rx_bytes += len(block)
            self.rx_chunks += 1
            return block
        if self.fail_after_blocks and not self.failed:
            self.failed = True
            raise RuntimeError('reader failed')
        self.stop_event.set()
        return b''

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        return self.drain_blocks[:max_rounds]

    def close(self) -> None:
        self.opened = False

    def reset_target(self) -> bool:
        return False

    def status(self) -> TransportStatus:
        return TransportStatus(
            mode=TransportMode.UART,
            display_name=self.display_name,
            opened=self.opened,
            healthy=self.opened,
            rx_bytes=self.rx_bytes,
            rx_chunks=self.rx_chunks,
        )


class FailingBinaryFile:
    def write(self, data: bytes) -> int:
        raise OSError('disk full')

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        raise OSError('no fileno')

    def close(self) -> None:
        pass


def test_fake_reader_writes_raw_file(tmp_path: Path) -> None:
    stop_event = Event()
    reader = FakeReader([b'one', b'two'], stop_event)
    output_path = tmp_path / 'ble_log.bin'

    result = run_capture_pipeline_inprocess(reader, RawWriterConfig(output_path), stop_requested=stop_event)

    assert result.completed
    assert result.reader_error is None
    assert result.writer_error is None
    assert result.parser_error is None
    assert result.aggregator_error is None
    assert result.raw_bytes == len(b'onetwo')
    assert result.raw_paths == (output_path,)
    assert output_path.read_bytes() == b'onetwo'


def test_stop_drains_reader_data_into_raw_file(tmp_path: Path) -> None:
    stop_event = Event()
    stop_event.set()
    reader = FakeReader([], stop_event, drain_blocks=[b'last'])
    output_path = tmp_path / 'ble_log.bin'

    result = run_capture_pipeline_inprocess(reader, RawWriterConfig(output_path), stop_requested=stop_event)

    assert result.completed
    assert output_path.read_bytes() == b'last'


def test_parser_process_completes_with_raw_capture(tmp_path: Path) -> None:
    stop_event = Event()
    reader = FakeReader([b'one', b'two'], stop_event)
    output_path = tmp_path / 'ble_log.bin'

    result = run_capture_pipeline_inprocess(reader, RawWriterConfig(output_path), stop_requested=stop_event)

    assert result.completed
    assert result.parser_error is None
    assert output_path.read_bytes() == b'onetwo'


def test_pipeline_aggregates_parser_events_and_raw_bytes(tmp_path: Path) -> None:
    stop_event = Event()
    frames = _sync_frames()
    reader = FakeReader([frames], stop_event)
    output_path = tmp_path / 'ble_log.bin'

    result = run_capture_pipeline_inprocess(reader, RawWriterConfig(output_path), stop_requested=stop_event)

    assert result.completed
    assert result.raw_bytes == len(frames)
    assert result.parser_raw_bytes == len(frames)
    assert result.parser_frames == 3
    assert result.parser_carried_bytes == 0
    assert output_path.read_bytes() == frames


def test_pipeline_result_reports_parse_backlog_metrics(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    status = RawWriterStatus(
        base_path=output_path,
        paths=(output_path,),
        bytes_written=100,
        chunks_written=2,
        current_part=1,
        finalized=True,
    )

    result = _result_from_events(
        [
            ReaderProcessEvent(
                kind='parse_backlog_summary',
                parse_dropped_chunks=2,
                parse_dropped_bytes=40,
            ),
            RawWriterProcessEvent(kind='finalized', status=status),
            AggregatorSnapshot(
                stats=FrameStats(),
                funnel_snapshots=(),
                buf_util_snapshots=(),
                captured_bytes=100,
                parser_raw_bytes=60,
                parser_frames=3,
                parser_carried_bytes=0,
            ),
        ]
    )

    assert result.parse_backlog
    assert result.parse_dropped_chunks == 2
    assert result.parse_dropped_bytes == 40
    assert result.parser_lag_bytes == 40


def test_pipeline_drain_events_keeps_result_relevant_state(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    pipeline = CapturePipeline(
        TransportConfig(mode=TransportMode.UART, label='fake', port='fake'),
        RawWriterConfig(output_path),
    )
    event_queue: Queue[object] = Queue()
    status = RawWriterStatus(
        base_path=output_path,
        paths=(output_path,),
        bytes_written=3,
        chunks_written=1,
        current_part=1,
        finalized=True,
    )
    event_queue.put(AggregatorUpdate(frames_seen=1))
    event_queue.put(RawWriterProcessEvent(kind='finalized', status=status))
    pipeline._event_queue = event_queue  # type: ignore[attr-defined]

    events = pipeline.drain_events()

    assert [type(event) for event in events] == [AggregatorUpdate, RawWriterProcessEvent]
    assert pipeline._result_events == [events[1]]  # type: ignore[attr-defined]


def test_writer_error_marks_pipeline_incomplete(tmp_path: Path) -> None:
    stop_event = Event()
    reader = FakeReader([b'one'], stop_event)

    def factory(path: Path) -> IO[bytes]:
        return FailingBinaryFile()  # type: ignore[return-value]

    result = run_capture_pipeline_inprocess(
        reader,
        RawWriterConfig(tmp_path / 'ble_log.bin'),
        stop_requested=stop_event,
        writer_file_factory=factory,
    )

    assert not result.completed
    assert result.writer_error == 'disk full'


def test_reader_error_marks_pipeline_incomplete_but_finalizes_written_data(tmp_path: Path) -> None:
    stop_event = Event()
    reader = FakeReader([b'one'], stop_event, fail_after_blocks=True)
    output_path = tmp_path / 'ble_log.bin'

    result = run_capture_pipeline_inprocess(reader, RawWriterConfig(output_path), stop_requested=stop_event)

    assert not result.completed
    assert result.reader_error == 'reader failed'
    assert result.raw_paths == (output_path,)
    assert result.raw_bytes == len(b'one')
    assert output_path.read_bytes() == b'one'
