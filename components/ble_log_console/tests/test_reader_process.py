# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from queue import Empty
from queue import Queue
from threading import Event

from src.backend.io.reader import ReaderCommand
from src.backend.io.reader import ReaderProcessEvent
from src.backend.io.reader import run_reader_loop
from src.backend.io.writer import WriterStatus
from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.models import TransportBitrate
from src.backend.models import TransportMode
from src.backend.support.transport import TransportStatus


class FakeReader:
    def __init__(
        self,
        blocks: list[bytes],
        stop_event: Event,
        drain_blocks: list[bytes] | None = None,
        *,
        reset_result: bool = False,
    ) -> None:
        self.blocks = list(blocks)
        self.drain_blocks = list(drain_blocks or [])
        self.stop_event = stop_event
        self.reset_result = reset_result
        self.opened = False
        self.rx_bytes = 0
        self.rx_chunks = 0
        self.read_calls = 0
        self.drain_calls = 0
        self.reset_calls = 0

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
        self.read_calls += 1
        if not self.blocks:
            self.stop_event.set()
            return b''
        block = self.blocks.pop(0)
        self.rx_bytes += len(block)
        self.rx_chunks += 1
        return block

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        self.drain_calls += 1
        return self.drain_blocks[:max_rounds]

    def close(self) -> None:
        self.opened = False

    def reset_target(self) -> bool:
        self.reset_calls += 1
        return self.reset_result

    def status(self) -> TransportStatus:
        return TransportStatus(
            mode=TransportMode.UART,
            display_name=self.display_name,
            opened=self.opened,
            healthy=self.opened,
            rx_bytes=self.rx_bytes,
            rx_chunks=self.rx_chunks,
        )


class FakeWriter:
    emits_events = False

    def __init__(self, *, fail_on_write: bool = False) -> None:
        self.blocks: list[bytes] = []
        self.finalized = False
        self.fail_on_write = fail_on_write
        self._paths = ()

    @property
    def paths(self) -> tuple[Path, ...]:
        return self._paths

    def status(self) -> WriterStatus:
        return WriterStatus(
            base_path=Path('fake.bin'),
            paths=self._paths,
            bytes_written=sum(len(block) for block in self.blocks),
            chunks_written=len(self.blocks),
            current_part=1,
            finalized=self.finalized,
            last_error='disk full' if self.fail_on_write and not self.blocks else None,
        )

    def write(self, block: bytes, *, timeout: float | None = None) -> None:
        del timeout
        if self.fail_on_write:
            raise OSError('disk full')
        if not self._paths:
            self._paths = (Path('fake.bin'),)
        self.blocks.append(block)

    def finalize(self) -> None:
        self.finalized = True


def _events(ui_queue: Queue[object]) -> list[object]:
    result: list[object] = []
    while True:
        try:
            result.append(ui_queue.get_nowait())
        except Empty:
            return result


class TestReaderProcessLoop:
    def test_fans_out_blocks_and_sends_sentinels(self) -> None:
        stop_event = Event()
        reader = FakeReader([b'one', b'two'], stop_event)
        writer = FakeWriter()
        parse_queue: Queue[ReceivedChunk | None] = Queue()
        ui_queue: Queue[object] = Queue()
        raw_stats_queue: Queue[int | None] = Queue()

        received_times = iter((100, 200))
        run_reader_loop(
            reader,
            writer,
            parse_queue,
            ui_queue,
            stop_event,
            raw_stats_queue=raw_stats_queue,
            wall_clock_ms=lambda: next(received_times),
        )

        assert writer.blocks == [b'one', b'two']
        assert raw_stats_queue.get_nowait() == len(b'onetwo')
        assert raw_stats_queue.get_nowait() is None
        assert parse_queue.get_nowait() == ReceivedChunk(b'one', 100)
        assert parse_queue.get_nowait() == ReceivedChunk(b'two', 200)
        assert parse_queue.get_nowait() is None
        assert [event.kind for event in _events(ui_queue)] == ['opened', 'opened', 'finalized', 'stopped']
        assert reader.read_calls == 3

    def test_stop_drains_remaining_transport_data(self) -> None:
        stop_event = Event()
        stop_event.set()
        reader = FakeReader([], stop_event, drain_blocks=[b'last'])
        writer = FakeWriter()
        parse_queue: Queue[ReceivedChunk | None] = Queue()
        ui_queue: Queue[object] = Queue()

        run_reader_loop(reader, writer, parse_queue, ui_queue, stop_event, wall_clock_ms=lambda: 300)

        assert writer.blocks == [b'last']
        assert parse_queue.get_nowait() == ReceivedChunk(b'last', 300)
        assert parse_queue.get_nowait() is None
        assert reader.drain_calls == 1

    def test_writer_error_reports_error(self) -> None:
        stop_event = Event()
        reader = FakeReader([b'one', b'two'], stop_event)
        writer = FakeWriter(fail_on_write=True)
        parse_queue: Queue[ReceivedChunk | None] = Queue()
        ui_queue: Queue[object] = Queue()

        run_reader_loop(reader, writer, parse_queue, ui_queue, stop_event)

        kinds = [event.kind for event in _events(ui_queue)]
        assert kinds == ['opened', 'error', 'stopped']
        assert writer.blocks == []

    def test_parse_queue_full_reports_backlog_without_stopping_raw(self) -> None:
        stop_event = Event()
        reader = FakeReader([b'one'], stop_event)
        writer = FakeWriter()
        parse_queue: Queue[ReceivedChunk | None] = Queue(maxsize=1)
        parse_queue.put(ReceivedChunk(b'existing', 0))
        ui_queue: Queue[object] = Queue()

        run_reader_loop(reader, writer, parse_queue, ui_queue, stop_event)

        events = _events(ui_queue)
        kinds = [event.kind for event in events]
        assert kinds == ['opened', 'opened', 'parse_backlog', 'finalized', 'parse_backlog_summary', 'stopped']
        assert events[2].parse_dropped_chunks == 1
        assert events[2].parse_dropped_bytes == len(b'one')
        assert events[4].parse_dropped_chunks == 1
        assert events[4].parse_dropped_bytes == len(b'one')
        assert writer.blocks == [b'one']

    def test_reader_command_resets_target(self) -> None:
        stop_event = Event()
        reader = FakeReader([], stop_event, reset_result=True)
        writer = FakeWriter()
        parse_queue: Queue[ReceivedChunk | None] = Queue()
        ui_queue: Queue[object] = Queue()
        command_queue: Queue[ReaderCommand] = Queue()
        command_queue.put(ReaderCommand(kind='reset_target'))

        run_reader_loop(reader, writer, parse_queue, ui_queue, stop_event, command_queue=command_queue)

        events = _events(ui_queue)
        assert [event.kind for event in events] == ['opened', 'reset_done', 'finalized', 'stopped']
        assert reader.reset_calls == 1

    def test_reader_command_reports_reset_unsupported(self) -> None:
        stop_event = Event()
        reader = FakeReader([], stop_event, reset_result=False)
        writer = FakeWriter()
        parse_queue: Queue[ReceivedChunk | None] = Queue()
        ui_queue: Queue[object] = Queue()
        command_queue: Queue[ReaderCommand] = Queue()
        command_queue.put(ReaderCommand(kind='reset_target'))

        run_reader_loop(reader, writer, parse_queue, ui_queue, stop_event, command_queue=command_queue)

        events = _events(ui_queue)
        assert [event.kind for event in events] == ['opened', 'reset_unsupported', 'finalized', 'stopped']
        assert reader.reset_calls == 1
