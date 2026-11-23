# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from pytest_bdd import given, scenarios, then, when
from src.app import BLELogApp
from src.backend.support.transport.base import PortScan
from textual.widgets import Input, Select

from tests.test_host_logs import make_database

scenarios("features/database_memory.feature")


@given("用户有一份有效 Host 字典", target_fixture="world")
def dictionary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_scan", lambda mode: PortScan(options=[("test", "test")])
    )
    return SimpleNamespace(database=make_database(tmp_path), log_dir=tmp_path / "logs")


def reopen(world, value, *, connect=True):
    async def run():
        with patch("src.frontend.capture_session.CapturePipeline") as pipeline:
            pipeline.return_value.io_is_alive.return_value = True
            pipeline.return_value.drain_events.return_value = []
            pipeline.return_value.check_io_shutdown.return_value = []
            app = BLELogApp(log_dir=world.log_dir)
            async with app.run_test(size=(100, 50)) as pilot:
                app.screen.query_one("#database-input", Input).value = value
                if connect:
                    await pilot.click("#connect-btn")
                    await pilot.pause()
                    assert app._capture_session is not None
                    assert not app._capture_session.finished
                else:
                    await pilot.press("escape")
                    app.exit()
            reopened = BLELogApp(log_dir=world.log_dir)
            async with reopened.run_test(size=(100, 50)):
                world.restored = reopened.screen.query_one("#database-input", Input).value

    asyncio.run(run())


@when("用户选择字典并成功开始录制后重新打开程序")
def remember(world):
    reopen(world, str(world.database))


@when("用户清空字典并成功开始录制后重新打开程序")
def clear(world):
    reopen(world, "")


@when("用户修改字典但取消设置后重新打开程序")
def cancel(world):
    reopen(world, "", connect=False)


@then("字典输入框恢复上次的目录")
def restored(world):
    assert world.restored == str(world.database)


@then("字典输入框为空")
def empty(world):
    assert world.restored == ""


@when("用户点击连接但所选端口已消失")
def connect_missing_port(world, monkeypatch):
    missing = str(world.log_dir.parent / "missing-tty")
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_scan", lambda mode: PortScan(options=[(missing, missing)])
    )
    # Use paths distinct from both automatic defaults.
    world.database = world.database.rename(world.database.with_name("chosen-db"))
    world.log_dir = world.log_dir.with_name("chosen-logs")

    async def run():
        app = BLELogApp()
        async with app.run_test(size=(100, 50)) as pilot:
            app.screen.query_one("#mode-select", Select).value = "usb"
            await pilot.pause()
            app.screen.query_one("#dir-input", Input).value = str(world.log_dir)
            app.screen.query_one("#database-input", Input).value = str(world.database)
            await pilot.click("#connect-btn")
            async with asyncio.timeout(10):
                while app.capture_report is None:
                    await asyncio.sleep(0.05)
            assert any(missing in error for error in app.capture_report.errors)

    asyncio.run(run())


@then("重启后恢复确认的保存目录和字典")
def failed_connection_paths(world):
    async def run():
        async with BLELogApp().run_test(size=(100, 50)) as pilot:
            assert pilot.app.screen.query_one("#dir-input", Input).value == str(world.log_dir)
            assert pilot.app.screen.query_one("#database-input", Input).value == str(world.database)

    asyncio.run(run())
