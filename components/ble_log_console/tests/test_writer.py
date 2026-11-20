# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import IO

import pytest
from src.backend.io.writer import AsyncBatchWriter, Writer, WriterConfig, WriterEvent


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
            raise OSError("disk full")
        self.write_calls.append(data)
        self.data.extend(data)
        return len(data)

    def flush(self) -> None:
        self.flush_count += 1

    def fileno(self) -> int:
        raise OSError("no fileno")

    def close(self) -> None:
        self.closed = True


def _events(ui_queue: Queue[WriterEvent]) -> list[WriterEvent]:
    result: list[WriterEvent] = []
    while True:
        try:
            result.append(ui_queue.get_nowait())
        except Empty:
            return result


def test_writes_all_chunks_to_single_file(tmp_path: Path) -> None:
    ui_queue: Queue[WriterEvent] = Queue()
    output_path = tmp_path / "ble_log.bin"
    writer = AsyncBatchWriter(WriterConfig(output_path), ui_queue, batch_timeout_sec=0)

    writer.start()
    writer.write(b"one", timeout=1)
    writer.write(b"two", timeout=1)
    writer.finalize()

    assert output_path.read_bytes() == b"onetwo"
    events = _events(ui_queue)
    assert [event.kind for event in events] == ["opened", "finalized"]
    assert events[0].message == str(output_path)
    assert events[0].status is not None
    assert events[0].status.paths == (output_path,)
    assert events[-1].status is not None
    assert events[-1].status.paths == (output_path,)
    assert events[-1].status.bytes_written == 6
    assert events[-1].status.finalized


def test_empty_input_does_not_create_file(tmp_path: Path) -> None:
    ui_queue: Queue[WriterEvent] = Queue()
    output_path = tmp_path / "ble_log.bin"
    writer = AsyncBatchWriter(WriterConfig(output_path), ui_queue, batch_timeout_sec=0)

    writer.start()
    writer.finalize()

    assert not output_path.exists()
    events = _events(ui_queue)
    assert [event.kind for event in events] == ["finalized"]
    assert events[-1].status is not None
    assert events[-1].status.paths == ()


def test_each_chunk_calls_write_and_flushes_every_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_file = FakeBinaryFile()
    monkeypatch.setattr(fake_file, "fileno", lambda: 0)
    monkeypatch.setattr("src.backend.io.writer.os.fsync", lambda fd: None)
    clock = FakeClock()

    def factory(path: Path) -> IO[bytes]:
        return fake_file  # type: ignore[return-value]

    writer = Writer(WriterConfig(tmp_path / "ble_log.bin", flush_interval_sec=1.0), clock=clock, file_factory=factory)

    writer.write(b"a")
    clock.now = 0.5
    writer.write(b"b")
    assert fake_file.write_calls == [b"a", b"b"]
    assert fake_file.flush_count == 0

    clock.now = 1.0
    writer.write(b"c")
    assert fake_file.write_calls == [b"a", b"b", b"c"]
    assert fake_file.flush_count == 1

    writer.finalize()
    assert fake_file.flush_count == 2
    assert fake_file.closed


def test_rotates_capture_parts_with_legacy_names(tmp_path: Path) -> None:
    ui_queue: Queue[WriterEvent] = Queue()
    output_path = tmp_path / "ble_log.bin"
    writer = AsyncBatchWriter(WriterConfig(output_path, part_max_bytes=3), ui_queue, batch_timeout_sec=0)

    writer.start()
    writer.write(b"abc", timeout=1)
    writer.write(b"de", timeout=1)
    writer.finalize()

    part2 = tmp_path / "ble_log_part002.bin"
    assert output_path.read_bytes() == b"abc"
    assert part2.read_bytes() == b"de"
    events = _events(ui_queue)
    assert [event.kind for event in events] == ["opened", "rotated", "finalized"]
    assert events[1].message == str(part2)
    assert events[-1].status is not None
    assert events[-1].status.paths == (output_path, part2)


def test_write_error_reports_error_and_closes_file(tmp_path: Path) -> None:
    fake_file = FakeBinaryFile(fail_write=True)

    def factory(path: Path) -> IO[bytes]:
        return fake_file  # type: ignore[return-value]

    ui_queue: Queue[WriterEvent] = Queue()
    writer = AsyncBatchWriter(
        WriterConfig(tmp_path / "ble_log.bin"),
        ui_queue,
        batch_timeout_sec=0,
        file_factory=factory,
    )

    writer.start()
    writer.write(b"boom", timeout=1)
    writer.finalize()

    events = _events(ui_queue)
    assert events[0].kind == "error"
    assert events[0].message == "disk full"
    assert fake_file.closed


