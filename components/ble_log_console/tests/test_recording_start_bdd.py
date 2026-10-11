# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
import errno
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.app import BLELogApp
from src.backend.support.transport.registry import list_transport_port_options
from src.frontend.capture_session import CaptureSession
from src.frontend.launch_screen import LaunchScreen
from src.frontend.log_view import LogView
from src.frontend.status_panel import StatusPanel
from textual.widgets import Button, Input, Select

scenarios("features/recording_start.feature")


@pytest.fixture
def start_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setattr("src.i18n._language", "en")
    monkeypatch.setattr("src.frontend.launch_screen.list_transport_port_options", lambda mode: [("other", "other")])
    runner = asyncio.Runner()
    world = SimpleNamespace(tmp_path=tmp_path, runner=runner, run=None, app=None)
    with (
        patch("src.app.CaptureSession", wraps=CaptureSession) as session_type,
        patch("src.frontend.capture_session.CapturePipeline") as pipeline_type,
    ):
        world.session_type = session_type
        world.pipeline_type = pipeline_type
        pipeline_type.return_value.io_is_alive.return_value = True
        pipeline_type.return_value.drain_events.return_value = []
        try:
            yield world
        finally:
            try:
                if world.run is not None:
                    runner.run(world.run.__aexit__(None, None, None))
            finally:
                runner.close()


def _recording_state(app: BLELogApp) -> dict[str, object]:
    button = app.query_one("#stop-review", Button)
    panel = app.query_one(StatusPanel)
    return {
        "output_path": app._output_path,
        "raw_path": app.saved_capture_path,
        "raw_paths": app.saved_capture_paths,
        "console_path": app.saved_console_log_path,
        "console_paths": app.saved_console_log_paths,
        "report_path": app.saved_report_path,
        "report": app._capture_report,
        "session": app._capture_session,
        "finalizing": app._finalizing,
        "log_rows": tuple(row.text for row in app.query_one(LogView).lines),
        "stop_disabled": button.disabled,
        "stop_label": str(button.label),
        "stats": asdict(panel.stats),
        "disconnected": panel.disconnected,
        "panel_finalizing": panel.finalizing,
    }


def _pause(world: SimpleNamespace) -> None:
    world.runner.run(world.pilot.pause())
    if world.app._exception is not None:
        raise world.app._exception


@when("用户在设置页按 q")
def cancel_setup(start_world: SimpleNamespace) -> None:
    start_world.runner.run(start_world.pilot.press("q"))
    _pause(start_world)


@then("程序正常退出，保留先前录制路径和文件")
def cancel_keeps_recording(start_world: SimpleNamespace) -> None:
    world = start_world
    assert world.app._exception is None and not world.app.is_running
    assert world.app.saved_capture_paths == world.before["raw_paths"]
    assert world.app.saved_console_log_paths == world.before["console_paths"]
    assert world.app.saved_report_path == world.before["report_path"]
    assert all(path.read_bytes() == data for path, data in world.files.items())
    assert world.session_type.call_count == world.initial_count


@given("初始 UART 端口发现被拒绝")
def initial_discovery_refused(start_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_discovery():
        raise PermissionError(errno.EACCES, "discovery [refused]")

    monkeypatch.setattr("serial.tools.list_ports.comports", refuse_discovery)
    monkeypatch.setattr("src.frontend.launch_screen.list_transport_port_options", list_transport_port_options)


@when("用户打开设置页")
def open_fresh_setup(start_world: SimpleNamespace) -> None:
    world = start_world
    world.app = BLELogApp(log_dir=world.tmp_path)
    world.run = world.app.run_test(size=(120, 55))
    world.pilot = world.runner.run(world.run.__aenter__())
    _pause(world)
    world.before = _recording_state(world.app)
    world.files = {}
    world.initial_count = 0


@when(parsers.parse("用户将显示语言切换为 {language}"))
def select_setup_language(start_world: SimpleNamespace, language: str) -> None:
    start_world.app.screen.query_one("#language-select", Select).value = language
    _pause(start_world)
    start_world.language = language


@then("设置控件已经挂载，Refresh 后空端口仍不能开始录制")
def fresh_setup_rejects_blank_port(start_world: SimpleNamespace) -> None:
    world = start_world
    screen = world.app.screen
    assert isinstance(screen, LaunchScreen)
    assert screen.query_one("#dir-input", Input).value == str(world.tmp_path)
    assert screen.query_one("#port-select", Select).is_blank()
    world.runner.run(world.pilot.click("#refresh-btn"))
    _pause(world)
    assert screen.query_one("#port-select", Select).is_blank()
    world.runner.run(world.pilot.click("#connect-btn"))
    _pause(world)
    assert world.app.screen is screen
    assert world.session_type.call_count == world.pipeline_type.call_count == 0
    expected = {"en": "Please select a port", "zh_CN": "请选择端口"}[world.language]
    assert expected in [notification.message for notification in world.app._notifications]
