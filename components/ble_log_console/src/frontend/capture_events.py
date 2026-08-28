# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Presentation layer for capture pipeline events."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO
from typing import Any

from textual.message import Message

from src.backend.analysis.worker import AggregatorProcessEvent
from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.analysis.aggregator import AggregatorUpdate
from src.backend.pipeline.controller import CapturePipelineResult
from src.backend.io.writer import CAPTURE_PART_MAX_BYTES
from src.backend.io.writer import WriterEvent
from src.backend.io.reader import ReaderProcessEvent
from src.backend.analysis.worker import ParserStatus
from src.backend.models import BackendStopped
from src.backend.models import FrameLossDetected
from src.backend.models import InternalFrameDecoded
from src.backend.models import LogLine
from src.backend.models import StatsUpdated
from src.backend.models import UserNotice
from src.backend.models import format_bytes
from src.frontend.rendering import normalize_console_text
from src.frontend.rendering import strip_ansi_sequences

REDIR_LINE_BUFFER_LIMIT = 16 * 1024
REDIR_UI_BATCH_LINE_LIMIT = 128
CONSOLE_LOG_FLUSH_INTERVAL_SEC = 1.0
NO_DATA_WARNING_SEC = 10.0
NO_DATA_WARNING_COOLDOWN_SEC = 60.0
NO_FRAME_WARNING_SEC = 10.0
NO_FRAME_WARNING_COOLDOWN_SEC = 60.0
CAPTURE_NOTICE_THRESHOLDS = (
    100 * 1024,
    500 * 1024,
    1 * 1024 * 1024,
    10 * 1024 * 1024,
    50 * 1024 * 1024,
    100 * 1024 * 1024,
)
CAPTURE_NOTICE_STEP = 100 * 1024 * 1024

