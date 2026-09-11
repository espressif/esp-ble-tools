# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Modal screen showing available keyboard shortcuts.

Pushed by the 'h' keybinding; dismissed by Escape or 'h' again.
"""

from rich import box
from rich.table import Table
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static

from src.frontend.rendering import normalize_display_text
from src.frontend.rendering import table_ascii_box
from src.frontend.rendering import table_safe_box
from src.frontend.rendering import terminal_border_style

_SHORTCUTS = [
    ('q', 'Stop & review; exit from report'),
    ('c', 'Clear log'),
    ('s', 'Toggle auto-scroll'),
    ('d', 'Frame statistics'),
    ('m', 'Buffer utilization'),
    ('h', 'This help screen'),
    ('r', 'Reset chip'),
]

WINDOWS_SAFE_BOX = table_safe_box()
WINDOWS_ASCII_BOX = table_ascii_box()


def _build_shortcut_table() -> Table:
    """Build a Rich Table listing all keyboard shortcuts."""
    kwargs = {'title': 'Keyboard Shortcuts', 'expand': True, 'safe_box': WINDOWS_SAFE_BOX}
    if WINDOWS_ASCII_BOX:
        kwargs['box'] = box.ASCII
    table = Table(**kwargs)
    table.add_column('Key', style='cyan', no_wrap=True)
    table.add_column('Action')

    for key, action in _SHORTCUTS:
        table.add_row(key, action)

    return table


class ShortcutScreen(ModalScreen):
    """Modal overlay showing available keyboard shortcuts."""

    DEFAULT_CSS = """
    ShortcutScreen {
        align: center middle;
    }

    ShortcutScreen > Static {
        width: 60;
        max-height: 80%;
        background: $surface;
        padding: 1 2;
        border: __BORDER_STYLE__ $accent;
    }
    """.replace('__BORDER_STYLE__', terminal_border_style())

    BINDINGS = [
        Binding('escape', 'dismiss', 'Close'),
        Binding('h', 'dismiss', 'Close'),
        Binding('H', 'dismiss', show=False),
    ]

    def compose(self) -> ComposeResult:
        table = _build_shortcut_table()
        content = Static()
        content.update(table)
        yield content
        yield Static(normalize_display_text('[dim]Press Escape to return[/dim]'))
