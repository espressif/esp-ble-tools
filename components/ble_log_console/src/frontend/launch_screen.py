# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Interactive setup for transport mode, port, and log directory.

Shown at startup without --port or when the log directory or recording file cannot be created.
Dismissed with a LaunchConfig result on Connect, or None on quit.
"""

from pathlib import Path
from typing import ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select
from textual_fspicker import SelectDirectory

from src.backend.models import LaunchConfig, TransportConfig, TransportMode
from src.backend.support.transport import PortIssue, PortScan, list_transport_modes, list_transport_port_scan
from src.frontend.port_diagnostics import describe_port_issues
from src.frontend.rendering import (
    launch_control_css,
    launch_screen_safe_css,
    launch_width_stable_css,
    terminal_border_style,
)
from src.i18n import get_language, set_language, tr

BAUD_RATES: list[int] = [115200, 230400, 460800, 921600, 1500000, 2000000, 3000000, 4000000, 5000000]
DEFAULT_BAUD_RATE: int = 3000000
DEFAULT_TRANSPORT_MODE = TransportMode.UART
SPI_PORT_LABEL_PREFIX = "SPI-BRIDGE"
MAX_PORT_LABEL_LEN = 36


def find_log_database() -> Path | None:
    """Find the Host dictionary in the working directory, without recursive guessing."""
    for directory in (Path.cwd() / "ble_log_database", Path.cwd()):
        if (directory / "BLE_HOST_logs.json").is_file():
            return directory
    return None


def _mode_select_value(mode: TransportMode) -> str:
    if mode is TransportMode.SPI_USB_BRIDGE:
        return "spi"
    if mode in (TransportMode.USB_OUTPUT, TransportMode.USJ):
        return "usb"
    return mode.value


class LaunchScreen(Screen[LaunchConfig | None]):
    """Interactive setup screen for BLE Log Console."""

    DEFAULT_CSS = (
        """
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
    #baud-select,
    #language-select {
        width: 100%;
    }

    #port-select {
        width: 1fr;
        min-width: 0;
    }

    #dir-input,
    #database-input {
        width: 1fr;
        min-width: 0;
    }

    #refresh-btn {
        width: 15;
        min-width: 15;
        max-width: 15;
        text-align: center;
    }

    #browse-btn,
    #database-browse-btn {
        width: 18;
        min-width: 18;
        max-width: 18;
        text-align: center;
    }

    #connect-btn {
        margin-top: 2;
    }

    __LAUNCH_CONTROL_CSS__

    #port-diagnostic-label {
        color: $warning;
        width: 100%;
        height: auto;
        text-wrap: wrap;
    }

    #start-error {
        width: 100%;
        height: auto;
        color: $error;
        margin-top: 1;
    }
    __WINDOWS_SAFE_WIDGET_CSS__
    __LAUNCH_WIDTH_STABLE_CSS__
    """.replace("__BORDER_STYLE__", terminal_border_style())
        .replace(
            "__LAUNCH_CONTROL_CSS__",
            launch_control_css(),
        )
        .replace(
            "__WINDOWS_SAFE_WIDGET_CSS__",
            launch_screen_safe_css(),
        )
        .replace(
            "__LAUNCH_WIDTH_STABLE_CSS__",
            launch_width_stable_css(),
        )
    )

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("Q", "quit", show=False),
        Binding("ctrl+c", "quit", show=False, priority=True),
    ]

    def __init__(
        self,
        default_log_dir: Path | None = None,
        *,
        default_transport_config: TransportConfig | None = None,
        log_database: Path | None = None,
        start_error: str | None = None,
    ) -> None:
        super().__init__()
        self._default_transport_config = default_transport_config
        self._start_error = start_error
        self._log_database = log_database
        self._mode = default_transport_config.mode if default_transport_config is not None else DEFAULT_TRANSPORT_MODE
        if self._mode is TransportMode.USJ:
            self._mode = TransportMode.USB_OUTPUT
        self._port_modes: dict[str, TransportMode] = {}
        self._default_log_dir = default_log_dir or Path.cwd() / "logs"
        self._port_issues: list[PortIssue] = []

    def _port_diagnostic_label(self, issues: list[PortIssue]) -> Label:
        """The reason a device that is plugged in is absent from the list."""
        label = Label("", id="port-diagnostic-label")
        self._show_port_issues(label, issues)
        return label

    def _show_port_issues(self, label: Label, issues: list[PortIssue]) -> None:
        text = "\n".join(describe_port_issues(issues))
        label.display = bool(text)
        if text:
            label.update(text)

    def _refresh_port_diagnostics(self) -> None:
        try:
            label = self.query_one("#port-diagnostic-label", Label)
        except NoMatches:
            return
        self._show_port_issues(label, self._port_issues)

    def compose(self) -> ComposeResult:
        mode_options = [
            (label, _mode_select_value(mode)) for label, mode in list_transport_modes() if mode is not TransportMode.USJ
        ]
        port_options = self._list_port_options()
        config = self._default_transport_config
        baudrate = config.baudrate if config is not None else DEFAULT_BAUD_RATE
        baud_options = [(str(b), b) for b in sorted(set(BAUD_RATES) | {baudrate})]
        port = port_options[0][1] if port_options else Select.NULL
        if config is not None:
            port = config.port

        with Vertical(id="launch-container"):
            yield Label("BLE Log Console Setup", id="launch-title")
            if self._start_error is not None:
                yield Label(self._start_error, markup=False, id="start-error")

            yield Label("Language / 语言", classes="field-label")
            yield Select(
                (("English", "en"), ("简体中文", "zh_CN")),
                value=get_language(),
                allow_blank=False,
                id="language-select",
            )

            yield Label("Transport Mode", classes="field-label")
            yield Select(mode_options, value=_mode_select_value(self._mode), id="mode-select")

            yield Label("Port", classes="field-label")
            with Horizontal(classes="field-row"):
                if port_options:
                    yield Select(port_options, value=port, id="port-select")
                else:
                    yield Select([], id="port-select", prompt="No ports detected")
                yield Button("Refresh", id="refresh-btn")
            yield self._port_diagnostic_label(self._port_issues)

            yield Label("Baud Rate", classes="field-label", id="baud-label")
            yield Select(baud_options, value=baudrate, id="baud-select")

            yield Label("Log Directory", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(str(self._default_log_dir), id="dir-input")
                yield Button("Browse...", id="browse-btn")

            yield Label(tr("Log Database (optional)"), classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(
                    str(self._log_database) if self._log_database else "",
                    id="database-input",
                    placeholder=tr("Empty: skip compressed Host logs"),
                )
                yield Button("Browse...", id="database-browse-btn")

            with Center():
                yield Button("Connect", variant="primary", id="connect-btn")

    def on_mount(self) -> None:
        self._sync_mode_fields()

    @on(Select.Changed, "#language-select")
    def language_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.NULL:
            set_language(str(event.value))
            # The diagnostics were rendered in the previous language.
            self._refresh_port_diagnostics()

    @on(Button.Pressed, "#refresh-btn")
    def refresh_ports(self) -> None:
        """Re-scan current transport ports and update the Select widget."""
        self._refresh_port_options()

    @on(Select.Changed, "#mode-select")
    def transport_mode_changed(self, event: Select.Changed) -> None:
        """Refresh visible setup fields when the transport mode changes."""
        mode = self._mode_from_select_value(event.value)
        if mode is None or mode is self._mode:
            return
        self._mode = mode
        self._refresh_port_options()
        self._sync_mode_fields()

    def _sync_mode_fields(self) -> None:
        show_baud = self._mode is TransportMode.UART
        try:
            self.query_one("#baud-label", Label).display = show_baud
            self.query_one("#baud-select", Select).display = show_baud
        except NoMatches:
            return

    def _list_port_options(self) -> list[tuple[str, str]]:
        self._port_modes.clear()
        self._port_issues.clear()
        raw_port_options = []
        modes = (
            (TransportMode.USB_OUTPUT, TransportMode.USJ) if self._mode is TransportMode.USB_OUTPUT else (self._mode,)
        )
        for mode in modes:
            try:
                scan = list_transport_port_scan(mode)
                self._port_issues.extend(scan.issues)
                options = scan.options
            except Exception as error:
                self.notify(tr("Failed to list ports: {message}", message=error))
                continue
            for label, port in options:
                if mode is TransportMode.USB_OUTPUT:
                    label = label.replace("USB", "USB OTG", 1)
                raw_port_options.append((label, port))
                self._port_modes[port] = mode
        return self._display_port_options(raw_port_options)

    def _refresh_port_options(self) -> None:
        port_options = self._list_port_options()
        try:
            port_select = self.query_one("#port-select", Select)
            diagnostic_label = self.query_one("#port-diagnostic-label", Label)
        except NoMatches:
            return
        selected = port_select.value
        port_select.set_options(port_options)
        if port_options:
            port_select.value = selected if selected in [value for _, value in port_options] else port_options[0][1]
        self._show_port_issues(diagnostic_label, self._port_issues)

    def _truncate_port_label(self, label: str) -> str:
        if len(label) <= MAX_PORT_LABEL_LEN:
            return label
        return f"{label[: MAX_PORT_LABEL_LEN - 3]}..."

    def _display_port_options(self, port_options: list[tuple[str, str]]) -> list[tuple[str, str]]:
        config = self._default_transport_config
        if (
            config is not None
            and _mode_select_value(self._mode) == _mode_select_value(config.mode)
            and config.port not in [value for _, value in port_options]
        ):
            port_options = [*port_options, (config.label, config.port)]
            self._port_modes[config.port] = config.mode
        if self._mode is TransportMode.SPI_USB_BRIDGE:
            return [
                (self._truncate_port_label(f"{SPI_PORT_LABEL_PREFIX}  {value}"), value) for _, value in port_options
            ]
        return [(self._truncate_port_label(label), value) for label, value in port_options]

    def _mode_from_select_value(self, value: object) -> TransportMode | None:
        if value is Select.NULL:
            return None
        value_text = str(value)
        for label, mode in list_transport_modes():
            if value_text in (_mode_select_value(mode), mode.value, label):
                return mode
        try:
            return TransportMode(value_text)
        except ValueError:
            self.notify(tr("Unsupported transport mode: {mode}\nPlease select the right mode.", mode=value_text))
            return None

    @on(Button.Pressed, "#browse-btn")
    @work
    async def browse_directory(self) -> None:
        """Open a directory picker dialog."""
        current = self.query_one("#dir-input", Input).value
        start = Path(current) if current else Path.cwd()
        if not start.is_dir():
            start = Path.cwd()
        chosen = await self.app.push_screen_wait(SelectDirectory(location=start))
        if chosen is not None:
            self.query_one("#dir-input", Input).value = str(chosen)

    @on(Button.Pressed, "#database-browse-btn")
    @work
    async def browse_database(self) -> None:
        current = self.query_one("#database-input", Input).value.strip()
        start = Path(current).expanduser() if current else Path.cwd()
        chosen = await self.app.push_screen_wait(SelectDirectory(location=start if start.is_dir() else Path.cwd()))
        if chosen is not None:
            self.query_one("#database-input", Input).value = str(chosen)

    @on(Button.Pressed, "#connect-btn")
    def connect(self) -> None:
        """Validate and return config."""
        port_select = self.query_one("#port-select", Select)
        dir_input = self.query_one("#dir-input", Input)

        if port_select.value is Select.NULL:
            self.notify(tr("Please select a port"), severity="error")
            return

        default_config = self._default_transport_config
        baudrate = (
            default_config.baudrate
            if default_config is not None and _mode_select_value(self._mode) == _mode_select_value(default_config.mode)
            else DEFAULT_BAUD_RATE
        )
        if self._mode is TransportMode.UART:
            baud_select = self.query_one("#baud-select", Select)
            if baud_select.value is Select.NULL:
                self.notify(tr("Please select a baud rate"), severity="error")
                return
            baudrate = int(baud_select.value)  # type: ignore[arg-type]  # guarded above

        log_dir = Path(dir_input.value)
        port = str(port_select.value)
        transport_config = TransportConfig(
            mode=self._port_modes.get(port, self._mode),
            label=port,
            port=port,
            baudrate=baudrate,
        )

        database_text = self.query_one("#database-input", Input).value.strip()
        database = Path(database_text).expanduser().resolve() if database_text else None
        if database is not None and not (database / "BLE_HOST_logs.json").is_file():
            self.notify(tr("Select a directory containing BLE_HOST_logs.json, or leave it empty."), severity="error")
            return

        config = LaunchConfig(
            transport_config=transport_config,
            log_dir=log_dir,
            log_database=database,
        )
        self.dismiss(config)

    def action_quit(self) -> None:
        self.dismiss(None)
