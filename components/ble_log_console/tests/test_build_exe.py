# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace
from unittest.mock import Mock

import build_exe
import pytest
from build_exe import PROJECT_VERSION_RE, _replace_document_versions


def test_replace_document_versions() -> None:
    text = """Version: v9.8.7
ble_log_console_windows_v9.8.7.exe
ble_log_console_ubuntu_v9.8.7
"""

    assert (
        _replace_document_versions(text, "1.0.5")
        == """Version: v1.0.5
ble_log_console_windows_v1.0.5.exe
ble_log_console_ubuntu_v1.0.5
"""
    )
    assert PROJECT_VERSION_RE.sub('version = "1.0.5"', 'version = "9.8.7"') == 'version = "1.0.5"'


def test_windows_build_includes_serial_backend_and_all_native_engines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dist").mkdir()
    monkeypatch.setattr(build_exe.sys, "platform", "win32")
    monkeypatch.setattr(build_exe, "_parse_args", lambda: SimpleNamespace(version="1.1.0", bump_patch=False))
    imported = Mock()
    monkeypatch.setattr(build_exe.importlib, "import_module", imported)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(build_exe.subprocess, "run", run)
    monkeypatch.setattr(build_exe, "_write_version", Mock())
    monkeypatch.setattr(build_exe, "_sync_version_references", Mock())

    build_exe.main()

    command = run.call_args.args[0]
    excluded = {command[i + 1] for i, value in enumerate(command) if value == "--exclude-module"}
    hidden = {command[i + 1] for i, value in enumerate(command) if value == "--hidden-import"}
    assert {"usb", "tools.spi_bulk_transport"} <= excluded
    assert not any(module == "usb" or module.startswith("usb.") for module in hidden)
    assert "serial.serialwin32" in command and "serial.win32" in command
    assert "serial.tools.list_ports_windows" in command
    assert "serial.tools.list_ports_linux" not in command and "serial.tools.list_ports_osx" not in command
    assert set(build_exe.NATIVE_MODULES) <= set(command)
    assert [call.args[0] for call in imported.call_args_list] == list(build_exe.NATIVE_MODULES)
    assert (tmp_path / "dist/artifact_name.txt").read_text().strip() == "ble_log_console_windows_v1.1.0.exe"


def test_missing_native_engine_stops_packaging_before_version_updates(monkeypatch):
    monkeypatch.setattr(build_exe, "_parse_args", lambda: SimpleNamespace(version="1.1.0", bump_patch=False))
    monkeypatch.setattr(build_exe.importlib, "import_module", Mock(side_effect=ImportError("missing native engine")))
    run = Mock()
    write_version = Mock()
    monkeypatch.setattr(build_exe.subprocess, "run", run)
    monkeypatch.setattr(build_exe, "_write_version", write_version)

    with pytest.raises(RuntimeError, match="MSVC"):
        build_exe.main()

    run.assert_not_called()
    write_version.assert_not_called()
