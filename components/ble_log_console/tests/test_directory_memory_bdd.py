# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from pytest_bdd import given, scenarios, then, when
from src.app import BLELogApp
from src.backend.support.transport.base import PortScan
from textual.widgets import Input, Select

scenarios("features/directory_memory.feature")


@given("用户在设置页选择包含中文和空格的录制目录", target_fixture="directory_world")
def directory_world(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_scan", lambda mode: PortScan(options=[("test", "test")])
    )
    return SimpleNamespace(directory=tmp_path / "日志 recording", tmp_path=tmp_path)


@when("用户点击连接开始录制并关闭工具")
def record(directory_world):
    async def run():
        with patch("src.frontend.capture_session.CapturePipeline") as pipeline:
            pipeline.return_value.drain_events.return_value = []
            pipeline.return_value.check_io_shutdown.return_value = []
            pipeline.return_value.io_is_alive.return_value = True
            app = BLELogApp()
            async with app.run_test(size=(120, 55)) as pilot:
                app.screen.query_one("#dir-input", Input).value = directory_world.directory.name
                app.screen.query_one("#port-select", Select).value = "test"
                await pilot.click("#connect-btn")
                await pilot.pause()
                pipeline.return_value.start.assert_called_once()
                assert not app._capture_session.finished

    asyncio.run(run())


@then("从其他工作目录重新打开工具仍显示上次录制目录")
def reopen(directory_world, monkeypatch):
    other = directory_world.tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    async def run():
        async with BLELogApp().run_test(size=(120, 55)) as pilot:
            await pilot.pause()
            assert pilot.app.screen.query_one("#dir-input", Input).value == str(directory_world.directory)

    asyncio.run(run())
