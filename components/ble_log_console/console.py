# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""BLE Log Console entry point.

Usage:
    python console.py                        # interactive setup
    python console.py --port /dev/ttyUSB0  --baudrate 3000000   # direct connect
    python console.py --mode spi --port cdc:/dev/ttyACM0
    python console.py --mode spi --port 1:8:0:129
    python console.py ports                  # list transport endpoints
    python console.py ls                     # list saved files
"""

from datetime import datetime
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

import click
from src.backend.models import format_bytes
from src.backend.models import TransportMode
from src.backend.support.transport.spi_usb_bridge_transport import PRODUCT_ID
from src.backend.support.transport.spi_usb_bridge_transport import VENDOR_ID
from src.backend.support.transport.registry import get_transport_provider
from src.backend.support.transport.registry import list_transport_modes
from src.backend.support.transport.registry import list_transport_port_options
from src.backend.support.transport.uart_transport import validate_uart_port

MODE_CHOICES = ('uart', 'spi')
UDEV_RULE_PATH = Path('/etc/udev/rules.d/99-ble-log-spi-bridge.rules')
UDEV_RULE = (
    f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{VENDOR_ID:04x}", '
    f'ATTR{{idProduct}}=="{PRODUCT_ID:04x}", MODE="0666", TAG+="uaccess"\n'
)


def _parse_transport_mode(mode: str) -> TransportMode:
    normalized = mode.lower()
    if normalized == 'spi':
        return TransportMode.SPI_USB_BRIDGE
    return TransportMode(normalized)


def _mode_cli_name(mode: TransportMode) -> str:
    if mode is TransportMode.SPI_USB_BRIDGE:
        return 'spi'
    return mode.value


def _endpoint_display_label(mode: TransportMode, label: str, value: str) -> str:
    if mode is TransportMode.SPI_USB_BRIDGE:
        return f'SPI-BRIDGE  {value}'
    return label


def _should_auto_install_udev(ctx: click.Context) -> bool:
    return (
        sys.platform == 'linux'
        and hasattr(os, 'geteuid')
        and os.geteuid() == 0
        and ctx.invoked_subcommand is None
        and len(sys.argv) == 1
    )


def _echo_saved_paths(label: str, paths: list[Path]) -> None:
    if not paths:
        return
    if len(paths) == 1:
        click.echo(f'{label} saved to: {paths[0]}')
        return

    click.echo(f'{label} saved to {len(paths)} files:')
    if len(paths) <= 5:
        for saved_path in paths:
            click.echo(f'  {saved_path}')
        return

    same_dir = all(saved_path.parent == paths[0].parent for saved_path in paths)
    if same_dir:
        first = paths[0]
        last = paths[-1]
        pattern = f'{first.stem}*{first.suffix}'
        click.echo(f'  Directory: {first.parent}')
        click.echo(f'  First:     {first.name}')
        click.echo(f'  Last:      {last.name}')
        click.echo(f'  Pattern:   {pattern}')
    else:
        click.echo(f'  First: {paths[0]}')
        click.echo(f'  Last:  {paths[-1]}')


def _install_udev_rules() -> None:
    try:
        already_installed = UDEV_RULE_PATH.exists() and UDEV_RULE_PATH.read_text(encoding='utf-8') == UDEV_RULE
    except OSError:
        already_installed = False

    if not already_installed:
        try:
            UDEV_RULE_PATH.write_text(UDEV_RULE, encoding='utf-8')
        except OSError as e:
            raise click.ClickException(f'Failed to write {UDEV_RULE_PATH}: {e}') from e

    for cmd in (
        ('udevadm', 'control', '--reload-rules'),
        ('udevadm', 'trigger'),
    ):
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            raise click.ClickException(f'Command failed: {" ".join(cmd)}')

    click.echo(f'Installed Linux USB permission rule: {UDEV_RULE_PATH}')
    click.echo('Unplug and replug the USB-SPI bridge, then run ble_log_console without sudo.')


@click.group(invoke_without_command=True)
@click.option(
    '--mode',
    '-m',
    type=click.Choice(MODE_CHOICES, case_sensitive=False),
    default='uart',
    show_default=True,
    help='Transport mode.',
)
@click.option(
    '--port',
    '-p',
    default=None,
    help='Transport endpoint. UART: /dev/ttyUSB0, SPI Bridge: cdc:/dev/ttyACM0 or bus:addr:intf:ep.',
)
@click.option('--baudrate', '-b', type=int, default=3_000_000, show_default=True, help='UART baud rate.')
@click.option('--debug', is_flag=True, help='Show internal traffic and firmware state events in the log view.')
@click.option(
    '--log-dir', '-d', type=click.Path(), default=None, help='Log save directory. Default: current working directory.'
)
@click.option(
    '--output',
    '-o',
    type=click.Path(),
    default=None,
    hidden=True,
    help='[Deprecated] Output binary file path. Use --log-dir instead.',
)
@click.pass_context
def cli(
    ctx: click.Context,
    mode: str,
    port: str | None,
    baudrate: int,
    debug: bool,
    log_dir: str | None,
    output: str | None,
) -> None:
    """BLE Log Console — real-time BLE log monitor."""
    if _should_auto_install_udev(ctx):
        _install_udev_rules()
        return

    if ctx.invoked_subcommand is not None:
        return

    # Resolve log directory
    resolved_log_dir: Path | None = None
    if output is not None:
        # Legacy --output: treat as full file path, use its parent as log_dir
        click.echo(
            'Warning: --output is deprecated and the filename is ignored. '
            'Use --log-dir instead. Saving to directory: ' + str(Path(output).parent),
            err=True,
        )
        resolved_log_dir = Path(output).parent
    elif log_dir is not None:
        resolved_log_dir = Path(log_dir)

    transport_mode = _parse_transport_mode(mode)

    if port is not None and transport_mode is TransportMode.UART:
        error = validate_uart_port(port)
        if error:
            raise click.BadParameter(error, param_hint="'--port'")

    from src.app import BLELogApp

    app = BLELogApp(
        mode=transport_mode,
        port=port,
        baudrate=baudrate,
        log_dir=resolved_log_dir,
        debug=debug,
    )
    app.run()
    _echo_saved_paths('Capture', app.saved_capture_paths)
    _echo_saved_paths('Console log', app.saved_console_log_paths)


@cli.command(name='ports')
@click.option(
    '--mode',
    '-m',
    type=click.Choice(MODE_CHOICES, case_sensitive=False),
    default=None,
    help='Only list endpoints for one transport mode.',
)
def list_ports(mode: str | None) -> None:
    """List available transport endpoints."""
    modes = [_parse_transport_mode(mode)] if mode is not None else [item[1] for item in list_transport_modes()]

    for index, transport_mode in enumerate(modes):
        if index > 0:
            click.echo()
        provider = get_transport_provider(transport_mode)
        click.echo(f'{provider.label}:')

        try:
            options = list_transport_port_options(transport_mode)
        except Exception as e:
            click.echo(f'  Failed to list endpoints: {e}')
            continue

        if not options:
            click.echo('  (none)')
            continue

        for label, value in options:
            click.echo(f'  {_endpoint_display_label(transport_mode, label, value)}')
            click.echo(f'    use: --mode {_mode_cli_name(transport_mode)} --port {value}')


@cli.command(name='ls')
@click.option(
    '--dir',
    '-d',
    'log_dir',
    type=click.Path(exists=True),
    default=None,
    help='Directory to list. Default: current directory.',
)
def list_files(log_dir: str | None) -> None:
    """List saved binary capture files."""
    search_dir = Path(log_dir) if log_dir else Path.cwd()

    files = sorted(search_dir.glob('ble_log_*.bin'), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        click.echo(f'No captures found in {search_dir}')
        return

    click.echo(f'Captures in {search_dir}:\n')
    for f in files:
        size = f.stat().st_size
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        size_str = format_bytes(size)
        click.echo(f'  {mtime}  {size_str:>10}  {f.name}')


if __name__ == '__main__':
    multiprocessing.freeze_support()
    cli()
