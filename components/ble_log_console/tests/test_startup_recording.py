# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime
from queue import Queue
from threading import Thread

import pytest
from ble_log_frame_decoder import FrameDecoder, is_snapshot
from src.backend.analysis.parser_events import ParseBatch, ReceivedChunk, ReceivedEnd
from src.backend.analysis.worker import run_analysis_loop, run_parser_loop
from src.backend.io.analysis_copy import AnalysisCopyResult, copy_recording_suffix
from src.backend.io.writer import Writer, WriterConfig, WriterEvent
from src.backend.models import CaptureVerdict, TransportConfig, TransportMode
from src.backend.pipeline.controller import _result_from_events
from src.frontend.capture_report import build_capture_report, format_capture_report, format_capture_summary
from src.frontend.capture_session import CaptureSession

from tests.helpers import build_frame, xor_checksum
from tests.test_startup import chunks


def record(tmp_path, *, stale=True, dropped_tail=False, collision=False, part_max_bytes=200 * 1024 * 1024):
    """Exercise raw saving, analysis, final result and report with timed input."""
    items = chunks(stale=stale)
    tail = build_frame(b"\x00" * 4 + b"user log", 1, 303 if stale else 104, xor_checksum)
    items.append(ReceivedChunk(tail, 2200 if stale else 3100, 2.2 if stale else 3.1, sum(len(c.data) for c in items)))
    config = WriterConfig(tmp_path / "capture.bin", part_max_bytes=part_max_bytes)
    writer = Writer(config)
    incoming, raw_counts, outgoing = Queue(), Queue(), Queue()
    for index, chunk in enumerate(items):
        writer.write(chunk.data)
        raw_counts.put(len(chunk.data))
        if not dropped_tail or index != len(items) - 1:
            incoming.put(chunk)
    writer.finalize()
    if collision:
        (tmp_path / "capture_analysis.bin").write_bytes(b"unrelated recording")
    incoming.put(ReceivedEnd(writer.status().bytes_written, writer.paths, True))
    raw_counts.put(None)
    run_analysis_loop(incoming, raw_counts, outgoing, analysis_output=config)
    events = [WriterEvent("finalized", status=writer.status())]
    while not outgoing.empty():
        events.append(outgoing.get_nowait())
    result = _result_from_events(events)
    now = datetime.now(UTC)
    report = build_capture_report(
        result,
        TransportConfig(TransportMode.USJ, "USJ", "test"),
        started_at=now,
        ended_at=now,
        duration_sec=3,
        console_log_paths=(),
        report_path=tmp_path / "capture_report.txt",
    )
    return items, result, report


def test_selected_file_is_exact_independently_decodable_suffix_and_report_scope(tmp_path):
    items, result, report = record(tmp_path)
    raw = b"".join(p.read_bytes() for p in result.raw_paths)
    assert raw == b"".join(c.data for c in items)
    assert result.startup.offset_bytes == len(items[0].data)
    selected = b"".join(p.read_bytes() for p in report.analysis_paths)
    assert selected == raw[result.startup.offset_bytes :]
    frames = FrameDecoder().feed(selected)
    assert is_snapshot(frames[0].payload)
    assert frames[0].sequence_number == 300
    assert report.verdict is CaptureVerdict.RECAPTURE  # Original stream still includes its opening gap.
    assert report.sequence.missing_frames == 199
    assert result.parser_frames == len(items)
    assert report.parser_complete
    assert report.raw_complete
    assert result.parser_raw_bytes == result.raw_bytes
    assert "suffix has not been evaluated separately" in format_capture_summary(report, "en")
    assert "capture_analysis.bin" in format_capture_report(report, "en")
    assert "Raw suffix offset (bytes)" in format_capture_report(report, "en")
    assert not list(tmp_path.glob("*.partial"))


def test_normal_recording_does_not_duplicate_or_cut_files(tmp_path):
    items, result, report = record(tmp_path, stale=False)
    assert result.startup.offset_bytes == 0
    assert not report.analysis_paths
    assert result.analysis_copy is None
    assert (tmp_path / "capture.bin").read_bytes() == b"".join(c.data for c in items)
    assert not list(tmp_path.glob("*analysis*"))


