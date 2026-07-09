# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Launch Screen — interactive setup for transport mode, port, and log directory.

Shown on startup when --port is not provided via CLI.
Dismissed with a LaunchConfig result on Connect, or None on quit.
"""

from pathlib import Path

from textual import on
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import Label
from textual.widgets import Select
from textual_fspicker import SelectDirectory

from src.backend.models import LaunchConfig
from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.support.transport import list_transport_modes
from src.backend.support.transport import list_transport_port_options
from src.frontend.rendering import launch_control_css
from src.frontend.rendering import launch_screen_safe_css
from src.frontend.rendering import launch_width_stable_css
from src.frontend.rendering import terminal_border_style

BAUD_RATES: list[int] = [115200, 230400, 460800, 921600, 1500000, 2000000, 3000000]
DEFAULT_BAUD_RATE: int = 3000000
DEFAULT_TRANSPORT_MODE = TransportMode.UART
SPI_PORT_LABEL_PREFIX = 'SPI-BRIDGE'
MAX_PORT_LABEL_LEN = 36


def _mode_select_value(mode: TransportMode) -> str:
    if mode is TransportMode.SPI_USB_BRIDGE:
        return 'spi'
    return mode.value


class LaunchScreen(Screen[LaunchConfig | None]):
    """Interactive setup screen for BLE Log Console."""

    DEFAULT_CSS = """
    LaunchScreen {
        align: center middle;
    }

    #launch-container {
        width: 90%;
        max-width: 60;
        height: auto;
        max-height: 80%;
        overflow-y: auto;
        background: $surface;
        padding: 1 2;
        border: __BORDER_STYLE__ $accent;
    }

    #launch-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
    }

    .field-row {
        width: 100%;
        height: auto;
        align: center middle;
    }

    #mode-select,
    #baud-select {
        width: 100%;
    }

    #port-select {
        width: 1fr;
        min-width: 0;
    }

    #dir-input {
        width: 1fr;
        min-width: 0;
    }

    #refresh-btn {
        width: 15;
        min-width: 15;
        max-width: 15;
        text-align: center;
    }

    #browse-btn {
        width: 18;
        min-width: 18;
        max-width: 18;
        text-align: center;
    }

    #connect-btn {
        margin-top: 2;
    }

    __LAUNCH_CONTROL_CSS__

    #no-ports-label {
        color: $warning;
    }
    __WINDOWS_SAFE_WIDGET_CSS__
    __LAUNCH_WIDTH_STABLE_CSS__
    """.replace('__BORDER_STYLE__', terminal_border_style()).replace(
        '__LAUNCH_CONTROL_CSS__',
        launch_control_css(),
    ).replace(
        '__WINDOWS_SAFE_WIDGET_CSS__',
        launch_screen_safe_css(),
    ).replace(
        '__LAUNCH_WIDTH_STABLE_CSS__',
        launch_width_stable_css(),
    )

    BINDINGS = [
        Binding('q', 'quit', 'Quit'),
        Binding('Q', 'quit', show=False),
        Binding('ctrl+c', 'quit', show=False, priority=True),
    ]

    def __init__(self, default_log_dir: Path | None = None) -> None:
        super().__init__()
        self._mode = DEFAULT_TRANSPORT_MODE
        self._default_log_dir = default_log_dir or Path.cwd()/ "logs"

    def compose(self) -> ComposeResult:
        mode_options = [(label, _mode_select_value(mode)) for label, mode in list_transport_modes()]
        raw_port_options = list_transport_port_options(self._mode)
        port_options = self._display_port_options(raw_port_options)
        baud_options = [(str(b), b) for b in BAUD_RATES]

        with Vertical(id='launch-container'):
            yield Label('BLE Log Console Setup', id='launch-title')

            yield Label('Transport Mode', classes='field-label')
            yield Select(mode_options, value=_mode_select_value(self._mode), id='mode-select')

            yield Label('Port', classes='field-label')
            with Horizontal(classes='field-row'):
                if port_options:
                    yield Select(port_options, value=port_options[0][1], id='port-select')
                else:
                    yield Select([], id='port-select', prompt='No ports detected')
                yield Button('Refresh', id='refresh-btn')

            yield Label('Baud Rate', classes='field-label', id='baud-label')
            yield Select(baud_options, value=DEFAULT_BAUD_RATE, id='baud-select')

            yield Label('Log Directory', classes='field-label')
            with Horizontal(classes='field-row'):
                yield Input(str(self._default_log_dir), id='dir-input')
                yield Button('Browse...', id='browse-btn')

            with Center():
                yield Button('Connect', variant='primary', id='connect-btn')

    def on_mount(self) -> None:
        self._sync_mode_fields()

    @on(Button.Pressed, '#refresh-btn')
    def refresh_ports(self) -> None:
        """Re-scan current transport ports and update the Select widget."""
        self._refresh_port_options()

    @on(Select.Changed, '#mode-select')
    def transport_mode_changed(self, event: Select.Changed) -> None:
        """Refresh visible setup fields when the transport mode changes."""
        mode = self._mode_from_select_value(event.value)
        if mode is None:
            return
        self._mode = mode
        self._refresh_port_options()
        self._sync_mode_fields()

    def _sync_mode_fields(self) -> None:
        show_baud = self._mode is TransportMode.UART
        try:
            self.query_one('#baud-label', Label).display = show_baud
            self.query_one('#baud-select', Select).display = show_baud
        except NoMatches:
            return

    def _refresh_port_options(self) -> None:
        try:
            raw_port_options = list_transport_port_options(self._mode)
            port_options = self._display_port_options(raw_port_options)
        except Exception as e:
            self.notify(f'Failed to list ports: {e}')
            port_options = []

        try:
            port_select = self.query_one('#port-select', Select)
        except NoMatches:
            return
        port_select.set_options(port_options)
        if port_options:
            port_select.value = port_options[0][1]

    def _truncate_port_label(self, label: str) -> str:
        if len(label) <= MAX_PORT_LABEL_LEN:
            return label
        return f'{label[: MAX_PORT_LABEL_LEN - 3]}...'

    def _display_port_options(self, port_options: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if self._mode is TransportMode.SPI_USB_BRIDGE:
            return [
                (self._truncate_port_label(f'{SPI_PORT_LABEL_PREFIX}  {value}'), value)
                for _, value in port_options
            ]
        return [(self._truncate_port_label(label), value) for label, value in port_options]

    def _mode_from_select_value(self, value: object) -> TransportMode | None:
        if value is Select.BLANK:
            return None
        value_text = str(value)
        for label, mode in list_transport_modes():
            if value_text in (_mode_select_value(mode), mode.value, label):
                return mode
        try:
            return TransportMode(value_text)
        except ValueError:
            self.notify(f"Unsupported transport mode: {value_text}'\n"
                        "Please select the right mode.")
            return None

    @on(Button.Pressed, '#browse-btn')
    @work
    async def browse_directory(self) -> None:
        """Open a directory picker dialog."""
        current = self.query_one('#dir-input', Input).value
        start = Path(current) if current else Path.cwd()
        if not start.is_dir():
            start = Path.cwd()
        chosen = await self.app.push_screen_wait(SelectDirectory(location=start))
        if chosen is not None:
            self.query_one('#dir-input', Input).value = str(chosen)

    @on(Button.Pressed, '#connect-btn')
    def connect(self) -> None:
        """Validate and return config."""
        port_select = self.query_one('#port-select', Select)
        dir_input = self.query_one('#dir-input', Input)

        if port_select.value is Select.BLANK:
            self.notify('Please select a port', severity='error')
            return

        baudrate = DEFAULT_BAUD_RATE
        if self._mode is TransportMode.UART:
            baud_select = self.query_one('#baud-select', Select)
            if baud_select.value is Select.BLANK:
                self.notify('Please select a baud rate', severity='error')
                return
            baudrate = int(baud_select.value)  # type: ignore[arg-type]  # guarded above

        log_dir = Path(dir_input.value)
        port = str(port_select.value)
        transport_config = TransportConfig(
            mode=self._mode,
            label=port,
            port=port,
            baudrate=baudrate,
        )

        config = LaunchConfig(
            transport_config=transport_config,
            log_dir=log_dir,
        )
        self.dismiss(config)

    def action_quit(self) -> None:
        self.dismiss(None)
