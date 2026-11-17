# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import errno
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import serial
import usb.core
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport.spi_usb_bridge_transport import (
    CDC_ENDPOINT_PREFIX,
    PROVIDER,
    SPI_BITS_PER_BYTE,
    SPI_WIRE_BPS,
    SpiUsbBridgeCdcTransport,
    scan_spi_usb_bridge_ports,
)
from tools.spi_bulk_transport import SpiUsbBridgeBulkTransport, SpiUsbBridgeEndpoint, _endpoint_from_key


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
    def test_lists_cdc_options(self, mock_cdc: MagicMock) -> None:
        mock_cdc.return_value = [("USB-SPI-BRIDGE CDC COM7", f"{CDC_ENDPOINT_PREFIX}COM7")]

        with patch("src.backend.support.transport.serial_reader.os.access", return_value=True):
            assert scan_spi_usb_bridge_ports().options == [("USB-SPI-BRIDGE CDC COM7", f"{CDC_ENDPOINT_PREFIX}COM7")]

    @patch("tools.spi_bulk_transport.list_spi_usb_bridge_bulk_endpoints")
    @patch("src.backend.support.transport.spi_usb_bridge_transport.list_spi_usb_bridge_cdc_options", return_value=[])
    def test_without_cdc_does_not_list_bulk_endpoints(self, _mock_cdc: MagicMock, mock_endpoints: MagicMock) -> None:
        endpoint = SpiUsbBridgeEndpoint(bus=1, address=2, interface=0, endpoint=0x81)
        mock_endpoints.return_value = [endpoint]

        assert scan_spi_usb_bridge_ports().options == []
        mock_endpoints.assert_not_called()


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

    def test_provider_rejects_legacy_bulk_endpoint(self) -> None:
        config = TransportConfig(
            mode=TransportMode.SPI_USB_BRIDGE,
            label="bridge",
            port="1:2:0:129",
            baudrate=3_000_000,
        )

        with patch("tools.spi_bulk_transport._find_endpoint_access") as mock_find:
            with pytest.raises(ValueError, match="CDC serial port"):
                PROVIDER.create_reader(config)

        mock_find.assert_not_called()

    @pytest.mark.parametrize("port", ["/dev/ttyACM0", "/dev/cu.usbmodem1", "COM7"])
    def test_provider_accepts_serial_port_without_prefix(self, port: str) -> None:
        reader = PROVIDER.create_reader(TransportConfig(mode=TransportMode.SPI_USB_BRIDGE, label="bridge", port=port))
        assert isinstance(reader, SpiUsbBridgeCdcTransport)
        assert reader.display_name.endswith(port)
        assert not reader.status().opened

    @pytest.mark.parametrize("port", ["", "cdc:"])
    def test_provider_rejects_empty_port(self, port: str) -> None:
        with pytest.raises(ValueError, match="CDC serial port"):
            PROVIDER.create_reader(TransportConfig(mode=TransportMode.SPI_USB_BRIDGE, label="bridge", port=port))

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

        mock_serial.assert_called_once_with("COM7", baudrate=3_000_000, timeout=0.1, exclusive=True)
        assert block == b"abc"
        assert status.opened is True
        assert status.rx_bytes == 3
        assert status.rx_chunks == 1
        serial_obj.close.assert_called_once()

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_cdc_open_wraps_serial_error_with_port_context(self, mock_serial: MagicMock) -> None:
        mock_serial.side_effect = serial.SerialException(errno.EACCES, "access denied")

        reader = SpiUsbBridgeCdcTransport("COM7", 3_000_000)
        with pytest.raises(RuntimeError, match=r"Failed to connect to the USB-SPI bridge CDC port COM7"):
            reader.open()

        # Permission or lock refusal must not fall back to a shared open.
        assert mock_serial.call_count == 1

        status = reader.status()
        assert status.opened is False
        assert status.last_error == str(mock_serial.side_effect)

    def test_provider_metadata(self) -> None:
        assert PROVIDER.mode is TransportMode.SPI_USB_BRIDGE
        assert PROVIDER.label == "SPI USB Bridge"


class TestSpiUsbBridgeBulkRead:
    def _transport_reading(self, read_error: Exception) -> SpiUsbBridgeBulkTransport:
        endpoint = SpiUsbBridgeEndpoint(bus=1, address=2, interface=0, endpoint=0x81)
        transport = SpiUsbBridgeBulkTransport(endpoint)
        device = MagicMock()
        device.read.side_effect = read_error
        transport._epa = SimpleNamespace(device=device, ep=0x81)
        transport._claimed = True
        return transport

    def test_idle_timeout_returns_an_empty_block(self) -> None:
        # libusb reports a timeout as USBTimeoutError carrying the platform ETIMEDOUT, 60 on macOS.
        transport = self._transport_reading(usb.core.USBTimeoutError("Operation timed out", -7, errno=60))

        assert transport.read() == b""
        assert transport.status().last_error is None

    def test_timeout_message_without_the_error_type_is_still_an_empty_block(self) -> None:
        transport = self._transport_reading(usb.core.USBError("Operation timed out", -7, errno=60))

        assert transport.read() == b""

    def test_other_usb_errors_still_fail_the_read(self) -> None:
        transport = self._transport_reading(usb.core.USBError("Pipe error", -9, errno=errno.EPIPE))

        with pytest.raises(RuntimeError, match="USB-SPI bridge read failed"):
            transport.read()
