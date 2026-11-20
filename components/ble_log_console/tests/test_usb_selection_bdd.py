# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import TransportConfig, TransportMode
from src.frontend.launch_screen import LaunchScreen
from textual.app import App
from textual.widgets import Select

scenarios("features/usb_selection.feature")


@pytest.fixture
def world(monkeypatch, tmp_path):
    opened = Mock(side_effect=AssertionError("Enumeration must not open a serial port"))
    monkeypatch.setattr("serial.Serial", opened)
    return SimpleNamespace(opened=opened, default=None, results=[], log_dir=tmp_path)


@given("系统同时枚举 USB OTG、USJ 和 SPI Bridge")
def mixed_ports(world, monkeypatch):
    ports = [
        SimpleNamespace(device="/dev/ttyACM0", vid=0x303A, pid=0x10B1, product="BLE-Log-Port (ESP32-S3)"),
        SimpleNamespace(device="/dev/ttyACM1", vid=0x303A, pid=0x1001, product="USB JTAG/serial debug"),
        SimpleNamespace(device="/dev/ttyACM2", vid=0x303A, pid=0x4001, product="SPI-BRIDGE"),
    ]
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: ports)


@given("默认录制配置是暂时未枚举到的 USJ 端口")
def missing_usj(world, monkeypatch):
    world.default = TransportConfig(mode=TransportMode.USJ, port="/dev/ttyACM1", label="USJ /dev/ttyACM1")
    monkeypatch.setattr("serial.tools.list_ports.comports", list)


def drive_selection(world, port=None):
    class LaunchApp(App):
        def on_mount(self):
            self.push_screen(
                LaunchScreen(default_log_dir=world.log_dir, default_transport_config=world.default),
                callback=world.results.append,
            )

    async def drive():
        app = LaunchApp()
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            mode = app.screen.query_one("#mode-select", Select)
            assert [value for _, value in mode._options if value is not Select.NULL] == ["uart", "spi", "usb"]
            if port is not None:
                mode.value = "usb"
                await pilot.pause()
            assert mode.value == "usb"
            assert not app.screen.query_one("#baud-select", Select).display
            await pilot.click("#refresh-btn")
            await pilot.pause()
            ports = app.screen.query_one("#port-select", Select)
            if port is not None:
                options = [(str(label), value) for label, value in ports._options if value is not Select.NULL]
                assert options == [
                    ("USB OTG  /dev/ttyACM0 (ESP32-S3)", "/dev/ttyACM0"),
                    ("USJ  /dev/ttyACM1", "/dev/ttyACM1"),
                ]
                ports.value = port
            else:
                assert ports.value == "/dev/ttyACM1"
            await pilot.click("#connect-btn")
            await pilot.pause()

    asyncio.run(drive())


@when(parsers.parse("在统一 USB 列表刷新并选择 {port}"))
def select_usb(world, port):
    drive_selection(world, port)


@when("在统一 USB 设置页重试连接")
def retry_usb(world):
    drive_selection(world)


@then(parsers.parse("连接使用 {mode} 且枚举没有打开串口"))
def correct_transport(world, mode):
    assert len(world.results) == 1
    assert world.results[0].transport_config.mode is TransportMode(mode)
    world.opened.assert_not_called()
