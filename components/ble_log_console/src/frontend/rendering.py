# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Terminal rendering helpers shared by Textual widgets."""

from __future__ import annotations

import re
import os
import sys


ANSI_ESCAPE_RE = re.compile(r'\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])')
SGR_ANSI_RE = re.compile(r'\x1b\[[0-9;:]*m')
CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]')
WINDOWS_TEXT_TRANSLATION = str.maketrans(
    {
        '—': '--',
        '–': '-',
        '…': '...',
    }
)


def use_windows_safe_rendering() -> bool:
    """Return True when the current terminal should avoid wide Unicode decorations."""
    override = os.environ.get('BLE_LOG_CONSOLE_ASCII')
    if override is not None:
        return override.lower() not in {'0', 'false', 'no', 'off'}
    return (
        sys.platform == 'win32'
        or os.name == 'nt'
        or os.environ.get('OS') == 'Windows_NT'
        or 'WT_SESSION' in os.environ
        or 'ANSICON' in os.environ
        or 'ConEmuANSI' in os.environ
    )


def terminal_border_style() -> str:
    """Return the shared Textual border style used on every platform."""
    override = os.environ.get('BLE_LOG_CONSOLE_ASCII')
    if override is not None and override.lower() not in {'0', 'false', 'no', 'off'}:
        return 'ascii'
    return 'solid'


def launch_control_css() -> str:
    """Use one border layer and one row height for selects, inputs, and side buttons."""
    border = terminal_border_style()
    return f"""
    LaunchScreen Select {{
        border: none;
        padding: 0;
        height: auto;
    }}

    LaunchScreen Select > SelectCurrent {{
        border: {border} $accent;
        padding: 0 1;
        height: 3;
        min-height: 3;
        max-height: 3;
        content-align: left middle;
    }}

    LaunchScreen Input {{
        border: {border} $accent;
        padding: 0 1;
        height: 3;
        min-height: 3;
        max-height: 3;
        content-align: left middle;
    }}

    #refresh-btn,
    #browse-btn {{
        padding: 0 1;
        height: 3;
        min-height: 3;
        max-height: 3;
        text-align: center;
        content-align: center middle;
    }}
    """


def launch_width_stable_css() -> str:
    """Lock launch-screen horizontal layout without changing height or borders."""
    arrow_css = ''
    if use_windows_safe_rendering():
        arrow_css = """
    LaunchScreen SelectCurrent .arrow,
    LaunchScreen SelectCurrent .down-arrow,
    LaunchScreen SelectCurrent .up-arrow,
    LaunchScreen Select.-expanded .up-arrow {
        display: none;
        width: 0;
        height: 0;
        padding: 0;
    }
    """
    return f"""
    #launch-container {{
        width: 60;
        min-width: 60;
        max-width: 60;
    }}

    #mode-select,
    #baud-select {{
        width: 100%;
        min-width: 0;
    }}

    #port-select {{
        width: 1fr;
        min-width: 0;
    }}

    LaunchScreen SelectCurrent Static#label {{
        width: 1fr;
        min-width: 0;
    }}

    LaunchScreen Select > SelectOverlay {{
        width: 100%;
        min-width: 0;
        overlay: screen;
    }}
    {arrow_css}
    """


def launch_screen_safe_css() -> str:
    """Return launch-screen focus styles for selects and inputs."""
    border = terminal_border_style()
    return f"""
    LaunchScreen Select.-expanded > SelectCurrent,
    LaunchScreen Select:focus > SelectCurrent,
    LaunchScreen Input:focus {{
        border: {border} $border;
        background-tint: $foreground 5%;
    }}

    LaunchScreen Select.-expanded > SelectOverlay {{
        border: {border} $border;
        max-height: 8;
    }}
    """


def table_safe_box() -> bool:
    """Return whether Rich tables should use legacy-safe box drawing."""
    override = os.environ.get('BLE_LOG_CONSOLE_ASCII')
    if override is not None:
        return override.lower() not in {'0', 'false', 'no', 'off'}
    return False


def table_ascii_box() -> bool:
    """Return whether Rich tables should force pure ASCII borders."""
    return table_safe_box()


def normalize_console_text(text: str) -> str:
    """Remove terminal control characters that can corrupt Textual layout."""
    normalized = text.replace('\r\n', '\n').replace('\r', '')
    normalized = normalized.expandtabs(4)
    return CONTROL_CHAR_RE.sub('', normalized)


def normalize_display_text(text: str) -> str:
    """Normalize static UI text that may render at unstable widths on Windows."""
    if use_windows_safe_rendering():
        return text.translate(WINDOWS_TEXT_TRANSLATION)
    return text


def keep_sgr_ansi_sequences(text: str) -> str:
    """Keep ANSI SGR styling while removing cursor/control escape sequences."""
    return ANSI_ESCAPE_RE.sub(lambda match: match.group(0) if SGR_ANSI_RE.fullmatch(match.group(0)) else '', text)


def strip_ansi_sequences(text: str) -> str:
    """Remove ANSI escapes when Rich's ANSI parser is unavailable."""
    return ANSI_ESCAPE_RE.sub('', text)
