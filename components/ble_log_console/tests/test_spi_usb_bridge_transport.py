# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock
from unittest.mock import patch

from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.transport.spi_usb_bridge_transport import CDC_ENDPOINT_PREFIX
from src.backend.transport.spi_usb_bridge_transport import SPI_BITS_PER_BYTE
from src.backend.transport.spi_usb_bridge_transport import SPI_WIRE_BPS
from src.backend.transport.spi_usb_bridge_transport import PROVIDER
from src.backend.transport.spi_usb_bridge_transport import SpiUsbBridgeEndpoint
from src.backend.transport.spi_usb_bridge_transport import _endpoint_from_key
from src.backend.transport.spi_usb_bridge_transport import list_spi_usb_bridge_port_options
from src.backend.transport.spi_usb_bridge_transport import open_spi_usb_bridge_transport


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
    @patch('src.backend.transport.spi_usb_bridge_transport.list_spi_usb_bridge_cdc_options')
    @patch('src.backend.transport.spi_usb_bridge_transport._is_windows', return_value=True)
    def test_windows_prefers_cdc_options(self, _mock_windows: MagicMock, mock_cdc: MagicMock) -> None:
        mock_cdc.return_value = [('USB-SPI-BRIDGE CDC COM7', f'{CDC_ENDPOINT_PREFIX}COM7')]

        assert list_spi_usb_bridge_port_options() == [('USB-SPI-BRIDGE CDC COM7', f'{CDC_ENDPOINT_PREFIX}COM7')]

    @patch('src.backend.transport.spi_usb_bridge_transport.list_spi_usb_bridge_endpoints')
    @patch('src.backend.transport.spi_usb_bridge_transport._is_windows', return_value=False)
    def test_non_windows_lists_bulk_endpoints(self, _mock_windows: MagicMock, mock_endpoints: MagicMock) -> None:
        endpoint = SpiUsbBridgeEndpoint(bus=1, address=2, interface=0, endpoint=0x81)
        mock_endpoints.return_value = [endpoint]

        assert list_spi_usb_bridge_port_options() == [(endpoint.label, endpoint.key)]


class TestSpiUsbBridgeTransportOpen:
    @patch('src.backend.transport.spi_usb_bridge_transport.serial.Serial')
    def test_cdc_transport_bitrate(self, mock_serial: MagicMock) -> None:
        mock_serial.return_value = MagicMock()

        transport = open_spi_usb_bridge_transport(f'{CDC_ENDPOINT_PREFIX}COM7')

        bitrate = transport.bitrate_config
        assert bitrate.bits_per_payload_byte == SPI_BITS_PER_BYTE
        assert bitrate.wire_bits_per_sec == float(SPI_WIRE_BPS)
        assert transport.display_name.endswith('COM7')

    def test_provider_metadata(self) -> None:
        assert PROVIDER.mode is TransportMode.SPI_USB_BRIDGE
        assert PROVIDER.label == 'SPI USB Bridge'

    @patch('src.backend.transport.spi_usb_bridge_transport.open_spi_usb_bridge_transport')
    def test_provider_opens_configured_port(self, mock_open: MagicMock) -> None:
        config = TransportConfig(
            mode=TransportMode.SPI_USB_BRIDGE,
            label='bridge',
            port='1:2:0:129',
            baudrate=3_000_000,
        )

        PROVIDER.open(config)

        mock_open.assert_called_once_with('1:2:0:129', 3_000_000)
