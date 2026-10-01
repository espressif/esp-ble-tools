# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/usb_output.feature."""

from __future__ import annotations

import errno
from types import SimpleNamespace

import pytest
import serial
from console import _parse_transport_mode
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import TransportMode
from src.backend.support.transport import usb_output_transport
from src.backend.support.transport.usb_output_transport import UsbOutputTransport
from src.frontend.launch_screen import _mode_select_value

from tests.helpers import SerialHandleStub

scenarios("features/usb_output.feature")

_SERIAL_CONSTRUCTOR = "src.backend.support.transport.serial_reader.serial.Serial"

_OPEN_FAILURES = {
    "权限不足": serial.SerialException(errno.EACCES, "Permission denied"),
    "端口被占用": serial.SerialException(errno.EBUSY, "Device or resource busy"),
    "设备已移除": serial.SerialException(errno.ENOENT, "No such file or directory"),
}


@pytest.fixture
def world() -> SimpleNamespace:
    return SimpleNamespace(ports=[], listed=[], reader=None, handle=None, open_failure="")


@given("系统上有这些串口设备", target_fixture="world")
def serial_devices(world: SimpleNamespace, datatable: list[list[str]]) -> SimpleNamespace:
    for device, vid_pid, product in (row for row in datatable[1:]):
        vendor, product_id = (int(part, 16) for part in vid_pid.split(":"))
        world.ports.append(
            SimpleNamespace(device=device, vid=vendor, pid=product_id, product=product, description=product)
        )
    return world


@given(parsers.parse('设备 "{device}" 的 USB 设备目录里 speed 为 "{speed}"'), target_fixture="world")
def set_device_speed(world: SimpleNamespace, tmp_path: object, device: str, speed: str) -> SimpleNamespace:
    (tmp_path / "speed").write_text(speed)  # type: ignore[operator]
    for port in world.ports:
        if port.device == device:
            port.usb_device_path = str(tmp_path)
    return world


@given(parsers.parse('设备 "{device}" 的 speed 信息为 "{state}"'), target_fixture="world")
def set_device_speed_unavailable(world: SimpleNamespace, tmp_path: object, device: str, state: str) -> SimpleNamespace:
    """`不存在`: no USB device directory; `读不出`: a directory without a speed file."""

    assert state in {"不存在", "读不出"}, f"unknown speed state: {state}"
    for port in world.ports:
        if port.device == device and state == "读不出":
            port.usb_device_path = str(tmp_path)
    return world


@when("列出 USB Output 端口")
def list_usb_ports(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(usb_output_transport.serial.tools.list_ports, "comports", lambda: list(world.ports))
    world.listed = usb_output_transport.list_usb_output_ports()


@then("列出的端口是")
def listed_ports_are(world: SimpleNamespace, datatable: list[list[str]]) -> None:
    assert [value for _, value in world.listed] == [row[0] for row in datatable]


@then(parsers.parse('端口标签是 "{label}"'))
def port_label_is(world: SimpleNamespace, label: str) -> None:
    assert [port_label for port_label, _ in world.listed] == [label]


@given(parsers.parse('一个 USB Output 端口 "{device}"'))
def usb_output_port(world: SimpleNamespace, device: str) -> None:
    world.reader = UsbOutputTransport(device, 3_000_000)


@when("打开该端口")
def open_port(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    world.handle = SerialHandleStub()
    monkeypatch.setattr(_SERIAL_CONSTRUCTOR, lambda *args, **kwargs: world.handle)
    world.reader.open()


@given(parsers.parse("打开端口会因「{failure}」失败"))
def open_will_fail(world: SimpleNamespace, failure: str) -> None:
    world.open_error = _OPEN_FAILURES[failure]


@when("尝试打开该端口")
def try_open_port(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise world.open_error

    monkeypatch.setattr(_SERIAL_CONSTRUCTOR, refuse)
    try:
        world.reader.open()
    except RuntimeError as error:
        world.open_failure = str(error)


@then(parsers.parse('错误提示建议 "{hint}"'))
def error_suggests(world: SimpleNamespace, hint: str) -> None:
    assert hint in world.open_failure


@then("该端口保持了 DTR 有效")
def dtr_stays_asserted(world: SimpleNamespace) -> None:
    assert world.handle.dtr_writes == [True]


@when("请求复位目标")
def request_reset(world: SimpleNamespace) -> None:
    world.reset_result = world.reader.reset_target()


@then("未发送 RTS 脉冲")
def no_rts_pulse(world: SimpleNamespace) -> None:
    assert world.handle.rts_writes == []


@then("复位报告为未执行")
def reset_reports_false(world: SimpleNamespace) -> None:
    assert world.reset_result is False


@when("读取该端口的速率配置")
def read_bitrate(world: SimpleNamespace) -> None:
    world.bitrate = world.reader.bitrate_config


@then("线速上限为空")
def no_wire_limit(world: SimpleNamespace) -> None:
    assert world.bitrate.wire_bits_per_sec is None
    assert world.bitrate.max_payload_bytes_per_sec is None


@when(parsers.parse('用 "{name}" 选择传输模式'))
def select_mode(world: SimpleNamespace, name: str) -> None:
    world.selected_mode = _parse_transport_mode(name)


@then("得到 USB Output 模式")
def got_usb_output_mode(world: SimpleNamespace) -> None:
    assert world.selected_mode is TransportMode.USB_OUTPUT
    assert _mode_select_value(world.selected_mode) == "usb"
