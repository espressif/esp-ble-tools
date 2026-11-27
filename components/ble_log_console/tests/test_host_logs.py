# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import json
import struct

import pytest
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import HostLogEvent
from src.backend.models import LogLine, TransportMode
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.launch_screen import find_log_database

from tests.helpers import build_frame, snapshot_payload, xor_checksum


def frame(source, sn, payload):
    return build_frame(payload, source, sn, xor_checksum)


def encoded(sn, *, log_id=1, buffer=None):
    payload = struct.pack("<IBBBH", sn * 10, 0, 1, 0x40 if buffer is None else 0x80, log_id)
    if buffer is not None:
        payload += struct.pack("<H", len(buffer)) + buffer
    return frame(7, sn, payload)


def make_database(tmp_path):
    db = tmp_path / "ble_log_database"
    db.mkdir()
    (db / "BLE_HOST_logs.json").write_text(
        json.dumps(
            {
                "logs": {
                    "1": {"id": 1, "format": "data=@hex_buffer0"},
                    "2": {"id": 2, "format": "hello compressed"},
                }
            }
        )
    )
    return db


@pytest.fixture
def database(tmp_path):
    return make_database(tmp_path)


def host_events(batch):
    return [event for event in batch.events if isinstance(event, HostLogEvent)]


def test_database_discovery(monkeypatch, tmp_path, database):
    monkeypatch.chdir(tmp_path)
    assert find_log_database() == database
    (database / "BLE_HOST_logs.json").rename(tmp_path / "BLE_HOST_logs.json")
    assert find_log_database() == tmp_path
    (tmp_path / "BLE_HOST_logs.json").unlink()
    assert find_log_database() is None


@pytest.mark.parametrize("mode", list(TransportMode))
def test_host_text_reaches_display_and_file_without_double_counting(tmp_path, mode):
    parser, aggregator = BleLogParser(), CaptureAggregator()
    presenter = CaptureEventPresenter(tmp_path / "capture.bin", mode=mode)
    payload = struct.pack("<I", 10) + "hello host 中文\n".encode()
    data = frame(5, 0, payload) + frame(2, 1, b"LL hidden") + frame(6, 2, b"HCI hidden")
    messages = presenter.handle_events([aggregator.consume_parser_batch(parser.feed(data))])
    messages += presenter.finish()
    assert any(isinstance(msg, LogLine) and "hello host 中文" in msg.text for msg in messages)
    text = presenter.state.saved_console_log_paths[0].read_text(encoding="utf-8")
    assert "hello host 中文" in text and "hidden" not in text
    assert aggregator.snapshot(1).stats.transport.rx_frames == 3
    assert parser.finalize().parsed_frames == 3


@pytest.mark.parametrize("chunk_size", [1, 65536])
def test_compressed_buffer_is_written_once_when_complete(database, chunk_size):
    parser = BleLogParser(log_database=database)
    data = frame(0, 0, snapshot_payload()) + encoded(1) + encoded(2, buffer=b"\x11\x22")
    events = []
    for offset in range(0, len(data), chunk_size):
        events.extend(host_events(parser.feed(data[offset : offset + chunk_size])))
    events.extend(host_events(parser.finalize()))
    assert len(events) == 1
    assert "data=1122" in events[0].text and not events[0].reason


def test_stop_preserves_incomplete_host_text(database):
    parser = BleLogParser(log_database=database)
    assert not host_events(parser.feed(frame(0, 0, snapshot_payload()) + encoded(1)))
    events = host_events(parser.finalize())
    assert len(events) == 1 and events[0].reason == "missing_buffer"
    assert "data=" in events[0].text


@pytest.mark.parametrize(
    ("log_format", "expected"),
    [
        ('"hello\\n"', '"hello"'),
        ('"hello\\r\\n"', '"hello"'),
        ('"hello\\n\\n"', '"hello"'),
        ("hello\\n", "hello"),
        ('"中文\\n"', '"中文"'),
        (r'"literal \\n"', r'"literal \\n"'),
        (r'"path C:\\new\\n"', r'"path C:\\new\\n"'),
        (r'"slash \\\n"', r'"slash \\"'),
        (r'"first\nsecond\n"', r'"first\nsecond"'),
    ],
)
def test_compressed_host_trailing_line_endings(database, log_format, expected):
    (database / "BLE_HOST_logs.json").write_text(json.dumps({"logs": {"2": {"id": 2, "format": log_format}}}))
    parser = BleLogParser(log_database=database)
    events = host_events(parser.feed(frame(0, 0, snapshot_payload()) + encoded(1, log_id=2)))
    events += host_events(parser.finalize())
    assert len(events) == 1
    assert events[0].text.endswith(" | " + expected + "\n")
    assert events[0].text.count("\n") == 1


def test_plain_host_literal_line_ending_is_preserved():
    parser = BleLogParser()
    payload = struct.pack("<I", 10) + b"literal \\n"
    events = host_events(parser.feed(frame(5, 0, payload))) + host_events(parser.finalize())
    assert len(events) == 1 and events[0].text == "literal \\n\n"


def test_missing_database_warns_once_and_keeps_checking():
    parser = BleLogParser()
    events = host_events(parser.feed(frame(0, 0, snapshot_payload()) + encoded(1) + encoded(2)))
    assert len(events) == 1 and events[0].reason == "missing_database"
    assert not events[0].text
    final = parser.finalize()
    assert final.parsed_frames == 3 and final.integrity is not None


def test_malformed_database_does_not_stop_recording(database):
    (database / "BLE_HOST_logs.json").write_text("{broken")
    parser = BleLogParser(log_database=database)
    events = host_events(parser.feed(frame(0, 0, snapshot_payload()) + encoded(1)))
    assert events and events[0].reason and not events[0].text
    assert parser.finalize().parsed_frames == 2


@pytest.mark.parametrize("version", [5, 8])
def test_spawned_analysis_delivers_final_host_records(database, version):
    import multiprocessing
    from queue import Empty

    from src.backend.analysis.aggregator import AggregatorUpdate
    from src.backend.analysis.parser_events import ReceivedChunk
    from src.backend.analysis.worker import AggregatorProcessEvent, ParserStatus, run_analysis_process

    ctx = multiprocessing.get_context("spawn")
    incoming, outgoing = ctx.Queue(), ctx.Queue()
    initial = frame(0, 0, snapshot_payload()) if version == 8 else frame(0, 0, struct.pack("<IBB", 0, 0, version))
    message = encoded(1) if version == 8 else frame(7, 1, struct.pack("<IBBH", 10, 0, 0x40, 1))
    incoming.put(ReceivedChunk(initial + message, 100))
    incoming.put(None)
    process = ctx.Process(
        target=run_analysis_process, args=(incoming, None, outgoing), kwargs={"log_database": database}
    )
    process.start()
    events = []
    try:
        while True:
            try:
                event = outgoing.get(timeout=10)
            except Empty:
                pytest.fail("Analysis did not finish")
            events.append(event)
            if isinstance(event, AggregatorProcessEvent):
                assert event.kind == "finalized", events
                break
        process.join(timeout=5)
        assert process.exitcode == 0
        assert not any(isinstance(event, ParserStatus) and event.kind == "error" for event in events)
        host = [
            item
            for event in events
            if isinstance(event, AggregatorUpdate)
            for item in event.console_events
            if isinstance(item, HostLogEvent)
        ]
        assert len(host) == 1 and host[0].reason == "missing_buffer"
        assert "data=" in host[0].text
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        for queue in (incoming, outgoing):
            queue.close()
            queue.join_thread()
