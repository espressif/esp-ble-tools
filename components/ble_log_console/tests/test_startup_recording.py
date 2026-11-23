# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime
from pathlib import Path
from queue import Queue

import pytest
from src.backend.analysis.parser_events import ReceivedChunk, ReceivedEnd
from src.backend.analysis.worker import run_analysis_loop
from src.backend.io.writer import Writer, WriterConfig, WriterEvent
from src.backend.models import CaptureVerdict, TransportConfig, TransportMode
from src.backend.pipeline.controller import _result_from_events
from src.frontend.capture_report import build_capture_report, format_capture_report, format_capture_summary
from src.frontend.capture_session import CaptureSession

from tests.helpers import build_frame, xor_checksum
from tests.test_startup import chunks


def record(
    tmp_path,
    *,
    stale=True,
    clock_origin=0,
    dropped_tail=False,
    part_max_bytes=200 * 1024 * 1024,
    bindings=False,
    fresh_gap=False,
):
    """Exercise raw saving, analysis, final result and report with timed input."""
    items = chunks(stale=stale, clock_origin=clock_origin)
    if bindings:
        import struct

        binding = build_frame(struct.pack("<IBB17s", 1, 9, 1, b"BTU_TASK"), 0, 0, xor_checksum)
        items = [ReceivedChunk(binding, 0, 0.0, 0)] + [
            chunk._replace(raw_offset=chunk.raw_offset + len(binding)) for chunk in items
        ]
    if fresh_gap:
        from tests.test_startup import snapshot

        for second, sn in enumerate(range(500, 505), start=73):
            offset = sum(len(chunk.data) for chunk in items)
            items.append(
                ReceivedChunk(snapshot(second, sn, second), (second - 70) * 1000 + 100, second - 70 + 0.1, offset)
            )
    tail = build_frame(b"\x00" * 4 + b"user log", 1, 505 if fresh_gap else 303 if stale else 104, xor_checksum)
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


def test_selected_interval_is_checked_live_and_raw_is_preserved(tmp_path):
    items, result, report = record(tmp_path)
    assert result.startup.offset_bytes == len(items[0].data)
    assert report.verdict is CaptureVerdict.READY
    assert report.sequence.missing_frames == 0
    assert report.original_sequence.missing_frames == 199
    assert result.parser_frames == len(items)
    assert report.parser_complete and report.raw_complete
    assert result.parser_raw_bytes == result.raw_bytes
    assert "Quality metrics cover the confirmed fresh interval" in format_capture_summary(report, "en")
    assert "Raw suffix offset (bytes)" in format_capture_report(report, "en")
    assert not list(tmp_path.glob("*analysis*"))
    assert (tmp_path / "capture.bin").read_bytes() == b"".join(c.data for c in items)


def test_normal_recording_does_not_duplicate_or_cut_files(tmp_path):
    items, result, report = record(tmp_path, stale=False)
    assert result.startup.offset_bytes == 0
    assert result.opening_quality is None
    assert report.quality_start_offset == 0
    assert (tmp_path / "capture.bin").read_bytes() == b"".join(c.data for c in items)
    assert not list(tmp_path.glob("*analysis*"))


def test_incomplete_analysis_never_claims_a_complete_fresh_interval(tmp_path):
    items, result, report = record(tmp_path, dropped_tail=True)
    assert result.writer_finalized and report.raw_complete
    assert (tmp_path / "capture.bin").read_bytes() == b"".join(c.data for c in items)
    assert result.opening_quality.error
    assert report.quality_start_offset == 0
    assert not report.parser_complete
    assert report.verdict in (CaptureVerdict.WARNING, CaptureVerdict.RECAPTURE)
    assert not list(tmp_path.glob("*analysis*"))


def test_rotation_keeps_raw_and_checks_the_same_interval(tmp_path):
    items, result, report = record(tmp_path, part_max_bytes=200)
    assert len(result.raw_paths) > 1
    assert b"".join(p.read_bytes() for p in result.raw_paths) == b"".join(c.data for c in items)
    assert report.verdict is CaptureVerdict.READY
    assert report.sequence.missing_frames == 0
    assert not list(tmp_path.glob("*analysis*"))


