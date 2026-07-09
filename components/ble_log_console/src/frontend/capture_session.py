# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""UI-facing capture session wrapper around the backend pipeline."""

from __future__ import annotations

from pathlib import Path

from textual.message import Message

from src.backend.models import BackendStopped
from src.backend.models import TransportConfig
from src.backend.models import UserNotice
from src.backend.pipeline import CapturePipeline
from src.backend.io import WriterConfig
from src.frontend.capture_events import CaptureEventPresenter

PIPELINE_JOIN_TIMEOUT_SEC = 2.0


class CaptureSession:
    """Bridge backend pipeline events into frontend messages."""

    def __init__(
        self,
        transport_config: TransportConfig,
        output_path: Path,
        *,
        debug: bool = False,
        join_timeout_sec: float = PIPELINE_JOIN_TIMEOUT_SEC,
    ) -> None:
        self._output_path = output_path
        self._join_timeout_sec = join_timeout_sec
        self._event_presenter = CaptureEventPresenter(output_path, debug=debug)
        self._pipeline = CapturePipeline(
            transport_config,
            WriterConfig(output_path),
        )
        self._finished = False

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def is_running(self) -> bool:
        return not self._finished and self._pipeline is not None

    @property
    def saved_capture_path(self) -> Path | None:
        return self._event_presenter.state.saved_capture_path

    @property
    def saved_capture_paths(self) -> list[Path]:
        return list(self._event_presenter.state.saved_capture_paths)

    @property
    def saved_console_log_path(self) -> Path | None:
        return self._event_presenter.state.saved_console_log_path

    @property
    def saved_console_log_paths(self) -> list[Path]:
        return list(self._event_presenter.state.saved_console_log_paths)

    def start(self) -> tuple[Message, ...]:
        try:
            self._pipeline.start()
        except Exception as e:
            self._finished = True
            return (
                UserNotice(f'Failed to start capture: {e}', level='warning'),
                BackendStopped(str(e)),
            )
        return ()

    def poll(self) -> tuple[Message, ...]:
        if self._finished:
            return ()

        messages = self._event_presenter.handle_events(self._pipeline.drain_events())
        if self._pipeline.is_alive():
            return messages

        return messages + self._finish()

    def stop(self) -> None:
        if not self._finished:
            self._pipeline.stop()

    def reset_target(self) -> bool:
        if self._finished:
            return False
        self._pipeline.reset_target()
        return True

    def _finish(self) -> tuple[Message, ...]:
        if self._finished:
            return ()
        self._finished = True
        events, result = self._pipeline.wait_with_events(self._join_timeout_sec)
        return self._event_presenter.handle_events(events) + self._event_presenter.handle_result(result)
