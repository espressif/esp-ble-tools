# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from console import cli
from src.app import BLELogApp
from src.backend.support.transport.base import PortScan
from src.preferences import load_log_database, load_log_dir, save_log_database, save_log_dir


@pytest.mark.parametrize("contents", [b"", b"relative/path", b"/bad\x00path", b"\xff"])
def test_invalid_preferences_use_default(tmp_path, monkeypatch, contents):
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "last_log_dir.txt").write_bytes(contents)
    assert BLELogApp()._log_dir == tmp_path / "logs"


def test_failed_update_preserves_previous_directory(tmp_path, monkeypatch):
    def refuse_replace(*args):
        raise PermissionError("read only")

    save_log_dir(tmp_path / "previous")
    with monkeypatch.context() as context:
        context.setattr(Path, "replace", refuse_replace)
        save_log_dir(tmp_path / "new")
    assert load_log_dir() == tmp_path / "previous"
    assert len(list((tmp_path / "settings").iterdir())) == 1


@pytest.mark.parametrize("option", ["--log-dir", "--output"])
def test_explicit_cli_directory_overrides_memory(tmp_path, monkeypatch, option):
    save_log_dir(tmp_path / "remembered")
    selected = tmp_path / "explicit"
    argument = selected / "old.bin" if option == "--output" else selected
    observed = []
    monkeypatch.setattr(BLELogApp, "run", lambda app: observed.append(app._log_dir))
    result = CliRunner().invoke(cli, [option, str(argument)])
    assert result.exit_code == 0, result.output
    assert observed == [selected]
    assert load_log_dir() == tmp_path / "remembered"


@pytest.mark.parametrize("failure", ["storage", "pipeline", "preferences"])
def test_start_failures_and_unwritable_preferences(tmp_path, failure):
    previous = tmp_path / "previous"
    save_log_dir(previous)
    previous_db = tmp_path / "previous_db"
    previous_db.mkdir()
    (previous_db / "BLE_HOST_logs.json").write_text('{"logs": {}}')
    save_log_database(previous_db)
    selected_db = tmp_path / "new_db"
    selected_db.mkdir()
    (selected_db / "BLE_HOST_logs.json").write_text('{"logs": {}}')
    chosen = tmp_path / "chosen"
    if failure == "storage":
        chosen.write_bytes(b"not a directory")
    if failure == "preferences":
        (tmp_path / "settings" / "last_log_dir.txt").unlink()
        (tmp_path / "settings" / "last_log_database.txt").unlink()
        (tmp_path / "settings").rmdir()
        (tmp_path / "settings").write_bytes(b"not a directory")

    async def run():
        with (
            patch(
                "src.frontend.launch_screen.list_transport_port_scan", return_value=PortScan(options=[("test", "test")])
            ),
            patch("src.frontend.capture_session.CapturePipeline") as pipeline,
        ):
            pipeline.return_value.io_is_alive.return_value = True
            pipeline.return_value.drain_events.return_value = []
            pipeline.return_value.check_io_shutdown.return_value = []
            if failure == "pipeline":
                pipeline.return_value.start.side_effect = OSError("cannot start")
            app = BLELogApp(port="test", log_dir=chosen, log_database=selected_db)
            async with app.run_test(size=(120, 55)) as pilot:
                await pilot.pause()
                if failure == "preferences":
                    assert not app._capture_session.finished
                elif failure == "pipeline":
                    assert load_log_dir() == chosen
                    assert load_log_database() == selected_db
                else:
                    assert load_log_dir() == previous
                    assert load_log_database() == previous_db

    asyncio.run(run())


def test_database_is_remembered_and_explicit_choice_wins(tmp_path, monkeypatch):
    db = tmp_path / "dictionary"
    db.mkdir()
    (db / "BLE_HOST_logs.json").write_text('{"logs": {}}')
    save_log_database(db)
    monkeypatch.chdir(tmp_path)
    assert BLELogApp()._log_database == db
    assert BLELogApp(log_database=tmp_path / "explicit")._log_database == tmp_path / "explicit"
    assert load_log_database() == db
    save_log_database(None)
    assert load_log_database(default=db) is None
    (db / "BLE_HOST_logs.json").unlink()
    save_log_database(db)
    assert load_log_database() is None
