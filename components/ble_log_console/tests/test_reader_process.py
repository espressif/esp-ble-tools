# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from queue import Empty
from queue import Queue
from threading import Event

from src.backend.pipeline.reader import ReaderProcessEvent
from src.backend.pipeline.reader import ReaderCommand
from src.backend.pipeline.reader import run_reader_loop
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


def _events(event_queue: Queue[ReaderProcessEvent]) -> list[ReaderProcessEvent]:
    result: list[ReaderProcessEvent] = []
    while True:
        try:
            result.append(event_queue.get_nowait())
        except Empty:
            return result


class TestReaderProcessLoop:
    def test_fans_out_blocks_and_sends_sentinels(self) -> None:
        stop_event = Event()
        reader = FakeReader([b'one', b'two'], stop_event)
        raw_queue: Queue[bytes | None] = Queue()
        parse_queue: Queue[bytes | None] = Queue()
        event_queue: Queue[ReaderProcessEvent] = Queue()

        run_reader_loop(reader, raw_queue, parse_queue, event_queue, stop_event)

        assert raw_queue.get_nowait() == b'one'
        assert raw_queue.get_nowait() == b'two'
        assert raw_queue.get_nowait() is None
        assert parse_queue.get_nowait() == b'one'
        assert parse_queue.get_nowait() == b'two'
        assert parse_queue.get_nowait() is None
        assert [event.kind for event in _events(event_queue)] == ['opened', 'stopped']
        assert reader.read_calls == 3

    def test_stop_drains_remaining_transport_data(self) -> None:
        stop_event = Event()
        stop_event.set()
        reader = FakeReader([], stop_event, drain_blocks=[b'last'])
        raw_queue: Queue[bytes | None] = Queue()
        parse_queue: Queue[bytes | None] = Queue()
        event_queue: Queue[ReaderProcessEvent] = Queue()

        run_reader_loop(reader, raw_queue, parse_queue, event_queue, stop_event)

        assert raw_queue.get_nowait() == b'last'
        assert raw_queue.get_nowait() is None
        assert parse_queue.get_nowait() == b'last'
        assert parse_queue.get_nowait() is None
        assert reader.drain_calls == 1

    def test_raw_queue_full_reports_error(self) -> None:
        stop_event = Event()
        reader = FakeReader([b'one', b'two'], stop_event)
        raw_queue: Queue[bytes | None] = Queue(maxsize=1)
        parse_queue: Queue[bytes | None] = Queue()
        event_queue: Queue[ReaderProcessEvent] = Queue()

        run_reader_loop(reader, raw_queue, parse_queue, event_queue, stop_event, raw_put_timeout=0.01)

        kinds = [event.kind for event in _events(event_queue)]
        assert kinds == ['opened', 'error', 'stopped']
        assert raw_queue.get_nowait() == b'one'

    def test_parse_queue_full_reports_backlog_without_stopping_raw(self) -> None:
        stop_event = Event()
        reader = FakeReader([b'one'], stop_event)
        raw_queue: Queue[bytes | None] = Queue()
        parse_queue: Queue[bytes | None] = Queue(maxsize=1)
        parse_queue.put(b'existing')
        event_queue: Queue[ReaderProcessEvent] = Queue()

        run_reader_loop(reader, raw_queue, parse_queue, event_queue, stop_event)

        kinds = [event.kind for event in _events(event_queue)]
        assert kinds == ['opened', 'parse_backlog', 'stopped']
        assert raw_queue.get_nowait() == b'one'
        assert raw_queue.get_nowait() is None

    def test_reader_command_resets_target(self) -> None:
        stop_event = Event()
        reader = FakeReader([], stop_event, reset_result=True)
        raw_queue: Queue[bytes | None] = Queue()
        parse_queue: Queue[bytes | None] = Queue()
        event_queue: Queue[ReaderProcessEvent] = Queue()
        command_queue: Queue[ReaderCommand] = Queue()
        command_queue.put(ReaderCommand(kind='reset_target'))

        run_reader_loop(reader, raw_queue, parse_queue, event_queue, stop_event, command_queue=command_queue)

        events = _events(event_queue)
        assert [event.kind for event in events] == ['opened', 'reset_done', 'stopped']
        assert reader.reset_calls == 1

    def test_reader_command_reports_reset_unsupported(self) -> None:
        stop_event = Event()
        reader = FakeReader([], stop_event, reset_result=False)
        raw_queue: Queue[bytes | None] = Queue()
        parse_queue: Queue[bytes | None] = Queue()
        event_queue: Queue[ReaderProcessEvent] = Queue()
        command_queue: Queue[ReaderCommand] = Queue()
        command_queue.put(ReaderCommand(kind='reset_target'))

        run_reader_loop(reader, raw_queue, parse_queue, event_queue, stop_event, command_queue=command_queue)

        events = _events(event_queue)
        assert [event.kind for event in events] == ['opened', 'reset_unsupported', 'stopped']
        assert reader.reset_calls == 1
