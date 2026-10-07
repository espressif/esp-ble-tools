# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Recording save-failure scenarios through the real host-side pipeline."""

from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import IO

import pytest
from pytest_bdd import given, scenarios, then, when
from src.backend.io.writer import CAPTURE_PART_MAX_BYTES, WriterConfig
from src.backend.models import BleLogSource, CaptureVerdict, TransportConfig, TransportMode
from src.backend.pipeline import run_capture_pipeline_inprocess
from src.frontend.capture_report import build_capture_report

from tests.helpers import BytesReader, build_frame, xor_checksum

scenarios("features/recording_save.feature")


@given("Console 收到三个连续的 BLE Log 帧", target_fixture="recording")
def recording(tmp_path: Path) -> SimpleNamespace:
    frames = [build_frame(b"log", int(BleLogSource.LL_TASK), sn, xor_checksum) for sn in range(3)]
    return SimpleNamespace(frames=frames, tmp_path=tmp_path, opened=[], report=None)


def _run_recording(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, fail: bool, rotate: bool) -> None:
    def factory(path: Path) -> IO[bytes]:
        file_obj = path.open("wb")
        recording.opened.append(file_obj)
        return file_obj

    def fail_sync(fd: int) -> None:
        raise OSError("fsync failed")

    if fail:
        monkeypatch.setattr("src.backend.io.writer.os.fsync", fail_sync)
    stream = b"".join(recording.frames)
    recording.expected_raw = b"".join(recording.frames[:2]) if rotate else stream
    output_path = recording.tmp_path / "recording.bin"
    stop_event = Event()
    result = run_capture_pipeline_inprocess(
        BytesReader(stream, stop_event),
        WriterConfig(output_path, part_max_bytes=len(recording.expected_raw) if rotate else CAPTURE_PART_MAX_BYTES),
        stop_requested=stop_event,
        writer_file_factory=factory,
    )
    recording.report = build_capture_report(
        result,
        TransportConfig(mode=TransportMode.USB_OUTPUT, label="replay", port="replay"),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        duration_sec=1.0,
        console_log_paths=(),
        report_path=output_path.with_name("recording_report.txt"),
    )


@when("结束录制且文件同步成功")
def finish_successfully(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _run_recording(recording, monkeypatch, fail=False, rotate=False)


@when("结束录制时文件同步失败")
def fail_on_finalization(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _run_recording(recording, monkeypatch, fail=True, rotate=False)


@when("第一个分片关闭时文件同步失败")
def fail_on_rotation(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _run_recording(recording, monkeypatch, fail=True, rotate=True)


@then("报告确认原始数据完整保存")
def raw_complete(recording: SimpleNamespace) -> None:
    assert recording.report.raw_complete


@then("报告不确认原始数据完整保存")
def raw_not_complete(recording: SimpleNamespace) -> None:
    assert not recording.report.raw_complete


@then("报告显示文件同步错误")
def sync_error_is_reported(recording: SimpleNamespace) -> None:
    assert any("fsync failed" in error for error in recording.report.errors)


@then("报告判定录制可分析")
def ready(recording: SimpleNamespace) -> None:
    assert recording.report.verdict is CaptureVerdict.READY


@then("报告判定录制需要重录")
def recapture(recording: SimpleNamespace) -> None:
    assert recording.report.verdict is CaptureVerdict.RECAPTURE


@then("先前写入的原始字节仍可读取")
def raw_bytes_are_retained(recording: SimpleNamespace) -> None:
    assert recording.report.raw_paths == (recording.tmp_path / "recording.bin",)
    assert recording.report.raw_paths[0].read_bytes() == recording.expected_raw


@then("所有录制文件均已关闭")
def files_are_closed(recording: SimpleNamespace) -> None:
    assert recording.opened
    assert all(file_obj.closed for file_obj in recording.opened)
