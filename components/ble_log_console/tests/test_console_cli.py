# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from click.testing import CliRunner

from console import cli


def test_cli_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ['--help'])

    assert result.exit_code == 0
    assert '[uart|spi]' in result.output
    assert 'spi_usb_bridge' not in result.output


def test_ports_help_exposes_only_user_transport_modes() -> None:
    result = CliRunner().invoke(cli, ['ports', '--help'])

    assert result.exit_code == 0
    assert '[uart|spi]' in result.output
    assert 'spi_usb_bridge' not in result.output