def test_unavailable_file_descriptor_is_reported_and_file_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_file = FakeBinaryFile()
    sync_calls: list[int] = []
    monkeypatch.setattr("src.backend.io.writer.os.fsync", sync_calls.append)

    def factory(path: Path) -> IO[bytes]:
        return fake_file  # type: ignore[return-value]

    writer = Writer(WriterConfig(tmp_path / "recording.bin"), file_factory=factory)
    writer.write(b"abc")

    with pytest.raises(OSError, match="no fileno"):
        writer.finalize()

    assert not sync_calls
    assert fake_file.closed
    assert fake_file.data == b"abc"
    assert writer.status().last_error == "no fileno"


@pytest.mark.parametrize("stage", ["finalize", "rotate"])
def test_sync_failure_preserves_written_bytes_and_closes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    opened: list[IO[bytes]] = []
    sync_calls: list[int] = []
    output_path = tmp_path / "recording.bin"

    def factory(path: Path) -> IO[bytes]:
        file_obj = path.open("wb")
        opened.append(file_obj)
        return file_obj

    def fail_sync(fd: int) -> None:
        sync_calls.append(fd)
        raise OSError("fsync failed")

    monkeypatch.setattr("src.backend.io.writer.os.fsync", fail_sync)
    writer = Writer(WriterConfig(output_path, part_max_bytes=3), file_factory=factory)
    writer.write(b"abc")

    with pytest.raises(OSError, match="fsync failed"):
        if stage == "rotate":
            writer.write(b"def")
        else:
            writer.finalize()

    # Cleanup must not retry a closed rotation handle or replace the sync error.
    writer.finalize()
    assert len(sync_calls) == 1
    assert len(opened) == 1 and opened[0].closed
    assert output_path.read_bytes() == b"abc"
    assert writer.paths == (output_path,)
    assert not (tmp_path / "recording_part002.bin").exists()
    assert writer.status().last_error == "fsync failed"
    assert writer.status().bytes_written == 3
    assert writer.status().finalized


@pytest.mark.parametrize("stage", ["finalize", "rotate"])
def test_async_sync_failure_emits_error_instead_of_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    opened: list[IO[bytes]] = []
    release_sync = Event()
    output_path = tmp_path / "recording.bin"
    ui_queue: Queue[WriterEvent] = Queue()

    def factory(path: Path) -> IO[bytes]:
        file_obj = path.open("wb")
        opened.append(file_obj)
        return file_obj

    def fail_sync(fd: int) -> None:
        # Hold the failure until all test input has been accepted by the queue.
        assert release_sync.wait(5), "test did not release file synchronization"
        raise OSError("fsync failed")

    monkeypatch.setattr("src.backend.io.writer.os.fsync", fail_sync)
    writer = AsyncBatchWriter(
        WriterConfig(output_path, part_max_bytes=3), ui_queue, batch_timeout_sec=0, file_factory=factory
    )
    writer.start()
    try:
        writer.write(b"abc", timeout=1)
        if stage == "rotate":
            writer.write(b"def", timeout=1)
    finally:
        release_sync.set()
        writer.finalize()

    events = _events(ui_queue)
    errors = [event for event in events if event.kind == "error"]
    assert len(errors) == 1
    assert "fsync failed" in errors[0].message
    assert not any(event.kind == "finalized" for event in events)
    assert len(opened) == 1 and opened[0].closed
    assert output_path.read_bytes() == b"abc"
    assert writer.status().last_error == "fsync failed"


def test_graceful_finalize_waits_for_all_accepted_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = Event()
    release = Event()
    finished = Event()
    opened: list[IO[bytes]] = []
    errors: list[Exception] = []
    ui_queue: Queue[WriterEvent] = Queue()
    path = tmp_path / "recording.bin"

    def factory(output: Path) -> IO[bytes]:
        file_obj = output.open("wb")
        opened.append(file_obj)
        original_write = file_obj.write

        def write(data: bytes) -> int:
            if data == b"first":
                blocked.set()
                assert release.wait(5), "test did not release the pending write"
            return original_write(data)

        monkeypatch.setattr(file_obj, "write", write)
        return file_obj

    writer = AsyncBatchWriter(WriterConfig(path), ui_queue, queue_max_blocks=1, batch_max_bytes=1, file_factory=factory)

    def finalize() -> None:
        try:
            writer.finalize()
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    finalizer = Thread(target=finalize)
    writer.start()
    try:
        writer.write(b"first", timeout=1)
        assert blocked.wait(5)
        writer.write(b"second", timeout=1)
        finalizer.start()
        assert not finished.wait(0.05), "finalize returned while accepted data was still pending"
    finally:
        release.set()
        if finalizer.ident is None:
            finalizer.start()
        finalizer.join(5)
        assert not finalizer.is_alive(), "test left a finalizer thread running"

    assert not errors
    assert path.read_bytes() == b"firstsecond"
    assert all(file_obj.closed for file_obj in opened)
    assert writer.status().finalized
    assert writer.status().last_error is None
    assert any(event.kind == "finalized" for event in _events(ui_queue))
