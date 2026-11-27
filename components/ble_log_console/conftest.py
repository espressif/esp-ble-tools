# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def linux_serial_platform(monkeypatch):
    """Exercise Linux tty semantics independently of the test runner's OS."""
    monkeypatch.setattr("src.backend.support.transport.serial_reader.sys", SimpleNamespace(platform="linux"))


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    monkeypatch.setattr("src.preferences.get_app_dir", lambda name: str(tmp_path / "settings"))
