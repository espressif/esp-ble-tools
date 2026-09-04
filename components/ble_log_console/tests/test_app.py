# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys

import pytest

from src.app import _spawn_stderr_with_real_fileno


@pytest.mark.skipif(sys.platform == 'win32', reason='requires the POSIX multiprocessing resource tracker')
def test_capture_start_uses_real_stderr_fd_for_spawn() -> None:
    project_root = Path(__file__).resolve().parents[1]
    probe = Path(__file__).with_name('spawn_stderr_probe.py')

    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_spawn_stderr_proxy_restores_stream_after_error(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', capture)

    with pytest.raises(RuntimeError, match='start failed'):
        with _spawn_stderr_with_real_fileno():
            assert sys.stderr is not capture
            sys.stderr.write('delegated')
            raise RuntimeError('start failed')

    assert sys.stderr is capture
    assert capture.getvalue() == 'delegated'


def test_spawn_stderr_proxy_leaves_other_streams_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    class ValidStderr:
        def fileno(self) -> int:
            return 2

    class NoFileno:
        pass

    for stream in (ValidStderr(), NoFileno()):
        monkeypatch.setattr(sys, 'stderr', stream)
        with _spawn_stderr_with_real_fileno():
            assert sys.stderr is stream
        assert sys.stderr is stream
