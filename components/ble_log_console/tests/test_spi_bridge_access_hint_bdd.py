# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/spi_bridge_access_hint.feature.

The observed path is the shipped one: the `ports` subcommand prints whatever the
SPI transport scan reports. Only the pyusb enumeration is faked.
"""

from __future__ import annotations

import errno
from types import SimpleNamespace
from typing import Any

import pytest
import usb.core
from click.testing import CliRunner
from console import cli
from pytest_bdd import given, parsers, scenarios, then, when
from src.i18n import set_language

from tests.helpers import usb_bridge_device, usb_bridge_unreadable_configuration

scenarios("features/spi_bridge_access_hint.feature")


@pytest.fixture(autouse=True)
def english_output() -> Any:
    """The assertions read the shipped English catalog; Chinese is unit-tested."""
    set_language("en")
    yield
    set_language("en")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(
        "src.backend.support.transport.spi_usb_bridge_transport._is_windows",
        lambda: False,
    )
    return SimpleNamespace(devices=None, find_error=None, output="")


@given(parsers.parse("系统上有一个 bus 为 {bus:d}、addr 为 {address:d} 的 SPI Bridge"), target_fixture="world")
def one_bridge(world: SimpleNamespace, bus: int, address: int) -> SimpleNamespace:
    world.devices = [usb_bridge_device(bus=bus, address=address)]
    return world


@given("这个 SPI Bridge 因为缺少权限而打不开", target_fixture="world")
def bridge_without_permission(world: SimpleNamespace) -> SimpleNamespace:
    world.devices = [
        usb_bridge_device(bus=1, address=8, open_error=usb.core.USBError("Access denied", errno=errno.EACCES))
    ]
    return world


@given("这个 SPI Bridge 读配置里的接口时报 I/O 错误", target_fixture="world")
def bridge_endpoints_unreadable(world: SimpleNamespace) -> SimpleNamespace:
    world.devices = [usb_bridge_device(bus=1, address=8, configuration=usb_bridge_unreadable_configuration())]
    return world


@given("枚举 USB 设备时没有可用的 libusb 后端", target_fixture="world")
def no_libusb_backend(world: SimpleNamespace) -> SimpleNamespace:
    world.find_error = usb.core.NoBackendError("No backend available")
    return world


@given("系统上没有挂 SPI Bridge", target_fixture="world")
def no_bridge(world: SimpleNamespace) -> SimpleNamespace:
    world.devices = []
    return world


@when("列出 SPI 模式的端口")
def list_spi_ports(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_find(**_kwargs: object) -> list[Any]:
        if world.find_error is not None:
            raise world.find_error
        return world.devices or []

    monkeypatch.setattr("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find", fake_find)
    result = CliRunner().invoke(cli, ["ports", "--mode", "spi"])
    assert result.exit_code == 0, result.output
    world.output = result.output


@then(parsers.parse('输出显示 "{text}"'))
def output_shows(world: SimpleNamespace, text: str) -> None:
    assert text in world.output, world.output


@then(parsers.parse('输出列出端点 "{text}"'))
def output_lists_endpoint(world: SimpleNamespace, text: str) -> None:
    assert text in world.output, world.output


@then("输出说明没有 USB 访问权限，并给出用 sudo 运行一次工具的办法")
def output_explains_permission(world: SimpleNamespace) -> None:
    assert (
        "  SPI Bridge (bus 1, addr 8): no USB access permission. "
        "Run this tool once with sudo (no arguments), then replug the bridge.\n"
    ) in world.output, world.output


@then(parsers.parse('输出原样给出设备报告的 "{text}"'))
def output_repeats_device_error(world: SimpleNamespace, text: str) -> None:
    assert text in world.output, world.output


@then("输出说明缺少 libusb-1.0")
def output_explains_libusb(world: SimpleNamespace) -> None:
    assert "  libusb-1.0 not found. Install it first: sudo apt install libusb-1.0-0\n" in world.output, world.output


@then("输出只字不提 USB 权限或 libusb")
def output_silent_about_causes(world: SimpleNamespace) -> None:
    assert "access permission" not in world.output, world.output
    assert "libusb" not in world.output, world.output
