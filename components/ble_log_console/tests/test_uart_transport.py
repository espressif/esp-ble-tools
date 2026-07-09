# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch
from unittest.mock import MagicMock

from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.support.transport.uart_transport import PROVIDER
from src.backend.support.transport.uart_transport import UartTransport
from src.backend.support.transport.uart_transport import validate_uart_port


class TestValidateUartPort:
    @patch('src.backend.support.transport.uart_transport.list_serial_ports', return_value=['/dev/ttyUSB0', '/dev/ttyUSB1'])
    def test_valid_port_returns_none(self, _mock: object) -> None:
        assert validate_uart_port('/dev/ttyUSB0') is None

    @patch('src.backend.support.transport.uart_transport.list_serial_ports', return_value=['/dev/ttyUSB0'])
    def test_invalid_port_returns_error(self, _mock: object) -> None:
        result = validate_uart_port('/dev/ttyUSB99')
        assert result is not None
        assert '/dev/ttyUSB99' in result

    @patch('src.backend.support.transport.uart_transport.list_serial_ports', return_value=['COM3', 'COM4'])
    def test_windows_com_port_valid(self, _mock: object) -> None:
        """COM ports don't exist as filesystem paths — must not use Path.exists()."""
        assert validate_uart_port('COM3') is None

    @patch('src.backend.support.transport.uart_transport.list_serial_ports', return_value=[])
    def test_empty_port_list(self, _mock: object) -> None:
        result = validate_uart_port('/dev/ttyUSB0')
        assert result is not None


class TestUartTransportReader:
    def test_create_reader_does_not_open_serial(self) -> None:
        config = TransportConfig(
            mode=TransportMode.UART,
            label='/dev/ttyUSB0',
            port='/dev/ttyUSB0',
            baudrate=3_000_000,
        )

        with patch('src.backend.support.transport.uart_transport.serial.Serial') as mock_serial:
            reader = PROVIDER.create_reader(config)

        mock_serial.assert_not_called()
        assert isinstance(reader, UartTransport)
        assert reader.status().opened is False

    def test_open_read_close_status(self) -> None:
        serial_obj = MagicMock()
        serial_obj.is_open = True
        serial_obj.read.return_value = b'abc'

        with patch('src.backend.support.transport.uart_transport.serial.Serial', return_value=serial_obj):
            reader = UartTransport('/dev/ttyUSB0', 3_000_000)
            reader.open()
            block = reader.read()
            status = reader.status()
            reader.close()

        assert block == b'abc'
        assert status.opened is True
        assert status.healthy is True
        assert status.rx_bytes == 3
        assert status.rx_chunks == 1
        serial_obj.close.assert_called_once()

    def test_reset_target_preserves_existing_behavior(self) -> None:
        serial_obj = MagicMock()
        serial_obj.is_open = True

        with patch('src.backend.support.transport.uart_transport.serial.Serial', return_value=serial_obj):
            with patch('src.backend.support.transport.uart_transport.time.sleep'):
                reader = UartTransport('/dev/ttyUSB0', 3_000_000)
                reader.open()

                assert reader.reset_target() is True

        assert serial_obj.dtr is False
        assert serial_obj.rts is False
