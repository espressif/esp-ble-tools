# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/console_text.feature."""

from __future__ import annotations

import asyncio
import errno
import multiprocessing
import os
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.app import BLELogApp
from src.backend.models import (
    BleLogSource,
    CaptureFinished,
    CaptureVerdict,
    TransportMode,
)
from src.backend.support.transport.spi_usb_bridge_transport import CDC_ENDPOINT_PREFIX
from src.frontend.capture_events import CaptureEventPresenter, _default_text_file_factory
from src.frontend.capture_report import (
    CaptureReportScreen,
)
from src.frontend.log_view import LogView
from textual.pilot import Pilot
from textual.widgets import Button

from tests.helpers import build_frame, xor_checksum

scenarios("features/console_text.feature")


REDIR_LINE = b"I (900) app: forwarded through BLE Log\n"


MODES = {mode.name: mode for mode in TransportMode}


def _frame(payload: bytes, source: int, sn: int) -> bytes:
    return build_frame(payload, source, sn, xor_checksum)


def _redir_frames(count: int) -> bytes:
    return b"".join(_frame(REDIR_LINE, BleLogSource.REDIR, sn) for sn in range(count))


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(tmp_path=tmp_path, mode=TransportMode.UART, chunks=[], live=[], records=[])


def _set_stream(world: SimpleNamespace, mode: str, chunks: list[bytes]) -> SimpleNamespace:
    world.mode = MODES[mode]
    world.chunks = chunks
    world.data = b"".join(chunks)
    return world


def _rendered_rows(app: BLELogApp) -> list[str]:
    return [strip.text.rstrip() for strip in app.query_one(LogView).lines]


