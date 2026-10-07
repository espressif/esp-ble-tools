# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Recording shutdown through real processes with controlled IO stalls."""

from __future__ import annotations

import multiprocessing
import time
from functools import partial
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import CaptureFinished, CaptureVerdict, StatsUpdated, TransportConfig, TransportMode
from src.frontend.capture_session import CaptureSession
from src.i18n import ENGLISH, get_language, set_language

from tests.helpers import BytesReader
from tests.io_shutdown_probe import run_stalled_io, shutdown_frames

scenarios("features/recording_shutdown.feature")


def _poll_until(recording: SimpleNamespace, predicate: Any, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        recording.messages.extend(recording.session.poll())
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("recording did not reach the expected state")


@pytest.fixture
def recording(tmp_path: Path):
    language = get_language()
    set_language(ENGLISH)
    state = SimpleNamespace(tmp_path=tmp_path, session=None, release=None, now=0.0, messages=[])
    yield state
    try:
        if state.session is not None:
            pipeline = state.session._pipeline
            # A terminated Event waiter cannot acknowledge notify_all().
            # Never reuse its semaphore after the watchdog killed that process.
            if pipeline.io_is_alive():
                state.release.set()
            pipeline.stop()
            deadline = time.monotonic() + 10
            while (pipeline.io_is_alive() or pipeline.analysis_is_alive()) and time.monotonic() < deadline:
                pipeline.drain_events()
                time.sleep(0.01)
            for process in (pipeline._io_process, pipeline._analysis_process):
                if process is not None:
                    if process.is_alive():
                        process.terminate()
                        process.join(1)
                    if process.is_alive():
                        process.kill()
                        process.join(1)
                    assert not process.is_alive(), "test left a capture process running"
            for queue in (
                pipeline._parse_queue,
                pipeline._raw_stats_queue,
                pipeline._ui_queue,
                pipeline._command_queue,
            ):
                queue.close()
                queue.join_thread()
    finally:
        set_language(language)


@given(parsers.parse("文件{operation}停滞且第一帧已保存"))
def stalled_file(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    assert operation in ("写入", "同步")
    _start_stalled(recording, monkeypatch, "write" if operation == "写入" else "fsync")


@given("Transport 接收停滞且第一帧已保存")
def stalled_receive(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _start_stalled(recording, monkeypatch, "read")


def _start_stalled(recording: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    frames = shutdown_frames()
    recording.expected_saved_bytes = frames[0] if stage in ("read", "write") else b"".join(frames)
    ctx = multiprocessing.get_context("spawn")
    blocked = ctx.Event()
    recording.release = ctx.Event()
    monkeypatch.setattr(
        "src.backend.pipeline.controller.run_io_process",
        partial(run_stalled_io, blocked=blocked, release=recording.release, stage=stage),
    )
    monkeypatch.setattr(
        "src.backend.pipeline.controller.create_transport_reader", lambda config: BytesReader(b"", Event())
    )
    recording.session = CaptureSession(
        TransportConfig(TransportMode.USB_OUTPUT, "replay", "replay"),
        recording.tmp_path / "recording.bin",
        clock=lambda: recording.now,
    )
    recording.session._pipeline._ctx = ctx
    assert recording.session.start() == ()
    assert blocked.wait(10), "file operation did not reach the injected stall"
    _poll_until(recording, lambda: bool(recording.session.saved_capture_paths))
    if stage == "read":
        # A real parser has handled the first frame and waits for more input.
        _poll_until(
            recording,
            lambda: any(
                isinstance(message, StatsUpdated) and message.stats.transport.rx_frames == 1
                for message in recording.messages
            ),
        )
        assert recording.session._pipeline.analysis_is_alive()
    else:
        # Analysis consumes accepted input, even though the second raw write may be pending.
        _poll_until(recording, lambda: not recording.session._pipeline.analysis_is_alive())
    assert (recording.tmp_path / "recording.bin").read_bytes().startswith(shutdown_frames()[0])


@when("用户停止录制")
def stop(recording: SimpleNamespace) -> None:
    recording.session.stop()


@when("停止等待尚未到期")
def before_deadline(recording: SimpleNamespace) -> None:
    recording.now = 19.9
    recording.messages.extend(recording.session.poll())
    # A repeated Stop must not reset the original deadline.
    recording.session.stop()


@when("停止等待到期")
def at_deadline(recording: SimpleNamespace) -> None:
    recording.now = 20.0
    recording.messages.extend(recording.session.poll())
    assert recording.session.finished, "IO shutdown deadline did not finish the recording"


@when("通过 pipeline 等待停止期限到期")
def wait_at_deadline(recording: SimpleNamespace) -> None:
    recording.now = 20.0
    completed = Event()
    errors: list[Exception] = []

    def wait() -> None:
        try:
            recording.session._pipeline.wait_with_events(None)
        except Exception as error:
            errors.append(error)
        finally:
            completed.set()

    waiter = Thread(target=wait)
    waiter.start()
    try:
        assert completed.wait(5), "pipeline wait ignored the IO shutdown deadline"
    finally:
        if not completed.is_set():
            recording.release.set()
        waiter.join(10)
        assert not waiter.is_alive(), "test left a pipeline waiter running"
    assert not errors
    recording.messages.extend(recording.session.poll())
    assert recording.session.finished


@when("Reader 已结束读取而用户没有额外停止")
def reader_finished(recording: SimpleNamespace) -> None:
    assert not recording.session.finished
    assert recording.session._pipeline.io_is_alive()


@when("文件操作在期限内恢复")
def recover(recording: SimpleNamespace) -> None:
    recording.release.set()
    _poll_until(recording, lambda: recording.session.finished)


@then("录制尚未完成且 IO process 仍在运行")
def still_finalizing(recording: SimpleNamespace) -> None:
    assert not recording.session.finished
    assert recording.session._pipeline.io_is_alive()
    assert not any(isinstance(message, CaptureFinished) for message in recording.messages)


@then("报告不确认原始数据完整保存并建议重录")
def unsafe_report(recording: SimpleNamespace) -> None:
    report = recording.session.report
    assert not report.raw_complete
    assert report.verdict is CaptureVerdict.RECAPTURE
    assert sum(isinstance(message, CaptureFinished) for message in recording.messages) == 1
    assert report.report_path.is_file()
    assert recording.session.poll() == ()


@then("报告记录 IO 停止超时")
def timeout_reported(recording: SimpleNamespace) -> None:
    assert any("did not finish within 20 seconds" in error for error in recording.session.report.errors)


@then("之前保存的原始字节仍可读取")
def prefix_retained(recording: SimpleNamespace) -> None:
    assert recording.session.report.raw_paths == (recording.tmp_path / "recording.bin",)
    assert recording.session.report.raw_paths[0].read_bytes() == recording.expected_saved_bytes


@then("报告确认原始数据完整保存且可用于分析")
def complete_report(recording: SimpleNamespace) -> None:
    assert recording.session.report.raw_complete
    assert recording.session.report.verdict is CaptureVerdict.READY
    assert not recording.session.report.errors


@then("所有已接受的原始字节均可读取")
def all_bytes_retained(recording: SimpleNamespace) -> None:
    assert (recording.tmp_path / "recording.bin").read_bytes() == b"".join(shutdown_frames())


@then("IO 和 Analysis processes 都已退出")
def processes_stopped(recording: SimpleNamespace) -> None:
    assert not recording.session._pipeline.io_is_alive()
    assert not recording.session._pipeline.analysis_is_alive()
