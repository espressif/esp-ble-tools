# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import errno
from pathlib import Path
from unittest.mock import MagicMock, patch

import usb.core
from click.testing import CliRunner
from console import _echo_paths, cli
from src.i18n import set_language

from tests.helpers import usb_bridge_device


def _invoke_ports(language: str = "en") -> str:
    try:
        set_language(language)
        result = CliRunner().invoke(cli, ["ports", "--mode", "spi"])
    finally:
        set_language("en")
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "[uart|spi|usb|usj]" in result.output
    assert "spi_usb_bridge" not in result.output


def test_ports_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ["ports", "--help"])

    assert result.exit_code == 0
    assert "[uart|spi|usb|usj]" in result.output
    assert "spi_usb_bridge" not in result.output


@patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
@patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
def test_ports_names_the_missing_permission_rule_and_the_fix(mock_find: MagicMock, _mock_windows: MagicMock) -> None:
    mock_find.return_value = [
        usb_bridge_device(bus=1, address=8, open_error=usb.core.USBError("Access denied", errno=errno.EACCES))
    ]

    output = _invoke_ports()

    assert "(none)" in output
    assert (
        "  SPI Bridge (bus 1, addr 8): no USB access permission. "
        "Run this tool once with sudo (no arguments), then replug the bridge.\n"
    ) in output
    assert "udev" not in output


@patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
@patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
def test_ports_prints_the_chinese_hint_for_a_bridge_without_permission(
    mock_find: MagicMock, _mock_windows: MagicMock
) -> None:
    mock_find.return_value = [
        usb_bridge_device(bus=1, address=8, open_error=usb.core.USBError("Access denied", errno=errno.EACCES))
    ]

    output = _invoke_ports("zh_CN")

    assert (
        "  SPI Bridge（bus 1，addr 8）：没有 USB 访问权限。请用 sudo 运行一次本工具（不带参数），然后重新拔插 Bridge。\n"
        in (output)
    )


@patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
@patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
def test_ports_names_the_missing_libusb_backend(mock_find: MagicMock, _mock_windows: MagicMock) -> None:
    mock_find.side_effect = usb.core.NoBackendError("No backend available")

    output = _invoke_ports()

    assert "(none)" in output
    assert "  libusb-1.0 not found. Install it first: sudo apt install libusb-1.0-0\n" in output


@patch("src.backend.support.transport.spi_usb_bridge_transport._is_windows", return_value=False)
@patch("src.backend.support.transport.spi_usb_bridge_transport.usb.core.find")
def test_ports_still_lists_a_healthy_bridge_without_a_diagnostic(
    mock_find: MagicMock, _mock_windows: MagicMock
) -> None:
    mock_find.return_value = [usb_bridge_device(bus=1, address=8)]

    output = _invoke_ports()

    assert "--port 1:8:0:129" in output
    assert "no USB access permission" not in output
    assert "libusb" not in output


def test_single_path_output_names_the_file_without_claiming_a_saved_recording(capsys) -> None:
    _echo_paths("Recording file", [Path("/logs/ble_log_20260101_120000.bin")])

    assert capsys.readouterr().out == "Recording file: /logs/ble_log_20260101_120000.bin\n"


def test_multi_part_output_lists_the_files_without_claiming_a_saved_recording(capsys) -> None:
    paths = [Path(f"/logs/ble_log_20260101_120000_part{index:03d}.bin") for index in (2, 3)]

    _echo_paths("Recording file", paths)

    output = capsys.readouterr().out
    assert output.splitlines()[0] == "Recording file: 2 files"
    assert "saved" not in output
    assert all(str(path) in output for path in paths)


def test_cli_passes_explicit_host_database(tmp_path, monkeypatch) -> None:
    from unittest.mock import MagicMock

    (tmp_path / "BLE_HOST_logs.json").write_text("{}")
    app = MagicMock()
    monkeypatch.setattr("src.app.BLELogApp", app)
    monkeypatch.setattr("console._should_auto_install_udev", lambda ctx: False)
    result = CliRunner().invoke(cli, ["--log-database", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert app.call_args.kwargs["log_database"] == tmp_path
    app.return_value.run.assert_called_once()


def test_cli_rejects_directory_without_host_dictionary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("console._should_auto_install_udev", lambda ctx: False)
    result = CliRunner().invoke(cli, ["--log-database", str(tmp_path)])
    assert result.exit_code == 2
    assert "BLE_HOST_logs.json" in result.output