TextFileFactory = Callable[[Path], IO[str]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class CaptureEventState:
    """UI-owned capture state derived from pipeline events."""

    saved_capture_path: Path | None
    saved_capture_paths: tuple[Path, ...]
    saved_console_log_path: Path | None
    saved_console_log_paths: tuple[Path, ...]
    disconnected: bool


def console_log_part_path(base_path: Path, part_index: int) -> Path:
    """Return console log path matching legacy app naming."""

    suffix = '' if part_index <= 1 else f'_part{part_index:03d}'
    return base_path.with_name(f'{base_path.stem}_console{suffix}.log')


def _default_text_file_factory(path: Path) -> IO[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, 'w', encoding='utf-8', newline='\n')  # noqa: SIM115


def _flush_and_close_text_file(file_obj: IO[str]) -> None:
    try:
        file_obj.flush()
        try:
            os.fsync(file_obj.fileno())
        except OSError:
            pass
    finally:
        file_obj.close()


def _next_capture_notice_threshold(current: int) -> int:
    for threshold in CAPTURE_NOTICE_THRESHOLDS:
        if current < threshold:
            return threshold
    return current + CAPTURE_NOTICE_STEP


def _normalize_console_log_text(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return normalize_console_text(strip_ansi_sequences(text).replace('\x1b', ''))


def _format_receive_timestamp(received_at_ms: int) -> str:
    return datetime.fromtimestamp(received_at_ms / 1000).astimezone().isoformat(sep=' ', timespec='milliseconds')


class CaptureEventPresenter:
    """Translate capture pipeline events into existing Textual messages."""

    def __init__(
        self,
        output_path: Path,
        *,
        debug: bool = False,
        console_part_max_bytes: int = CAPTURE_PART_MAX_BYTES,
        text_file_factory: TextFileFactory = _default_text_file_factory,
        clock: Clock = time.monotonic,
    ) -> None:
        self._output_path = output_path
        self._debug = debug
        self._console_part_max_bytes = console_part_max_bytes
        self._text_file_factory = text_file_factory
        self._clock = clock
        self._saved_capture_paths: list[Path] = []
        self._saved_console_log_paths: list[Path] = []
        self._console_log_file: IO[str] | None = None
        self._console_log_path = console_log_part_path(output_path, 1)
        self._console_part_index = 1
        self._console_part_bytes = 0
        self._console_line_buf = ''
        self._console_line_prefixed = False
        self._console_line_received_at_ms = 0
        self._console_timestamp_pending = False
        self._redir_line_buf = ''
        self._disconnected = False
        now = self._clock()
        self._last_console_flush_at = now
        self._last_data_at = now
        self._last_frame_at = now
        self._last_idle_warning_at = 0.0
        self._last_frame_warning_at = 0.0
        self._last_captured_bytes = 0
        self._last_parser_frames = 0
        self._next_capture_notice = CAPTURE_NOTICE_THRESHOLDS[0]

    @property
    def state(self) -> CaptureEventState:
        return CaptureEventState(
            saved_capture_path=self._saved_capture_paths[-1] if self._saved_capture_paths else None,
            saved_capture_paths=tuple(self._saved_capture_paths),
            saved_console_log_path=self._saved_console_log_paths[-1] if self._saved_console_log_paths else None,
            saved_console_log_paths=tuple(self._saved_console_log_paths),
            disconnected=self._disconnected,
        )

    def handle_event(self, event: Any) -> tuple[Message, ...]:
        """Translate one pipeline event into UI messages."""

        if isinstance(event, AggregatorSnapshot):
            return self._handle_snapshot(event)
        if isinstance(event, AggregatorUpdate):
            return self._handle_aggregator_update(event)
        if isinstance(event, WriterEvent):
            return self._handle_writer_event(event)
        if isinstance(event, ReaderProcessEvent):
            return self._handle_reader_event(event)
        if isinstance(event, ParserStatus):
            return self._handle_parser_status(event)
        if isinstance(event, AggregatorProcessEvent):
            return self._handle_aggregator_status(event)
        return ()

    def handle_events(self, events: list[Any]) -> tuple[Message, ...]:
        """Translate a batch of pipeline events while preserving order."""

        messages: list[Message] = []
        for event in events:
            messages.extend(self.handle_event(event))
        return tuple(messages)

    def handle_result(self, result: CapturePipelineResult) -> tuple[Message, ...]:
        """Translate final pipeline result and close UI-owned sinks."""

        self.close()
        self._disconnected = True
        if result.completed:
            return (BackendStopped('Capture completed'),)

        errors = [
            result.reader_error,
            result.writer_error,
            result.parser_error,
            result.aggregator_error,
        ]
        reason = '; '.join(error for error in errors if error) or 'Capture stopped before completion'
        return (
            UserNotice(f'Capture failed: {reason}', level='warning'),
            BackendStopped(reason),
        )

    def close(self) -> None:
        """Flush and close UI-owned output files."""

        if self._console_log_file is None:
            return
        if self._console_line_buf.endswith('\r'):
            self._write_console_line(self._console_line_buf[:-1], self._console_line_received_at_ms, complete=True)
        else:
            self._write_console_line(self._console_line_buf, self._console_line_received_at_ms, complete=False)
        self._console_line_buf = ''
        _flush_and_close_text_file(self._console_log_file)
        self._console_log_file = None

    def _handle_snapshot(self, event: AggregatorSnapshot) -> tuple[Message, ...]:
        now = self._clock()
        messages: list[Message] = [
            StatsUpdated(
                event.stats,
                list(event.funnel_snapshots),
                list(event.buf_util_snapshots),
            )
        ]

        if event.captured_bytes > self._last_captured_bytes:
            self._last_data_at = now
        if event.parser_frames > self._last_parser_frames:
            self._last_frame_at = now

        self._last_captured_bytes = event.captured_bytes
        self._last_parser_frames = event.parser_frames

        if not self._debug:
            if (
                event.captured_bytes == 0
                and now - self._last_data_at >= NO_DATA_WARNING_SEC
                and now - self._last_idle_warning_at >= NO_DATA_WARNING_COOLDOWN_SEC
            ):
                messages.append(
                    UserNotice(
                        'No data received for 10s. Check transport mode, port, cable, and firmware logging.',
                        level='warning',
                    )
                )
                self._last_idle_warning_at = now

            if (
                event.captured_bytes > 0
                and now - self._last_frame_at >= NO_FRAME_WARNING_SEC
                and now - self._last_frame_warning_at >= NO_FRAME_WARNING_COOLDOWN_SEC
            ):
                messages.append(
                    UserNotice(
                        'Data is arriving, but no BLE log frames were decoded for 10s. '
                        'Check transport mode, wiring, and firmware log configuration.',
                        level='warning',
                    )
                )
                self._last_frame_warning_at = now

            while event.captured_bytes >= self._next_capture_notice:
                messages.append(
                    UserNotice(
                        f'Have captured {format_bytes(event.captured_bytes)}, {event.parser_frames} frames'
                    )
                )
                self._next_capture_notice = _next_capture_notice_threshold(self._next_capture_notice)

        return tuple(messages)

    def _handle_aggregator_update(self, event: AggregatorUpdate) -> tuple[Message, ...]:
        messages: list[Message] = []
        for internal in event.internal_frames:
            messages.append(InternalFrameDecoded(internal.int_src, internal.decoded))
        for loss in event.frame_losses:
            messages.append(
                FrameLossDetected(
                    loss.source_name,
                    loss.loss_type,
                    loss.lost_frames,
                    loss.lost_bytes,
                    sn_range=loss.sn_range,
                )
            )
        for redir in event.redir_events:
            messages.extend(self._write_redir_text(redir.text, redir.received_at_ms))
        return tuple(messages)

    def _handle_writer_event(self, event: WriterEvent) -> tuple[Message, ...]:
        if event.status is not None:
            self._saved_capture_paths = list(event.status.paths)

        if event.kind == 'opened' and event.status is not None and event.status.paths:
            return (LogLine(f'Saving to {event.status.paths[-1]}'),)
        if event.kind == 'rotated' and event.status is not None and event.status.paths:
            return (UserNotice(f'Capture file rotated to {event.status.paths[-1]}'),)
        if event.kind == 'error':
            return (UserNotice(f'Writer error: {event.message}', level='warning'),)
        return ()

    def _handle_reader_event(self, event: ReaderProcessEvent) -> tuple[Message, ...]:
        if event.kind == 'opened' and event.status is not None:
            return (UserNotice(f'Connected to {event.status.display_name}'),)
        if event.kind == 'parse_backlog':
            return (
                UserNotice(
                    event.message
                    or 'Realtime parser fell behind; raw capture continues, live stats may be incomplete.',
                    level='warning',
                ),
            )
        if event.kind == 'parse_backlog_summary' and event.parse_dropped_chunks:
            return (
                UserNotice(
                    'Realtime parser skipped '
                    f'{event.parse_dropped_chunks} chunks ({format_bytes(event.parse_dropped_bytes)}); '
                    'raw capture saved them, live stats are incomplete.',
                    level='warning',
                ),
            )
        if event.kind in {'reset_done', 'reset_unsupported'}:
            return (UserNotice(event.message),)
        if event.kind == 'reset_error':
            return (UserNotice(f'Reset failed: {event.message}', level='warning'),)
        if event.kind == 'error':
            return (UserNotice(f'Reader error: {event.message}', level='warning'),)
        return ()

    def _handle_parser_status(self, event: ParserStatus) -> tuple[Message, ...]:
        if event.kind == 'error':
            return (UserNotice(f'Parser error: {event.message}', level='warning'),)
        return ()

    def _handle_aggregator_status(self, event: AggregatorProcessEvent) -> tuple[Message, ...]:
        if event.kind == 'error':
            return (UserNotice(f'Aggregator error: {event.message}', level='warning'),)
        return ()

    def _write_redir_text(self, text: str, received_at_ms: int) -> list[Message]:
        messages: list[Message] = []
        self._console_timestamp_pending = not self._console_line_prefixed
        old_console_path_count = len(self._saved_console_log_paths)
        self._ensure_console_log_open()
        if len(self._saved_console_log_paths) > old_console_path_count and old_console_path_count > 0:
            messages.append(UserNotice(f'Console log rotated to {self._saved_console_log_paths[-1]}'))

        self._console_line_buf += text
        self._console_line_received_at_ms = received_at_ms
        while True:
            cr = self._console_line_buf.find('\r')
            lf = self._console_line_buf.find('\n')
            line_end = min(index for index in (cr, lf) if index >= 0) if cr >= 0 or lf >= 0 else -1
            if line_end < 0 or (line_end == len(self._console_line_buf) - 1 and cr == line_end):
                break
            separator_size = (
                2 if cr == line_end and self._console_line_buf[line_end : line_end + 2] == '\r\n' else 1
            )
            line = self._console_line_buf[:line_end]
            self._console_line_buf = self._console_line_buf[line_end + separator_size :]
            self._write_console_line(line, received_at_ms, complete=True)
        # ponytail: bound unterminated lines; add a streaming ANSI parser only if firmware emits larger lines.
        while len(self._console_line_buf) > REDIR_LINE_BUFFER_LIMIT:
            console_text = self._console_line_buf[:REDIR_LINE_BUFFER_LIMIT]
            self._console_line_buf = self._console_line_buf[REDIR_LINE_BUFFER_LIMIT:]
            self._write_console_line(console_text, received_at_ms, complete=False)

        self._redir_line_buf += text
        if '\n' in self._redir_line_buf:
            lines = self._redir_line_buf.split('\n')
            self._redir_line_buf = lines.pop()
            self._append_redir_log_lines(messages, lines)
        while len(self._redir_line_buf) > REDIR_LINE_BUFFER_LIMIT:
            messages.append(LogLine(self._redir_line_buf[:REDIR_LINE_BUFFER_LIMIT]))
            self._redir_line_buf = self._redir_line_buf[REDIR_LINE_BUFFER_LIMIT:]
        return messages

    def _write_console_line(self, text: str, received_at_ms: int, *, complete: bool) -> None:
        normalized = _normalize_console_log_text(text)
        if normalized and self._console_timestamp_pending and not self._console_line_prefixed:
            timestamp = _format_receive_timestamp(received_at_ms)
            self._append_console_log_text(f'[{timestamp}] ')
            self._console_line_prefixed = True
            self._console_timestamp_pending = False
        self._append_console_log_text(normalized)
        if complete:
            self._append_console_log_text('\n')
            self._console_line_prefixed = False

    def _append_console_log_text(self, text: str) -> None:
        if self._console_log_file is None or not text:
            return
        self._console_log_file.write(text)
        self._console_part_bytes += len(text.encode(errors='replace'))
        self._flush_console_log_if_due()

    def _append_redir_log_lines(self, messages: list[Message], lines: list[str]) -> None:
        non_empty_lines = [line for line in lines if line]
        for start in range(0, len(non_empty_lines), REDIR_UI_BATCH_LINE_LIMIT):
            batch = non_empty_lines[start : start + REDIR_UI_BATCH_LINE_LIMIT]
            if batch:
                messages.append(LogLine('\n'.join(batch)))

    def _flush_console_log_if_due(self) -> None:
        if self._console_log_file is None:
            return
        now = self._clock()
        if now - self._last_console_flush_at < CONSOLE_LOG_FLUSH_INTERVAL_SEC:
            return
        self._console_log_file.flush()
        self._last_console_flush_at = now

    def _ensure_console_log_open(self) -> None:
        if self._console_log_file is None:
            self._console_log_path = console_log_part_path(self._output_path, self._console_part_index)
            self._console_log_file = self._text_file_factory(self._console_log_path)
            self._last_console_flush_at = self._clock()
            self._saved_console_log_paths.append(self._console_log_path)
            return

        if self._console_part_bytes < self._console_part_max_bytes:
            return

        _flush_and_close_text_file(self._console_log_file)
        self._console_part_index += 1
        self._console_part_bytes = 0
        self._console_log_path = console_log_part_path(self._output_path, self._console_part_index)
        self._console_log_file = self._text_file_factory(self._console_log_path)
        self._last_console_flush_at = self._clock()
        self._saved_console_log_paths.append(self._console_log_path)
