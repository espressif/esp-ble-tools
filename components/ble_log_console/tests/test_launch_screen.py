# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.backend.models import LaunchConfig, TransportMode
from src.backend.support.transport.base import PortIssue, PortIssueKind, PortScan
from src.frontend.launch_screen import BAUD_RATES, DEFAULT_BAUD_RATE, SPI_PORT_LABEL_PREFIX, LaunchScreen
from src.i18n import get_language, set_language

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestBaudRateConstants:
    def test_baud_rates_ascending(self) -> None:
        assert BAUD_RATES == sorted(BAUD_RATES)

    def test_default_baud_rate_in_list(self) -> None:
        assert DEFAULT_BAUD_RATE in BAUD_RATES

    def test_default_baud_rate_value(self) -> None:
        assert DEFAULT_BAUD_RATE == 3_000_000

    def test_common_rates_present(self) -> None:
        """Standard UART baud rates used by ESP-IDF should be available."""
        assert 115200 in BAUD_RATES
        assert 921600 in BAUD_RATES


# ---------------------------------------------------------------------------
# LaunchScreen instantiation
# ---------------------------------------------------------------------------


class TestLaunchScreenInit:
    def test_default_log_dir_is_logs_under_cwd(self) -> None:
        screen = LaunchScreen()
        assert screen._default_log_dir == Path.cwd() / "logs"

    def test_custom_log_dir(self) -> None:
        custom = Path("/tmp/my_logs")
        screen = LaunchScreen(default_log_dir=custom)
        assert screen._default_log_dir == custom

    def test_bindings_include_quit(self) -> None:
        """LaunchScreen should have a quit binding on 'q'."""
        keys = [b.key for b in LaunchScreen.BINDINGS]
        assert "q" in keys

    def test_language_is_selected_before_connecting(self) -> None:
        screen = LaunchScreen()
        event = MagicMock()
        event.value = "zh_CN"
        try:
            screen.language_changed(event)
            assert get_language() == "zh_CN"
        finally:
            set_language("en")


# ---------------------------------------------------------------------------
# refresh_ports — unit-level (mocked widgets)
# ---------------------------------------------------------------------------


class TestRefreshPorts:
    @patch("src.frontend.launch_screen.list_transport_port_scan")
    def test_refresh_updates_select_with_ports(self, mock_scan: MagicMock) -> None:
        """refresh_ports should scan ports and update the Select widget."""
        mock_scan.return_value = PortScan(options=[("/dev/ttyUSB0", "/dev/ttyUSB0"), ("/dev/ttyUSB1", "/dev/ttyUSB1")])
        screen = LaunchScreen()

        mock_select = MagicMock()
        screen.query_one = MagicMock(return_value=mock_select)  # type: ignore[method-assign]

        screen.refresh_ports()

        mock_scan.assert_called_once_with(TransportMode.UART)
        mock_select.set_options.assert_called_once_with(
            [("/dev/ttyUSB0", "/dev/ttyUSB0"), ("/dev/ttyUSB1", "/dev/ttyUSB1")]
        )
        assert mock_select.value == "/dev/ttyUSB0"

    @patch("src.frontend.launch_screen.list_transport_port_scan")
    def test_refresh_empty_ports_no_value_set(self, mock_scan: MagicMock) -> None:
        """When no ports found, set_options is called with empty list and value is not set."""
        mock_scan.return_value = PortScan()
        screen = LaunchScreen()

        mock_select = MagicMock()
        screen.query_one = MagicMock(return_value=mock_select)  # type: ignore[method-assign]

        screen.refresh_ports()

        mock_select.set_options.assert_called_once_with([])
        # value should NOT have been reassigned when ports list is empty
        assert mock_select.value != "/dev/ttyUSB0"

    @patch("src.frontend.launch_screen.list_transport_port_scan")
    def test_refresh_shows_why_a_present_bridge_is_missing(self, mock_scan: MagicMock, linux_serial_platform) -> None:
        """An unusable bridge must not leave the user with a bare empty list."""
        mock_scan.return_value = PortScan(
            issues=[PortIssue(kind=PortIssueKind.PERMISSION_DENIED, port="/dev/ttyACM0", label="SPI Bridge")]
        )
        screen = LaunchScreen()
        screen._mode = TransportMode.SPI_USB_BRIDGE
        try:
            set_language("en")
            label = MagicMock()
            screen.query_one = MagicMock(return_value=label)  # type: ignore[method-assign]

            screen.refresh_ports()
        finally:
            set_language("en")

        assert label.display is True
        assert (
            label.update.call_args[0][0] == "SPI Bridge /dev/ttyACM0: no read/write permission. "
            "Permission denied. On Linux, add your user to the dialout group "
            "(or install a udev rule for this device) and open the port again."
        )

    @patch("src.frontend.launch_screen.list_transport_port_scan")
    def test_refresh_shows_the_chinese_hint_when_the_app_language_is_chinese(
        self, mock_scan: MagicMock, linux_serial_platform
    ) -> None:
        mock_scan.return_value = PortScan(
            issues=[PortIssue(kind=PortIssueKind.PERMISSION_DENIED, port="/dev/ttyACM0", label="SPI Bridge")]
        )
        screen = LaunchScreen()
        screen._mode = TransportMode.SPI_USB_BRIDGE
        label = MagicMock()
        screen.query_one = MagicMock(return_value=label)  # type: ignore[method-assign]
        try:
            set_language("zh_CN")
            screen.refresh_ports()
        finally:
            set_language("en")

        assert label.display is True
        assert (
            label.update.call_args[0][0] == "SPI Bridge /dev/ttyACM0：没有读写权限。 "
            "权限不足。Linux 下请将当前用户加入 dialout 组（或为设备安装 udev 规则），然后重新打开端口。"
        )

    @patch("src.frontend.launch_screen.list_transport_port_scan")
    def test_switching_the_app_language_re_renders_the_visible_hint(
        self, mock_scan: MagicMock, linux_serial_platform
    ) -> None:
        """The hint is already on screen when the user picks 简体中文."""
        mock_scan.return_value = PortScan(
            issues=[PortIssue(kind=PortIssueKind.PERMISSION_DENIED, port="/dev/ttyACM0", label="SPI Bridge")]
        )
        screen = LaunchScreen()
        screen._mode = TransportMode.SPI_USB_BRIDGE
        label = MagicMock()
        screen.query_one = MagicMock(return_value=label)  # type: ignore[method-assign]
        try:
            set_language("en")
            screen.refresh_ports()
            event = MagicMock()
            event.value = "zh_CN"

            screen.language_changed(event)
        finally:
            set_language("en")

        assert (
            label.update.call_args[0][0] == "SPI Bridge /dev/ttyACM0：没有读写权限。 "
            "权限不足。Linux 下请将当前用户加入 dialout 组（或为设备安装 udev 规则），然后重新打开端口。"
        )


