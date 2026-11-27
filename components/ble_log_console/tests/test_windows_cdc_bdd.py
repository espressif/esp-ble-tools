# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock

import pytest
import serial
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport import create_transport_reader, list_transport_port_scan

scenarios("features/windows_cdc.feature")


@given(parsers.parse("Windows 上有一个 {mode} CDC 端口 COM12"), target_fixture="world")
def windows_port(monkeypatch, mode):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("src.i18n._language", "en")
    pid = {"SPI_USB_BRIDGE": 0x4001, "USB_OUTPUT": 0x10B1, "USJ": 0x1001}[mode]
    port = SimpleNamespace(device="COM12", vid=0x303A, pid=pid, product=None, description="USB Serial Device (COM12)")
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [port])
    bulk = Mock(side_effect=AssertionError("CDC must not access Bulk"))
    monkeypatch.setattr("usb.core.find", bulk)
    handle = Mock(is_open=True)
    handle.read.return_value = b"log-data"
    opened = Mock(return_value=handle)
    monkeypatch.setattr("serial.Serial", opened)
    key = "cdc:COM12" if mode == "SPI_USB_BRIDGE" else "COM12"
    config = TransportConfig(TransportMode[mode], "CDC", key)
    return SimpleNamespace(
        config=config, handle=handle, opened=opened, bulk=bulk, reader=create_transport_reader(config)
    )


@when("枚举并打开这个 CDC 端口")
def enumerate_and_open(world):
    world.options = list_transport_port_scan(world.config.mode).options
    world.opened.assert_not_called()
    world.reader.open()
    world.data = world.reader.read()


@then("仅按设备身份选择 COM12 并独占打开")
def serial_only(world):
    assert [key for _, key in world.options] == [world.config.port]
    assert all("esp32" not in label.lower() for label, _ in world.options)
    assert world.data == b"log-data"
    assert world.opened.call_count == 1
    assert world.opened.call_args.args == ("COM12",)
    assert world.opened.call_args.kwargs["exclusive"] is True
    world.bulk.assert_not_called()
    if world.config.mode is TransportMode.USJ:
        assert [(call[0], call[1]) for call in world.handle.mock_calls] == [("read", (65536,))]
        assert world.handle.rts is False and world.handle.dtr is False
    world.reader.close()
    world.handle.close.assert_called_once()


@given("Windows 返回访问被拒绝错误")
def access_denied(world):
    world.opened.side_effect = serial.SerialException(
        "could not open port 'COM12': PermissionError(13, 'Access is denied.', None, 5)"
    )


@given("设置 DTR 时设备返回 I/O 错误")
def dtr_failure(world):
    type(world.handle).dtr = PropertyMock(side_effect=serial.SerialException("SetCommState failed: device removed"))


@when("尝试打开这个 CDC 端口")
def try_open(world):
    with pytest.raises((serial.SerialException, RuntimeError, OSError)) as error:
        world.reader.open()
    world.error = error.value


@then("只尝试一次并提示检查 Windows COM 端口")
def one_attempt(world):
    assert world.opened.call_count == 1
    assert "COM12" in str(world.error)
    assert "Device Manager" in str(world.error)
    assert "dialout" not in str(world.error)
    assert not world.reader.status().opened
    world.bulk.assert_not_called()


@then("打开失败且设备句柄已关闭")
def failed_and_closed(world):
    assert world.opened.call_count == 1
    world.handle.close.assert_called_once()
    assert not world.reader.status().opened
    assert "device removed" in str(world.error)


@pytest.mark.parametrize("mode", [TransportMode.SPI_USB_BRIDGE, TransportMode.USB_OUTPUT, TransportMode.USJ])
@pytest.mark.parametrize("message", ["Not a valid baudrate: -1", "exclusive configuration rejected"])
def test_invalid_configuration_is_not_retried(monkeypatch, mode, message):
    opened = Mock(side_effect=ValueError(message))
    monkeypatch.setattr("serial.Serial", opened)
    reader = create_transport_reader(TransportConfig(mode, "CDC", "COM12", -1))
    with pytest.raises(ValueError, match=message):
        reader.open()
    opened.assert_called_once()


@pytest.mark.parametrize("mode", ["SPI_USB_BRIDGE", "USB_OUTPUT", "USJ"])
def test_windows_error_hint_uses_selected_language(monkeypatch, mode):
    world = windows_port(monkeypatch, mode)
    access_denied(world)
    monkeypatch.setattr("src.i18n._language", "zh_CN")
    try_open(world)
    assert "设备管理器" in str(world.error)
    assert "COM12" in str(world.error)
    assert "dialout" not in str(world.error)
    world.opened.assert_called_once()