@pytest.mark.parametrize("failure", ["dropped_tail", "collision"])
def test_incomplete_analysis_never_publishes_a_successful_copy_or_damages_raw(tmp_path, failure):
    items, result, report = record(tmp_path, **{failure: True})
    assert result.writer_finalized and report.raw_complete
    assert (tmp_path / "capture.bin").read_bytes() == b"".join(c.data for c in items)
    assert not report.analysis_paths
    assert result.analysis_copy.error
    assert report.analysis_error
    assert report.verdict in (CaptureVerdict.WARNING, CaptureVerdict.RECAPTURE)
    if failure == "collision":
        assert (tmp_path / "capture_analysis.bin").read_bytes() == b"unrelated recording"
    else:
        assert not (tmp_path / "capture_analysis.bin").exists()
    assert not list(tmp_path.glob("*.partial"))


def test_rotation_preserves_raw_and_selected_concatenation(tmp_path):
    items, result, report = record(tmp_path, part_max_bytes=200)
    raw = b"".join(c.data for c in items)
    assert len(result.raw_paths) > 1
    assert len(report.analysis_paths) > 1
    assert b"".join(p.read_bytes() for p in result.raw_paths) == raw
    assert b"".join(p.read_bytes() for p in report.analysis_paths) == raw[len(items[0].data) :]


def test_copy_fsync_failure_does_not_publish_file(tmp_path, monkeypatch):
    raw = tmp_path / "capture.bin"
    raw.write_bytes(b"oldnew")

    def fail(_fd):
        raise OSError("disk sync failed")

    monkeypatch.setattr("src.backend.io.writer.os.fsync", fail)
    result = copy_recording_suffix(WriterConfig(raw), (raw,), offset=3, raw_bytes=6)
    assert isinstance(result, AnalysisCopyResult)
    assert result.paths == ()
    assert "disk sync failed" in result.error
    assert list(tmp_path.iterdir()) == [raw]
    assert raw.read_bytes() == b"oldnew"


def test_session_defaults_to_analysis_file_and_retains_raw_paths_in_report(tmp_path):
    _, result, _ = record(tmp_path)
    session = CaptureSession(TransportConfig(TransportMode.USJ, "USJ", "test"), tmp_path / "capture.bin")
    session._finish_result(result)
    assert session.saved_capture_path == tmp_path / "capture_analysis.bin"
    assert session.saved_capture_paths == [tmp_path / "capture_analysis.bin"]
    assert session.report.raw_paths == (tmp_path / "capture.bin",)
    assert "File for analysis" in session.report.report_path.read_text()


def test_failed_publication_preserves_colliding_later_part(tmp_path):
    raw = tmp_path / "capture.bin"
    raw.write_bytes(b"oldabcdef")
    unrelated = tmp_path / "capture_analysis_part002.bin"
    unrelated.write_bytes(b"another recording")
    result = copy_recording_suffix(WriterConfig(raw, part_max_bytes=3), (raw,), offset=3, raw_bytes=9)
    assert result.error and not result.paths
    assert unrelated.read_bytes() == b"another recording"
    assert not (tmp_path / "capture_analysis.bin").exists()
    assert not list(tmp_path.glob("*.partial"))


def test_live_parsing_does_not_write_a_copy_before_raw_finalization(tmp_path):
    config = WriterConfig(tmp_path / "capture.bin")
    writer = Writer(config)
    incoming, outgoing = Queue(), Queue()
    items = chunks()
    for chunk in items:
        writer.write(chunk.data)
        incoming.put(chunk)
    thread = Thread(target=run_parser_loop, args=(incoming, outgoing), kwargs={"analysis_output": config}, daemon=True)
    thread.start()
    try:
        frames = 0
        while frames < 4:
            event = outgoing.get(timeout=2)
            if isinstance(event, ParseBatch):
                frames += event.parsed_frames
        assert not list(tmp_path.glob("*analysis*"))
        writer.finalize()
        incoming.put(ReceivedEnd(writer.status().bytes_written, writer.paths, True))
        thread.join(2)
        assert not thread.is_alive()
        expected = b"".join(c.data for c in items[1:])
        assert (tmp_path / "capture_analysis.bin").read_bytes() == expected
    finally:
        writer.finalize()
        incoming.put(None)
        thread.join(2)
