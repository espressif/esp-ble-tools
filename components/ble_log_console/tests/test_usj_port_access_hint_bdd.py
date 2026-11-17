# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/usj_port_access_hint.feature.

The observed path is the shipped one: the `ports` subcommand prints whatever the
USJ transport scan reports. Only pyserial's enumeration and the permission check
are faked; nothing opens a device.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner
from console import cli
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.support.transport.usj_transport import PRODUCT_ID, VENDOR_ID
from src.i18n import set_language

scenarios("features/usj_port_access_hint.feature")

_COMPORTS = "serial.tools.list_ports.comports"
_CAN_OPEN = "src.backend.support.transport.serial_reader.os.access"


def _usj_serial_port(device: str) -> SimpleNamespace:
    return SimpleNamespace(device=device, vid=VENDOR_ID, pid=PRODUCT_ID)


@pytest.fixture(autouse=True)
def english_output() -> Any:
    """The assertions read the shipped English catalog; Chinese is unit-tested."""
    set_language("en")
    yield
    set_language("en")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    namespace = SimpleNamespace(devices=[], can_open=True, output="")
    monkeypatch.setattr(_COMPORTS, lambda: list(namespace.devices))
    # The decision under test is what the scan reports; whether a real tty node
    # is readable is the operating system's answer, not a portable test fixture.
    monkeypatch.setattr(_CAN_OPEN, lambda device, mode: namespace.can_open)
    return namespace


@given(parsers.parse('系统上有一个 USJ 端口 "{device}"'), target_fixture="world")
def one_usj_port(world: SimpleNamespace, device: str) -> SimpleNamespace:
    world.devices = [_usj_serial_port(device)]
    return world


@given("当前用户不能读写这个 USJ 端口", target_fixture="world")
def port_without_permission(world: SimpleNamespace) -> SimpleNamespace:
    world.can_open = False
    return world


@given("系统上没有挂 USJ 设备", target_fixture="world")
def no_usj_device(world: SimpleNamespace) -> SimpleNamespace:
    world.devices = []
    return world


@when("列出 USJ 模式的端口")
def list_usj_ports(world: SimpleNamespace) -> None:
    result = CliRunner().invoke(cli, ["ports", "--mode", "usj"])
    assert result.exit_code == 0, result.output
    world.output = result.output


@then(parsers.parse('输出显示 "{text}"'))
def output_shows(world: SimpleNamespace, text: str) -> None:
    assert text in world.output, world.output


@then(parsers.parse('输出列出端点 "{text}"'))
def output_lists_endpoint(world: SimpleNamespace, text: str) -> None:
    assert text in world.output, world.output


@then("输出说明该端口没有读写权限，并给出把用户加入 dialout 组的办法")
def output_explains_permission(world: SimpleNamespace) -> None:
    assert ("USJ /dev/ttyACM1: no read/write permission.") in world.output, world.output
    assert "dialout" in world.output


@then("输出只字不提读写权限或 dialout")
def output_silent_about_permissions(world: SimpleNamespace) -> None:
    assert "permission" not in world.output, world.output
    assert "dialout" not in world.output, world.output
