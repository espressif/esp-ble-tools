# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""UI-facing capture session wrapper around the backend pipeline."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from textual.message import Message

from src.backend.io import WriterConfig
from src.backend.models import CaptureFinished, CaptureReport, TransportConfig, UserNotice
from src.backend.pipeline import CapturePipeline
from src.backend.pipeline.controller import IO_SHUTDOWN_TIMEOUT_SEC, CapturePipelineResult
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.capture_report import build_capture_report, report_path_for_capture
from src.frontend.recording_files import RecordingFiles
from src.i18n import tr

PIPELINE_JOIN_TIMEOUT_SEC = 2.0
ANALYSIS_DRAIN_TIMEOUT_SEC = 20.0


class CaptureSession:
    """Bridge backend pipeline events into frontend messages."""

    def __init__(
        self,
        transport_config: TransportConfig,
        output_path: Path,
        *,
        debug: bool = False,
        log_database: Path | None = None,
        show_logs: frozenset[str] = frozenset(),
        join_timeout_sec: float = PIPELINE_JOIN_TIMEOUT_SEC,
        analysis_drain_timeout_sec: float = ANALYSIS_DRAIN_TIMEOUT_SEC,
        io_shutdown_timeout_sec: float = IO_SHUTDOWN_TIMEOUT_SEC,
        clock=time.monotonic,
    ) -> None:
        self._output_path = output_path
        self._transport_config = transport_config
        self._join_timeout_sec = join_timeout_sec
        self._analysis_drain_timeout_sec = analysis_drain_timeout_sec
        self._clock = clock
        self._event_presenter = CaptureEventPresenter(
            output_path, debug=debug, mode=transport_config.mode, show_logs=show_logs
        )
        self._log_database = log_database
        self._files: RecordingFiles | None = None
        self._pipeline = CapturePipeline(
            transport_config,
            WriterConfig(output_path),
            log_database=log_database,
            io_shutdown_timeout_sec=io_shutdown_timeout_sec,
            clock=clock,
        )
        self._stop_requested = False
        self._analysis_drain_started_at: float | None = None
        self._started_at = datetime.now().astimezone()
        self._started_monotonic = self._clock()

    @property
    def finished(self) -> bool:
        return self._files is not None

    @property
    def is_running(self) -> bool:
        return not self.finished

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
        return self._files.report if self._files else None

    def start(self) -> tuple[Message, ...]:
        try:
            self._pipeline.start()
        except Exception as e:
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
            return (
                UserNotice(tr("Failed to start recording: {message}", message=e), level="warning"),
            ) + self._finish_result(result)
        return ()

    def poll(self) -> tuple[Message, ...]:
        if self.finished:
            return ()

        events = self._pipeline.drain_events()
        events.extend(self._pipeline.check_io_shutdown())
        messages = self._event_presenter.handle_events(events)
        if self._pipeline.io_is_alive():
            return messages

        if self._pipeline.analysis_is_alive():
            now = self._clock()
            if self._analysis_drain_started_at is None:
                self._analysis_drain_started_at = now
            if now - self._analysis_drain_started_at < self._analysis_drain_timeout_sec:
                return messages
            self._pipeline.abort_analysis(
                tr(
                    "Live quality check did not finish within {seconds:g} seconds.",
                    seconds=self._analysis_drain_timeout_sec,
                )
            )
            if self._pipeline.analysis_is_alive():
                return messages + (
                    UserNotice(
                        tr("Recording processes could not be stopped; completion is still pending."), level="warning"
                    ),
                )

        return messages + self._finish()

    def stop(self) -> None:
        if not self.finished and not self._stop_requested:
            self._stop_requested = True
            self._pipeline.stop()

    def reset_target(self) -> bool:
        if self.finished:
            return False
        self._pipeline.reset_target()
        return True

    def _finish(self) -> tuple[Message, ...]:
        events, result = self._pipeline.wait_with_events(self._join_timeout_sec)
        return self._event_presenter.handle_events(events) + self._finish_result(result)

    def _finish_result(self, result: CapturePipelineResult) -> tuple[Message, ...]:
        messages: list[Message] = list(self._event_presenter.finish())
        ended_at = datetime.now().astimezone()
        presenter_state = self._event_presenter.state
        report = build_capture_report(
            result,
            self._transport_config,
            started_at=self._started_at,
            ended_at=ended_at,
            duration_sec=self._clock() - self._started_monotonic,
            console_log_paths=presenter_state.saved_console_log_paths,
            report_path=report_path_for_capture(self._output_path),
            console_log_error=presenter_state.console_log_error,
            hci_paths=presenter_state.hci_paths,
            hci_error=presenter_state.hci_error,
        )
        database = self._log_database if result.raw_bytes and result.raw_paths else None
        self._files = RecordingFiles(report, self._output_path, database)
        saved = self._files.report
        if saved.report_write_error:
            messages.append(
                UserNotice(
                    tr("Recording report could not be saved: {message}", message=saved.report_write_error),
                    level="warning",
                )
            )
        messages.append(CaptureFinished(saved))
        return tuple(messages)
