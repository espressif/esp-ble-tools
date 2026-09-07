# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""UI-facing capture session wrapper around the backend pipeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import time

from textual.message import Message

from src.backend.models import CaptureFinished
from src.backend.models import CaptureReport
from src.backend.models import TransportConfig
from src.backend.models import UserNotice
from src.backend.pipeline.controller import CapturePipelineResult
from src.backend.pipeline import CapturePipeline
from src.backend.io import WriterConfig
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.capture_report import build_capture_report
from src.frontend.capture_report import report_path_for_capture
from src.frontend.capture_report import write_capture_report
from src.i18n import tr

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
        self._transport_config = transport_config
        self._join_timeout_sec = join_timeout_sec
        self._event_presenter = CaptureEventPresenter(output_path, debug=debug)
        self._pipeline = CapturePipeline(
            transport_config,
            WriterConfig(output_path),
        )
        self._finished = False
        self._stop_requested = False
        self._report: CaptureReport | None = None
        self._started_at = datetime.now().astimezone()
        self._started_monotonic = time.monotonic()

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

    @property
    def report(self) -> CaptureReport | None:
        return self._report

    def start(self) -> tuple[Message, ...]:
        try:
            self._pipeline.start()
        except Exception as e:
            self._finished = True
            result = CapturePipelineResult(
                raw_paths=(),
                reader_error=str(e),
                writer_error=None,
                parser_error=None,
                aggregator_error=None,
                parse_backlog=False,
                raw_bytes=0,
                parser_raw_bytes=0,
                parser_frames=0,
                parser_carried_bytes=0,
                completed=False,
            )
            return (UserNotice(tr('Failed to start capture: {message}', message=e), level='warning'),) + self._finish_result(result)
        return ()

    def poll(self) -> tuple[Message, ...]:
        if self._finished:
            return ()

        messages = self._event_presenter.handle_events(self._pipeline.drain_events())
        if self._pipeline.is_alive():
            return messages

        return messages + self._finish()

    def stop(self) -> None:
        if not self._finished and not self._stop_requested:
            self._stop_requested = True
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
        return self._event_presenter.handle_events(events) + self._finish_result(result)

    def _finish_result(self, result: CapturePipelineResult) -> tuple[Message, ...]:
        self._event_presenter.finish()
        ended_at = datetime.now().astimezone()
        report = build_capture_report(
            result,
            self._transport_config,
            started_at=self._started_at,
            ended_at=ended_at,
            duration_sec=time.monotonic() - self._started_monotonic,
            console_log_paths=self._event_presenter.state.saved_console_log_paths,
            report_path=report_path_for_capture(self._output_path),
        )
        messages: list[Message] = []
        try:
            write_capture_report(report)
        except OSError as e:
            report = replace(report, report_write_error=str(e))
            messages.append(UserNotice(tr('Capture report could not be saved: {message}', message=e), level='warning'))
        self._report = report
        messages.append(CaptureFinished(report))
        return tuple(messages)
