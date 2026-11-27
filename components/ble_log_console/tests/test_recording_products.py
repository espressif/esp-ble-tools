# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from queue import Queue

from src.backend.analysis.parser_events import ReceivedChunk, ReceivedEnd
from src.backend.analysis.recording_products import RecordingProducts
from src.backend.analysis.worker import run_parser_loop
from src.backend.io.writer import WriterConfig

from tests.test_host_logs import frame


def test_missing_middle_and_tail_across_raw_parts(tmp_path):
    path = tmp_path / "rec.bin"
    raw = frame(5, 1, bytes(4) + b"first\n") + frame(5, 2, bytes(4) + b"second\n")
    second = path.with_name("rec_part002.bin")
    path.write_bytes(raw[:11])
    second.write_bytes(raw[11:])
    incoming, events = Queue(), Queue()
    incoming.put(ReceivedChunk(raw[:8], 1, raw_offset=0))
    incoming.put(ReceivedChunk(raw[16:21], 2, raw_offset=16))
    incoming.put(ReceivedEnd(len(raw), (path, second), True))
    run_parser_loop(incoming, events, analysis_output=WriterConfig(path))
    result = next(item for item in events.queue if isinstance(item, RecordingProducts))
    assert result.error is None
    assert [p.read_bytes() for p in result.paths] == [b"first\nsecond\n"]


def test_unconfirmed_raw_never_publishes_ordered_products(tmp_path):
    path = tmp_path / "rec.bin"
    incoming, events = Queue(), Queue()
    incoming.put(ReceivedChunk(frame(5, 1, bytes(4) + b"first"), 1, raw_offset=0))
    incoming.put(ReceivedEnd(50, (), False))
    run_parser_loop(incoming, events, analysis_output=WriterConfig(path))
    result = next(item for item in events.queue if isinstance(item, RecordingProducts))
    assert result.error and not result.paths
    assert not list(tmp_path.iterdir())


def test_resume_during_recording_only_reads_to_next_chunk(tmp_path):
    from src.backend.analysis.recording_products import RecordingProductWriter

    path = tmp_path / "rec.bin"
    data = frame(5, 1, bytes(4) + b"start") + frame(5, 2, bytes(4) + b"end")
    path.write_bytes(data)
    writer = RecordingProductWriter(path, None, None)
    writer.receive(ReceivedChunk(data[:7], 0, raw_offset=0))
    writer.receive(ReceivedChunk(data[14:20], 1, raw_offset=14, saved_paths=(path,)))
    assert writer.offset == 20
    writer.receive(ReceivedChunk(data[20:], 2, raw_offset=20))
    result = writer.finish(ReceivedEnd(len(data), (path,), True))
    assert result.error is None
    assert result.paths[0].read_bytes() == b"startend"


def test_compressed_host_in_excluded_prefix_does_not_require_text_output(tmp_path):
    from src.backend.analysis.startup import StartupDecision
    from src.backend.models import CompressedHostStatus

    from tests.test_host_logs import encoded, make_database
    from tests.test_startup import snapshot

    database = make_database(tmp_path)
    (database / "BLE_HOST_logs.json").write_text("{broken")
    blocks = [snapshot(10, 100, 10) + encoded(101), snapshot(70, 300, 70), snapshot(71, 301, 71), snapshot(72, 302, 72)]
    path = tmp_path / "rec.bin"
    path.write_bytes(b"".join(blocks))
    incoming, events = Queue(), Queue()
    offset = 0
    for block, ts in zip(blocks, (0, 0.1, 1.1, 2.1)):
        incoming.put(ReceivedChunk(block, int(ts * 1000), ts, offset))
        offset += len(block)
    incoming.put(ReceivedEnd(offset, (path,), True))
    run_parser_loop(incoming, events, analysis_output=WriterConfig(path), log_database=database)
    assert next(e.offset_bytes for e in events.queue if isinstance(e, StartupDecision)) == len(blocks[0])
    products = next(e for e in events.queue if isinstance(e, RecordingProducts))
    assert not products.error and products.compressed_host_status == CompressedHostStatus.NO_INPUT


def test_host_frame_recovered_from_raw_missing_from_live_queue(tmp_path):
    from src.backend.models import CompressedHostStatus

    from tests.helpers import snapshot_payload
    from tests.test_host_logs import encoded, make_database

    db = make_database(tmp_path)
    path = tmp_path / "rec.bin"
    prefix = frame(0, 0, snapshot_payload())
    raw = prefix + encoded(1, log_id=99)
    path.write_bytes(raw)
    incoming, events = Queue(), Queue()
    incoming.put(ReceivedChunk(prefix, 0, raw_offset=0))
    incoming.put(ReceivedEnd(len(raw), (path,), True))
    run_parser_loop(incoming, events, analysis_output=WriterConfig(path), log_database=db)
    result = next(item for item in events.queue if isinstance(item, RecordingProducts))
    assert result.host_missing_id_frames == 1
    assert result.compressed_host_status == CompressedHostStatus.NO_TEXT
