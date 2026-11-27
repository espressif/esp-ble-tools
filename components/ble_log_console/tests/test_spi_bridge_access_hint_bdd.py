# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Observe CDC diagnostics through the CLI, without opening hardware."""

from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from console import cli
from pytest_bdd import given, scenarios, then, when

scenarios("features/spi_bridge_access_hint.feature")


@pytest.fixture
def world(monkeypatch, linux_serial_platform):
    state = SimpleNamespace(devices=[], denied=set(), error=None)
    monkeypatch.setattr("src.i18n._language", "en")

    def ports():
        if state.error:
            raise state.error
        return [SimpleNamespace(device=device, vid=0x303A, pid=0x4001) for device in state.devices]

    monkeypatch.setattr("serial.tools.list_ports.comports", ports)
    monkeypatch.setattr(
        "src.backend.support.transport.serial_reader.os.access", lambda device, mode: device not in state.denied
    )
    return state


@given("系统枚举 SPI Bridge CDC 端口但用户没有读写权限")
def denied(world):
    world.devices = ["/dev/ttyACM0"]
    world.denied = set(world.devices)


@given("系统同时枚举可用和无权限的 SPI Bridge CDC 端口")
def mixed(world):
    denied(world)
    world.devices.append("/dev/ttyACM1")


@given("系统上没有挂 SPI Bridge")
def absent(world):
    world.devices = []


@given("系统枚举可用 SPI Bridge CDC 端口且 libusb 不可用")
def no_libusb(world, monkeypatch):
    world.devices = ["/dev/ttyACM1"]

    def fail(**kwargs):
        raise AssertionError("CDC must not use libusb")

    monkeypatch.setattr("usb.core.find", fail)


@given("串口枚举发生 I/O 错误")
def failed_enumeration(world):
    world.error = OSError(5, "Input/output error")


@when("列出 SPI 模式的端口")
def list_ports(world):
    result = CliRunner().invoke(cli, ["ports", "--mode", "spi"])
    assert result.exit_code == 0, result.output
    world.output = result.output


@then("输出说明 CDC 端口没有权限并给出 dialout 提示")
def permission_hint(world):
    assert "SPI Bridge /dev/ttyACM0: no read/write permission." in world.output
    assert "dialout" in world.output
    assert "--port cdc:/dev/ttyACM0" not in world.output


@then("输出列出可用 CDC 端口并说明另一端口的权限问题")
def mixed_hint(world):
    permission_hint(world)
    assert "--port cdc:/dev/ttyACM1" in world.output


@then("输出为空且不提示权限或 libusb")
def no_hint(world):
    assert "(none)" in world.output
    assert "permission" not in world.output
    assert "libusb" not in world.output


@then("输出列出可用 CDC 端口且没有安装 libusb 的提示")
def cdc_only(world):
    assert "--port cdc:/dev/ttyACM1" in world.output
    assert "libusb" not in world.output


@then("输出说明枚举失败且保留原始错误")
def error_hint(world):
    assert "Failed to list endpoints:" in world.output
    assert "Input/output error" in world.output
