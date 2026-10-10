# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import errno
import io
import os
from datetime import datetime
from pathlib import Path

import pytest
from ble_log_frame_decoder import InternalLogInfo
from src.backend.analysis.aggregator import AggregatorSnapshot, AggregatorUpdate, InternalFrameUpdate
from src.backend.analysis.parser_events import RedirEvent
from src.backend.analysis.worker import AggregatorProcessEvent, ParserStatus
from src.backend.io.reader import ReaderProcessEvent
from src.backend.io.writer import WriterEvent, WriterStatus
from src.backend.models import (
    FrameStats,
    InternalFrameDecoded,
    InternalSource,
    LogLine,
    StatsUpdated,
    TransportMode,
    UserNotice,
)
from src.backend.support.transport import TransportStatus
from src.frontend.capture_events import CaptureEventPresenter, _default_text_file_factory, console_log_part_path
from src.i18n import set_language


def _redir(text: str, received_at_ms: int = 0) -> RedirEvent:
    return RedirEvent(
        frame_size=len(text) + 10,
        source_code=8,
        frame_sn=0,
        text=text,
        received_at_ms=received_at_ms,
    )


def _timestamp(received_at_ms: int) -> str:
    return datetime.fromtimestamp(received_at_ms / 1000).astimezone().isoformat(sep=" ", timespec="milliseconds")


def _short_timestamp(received_at_ms: int) -> str:
    return datetime.fromtimestamp(received_at_ms / 1000).astimezone().strftime("%H:%M:%S.%f")[:-3]


def test_snapshot_event_becomes_stats_updated(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin")
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=0,
        parser_raw_bytes=0,
        parser_frames=0,
        parser_carried_bytes=0,
    )

    messages = presenter.handle_event(snapshot)

    assert len(messages) == 1
    assert isinstance(messages[0], StatsUpdated)
    assert messages[0].stats is snapshot.stats


def test_capture_progress_notice_is_emitted_every_ten_seconds(tmp_path: Path) -> None:
    now = [100.0]
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin", clock=lambda: now[0])

    def snapshot(captured_bytes: int, parser_frames: int) -> AggregatorSnapshot:
        return AggregatorSnapshot(
            stats=FrameStats(),
            funnel_snapshots=(),
            buf_util_snapshots=(),
            captured_bytes=captured_bytes,
            parser_raw_bytes=captured_bytes,
            parser_frames=parser_frames,
            parser_carried_bytes=0,
            regular_frames=parser_frames,
        )

    now[0] = 109.0
    assert not any(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot(600_000, 10)))

    now[0] = 110.0
    notices = [message for message in presenter.handle_event(snapshot(700_000, 20)) if isinstance(message, UserNotice)]
    assert [notice.text for notice in notices] == ["Recorded 683.6 KB, 20 frames"]

    now[0] = 119.0
    assert not any(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot(2_000_000, 30)))

    now[0] = 120.0
    notices = [
        message for message in presenter.handle_event(snapshot(2_100_000, 40)) if isinstance(message, UserNotice)
    ]
    assert [notice.text for notice in notices] == ["Recorded 2.00 MB, 40 frames"]


def test_no_data_warning_repeats_every_ten_seconds(tmp_path: Path) -> None:
    now = [100.0]
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin", clock=lambda: now[0])
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=0,
        parser_raw_bytes=0,
        parser_frames=0,
        parser_carried_bytes=0,
    )

    now[0] = 110.0
    assert sum(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot)) == 1
    now[0] = 119.0
    assert not any(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot))
    now[0] = 120.0
    assert sum(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot)) == 1


def test_internal_frames_do_not_hide_repeated_no_valid_frame_warning(tmp_path: Path) -> None:
    now = [100.0]
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin", clock=lambda: now[0])

    def snapshot(captured_bytes: int, parser_frames: int) -> AggregatorSnapshot:
        return AggregatorSnapshot(
            stats=FrameStats(),
            funnel_snapshots=(),
            buf_util_snapshots=(),
            captured_bytes=captured_bytes,
            parser_raw_bytes=captured_bytes,
            parser_frames=parser_frames,
            parser_carried_bytes=0,
            regular_frames=0,
        )

    now[0] = 110.0
    notices = [message for message in presenter.handle_event(snapshot(700_000, 20)) if isinstance(message, UserNotice)]
    assert len(notices) == 1
    assert notices[0].level == "warning"
    assert notices[0].text == (
        "No valid BLE Log frames were decoded for 10s. Check transport mode, wiring, and firmware log configuration."
    )

    now[0] = 120.0
    notices = [
        message for message in presenter.handle_event(snapshot(1_400_000, 40)) if isinstance(message, UserNotice)
    ]
    assert len(notices) == 1
    assert notices[0].level == "warning"