# ---------------------------------------------------------------------------
# connect — unit-level (mocked widgets)
# ---------------------------------------------------------------------------


class TestConnect:
    def _make_screen_with_mocks(
        self,
        port_value: object,
        baud_value: int = 3000000,
        dir_value: str = "/tmp/logs",
    ) -> tuple[LaunchScreen, MagicMock, MagicMock, MagicMock]:
        """Helper: create a LaunchScreen with mocked query_one results."""
        screen = LaunchScreen()

        mock_port_select = MagicMock()
        mock_port_select.value = port_value

        mock_baud_select = MagicMock()
        mock_baud_select.value = baud_value

        mock_dir_input = MagicMock()
        mock_dir_input.value = dir_value

        def fake_query_one(selector: str, widget_type: type = object) -> MagicMock:
            if selector == "#port-select":
                return mock_port_select
            if selector == "#baud-select":
                return mock_baud_select
            if selector == "#database-input":
                return MagicMock(value="")
            if selector.startswith("#show-"):
                return MagicMock(value=False)
            if selector == "#dir-input":
                return mock_dir_input
            raise ValueError(f"Unexpected selector: {selector}")

        screen.query_one = fake_query_one  # type: ignore[assignment]
        screen.dismiss = MagicMock()  # type: ignore[method-assign]
        screen.notify = MagicMock()  # type: ignore[method-assign]

        return screen, mock_port_select, mock_baud_select, mock_dir_input

    def test_connect_with_valid_port(self) -> None:
        """connect() should dismiss with LaunchConfig when port is selected."""
        screen, _, _, _ = self._make_screen_with_mocks(
            port_value="/dev/ttyUSB0",
            baud_value=921600,
            dir_value="/tmp/logs",
        )

        screen.connect()

        screen.dismiss.assert_called_once()
        config = screen.dismiss.call_args[0][0]
        assert isinstance(config, LaunchConfig)
        assert config.transport_config.mode is TransportMode.UART
        assert config.transport_config.port == "/dev/ttyUSB0"
        assert config.transport_config.baudrate == 921600
        assert config.log_dir == Path("/tmp/logs")

    def test_connect_with_spi_uses_default_baudrate_without_baud_select(self) -> None:
        screen, _, _, _ = self._make_screen_with_mocks(
            port_value="usb:303a:4001",
            dir_value="/tmp/logs",
        )
        screen._mode = TransportMode.SPI_USB_BRIDGE

        screen.connect()

        config = screen.dismiss.call_args[0][0]
        assert config.transport_config.mode is TransportMode.SPI_USB_BRIDGE
        assert config.transport_config.port == "usb:303a:4001"
        assert config.transport_config.baudrate == DEFAULT_BAUD_RATE

    def test_connect_with_usb_output_passes_the_serial_device_through(self) -> None:
        screen, _, _, _ = self._make_screen_with_mocks(
            port_value="/dev/cu.usbmodem1234561",
            dir_value="/tmp/logs",
        )
        screen._mode = TransportMode.USB_OUTPUT

        screen.connect()

        config = screen.dismiss.call_args[0][0]
        assert config.transport_config.mode is TransportMode.USB_OUTPUT
        assert config.transport_config.port == "/dev/cu.usbmodem1234561"
        assert config.transport_config.baudrate == DEFAULT_BAUD_RATE

    @pytest.mark.parametrize("language, message", [("en", "Please select a port"), ("zh_CN", "请选择端口")])
    def test_connect_with_blank_port_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, language: str, message: str
    ) -> None:
        """A port with no selection must not submit a recording configuration."""
        from textual.widgets import Select

        monkeypatch.setattr("src.i18n._language", language)
        screen, _, _, _ = self._make_screen_with_mocks(port_value=Select.NULL)

        screen.connect()

        screen.notify.assert_called_once_with(message, severity="error")
        screen.dismiss.assert_not_called()

    @pytest.mark.parametrize("language, message", [("en", "Please select a baud rate"), ("zh_CN", "请选择波特率")])
    def test_connect_with_blank_baud_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, language: str, message: str
    ) -> None:
        from textual.widgets import Select

        monkeypatch.setattr("src.i18n._language", language)
        screen, _, baud_select, _ = self._make_screen_with_mocks(port_value="COM3")
        baud_select.value = Select.NULL

        screen.connect()

        screen.notify.assert_called_once_with(message, severity="error")
        screen.dismiss.assert_not_called()

    def test_connect_log_dir_is_path_object(self) -> None:
        """The log_dir in LaunchConfig should be a Path, not a string."""
        screen, _, _, _ = self._make_screen_with_mocks(port_value="COM3", dir_value="/home/user/logs")

        screen.connect()

        config = screen.dismiss.call_args[0][0]
        assert isinstance(config.log_dir, Path)
        assert config.log_dir == Path("/home/user/logs")


