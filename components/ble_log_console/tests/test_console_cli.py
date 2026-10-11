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


def test_ports_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ["ports", "--help"])

    assert result.exit_code == 0
    assert "[uart|spi|usb|usj]" in result.output
    assert "spi_usb_bridge" not in result.output


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
