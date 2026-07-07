# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from queue import Empty
from queue import Queue
from typing import IO

from src.backend.writer.raw_writer import RawWriter
from src.backend.writer.raw_writer import RawWriterConfig
from src.backend.writer.raw_writer import RawWriterProcessEvent
from src.backend.writer.raw_writer import run_raw_writer_loop


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeBinaryFile:
    def __init__(self, *, fail_write: bool = False) -> None:
        self.data = bytearray()
        self.write_calls: list[bytes] = []
        self.flush_count = 0
        self.closed = False
        self.fail_write = fail_write

    def write(self, data: bytes) -> int:
        if self.fail_write:
            raise OSError('disk full')
        self.write_calls.append(data)
        self.data.extend(data)
        return len(data)

    def flush(self) -> None:
        self.flush_count += 1

    def fileno(self) -> int:
        raise OSError('no fileno')

    def close(self) -> None:
        self.closed = True


def _events(event_queue: Queue[RawWriterProcessEvent]) -> list[RawWriterProcessEvent]:
    result: list[RawWriterProcessEvent] = []
    while True:
        try:
            result.append(event_queue.get_nowait())
        except Empty:
            return result


def test_writes_all_chunks_to_single_file(tmp_path: Path) -> None:
    raw_queue: Queue[bytes | None] = Queue()
    event_queue: Queue[RawWriterProcessEvent] = Queue()
    raw_queue.put(b'one')
    raw_queue.put(b'two')
    raw_queue.put(None)

    output_path = tmp_path / 'ble_log.bin'
    run_raw_writer_loop(RawWriterConfig(output_path), raw_queue, event_queue)

    assert output_path.read_bytes() == b'onetwo'
    events = _events(event_queue)
    assert [event.kind for event in events] == ['opened', 'finalized']
    assert events[0].message == str(output_path)
    assert events[0].status is not None
    assert events[0].status.paths == (output_path,)
    assert events[-1].status is not None
    assert events[-1].status.paths == (output_path,)
    assert events[-1].status.bytes_written == 6
    assert events[-1].status.chunks_written == 2
    assert events[-1].status.finalized


def test_empty_input_does_not_create_file(tmp_path: Path) -> None:
    raw_queue: Queue[bytes | None] = Queue()
    event_queue: Queue[RawWriterProcessEvent] = Queue()
    raw_queue.put(None)

    output_path = tmp_path / 'ble_log.bin'
    run_raw_writer_loop(RawWriterConfig(output_path), raw_queue, event_queue)

    assert not output_path.exists()
    events = _events(event_queue)
    assert [event.kind for event in events] == ['finalized']
    assert events[-1].status is not None
    assert events[-1].status.paths == ()


def test_each_chunk_calls_write_and_flushes_every_second(tmp_path: Path) -> None:
    fake_file = FakeBinaryFile()
    clock = FakeClock()

    def factory(path: Path) -> IO[bytes]:
        return fake_file  # type: ignore[return-value]

    writer = RawWriter(RawWriterConfig(tmp_path / 'ble_log.bin', flush_interval_sec=1.0), clock=clock, file_factory=factory)

    writer.write(b'a')
    clock.now = 0.5
    writer.write(b'b')
    assert fake_file.write_calls == [b'a', b'b']
    assert fake_file.flush_count == 0

    clock.now = 1.0
    writer.write(b'c')
    assert fake_file.write_calls == [b'a', b'b', b'c']
    assert fake_file.flush_count == 1

    writer.finalize()
    assert fake_file.flush_count == 2
    assert fake_file.closed


def test_rotates_capture_parts_with_legacy_names(tmp_path: Path) -> None:
    raw_queue: Queue[bytes | None] = Queue()
    event_queue: Queue[RawWriterProcessEvent] = Queue()
    raw_queue.put(b'abc')
    raw_queue.put(b'de')
    raw_queue.put(None)

    output_path = tmp_path / 'ble_log.bin'
    run_raw_writer_loop(RawWriterConfig(output_path, part_max_bytes=3), raw_queue, event_queue)

    part2 = tmp_path / 'ble_log_part002.bin'
    assert output_path.read_bytes() == b'abc'
    assert part2.read_bytes() == b'de'
    events = _events(event_queue)
    assert [event.kind for event in events] == ['opened', 'rotated', 'finalized']
    assert events[1].message == str(part2)
    assert events[-1].status is not None
    assert events[-1].status.paths == (output_path, part2)


def test_write_error_reports_error_and_closes_file(tmp_path: Path) -> None:
    fake_file = FakeBinaryFile(fail_write=True)

    def factory(path: Path) -> IO[bytes]:
        return fake_file  # type: ignore[return-value]

    raw_queue: Queue[bytes | None] = Queue()
    event_queue: Queue[RawWriterProcessEvent] = Queue()
    raw_queue.put(b'boom')
    raw_queue.put(None)

    run_raw_writer_loop(RawWriterConfig(tmp_path / 'ble_log.bin'), raw_queue, event_queue, file_factory=factory)

    events = _events(event_queue)
    assert events[0].kind == 'error'
    assert events[0].message == 'disk full'
    assert fake_file.closed