def test_redir_text_writes_console_log_and_emits_complete_lines(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    presenter = CaptureEventPresenter(output_path)

    first = presenter.handle_event(AggregatorUpdate(console_events=(_redir("hello ", 1000),)))
    second = presenter.handle_event(AggregatorUpdate(console_events=(_redir("world\npartial", 2000),)))

    assert first == ()
    assert len(second) == 1
    assert isinstance(second[0], LogLine)
    assert second[0].text == f"[{_short_timestamp(2000)}]  hello world"
    presenter.close()
    stamp = _timestamp(2000)
    assert console_log_part_path(output_path, 1).read_text() == f"[{stamp}] hello world\npartial"
    assert presenter.state.saved_console_log_paths == (console_log_part_path(output_path, 1),)


def test_redir_console_log_is_plain_text_across_chunks(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    presenter = CaptureEventPresenter(output_path)

    presenter.handle_event(AggregatorUpdate(console_events=(_redir("\x1b[0;", 1000),)))
    presenter.handle_event(AggregatorUpdate(console_events=(_redir("32mgreen\x1b[0m\r\nnext\rline\t\x01", 2000),)))
    presenter.close()

    stamp = _timestamp(2000).encode()
    assert console_log_part_path(output_path, 1).read_bytes() == (b"[" + stamp + b"] green\nnext\nline    ")


def test_redir_text_batches_complete_lines_for_ui(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    presenter = CaptureEventPresenter(output_path)

    messages = presenter.handle_event(AggregatorUpdate(console_events=(_redir("one\ntwo\nthree\n", 2000),)))

    assert len(messages) == 1
    assert isinstance(messages[0], LogLine)
    assert messages[0].text == f"[{_short_timestamp(2000)}]  one\ntwo\nthree"


def test_redir_text_without_newline_is_shown_on_next_snapshot(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin")
    assert presenter.handle_event(AggregatorUpdate(console_events=(_redir("prompt> ", 2000),))) == ()

    messages = presenter.handle_event(
        AggregatorSnapshot(
            stats=FrameStats(),
            funnel_snapshots=(),
            buf_util_snapshots=(),
            captured_bytes=17,
            parser_raw_bytes=17,
            parser_frames=1,
            parser_carried_bytes=0,
        )
    )

    assert isinstance(messages[1], LogLine)
    assert messages[1].text == f"[{_short_timestamp(2000)}]  prompt> "


def test_redir_console_log_rotates_with_legacy_name(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    presenter = CaptureEventPresenter(output_path, console_part_max_bytes=3)

    presenter.handle_event(AggregatorUpdate(console_events=(_redir("abc\n"),)))
    presenter.handle_event(AggregatorUpdate(console_events=(_redir("de\n"),)))
    presenter.close()

    assert console_log_part_path(output_path, 1).read_text().endswith("abc\n")
    assert console_log_part_path(output_path, 2).read_text().endswith("de\n")
    assert presenter.state.saved_console_log_paths == (
        console_log_part_path(output_path, 1),
        console_log_part_path(output_path, 2),
    )


def test_aggregator_update_maps_to_existing_ui_messages(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin")

    messages = presenter.handle_event(
        AggregatorUpdate(
            internal_frames=(
                InternalFrameUpdate(
                    int_src=InternalSource.INFO,
                    decoded=InternalLogInfo(log_os_ts=1, source=InternalSource.INFO, version=4),
                ),
            ),
        )
    )

    assert isinstance(messages[0], InternalFrameDecoded)
    assert messages[0].int_src == InternalSource.INFO
    assert messages[0].payload.version == 4


def test_writer_events_update_capture_paths_and_messages(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    part2 = tmp_path / "ble_log_part002.bin"
    presenter = CaptureEventPresenter(output_path)

    opened = presenter.handle_event(
        WriterEvent(
            kind="opened",
            status=WriterStatus(
                base_path=output_path,
                paths=(output_path,),
                bytes_written=3,
                chunks_written=1,
                current_part=1,
                finalized=False,
            ),
        )
    )
    rotated = presenter.handle_event(
        WriterEvent(
            kind="rotated",
            status=WriterStatus(
                base_path=output_path,
                paths=(output_path, part2),
                bytes_written=10,
                chunks_written=2,
                current_part=2,
                finalized=False,
            ),
        )
    )

    assert isinstance(opened[0], LogLine)
    assert str(output_path) in opened[0].text
    assert isinstance(rotated[0], UserNotice)
    assert str(part2) in rotated[0].text
    assert presenter.state.saved_capture_paths == (output_path, part2)


def test_process_errors_become_warning_notices(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin")

    events = [
        ReaderProcessEvent(kind="error", message="reader failed"),
        ParserStatus(kind="error", message="parser failed"),
        AggregatorProcessEvent(kind="error", message="aggregator failed"),
        WriterEvent(kind="error", message="disk full"),
    ]

    messages = [presenter.handle_event(event)[0] for event in events]

    assert [message.level for message in messages] == ["warning"] * 4
    assert [message.text for message in messages] == [
        "Reader error: reader failed",
        "Parser error: parser failed",
        "Aggregator error: aggregator failed",
        "Writer error: disk full",
    ]


def test_process_errors_follow_selected_language(tmp_path: Path) -> None:
    set_language("zh_CN")
    try:
        presenter = CaptureEventPresenter(tmp_path / "ble_log.bin")
        message = presenter.handle_event(ReaderProcessEvent(kind="error", message="device lost"))[0]
        assert message.text == "读取器错误：device lost"
    finally:
        set_language("en")


def test_reader_opened_becomes_connected_notice(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "ble_log.bin")
    messages = presenter.handle_event(
        ReaderProcessEvent(
            kind="opened",
            status=TransportStatus(
                mode=TransportMode.UART,
                display_name="fake reader",
                opened=True,
                healthy=True,
            ),
        )
    )

    assert isinstance(messages[0], UserNotice)
    assert messages[0].text == "Connected to fake reader"


def test_final_result_closes_console_log_and_marks_disconnected(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    presenter = CaptureEventPresenter(output_path)
    presenter.handle_event(AggregatorUpdate(console_events=(_redir("hello\n"),)))

    presenter.finish()

    assert console_log_part_path(output_path, 1).read_text() == f"[{_timestamp(0)}] hello\n"
    assert presenter.state.disconnected


def test_finish_without_console_log_marks_disconnected(tmp_path: Path) -> None:
    output_path = tmp_path / "ble_log.bin"
    presenter = CaptureEventPresenter(output_path)

    presenter.finish()

    assert presenter.state.disconnected
    assert presenter.state.saved_console_log_paths == ()


@pytest.mark.parametrize("rotating", [False, True], ids=["stop", "rotation"])
def test_console_fsync_failure_stops_only_the_console_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rotating: bool
) -> None:
    files = []
    opened = []
    sync_calls = []
    real_fsync = os.fsync

    def factory(path):
        opened.append(path)
        file = _default_text_file_factory(path)
        files.append(file)
        return file

    def refuse_console_sync(fd):
        if any(not file.closed and file.fileno() == fd for file in files):
            sync_calls.append(fd)
            raise OSError(errno.EIO, "console sync refused")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", refuse_console_sync)
    presenter = CaptureEventPresenter(
        tmp_path / "ble_log.bin", text_file_factory=factory, console_part_max_bytes=1 if rotating else 1024
    )
    messages = list(presenter.handle_event(AggregatorUpdate(console_events=(_redir("first\n"),))))
    for index in range(3):
        messages.extend(presenter.handle_event(AggregatorUpdate(console_events=(_redir(f"later {index}\n"),))))
    messages.extend(presenter.finish())
    error = presenter.state.console_log_error
    assert error == "[Errno 5] console sync refused"
    assert presenter.finish() == ()
    assert presenter.state.console_log_error == error
    assert len(sync_calls) == 1
    assert len(opened) == 1 and all(file.closed for file in files)
    assert [message.text.split("  ", 1)[-1] for message in messages if isinstance(message, LogLine)] == [
        "first",
        "later 0",
        "later 1",
        "later 2",
    ]
    notices = [message for message in messages if isinstance(message, UserNotice)]
    assert len(notices) == 1 and error in notices[0].text
    assert opened[0].read_text().endswith("first\n" if rotating else "later 2\n")
    assert presenter.state.saved_console_log_paths == (opened[0],)


@pytest.mark.parametrize("rotating", [False, True], ids=["stop", "rotation"])
@pytest.mark.parametrize("descriptor_error", [io.UnsupportedOperation, OSError])
def test_descriptorless_text_factory_still_closes_without_a_save_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rotating: bool, descriptor_error: type[OSError]
) -> None:
    files = []

    class NoDescriptor(io.StringIO):
        def fileno(self):
            raise descriptor_error("factory has no descriptor")

    def factory(path):
        file = NoDescriptor()
        files.append(file)
        return file

    def unexpected_sync(fd):
        pytest.fail("a descriptorless text factory must not call fsync")

    monkeypatch.setattr(os, "fsync", unexpected_sync)
    presenter = CaptureEventPresenter(
        tmp_path / "ble_log.bin", text_file_factory=factory, console_part_max_bytes=1 if rotating else 1024
    )
    messages = list(presenter.handle_event(AggregatorUpdate(console_events=(_redir("first\n"),))))
    messages.extend(presenter.handle_event(AggregatorUpdate(console_events=(_redir("later\n"),))))
    messages.extend(presenter.finish())
    assert presenter.finish() == ()
    assert presenter.state.console_log_error is None
    assert not any(isinstance(message, UserNotice) and message.level == "warning" for message in messages)
    assert len(files) == (2 if rotating else 1) and all(file.closed for file in files)
    assert [message.text.split("  ", 1)[-1] for message in messages if isinstance(message, LogLine)] == [
        "first",
        "later",
    ]


class _FailingConsoleFile:
    """A real console file that raises once at the chosen operation, like a full or revoked disk."""

    def __init__(self, path: Path, fail_on: str, files: list[_FailingConsoleFile]) -> None:
        self._file = _default_text_file_factory(path)
        self._fail_on = fail_on
        self.closed = False
        self.calls_after_close = 0
        files.append(self)

    def _maybe_fail(self, operation: str) -> None:
        if self.closed:
            self.calls_after_close += 1
        if operation == self._fail_on:
            self._fail_on = ""
            raise OSError(errno.ENOSPC, f"console {operation} refused")

    def write(self, text: str) -> int:
        self._maybe_fail("write")
        return self._file.write(text)

    def flush(self) -> None:
        self._maybe_fail("flush")
        self._file.flush()

    def fileno(self) -> int:
        return self._file.fileno()

    def close(self) -> None:
        self._maybe_fail("close")
        self._file.close()
        self.closed = True


# failure -> (operation that raises, console part it hits)
_CONSOLE_FAILURES = {
    "open": ("open", 1),
    "write": ("write", 1),
    "flush": ("flush", 1),
    "close": ("close", 1),
    "rotation close": ("close", 1),
    "rotation open": ("open", 2),
}


@pytest.mark.parametrize("failure", list(_CONSOLE_FAILURES))
def test_console_log_failure_keeps_ui_text_and_is_reported_once(tmp_path: Path, failure: str) -> None:
    """A console.log failure is auxiliary: UI text continues, the sink stops, and the failure stays visible."""
    fail_on, fail_part = _CONSOLE_FAILURES[failure]
    output_path = tmp_path / "ble_log.bin"
    now = [0.0]
    files: list[_FailingConsoleFile] = []
    opened: list[Path] = []

    def factory(path: Path) -> _FailingConsoleFile:
        opened.append(path)
        part = len(opened)
        if fail_on == "open" and part == fail_part:
            raise PermissionError(errno.EACCES, "console open refused", str(path))
        armed_at_open = part == fail_part and fail_on in ("flush", "close")
        return _FailingConsoleFile(path, fail_on if armed_at_open else "", files)

    rotating = failure.startswith("rotation")
    presenter = CaptureEventPresenter(
        output_path,
        text_file_factory=factory,
        clock=lambda: now[0],
        console_part_max_bytes=10 if rotating else 1024 * 1024,
    )
    messages = list(presenter.handle_event(AggregatorUpdate(console_events=(_redir("first\n", 0),))))
    if failure == "write":
        files[0]._fail_on = "write"
    now[0] = 5.0 if failure == "flush" else 0.0
    for index in range(3):
        messages.extend(presenter.handle_event(AggregatorUpdate(console_events=(_redir(f"later {index}\n", 0),))))
    messages.extend(presenter.finish())
    assert presenter.finish() == ()

    ui_lines = [message.text for message in messages if isinstance(message, LogLine)]
    assert [line.split("  ", 1)[-1] for line in ui_lines] == ["first", "later 0", "later 1", "later 2"]
    warnings = [message.text for message in messages if isinstance(message, UserNotice) and message.level == "warning"]
    assert len(warnings) == 1, warnings
    assert "refused" in warnings[0]
    error = presenter.state.console_log_error
    assert error is not None and "refused" in error
    assert all(file.closed for file in files)
    assert [file.calls_after_close for file in files] == [0] * len(files)
    assert len(opened) == fail_part, "a failed console log is never reopened"
    first_part = console_log_part_path(output_path, 1)
    if failure == "open":
        assert not first_part.exists()
        assert presenter.state.saved_console_log_paths == ()
    else:
        assert first_part.read_text().startswith(f"[{_timestamp(0)}] first\n")
        assert presenter.state.saved_console_log_paths[0] == first_part
