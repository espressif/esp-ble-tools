# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from click.testing import CliRunner
from console import _echo_paths, cli


def test_cli_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "[uart|spi|usb|usj]" in result.output
    assert "spi_usb_bridge" not in result.output
    assert "bus:addr:intf:ep" not in result.output


def test_ports_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ["ports", "--help"])

    assert result.exit_code == 0
    assert "[uart|spi|usb|usj]" in result.output
    assert "spi_usb_bridge" not in result.output


def test_single_path_output_names_the_file_without_claiming_a_saved_recording(capsys) -> None:
    path = Path("/logs/ble_log_20260101_120000.bin")
    _echo_paths("Recording file", [path])

    assert capsys.readouterr().out == f"Recording file: {path}\n"


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
    result = CliRunner().invoke(cli, ["--log-database", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert app.call_args.kwargs["log_database"] == tmp_path
    app.return_value.run.assert_called_once()


def test_cli_rejects_directory_without_host_dictionary(tmp_path, monkeypatch) -> None:
    result = CliRunner().invoke(cli, ["--log-database", str(tmp_path)])
    assert result.exit_code == 2
    assert "BLE_HOST_logs.json" in result.output


def test_cli_defaults_to_no_live_logs_and_accepts_multiple_categories(monkeypatch) -> None:
    from unittest.mock import MagicMock

    app = MagicMock()
    monkeypatch.setattr("src.app.BLELogApp", app)
    for arguments, expected in [([], frozenset()), (["--show-log", "host", "--show-log", "hci"], {"host", "hci"})]:
        result = CliRunner().invoke(cli, arguments)
        assert result.exit_code == 0, result.output
        assert app.call_args.kwargs["show_logs"] == expected
    invalid = CliRunner().invoke(cli, ["--show-log", "unknown"])
    assert invalid.exit_code == 2
