# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import errno
from unittest.mock import MagicMock, patch

import pytest
import serial
import usb.core
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport.base import PortIssueKind
from src.backend.support.transport.spi_usb_bridge_transport import (
    CDC_ENDPOINT_PREFIX,
    PROVIDER,
    SPI_BITS_PER_BYTE,
    SPI_WIRE_BPS,
    SpiUsbBridgeBulkTransport,
    SpiUsbBridgeCdcTransport,
    SpiUsbBridgeEndpoint,
    _endpoint_from_key,
    scan_spi_usb_bridge_ports,
)

from tests.helpers import usb_bridge_configuration, usb_bridge_device, usb_bridge_unreadable_configuration


class TestSpiUsbBridgeEndpoint:
    def test_key_round_trip(self) -> None:
        endpoint = SpiUsbBridgeEndpoint(bus=1, address=2, interface=3, endpoint=0x81)

        parsed = _endpoint_from_key(endpoint.key)

        assert parsed == endpoint
        assert "ep=0x81" in endpoint.label

    def test_invalid_key_raises_value_error(self) -> None:
        try:
            _endpoint_from_key("not-an-endpoint")
        except ValueError as e:
            assert "Invalid USB-SPI bridge endpoint key" in str(e)
        else:
            raise AssertionError("expected ValueError")


class TestSpiUsbBridgeOptions:
    @patch("src.backend.support.transport.spi_usb_bridge_transport.list_spi_usb_bridge_cdc_options")
    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=True)
    def test_windows_prefers_cdc_options(self, _mock_windows: MagicMock, mock_cdc: MagicMock) -> None:
        mock_cdc.return_value = [("USB-SPI-BRIDGE CDC COM7", f"{CDC_ENDPOINT_PREFIX}COM7")]

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == [("USB-SPI-BRIDGE CDC COM7", f"{CDC_ENDPOINT_PREFIX}COM7")]
        assert scan.issues == []

    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    def test_non_windows_lists_bulk_endpoints(self, _mock_windows: MagicMock, mock_find: MagicMock) -> None:
        mock_find.return_value = [usb_bridge_device()]

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == [("SPI-BRIDGE bus=1 addr=8 intf=0 ep=0x81", "1:8:0:129")]
        assert scan.issues == []


class TestSpiUsbBridgeScanIssues:
    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_a_bridge_without_permission_is_reported_with_its_bus_and_address(
        self, mock_find: MagicMock, _mock_windows: MagicMock
    ) -> None:
        mock_find.return_value = [
            usb_bridge_device(bus=3, address=11, open_error=usb.core.USBError("Access denied", errno=errno.EACCES))
        ]

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == []
        assert len(scan.issues) == 1
        issue = scan.issues[0]
        assert issue.kind is PortIssueKind.PERMISSION_DENIED
        assert (issue.bus, issue.address) == (3, 11)
        assert "Access denied" in issue.detail

    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_a_missing_libusb_backend_is_its_own_issue(self, mock_find: MagicMock, _mock_windows: MagicMock) -> None:
        mock_find.side_effect = usb.core.NoBackendError("No backend available")

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == []
        assert [issue.kind for issue in scan.issues] == [PortIssueKind.LIBUSB_MISSING]
        assert scan.issues[0].bus is None

    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_a_busy_bridge_keeps_the_libusb_error_text(self, mock_find: MagicMock, _mock_windows: MagicMock) -> None:
        mock_find.return_value = [usb_bridge_device(open_error=usb.core.USBError("Resource busy", errno=errno.EBUSY))]

        scan = scan_spi_usb_bridge_ports()

        assert [issue.kind for issue in scan.issues] == [PortIssueKind.DEVICE_ERROR]
        assert "Resource busy" in scan.issues[0].detail

    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_an_error_while_reading_endpoints_keeps_the_libusb_text(
        self, mock_find: MagicMock, _mock_windows: MagicMock
    ) -> None:
        """The configuration opened, but reading its interfaces failed on the device."""
        mock_find.return_value = [usb_bridge_device(configuration=usb_bridge_unreadable_configuration())]

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == []
        assert [issue.kind for issue in scan.issues] == [PortIssueKind.DEVICE_ERROR]
        assert (scan.issues[0].bus, scan.issues[0].address) == (1, 8)
        assert "Input/output error" in scan.issues[0].detail

    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_a_healthy_bridge_next_to_an_unusable_one_still_lists_its_endpoint(
        self, mock_find: MagicMock, _mock_windows: MagicMock
    ) -> None:
        mock_find.return_value = [
            usb_bridge_device(bus=1, address=8, open_error=usb.core.USBError("Access denied", errno=errno.EACCES)),
            usb_bridge_device(
                bus=1,
                address=9,
                configuration=usb_bridge_configuration(interface=1, endpoints=((0x82, 0x02),)),
            ),
        ]

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == [("SPI-BRIDGE bus=1 addr=9 intf=1 ep=0x82", "1:9:1:130")]
        assert [issue.kind for issue in scan.issues] == [PortIssueKind.PERMISSION_DENIED]

    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_no_bridge_at_all_is_still_a_silent_empty_list(
        self, mock_find: MagicMock, _mock_windows: MagicMock
    ) -> None:
        mock_find.return_value = None

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == []
        assert scan.issues == []

    @patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
    @patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
    def test_a_bridge_without_an_active_configuration_is_reported(
        self, mock_find: MagicMock, _mock_windows: MagicMock
    ) -> None:
        device = usb_bridge_device()
        device.get_active_configuration.return_value = None
        mock_find.return_value = [device]

        scan = scan_spi_usb_bridge_ports()

        assert scan.options == []
        assert [issue.kind for issue in scan.issues] == [PortIssueKind.DEVICE_ERROR]
        assert "active USB configuration" in scan.issues[0].detail


