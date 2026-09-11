# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import sys
from pathlib import Path



def _load_rendering_module():
    path = Path(__file__).resolve().parents[1] / 'src' / 'frontend' / 'rendering.py'
    spec = importlib.util.spec_from_file_location('rendering_under_test', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rendering = _load_rendering_module()


def test_windows_uses_ascii_border(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')

    assert rendering.use_windows_safe_rendering()
    assert rendering.terminal_border_style() == 'ascii'
    assert rendering.table_safe_box()
    assert rendering.table_ascii_box()
    assert 'SelectCurrent' in rendering.launch_screen_safe_css()


def test_launch_control_css_stabilizes_control_height(monkeypatch):
    monkeypatch.setenv('BLE_LOG_CONSOLE_ASCII', '1')

    css = rendering.launch_control_css()

    assert 'LaunchScreen Select > SelectCurrent' in css
    assert 'height: 3' in css
    assert '#refresh-btn' in css
    assert 'LaunchScreen Button' not in css


def test_launch_safe_css_keeps_focus_styles_narrow(monkeypatch):
    monkeypatch.setenv('BLE_LOG_CONSOLE_ASCII', '1')

    css = rendering.launch_screen_safe_css()

    assert 'Select.-expanded > SelectCurrent' in css
    assert 'max-height: 8' in css
    assert 'LaunchScreen Button' not in css


def test_non_windows_uses_solid_border(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(rendering.os, 'name', 'posix')
    monkeypatch.delenv('OS', raising=False)
    monkeypatch.delenv('WT_SESSION', raising=False)
    monkeypatch.delenv('ANSICON', raising=False)
    monkeypatch.delenv('ConEmuANSI', raising=False)
    monkeypatch.delenv('BLE_LOG_CONSOLE_ASCII', raising=False)

    assert not rendering.use_windows_safe_rendering()
    assert rendering.terminal_border_style() == 'solid'
    assert not rendering.table_safe_box()
    assert not rendering.table_ascii_box()
    assert rendering.launch_screen_safe_css() == ''


def test_windows_terminal_env_uses_ascii_border(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(rendering.os, 'name', 'posix')
    monkeypatch.setenv('WT_SESSION', '1')

    assert rendering.use_windows_safe_rendering()
    assert rendering.terminal_border_style() == 'ascii'


def test_ascii_rendering_env_override(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(rendering.os, 'name', 'posix')
    monkeypatch.setenv('BLE_LOG_CONSOLE_ASCII', '1')

    assert rendering.use_windows_safe_rendering()

    monkeypatch.setenv('BLE_LOG_CONSOLE_ASCII', '0')

    assert not rendering.use_windows_safe_rendering()


def test_normalize_console_text_removes_layout_controls():
    text = 'abc\r\nnext\tcol\x08\x00done'

    assert rendering.normalize_console_text(text) == 'abc\nnext    coldone'


def test_normalize_display_text_replaces_unstable_punctuation(monkeypatch):
    monkeypatch.setenv('BLE_LOG_CONSOLE_ASCII', '1')

    assert rendering.normalize_display_text('a—b–c…') == 'a--b-c...'


def test_keep_sgr_ansi_sequences_removes_cursor_controls():
    text = '\x1b[31mred\x1b[0m\x1b[2J\x1b[Hdone'

    assert rendering.keep_sgr_ansi_sequences(text) == '\x1b[31mred\x1b[0mdone'


def test_strip_ansi_sequences_removes_sgr_and_controls():
    text = '\x1b[31mred\x1b[0m\x1b[2Jdone'

    assert rendering.strip_ansi_sequences(text) == 'reddone'
