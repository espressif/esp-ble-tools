# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock
from unittest.mock import patch

from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.support.transport.spi_usb_bridge_transport import CDC_ENDPOINT_PREFIX
from src.backend.support.transport.spi_usb_bridge_transport import SPI_BITS_PER_BYTE
from src.backend.support.transport.spi_usb_bridge_transport import SPI_WIRE_BPS
from src.backend.support.transport.spi_usb_bridge_transport import PROVIDER
from src.backend.support.transport.spi_usb_bridge_transport import SpiUsbBridgeBulkTransport
from src.backend.support.transport.spi_usb_bridge_transport import SpiUsbBridgeCdcTransport
from src.backend.support.transport.spi_usb_bridge_transport import SpiUsbBridgeEndpoint
from src.backend.support.transport.spi_usb_bridge_transport import _endpoint_from_key
from src.backend.support.transport.spi_usb_bridge_transport import list_spi_usb_bridge_port_options


class TestSpiUsbBridgeEndpoint:
    def test_key_round_trip(self) -> None:
        endpoint = SpiUsbBridgeEndpoint(bus=1, address=2, interface=3, endpoint=0x81)

        parsed = _endpoint_from_key(endpoint.key)

        assert parsed == endpoint
        assert 'ep=0x81' in endpoint.label

    def test_invalid_key_raises_value_error(self) -> None:
        try:
            _endpoint_from_key('not-an-endpoint')
        except ValueError as e:
            assert 'Invalid USB-SPI bridge endpoint key' in str(e)
        else:
            raise AssertionError('expected ValueError')


class TestSpiUsbBridgeOptions:
    @patch('src.backend.support.transport.spi_usb_bridge_transport.list_spi_usb_bridge_cdc_options')
    @patch('src.backend.support.transport.spi_usb_bridge_transport._is_windows', return_value=True)
    def test_windows_prefers_cdc_options(self, _mock_windows: MagicMock, mock_cdc: MagicMock) -> None:
        mock_cdc.return_value = [('USB-SPI-BRIDGE CDC COM7', f'{CDC_ENDPOINT_PREFIX}COM7')]

        assert list_spi_usb_bridge_port_options() == [('USB-SPI-BRIDGE CDC COM7', f'{CDC_ENDPOINT_PREFIX}COM7')]

    @patch('src.backend.support.transport.spi_usb_bridge_transport.list_spi_usb_bridge_bulk_endpoints')
    @patch('src.backend.support.transport.spi_usb_bridge_transport._is_windows', return_value=False)
    def test_non_windows_lists_bulk_endpoints(self, _mock_windows: MagicMock, mock_endpoints: MagicMock) -> None:
        endpoint = SpiUsbBridgeEndpoint(bus=1, address=2, interface=0, endpoint=0x81)
        mock_endpoints.return_value = [endpoint]

        assert list_spi_usb_bridge_port_options() == [(endpoint.label, endpoint.key)]


class TestSpiUsbBridgeTransportOpen:
    def test_provider_create_reader_does_not_open_cdc(self) -> None:
        config = TransportConfig(
            mode=TransportMode.SPI_USB_BRIDGE,
            label='bridge',
            port=f'{CDC_ENDPOINT_PREFIX}COM7',
            baudrate=3_000_000,
        )

        with patch('src.backend.support.transport.spi_usb_bridge_transport.serial.Serial') as mock_serial:
            reader = PROVIDER.create_reader(config)

        mock_serial.assert_not_called()
        assert isinstance(reader, SpiUsbBridgeCdcTransport)
        assert reader.status().opened is False

    def test_provider_create_reader_does_not_claim_bulk_endpoint(self) -> None:
        config = TransportConfig(
            mode=TransportMode.SPI_USB_BRIDGE,
            label='bridge',
            port='1:2:0:129',
            baudrate=3_000_000,
        )

        with patch('src.backend.support.transport.spi_usb_bridge_transport._find_endpoint_access') as mock_find:
            reader = PROVIDER.create_reader(config)

        mock_find.assert_not_called()
        assert isinstance(reader, SpiUsbBridgeBulkTransport)
        assert reader.status().opened is False

    @patch('src.backend.support.transport.spi_usb_bridge_transport.serial.Serial')
    def test_cdc_transport_bitrate(self, mock_serial: MagicMock) -> None:
        mock_serial.return_value = MagicMock()

        transport = SpiUsbBridgeCdcTransport('COM7', 3_000_000)
        transport.open()

        bitrate = transport.bitrate_config
        assert bitrate.bits_per_payload_byte == SPI_BITS_PER_BYTE
        assert bitrate.wire_bits_per_sec == float(SPI_WIRE_BPS)
        assert transport.display_name.endswith('COM7')

    @patch('src.backend.support.transport.spi_usb_bridge_transport.serial.Serial')
    def test_cdc_reader_open_read_close_status(self, mock_serial: MagicMock) -> None:
        serial_obj = MagicMock()
        serial_obj.is_open = True
        serial_obj.read.return_value = b'abc'
        mock_serial.return_value = serial_obj

        reader = SpiUsbBridgeCdcTransport('COM7', 3_000_000)
        reader.open()
        block = reader.read()
        status = reader.status()
        reader.close()

        assert block == b'abc'
        assert status.opened is True
        assert status.rx_bytes == 3
        assert status.rx_chunks == 1
        serial_obj.close.assert_called_once()

    def test_provider_metadata(self) -> None:
        assert PROVIDER.mode is TransportMode.SPI_USB_BRIDGE
        assert PROVIDER.label == 'SPI USB Bridge'