class TestSpiUsbBridgeTransportOpen:
    def test_provider_create_reader_does_not_open_cdc(self) -> None:
        config = TransportConfig(
            mode=TransportMode.SPI_USB_BRIDGE,
            label="bridge",
            port=f"{CDC_ENDPOINT_PREFIX}COM7",
            baudrate=3_000_000,
        )

        with patch("src.backend.support.transport.serial_reader.serial.Serial") as mock_serial:
            reader = PROVIDER.create_reader(config)

        mock_serial.assert_not_called()
        assert isinstance(reader, SpiUsbBridgeCdcTransport)
        assert reader.status().opened is False

    def test_provider_create_reader_does_not_claim_bulk_endpoint(self) -> None:
        config = TransportConfig(
            mode=TransportMode.SPI_USB_BRIDGE,
            label="bridge",
            port="1:2:0:129",
            baudrate=3_000_000,
        )

        with patch("src.backend.support.transport.spi_usb_bridge_transport._find_endpoint_access") as mock_find:
            reader = PROVIDER.create_reader(config)

        mock_find.assert_not_called()
        assert isinstance(reader, SpiUsbBridgeBulkTransport)
        assert reader.status().opened is False

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_cdc_transport_bitrate(self, mock_serial: MagicMock) -> None:
        mock_serial.return_value = MagicMock()

        transport = SpiUsbBridgeCdcTransport("COM7", 3_000_000)
        transport.open()

        bitrate = transport.bitrate_config
        assert bitrate.bits_per_payload_byte == SPI_BITS_PER_BYTE
        assert bitrate.wire_bits_per_sec == float(SPI_WIRE_BPS)
        assert transport.display_name.endswith("COM7")

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_cdc_reader_open_read_close_status(self, mock_serial: MagicMock) -> None:
        serial_obj = MagicMock()
        serial_obj.is_open = True
        serial_obj.read.return_value = b"abc"
        mock_serial.return_value = serial_obj

        reader = SpiUsbBridgeCdcTransport("COM7", 3_000_000)
        reader.open()
        block = reader.read()
        status = reader.status()
        reader.close()

        assert block == b"abc"
        assert status.opened is True
        assert status.rx_bytes == 3
        assert status.rx_chunks == 1
        serial_obj.close.assert_called_once()

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_cdc_open_wraps_serial_error_with_port_context(self, mock_serial: MagicMock) -> None:
        mock_serial.side_effect = serial.SerialException("access denied")

        reader = SpiUsbBridgeCdcTransport("COM7", 3_000_000)
        with pytest.raises(RuntimeError, match=r"Failed to connect to the USB-SPI bridge CDC port COM7"):
            reader.open()

        # CDC is not exclusive: one attempt, and no retry while the port is busy.
        assert mock_serial.call_count == 1

        status = reader.status()
        assert status.opened is False
        assert status.last_error == "access denied"

    def test_provider_metadata(self) -> None:
        assert PROVIDER.mode is TransportMode.SPI_USB_BRIDGE
        assert PROVIDER.label == "SPI USB Bridge"