class TestTransportModeHelpers:
    def test_spi_display_options_are_prefixed(self) -> None:
        screen = LaunchScreen()
        screen._mode = TransportMode.SPI_USB_BRIDGE
        options = screen._display_port_options([("raw label", "usb:303a:4001")])
        assert options == [(f"{SPI_PORT_LABEL_PREFIX}  usb:303a:4001", "usb:303a:4001")]

    def test_blank_mode_does_not_report_an_unsupported_mode(self) -> None:
        from textual.widgets import Select

        screen = LaunchScreen()
        screen.notify = MagicMock()  # type: ignore[method-assign]

        assert screen._mode_from_select_value(Select.NULL) is None
        screen.notify.assert_not_called()

    @pytest.mark.parametrize(
        "language, message",
        [
            ("en", "Unsupported transport mode: unsupported\nPlease select the right mode."),
            ("zh_CN", "不支持的传输模式：unsupported\n请选择正确的模式。"),
        ],
    )
    def test_unsupported_mode_reports_in_selected_language(
        self, monkeypatch: pytest.MonkeyPatch, language: str, message: str
    ) -> None:
        monkeypatch.setattr("src.i18n._language", language)
        screen = LaunchScreen()
        screen.notify = MagicMock()  # type: ignore[method-assign]

        assert screen._mode_from_select_value("unsupported") is None
        screen.notify.assert_called_once_with(message)

    def test_mode_from_select_value_accepts_enum_value(self) -> None:
        screen = LaunchScreen()
        assert screen._mode_from_select_value("spi_usb_bridge") is TransportMode.SPI_USB_BRIDGE

    def test_mode_from_select_value_accepts_cli_value(self) -> None:
        screen = LaunchScreen()
        assert screen._mode_from_select_value("spi") is TransportMode.SPI_USB_BRIDGE

    def test_usb_output_keeps_its_own_port_labels(self) -> None:
        """The USB provider already names its ports, so nothing is prefixed."""
        screen = LaunchScreen()
        screen._mode = TransportMode.USB_OUTPUT
        options = screen._display_port_options([("USB HS  /dev/ttyACM0", "/dev/ttyACM0")])
        assert options == [("USB HS  /dev/ttyACM0", "/dev/ttyACM0")]

    def test_mode_from_select_value_accepts_usb_output(self) -> None:
        screen = LaunchScreen()
        assert screen._mode_from_select_value("usb_output") is TransportMode.USB_OUTPUT
        assert screen._mode_from_select_value("usb") is TransportMode.USB_OUTPUT


# ---------------------------------------------------------------------------
# action_quit
# ---------------------------------------------------------------------------


class TestActionQuit:
    def test_action_quit_dismisses_with_none(self) -> None:
        screen = LaunchScreen()
        screen.dismiss = MagicMock()  # type: ignore[method-assign]

        screen.action_quit()

        screen.dismiss.assert_called_once_with(None)
