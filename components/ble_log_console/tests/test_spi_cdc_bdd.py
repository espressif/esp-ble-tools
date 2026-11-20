# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace
from unittest.mock import Mock

from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport import create_transport_reader, list_transport_port_options
from src.backend.support.transport.serial_reader import SerialReader
from src.backend.support.transport.spi_usb_bridge_transport import SpiUsbBridgeCdcTransport

scenarios("features/spi_cdc.feature")


@given(parsers.parse("在 {platform} 上系统已枚举 Bridge CDC 端口"), target_fixture="world")
def cdc_available(monkeypatch, platform):
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
    world.options = list_transport_port_options(TransportMode.SPI_USB_BRIDGE)
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
