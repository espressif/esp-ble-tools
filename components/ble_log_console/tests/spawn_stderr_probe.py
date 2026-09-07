# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import multiprocessing
from pathlib import Path
import sys
from unittest.mock import patch

import src.app as app_module


class CapturedStderr(io.StringIO):
    def fileno(self) -> int:
        return -1


class SpawnCaptureSession:
    finished = True

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> tuple[object, ...]:
        queue = multiprocessing.get_context('spawn').Queue()
        try:
            real_stderr = sys.__stderr__
            assert real_stderr is not None
            assert sys.stderr.fileno() == real_stderr.fileno()
            sys.stderr.write('delegated')
        finally:
            queue.close()
            queue.join_thread()
        return ()


class WidgetStub:
    def clear(self) -> None:
        pass


class ProbeApp(app_module.BLELogApp):
    _widget = WidgetStub()

    def query_one(self, *args: object, **kwargs: object) -> WidgetStub:
        return self._widget

    def run_probe(self) -> None:
        self._output_path = Path('unused.bin')
        self._start_capture()

    def _publish_view_messages(self, messages: tuple[object, ...]) -> None:
        pass


def main() -> None:
    capture = CapturedStderr()
    original_stderr = sys.stderr
    with patch.object(app_module, 'CaptureSession', SpawnCaptureSession):
        sys.stderr = capture
        try:
            ProbeApp(port='test').run_probe()
            assert sys.stderr is capture
            assert capture.getvalue() == 'delegated'
        finally:
            sys.stderr = original_stderr


if __name__ == '__main__':
    main()