@given(parsers.parse("一个 {mode} 端口分两次输出转发日志帧"), target_fixture="world")
def redir_in_two_phases(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    first = b"".join(_frame(b"BEFORE SYNC\n", BleLogSource.REDIR, sn) for sn in range(3))
    later = b"".join(_frame(b"AFTER SYNC\n", BleLogSource.REDIR, sn) for sn in range(3, 6))
    world.phases = [
        (first, lambda app: sum("BEFORE SYNC" in row for row in _rendered_rows(app)) == 3),
        (later, lambda app: sum("AFTER SYNC" in row for row in _rendered_rows(app)) == 3),
    ]
    return _set_stream(world, mode, [first, later])


@given(parsers.parse("console.log 在{operation}时同步返回 I/O 错误"))
def console_sync_fails(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    parent_pid = os.getpid()
    real_fsync = os.fsync
    world.sync_files = []
    world.sync_paths = []
    world.sync_hits = []
    world.sync_error = "[Errno 5] console sync refused"
    world.double_failure = getattr(world, "double_failure", False)
    world.close_hits = []
    world.rotating = operation == "切换分片"
    world.child_pids = {process.pid for process in multiprocessing.active_children()}

    def factory(path):
        world.sync_paths.append(path)
        file = _default_text_file_factory(path)
        if world.double_failure:

            class CloseFailure:
                def __getattr__(self, name):
                    return getattr(file, name)

                def close(self):
                    file.close()
                    world.close_hits.append(path)
                    if len(world.close_hits) == 1:
                        raise OSError(errno.ENOSPC, "secondary console close failure")

            sink = CloseFailure()
        else:
            sink = file
        world.sync_files.append(sink)
        return sink

    def sync(fd):
        if os.getpid() == parent_pid and any(not file.closed and file.fileno() == fd for file in world.sync_files):
            world.sync_hits.append(fd)
            raise OSError(errno.EIO, "console sync refused")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(
        "src.frontend.capture_session.CaptureEventPresenter",
        partial(CaptureEventPresenter, text_file_factory=factory, console_part_max_bytes=1 if world.rotating else 1024),
    )


@given(parsers.parse("console.log 在{operation}时先同步失败，随后关闭返回不同错误"))
def console_sync_and_close_fail(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    world.double_failure = True
    console_sync_fails(world, monkeypatch, operation)


@when("Console 界面通过独立进程从虚拟串口录制这段数据，然后停止并查看报告")
def record_in_app(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    pty = pytest.importorskip("pty", reason="POSIX-only virtual terminal")
    import tty

    monkeypatch.setattr("src.i18n._language", "en")
    master_fd, slave_fd = pty.openpty()
    tty.setraw(slave_fd)
    port = os.ttyname(slave_fd)
    if world.mode is TransportMode.SPI_USB_BRIDGE:
        port = f"{CDC_ENDPOINT_PREFIX}{port}"
    app = BLELogApp(mode=world.mode, port=port, baudrate=115_200, log_dir=world.tmp_path / "app")

    async def drive() -> None:
        async with app.run_test(size=(140, 40)) as pilot:

            async def wait_for(predicate: Any, what: str, timeout: float = 15.0) -> None:
                deadline = time.monotonic() + timeout
                while not predicate():
                    if app._exception is not None:
                        raise app._exception
                    if time.monotonic() > deadline:
                        raise AssertionError(f"timed out waiting for {what}: {_rendered_rows(app)[-12:]}")
                    await pilot.pause(0.05)

            stop = app.query_one("#stop-review", Button)
            try:
                await wait_for(lambda: not stop.disabled, "recording start")
                # Opening the port discards whatever it already buffered, so the first write has to
                # wait for the reader process to report the port as connected.
                await wait_for(lambda: any("Connected to" in row for row in _rendered_rows(app)), "reader open")
                for index, (data, ready) in enumerate(world.phases):
                    os.write(master_fd, data)
                    await wait_for(lambda ready=ready: ready(app), f"phase {index}")
            finally:
                world.running_before_stop = (
                    app._capture_session.is_running and app._capture_session._pipeline.io_is_alive()
                )
                if app._exception is None:
                    if not stop.disabled:
                        await pilot.click("#stop-review")
                    await wait_for(lambda: app.saved_report_path is not None, "report after Stop & Review", 40.0)
                    await wait_for(
                        lambda: (
                            isinstance(app.screen, CaptureReportScreen)
                            and any(widget.is_mounted for widget in app.screen.query("#capture-report-verdict"))
                        ),
                        "mounted recording report",
                    )
            world.rendered = _rendered_rows(app)
            world.session = app._capture_session

    try:
        asyncio.run(drive())
    finally:
        os.close(master_fd)
        os.close(slave_fd)
    world.app = SimpleNamespace(
        raw=b"".join(path.read_bytes() for path in app.saved_capture_paths),
        console_log_paths=app.saved_console_log_paths,
        report_text=app.saved_report_path.read_text(encoding="utf-8"),
    )


@then("界面录制保存的原始数据与发送的字节完全一致")
def app_raw_exact(world: SimpleNamespace) -> None:
    assert world.app.raw == world.data


@then("同步失败只警告一次，保留首个错误且不再打开日志分片")
def app_sync_failure_visible_once(world: SimpleNamespace) -> None:
    notices = [index for index, row in enumerate(world.rendered) if "Console log could not be saved" in row]
    assert len(notices) == 1 and world.sync_error in world.rendered[notices[0]]
    assert len(world.sync_hits) == 1 and len(world.sync_paths) == 1
    assert all(file.closed for file in world.sync_files)
    if world.double_failure:
        assert world.close_hits
        assert "secondary console close failure" not in world.app.report_text
    if world.rotating:
        assert sum("AFTER SYNC" in row for row in world.rendered[notices[0] :]) == 3
    report = world.session.report
    assert report.console_log_error == world.sync_error
    assert report.verdict is CaptureVerdict.WARNING and report.raw_complete and report.parser_complete
    assert report.errors == ()
    assert world.running_before_stop
    assert world.session.finished and not world.session._pipeline.is_alive()
    assert world.session._event_presenter.finish() == ()
    assert world.session._event_presenter.state.console_log_error == world.sync_error
    assert {process.pid for process in multiprocessing.active_children()} == world.child_pids
    assert "Console log error: " + world.sync_error in world.app.report_text
    assert "this error does not itself stop raw recording" in world.app.report_text
    saved = world.sync_paths[0].read_text(encoding="utf-8")
    assert "BEFORE SYNC" in saved
    assert ("AFTER SYNC" in saved) is not world.rotating


def test_record_in_app_observes_mounted_report_after_saved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deferred = []
    post_message = BLELogApp.post_message
    pause = Pilot.pause
    rendered_rows = _rendered_rows
    snapshots = []

    def defer_finished(app, message):
        if isinstance(message, CaptureFinished):
            deferred.append((app, message))
            return True
        return post_message(app, message)

    async def deliver_on_next_pause(pilot, *args, **kwargs):
        while deferred:
            app, message = deferred.pop(0)
            post_message(app, message)
        await pause(pilot, *args, **kwargs)

    def observe_rows(app):
        if app.saved_report_path is not None:
            assert isinstance(app.screen, CaptureReportScreen), "saved path precedes report message delivery"
            assert app.screen.query_one("#capture-report-verdict").is_mounted
            snapshots.append(app.saved_report_path)
        return rendered_rows(app)

    monkeypatch.setattr(BLELogApp, "post_message", defer_finished)
    monkeypatch.setattr(Pilot, "pause", deliver_on_next_pause)
    monkeypatch.setattr(__name__ + "._rendered_rows", observe_rows)
    world = SimpleNamespace(
        tmp_path=tmp_path,
        mode=TransportMode.UART,
        phases=[
            (_redir_frames(3), lambda app: sum("forwarded through BLE Log" in row for row in _rendered_rows(app)) == 3)
        ],
    )

    record_in_app(world, monkeypatch)

    assert len(snapshots) == 1
    assert world.app.raw == _redir_frames(3)
    assert world.session.finished and not world.session._pipeline.is_alive()
