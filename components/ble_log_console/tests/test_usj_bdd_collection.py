# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Check actual USJ BDD collection without POSIX modules, not native Windows execution."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("missing", ["fcntl", "termios", "pty", "fcntl,termios,pty"])
def test_missing_posix_modules_skip_only_virtual_port_scenarios(tmp_path: Path, missing: str) -> None:
    component = Path(__file__).resolve().parents[1]
    script = """
import builtins
import importlib.abc
import sys
import console
import pytest
import src.frontend.launch_screen
import textual.app
import textual.widgets
if sys.platform != 'win32':
    import textual.drivers.linux_driver

real_import = builtins.__import__
missing = set(sys.argv[1].split(','))
class MissingModules(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in missing:
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
for name in missing:
    sys.modules.pop(name, None)
sys.meta_path.insert(0, MissingModules())
def denied(name, *args, **kwargs):
    if name.split('.')[0] in missing:
        raise ModuleNotFoundError(f"No module named '{name}'", name=name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = denied
raise SystemExit(pytest.main([
    '-p', 'no:cacheprovider', '-v', 'tests/test_usj_output_bdd.py', '--basetemp=' + sys.argv[2],
]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, missing, str(tmp_path / "pytest")],
        cwd=component,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "collected 10 items" in output
    assert "4 passed, 6 skipped" in output
    for scenario in (
        "枚举时只认_usj_身份",
        "usj_模式不按串口波特率推算线速",
        "命令行用_usj_选择该模式其他模式不变",
        "启动界面选择_usj_后隐藏波特率并原样传出端口",
    ):
        assert any(scenario in line and "PASSED" in line for line in output.splitlines()), output
