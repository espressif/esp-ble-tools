# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport import create_transport_reader, list_transport_port_scan
from src.backend.support.transport.serial_reader import SerialReader
from src.backend.support.transport.spi_usb_bridge_transport import SpiUsbBridgeCdcTransport

scenarios("features/spi_cdc.feature")


@given(parsers.parse("在 {platform} 上系统已枚举 Bridge CDC 端口"), target_fixture="world")
def cdc_available(monkeypatch, platform):
    monkeypatch.setattr("src.backend.support.transport.serial_reader.os.access", lambda device, mode: True)
    monkeypatch.setattr("sys.platform", platform)
    port = SimpleNamespace(device="COM7" if platform == "win32" else "/dev/ttyACM0", vid=0x303A, pid=0x4001)
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [port])
    bulk = Mock(side_effect=AssertionError("CDC discovery must not access USB Bulk"))
    monkeypatch.setattr("usb.core.find", bulk)
    opened = Mock(side_effect=AssertionError("Discovery must not open the port"))
    monkeypatch.setattr("serial.Serial", opened)
    return SimpleNamespace(port=port.device, bulk=bulk, opened=opened)


@when("查找并选择 SPI Bridge 接收端口")
def select_bridge(world):
    world.options = list_transport_port_scan(TransportMode.SPI_USB_BRIDGE).options
    world.reader = create_transport_reader(
        TransportConfig(mode=TransportMode.SPI_USB_BRIDGE, port=world.options[0][1], label=world.options[0][0])
    )


@then("使用共用串口接收器且不访问 USB Bulk")
def shared_serial_reader(world):
    assert world.options == [(f"SPI-BRIDGE CDC {world.port}", f"cdc:{world.port}")]
    assert isinstance(world.reader, SpiUsbBridgeCdcTransport)
    assert isinstance(world.reader, SerialReader)
    assert not world.reader.status().opened
    world.bulk.assert_not_called()
    world.opened.assert_not_called()


@given(parsers.parse("在 {platform} 上系统没有 Bridge CDC 端口"), target_fixture="world")
def cdc_unavailable(monkeypatch, platform):
    world = cdc_available(monkeypatch, platform)
    monkeypatch.setattr("serial.tools.list_ports.comports", list)
    return world


@when("查找 SPI Bridge 接收端口")
def discover_bridge(world):
    world.options = list_transport_port_scan(TransportMode.SPI_USB_BRIDGE).options


@then("没有可选端口且不访问 USB Bulk")
def no_bulk_fallback(world):
    assert world.options == []
    world.bulk.assert_not_called()
    world.opened.assert_not_called()


@when("使用旧的 Bulk 地址创建 SPI Bridge 接收器")
def reject_bulk_key(world):
    with pytest.raises(ValueError, match="CDC serial port") as error:
        create_transport_reader(TransportConfig(mode=TransportMode.SPI_USB_BRIDGE, label="bridge", port="1:8:0:129"))
    world.error = str(error.value)


@then("提示改用 CDC 串口且不访问 USB Bulk")
def cdc_hint(world):
    assert "cdc:/dev/ttyACM0" in world.error
    world.bulk.assert_not_called()
    world.opened.assert_not_called()


@when("在禁用 PyUSB 的新进程启动 Console 并接收各模式数据", target_fixture="without_pyusb")
def run_without_pyusb():
    return subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from unittest.mock import Mock, patch
sys.modules['usb'] = None
import console
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport import create_transport_reader
console.cli.main(['--help'], standalone_mode=False)
for mode in (TransportMode.SPI_USB_BRIDGE, TransportMode.USB_OUTPUT, TransportMode.USJ):
    handle = Mock(is_open=True)
    handle.read.return_value = b'cdc log'
    with patch('serial.Serial', return_value=handle):
        reader = create_transport_reader(TransportConfig(mode, 'test', '/dev/test'))
        reader.open()
        assert reader.read() == b'cdc log'
        reader.close()
        handle.close.assert_called_once()
assert 'tools.spi_bulk_transport' not in sys.modules
print('CDC_ONLY_OK')
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


@then("SPI、USB OTG 和 USJ 均可通过串口接收且不加载 Bulk 工具")
def cdc_without_pyusb(without_pyusb):
    assert without_pyusb.returncode == 0, without_pyusb.stderr
    assert "CDC_ONLY_OK" in without_pyusb.stdout
