# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Status panel widget — docked to bottom, shows live stats.

See Spec Section 11.
"""

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from src.backend.models import FrameStats
from src.backend.models import format_bitrate
from src.backend.models import format_bytes
from src.frontend.rendering import terminal_border_style


def _format_speed(bits_per_sec: float) -> str:
    return format_bitrate(bits_per_sec)  # type: ignore[no-any-return]


def _customer_state_markup(s: FrameStats, disconnected: bool) -> str:
    if disconnected:
        return '[bold red]DISCONNECTED[/bold red]'
    if s.transport.rx_bits_per_sec > 0 or s.transport.fps > 0:
        return '[bold green]RECEIVING[/bold green]'
    if s.transport.rx_bytes > 0:
        return '[yellow]IDLE[/yellow]'
    return '[cyan]CONNECTED[/cyan]'


def _compact_customer_state_markup(s: FrameStats, disconnected: bool) -> str:
    if disconnected:
        return '[bold red]DISC[/bold red]'
    if s.transport.rx_bits_per_sec > 0 or s.transport.fps > 0:
        return '[bold green]RECV[/bold green]'
    if s.transport.rx_bytes > 0:
        return '[yellow]IDLE[/yellow]'
    return '[cyan]CONN[/cyan]'


COMPACT_STATUS_WIDTH = 56
MEDIUM_STATUS_WIDTH = 88


class StatusPanel(Widget):
    DEFAULT_CSS = """
    StatusPanel {
        dock: bottom;
        height: 3;
        border-top: __BORDER_STYLE__ $accent;
        padding: 0 1;
    }
    """.replace('__BORDER_STYLE__', terminal_border_style())

    stats: reactive[FrameStats] = reactive(FrameStats)
    disconnected: reactive[bool] = reactive(False)

    def render(self) -> Text:
        s = self.stats
        width = self.size.width
        if self.disconnected:
            if width < COMPACT_STATUS_WIDTH:
                line1 = _compact_customer_state_markup(s, self.disconnected)
                line2 = 'Transport closed'
            else:
                line1 = f'Status: {_customer_state_markup(s, self.disconnected)}'
                line2 = 'Backend stopped - transport connection closed'
            return Text.from_markup(f'{line1}\n{line2}')

        t = s.transport
        loss = s.loss
        loss_style = 'red' if loss.total_frames > 0 else 'yellow'

        if width < COMPACT_STATUS_WIDTH:
            line1 = f'{_compact_customer_state_markup(s, self.disconnected)} | RX {format_bytes(t.rx_bytes)}'
            line2 = (
                f'{_format_speed(t.rx_bits_per_sec)} | '
                f'[{loss_style}]Lost {loss.total_frames}[/{loss_style}]'
            )
        elif width < MEDIUM_STATUS_WIDTH:
            line1 = (
                f'Status: {_customer_state_markup(s, self.disconnected)} | '
                f'[bold]h[/bold]: help'
            )
            line2 = (
                f'RX: {format_bytes(t.rx_bytes)}  '
                f'Frames: {t.rx_frames}  '
                f'Speed: {_format_speed(t.rx_bits_per_sec)}  '
                f'[{loss_style}]Lost: {loss.total_frames}[/{loss_style}]'
            )
        else:
            line1 = (
                f'Status: {_customer_state_markup(s, self.disconnected)} | '
                f'Press [bold]h[/bold] for help'
            )
            line2 = (
                f'RX: {format_bytes(t.rx_bytes)}  '
                f'Frames: {t.rx_frames}  '
                f'Speed: {_format_speed(t.rx_bits_per_sec)}  '
                f'Max: {_format_speed(t.max_rx_bits_per_sec)}  '
                f'Rate: {t.fps:.0f} fps  '
                f'[{loss_style}]Lost: {loss.total_frames} frames, {format_bytes(loss.total_bytes)}[/{loss_style}]'
            )

        return Text.from_markup(f'{line1}\n{line2}')