def test_session_retains_raw_as_the_analysis_input(tmp_path):
    _, result, _ = record(tmp_path)
    session = CaptureSession(TransportConfig(TransportMode.USJ, "USJ", "test"), tmp_path / "capture.bin")
    session._event_presenter._saved_capture_path = result.raw_paths[0]
    session._event_presenter._saved_capture_paths = list(result.raw_paths)
    session._finish_result(result)
    assert session.saved_capture_path == tmp_path / "capture.bin"
    assert session.saved_capture_paths == [tmp_path / "capture.bin"]
    assert session.report.raw_paths == (tmp_path / "capture.bin",)


def test_backlog_with_task_bindings_keeps_context_but_scores_fresh_data(tmp_path):
    items, result, report = record(tmp_path, bindings=True)
    assert result.startup.offset_bytes > 0
    assert result.startup.preserve_prefix
    assert report.verdict is CaptureVerdict.READY
    assert report.sequence.missing_frames == 0
    assert report.original_sequence.missing_frames > 0
    assert report.quality_start_offset == result.startup.offset_bytes
    assert b"".join(p.read_bytes() for p in report.raw_paths) == b"".join(c.data for c in items)


def test_loss_after_opening_boundary_still_requires_record_again(tmp_path):
    _, _, report = record(tmp_path, fresh_gap=True)
    assert report.quality_start_offset > 0
    assert report.sequence.missing_frames > 0
    assert report.verdict is CaptureVerdict.RECAPTURE


@pytest.mark.parametrize("stage", ["create", "feed", "finish"])
def test_failed_fresh_check_keeps_original_quality_verdict(tmp_path, monkeypatch, stage):
    from unittest.mock import Mock

    from src.backend.analysis import opening_quality

    original = opening_quality.LogChecker

    def checker():
        if stage == "create":
            raise OSError("checker failure")
        proxy = Mock(wraps=original())
        getattr(proxy, stage).side_effect = OSError("checker failure")
        return proxy

    monkeypatch.setattr(opening_quality, "LogChecker", checker)
    _, result, report = record(tmp_path, bindings=True)
    assert result.opening_quality.error
    assert report.quality_start_offset == 0
    assert report.verdict is CaptureVerdict.RECAPTURE
    assert report.sequence.missing_frames > 0
    assert "新数据区间未能完成检查" in format_capture_report(report, "zh_CN")


@pytest.mark.parametrize("bindings", [False, True])
def test_fresh_quality_never_reopens_raw_files(tmp_path, monkeypatch, bindings):
    original_open = Path.open

    def refuse_raw_read(path, mode="r", *args, **kwargs):
        if path.suffix == ".bin" and "r" in mode:
            raise AssertionError("Recording quality must use already decoded frames")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse_raw_read)
    _, result, report = record(tmp_path, bindings=bindings)
    assert result.opening_quality.error is None
    assert report.verdict is CaptureVerdict.READY


def test_fresh_quality_uses_only_one_frame_decoder(tmp_path, monkeypatch):
    from src.backend.analysis import parser as parser_module

    original = parser_module._decoder_for_mode
    calls = []

    def decoder(mode):
        calls.append(mode)
        return original(mode)

    monkeypatch.setattr(parser_module, "_decoder_for_mode", decoder)
    _, _, report = record(tmp_path, bindings=True)
    assert report.quality_start_offset > 0
    assert len(calls) == 1


def test_metadata_only_fresh_interval_reports_its_own_regular_frame_count(tmp_path, monkeypatch):
    old = build_frame(b"\0\0\0\0old log", 1, 99, xor_checksum)
    items = [ReceivedChunk(old, 0, 0.0, 0)] + [c._replace(raw_offset=c.raw_offset + len(old)) for c in chunks()]
    monkeypatch.setattr("tests.test_startup_recording.chunks", lambda **kwargs: items)
    monkeypatch.setattr("tests.test_startup_recording.build_frame", lambda *args: b"")
    _, _, report = record(tmp_path)
    assert report.verdict is CaptureVerdict.READY
    assert report.regular_frames == 1
    assert report.quality_regular_frames == 0
    assert "Regular BLE Log frames: 0" in format_capture_summary(report, "en")
