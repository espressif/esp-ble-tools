# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Undecoded console text: parser spans, worker batching, presenter UI and console.log."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from queue import Queue
from threading import Event
from typing import Any

import pytest
from src.backend.analysis.aggregator import AggregatorSnapshot, AggregatorUpdate
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import ReceivedChunk, RedirEvent, UndecodedEvent
from src.backend.analysis.stream_identification import DEFAULT_IDENTIFICATION_RULES
from src.backend.analysis.worker import ParserStatus, run_analysis_loop
from src.backend.io.writer import WriterConfig
from src.backend.models import BleLogSource, LogLine, TransportMode
from src.backend.pipeline import controller
from src.frontend.capture_events import REDIR_LINE_BUFFER_LIMIT, CaptureEventPresenter
from src.frontend.log_view import LogView
from src.i18n import tr
from textual.app import App, ComposeResult
from textual.strip import Strip

from tests.helpers import build_frame, xor_checksum
from tests.test_capture_pipeline import FakeReader

BEGIN = "--- Undecoded data ---"
END = "--- End of undecoded data ---"


def frame(text: bytes = b"redirected\n", source: int = BleLogSource.REDIR) -> bytes:
    return build_frame(text, source, 1, xor_checksum)


def _text_parser() -> BleLogParser:
    return BleLogParser(identification=DEFAULT_IDENTIFICATION_RULES)


def _present(presenter: CaptureEventPresenter, events: list[Any]) -> tuple[str, str]:
    messages = list(presenter.handle_events(events))
    messages.extend(presenter.finish())
    ui = "\n".join(message.text for message in messages if isinstance(message, LogLine))
    paths = presenter.state.saved_console_log_paths
    saved = paths[0].read_text() if paths else ""
    return ui, saved


def _assert_in_order(text: str, parts: list[str]) -> None:
    cursor = 0
    for part in parts:
        cursor = text.index(part, cursor) + len(part)


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("chunk_size", [1, 7, 4096])
def test_undecoded_text_reaches_ui_and_file_in_stream_order(tmp_path: Path, enabled: bool, chunk_size: int) -> None:
    data = (
        frame(b"before\n")
        + b"panic\tA\x00\xff\r\nBacktrace\rline\n"
        + frame(b"host", BleLogSource.HOST)
        + b"boot\n"
        + frame(b"after\n")
        + b"END"
    )
    incoming: Queue[Any] = Queue()
    counts: Queue[Any] = Queue()
    outgoing: Queue[Any] = Queue()
    for start in range(0, len(data), chunk_size):
        incoming.put(ReceivedChunk(data[start : start + chunk_size], 123))
    incoming.put(None)
    counts.put(len(data))
    counts.put(None)

    run_analysis_loop(incoming, counts, outgoing, identification=DEFAULT_IDENTIFICATION_RULES if enabled else None)

    events = []
    while not outgoing.empty():
        events.append(outgoing.get_nowait())
    assert not [event for event in events if isinstance(event, ParserStatus)]
    snapshots = [event for event in events if isinstance(event, AggregatorSnapshot)]
    ui, saved = _present(CaptureEventPresenter(tmp_path / "recording.bin"), events)
    begin, end = tr(BEGIN), tr(END)
    expected = (
        ["before", begin, "panic A", "Backtrace", "line", end, begin, "boot", end, "after", begin, "END", end]
        if enabled
        else ["before", "after"]
    )
    for text in (ui, saved):
        _assert_in_order(text, expected)
        assert text.count(begin) == text.count(end) == (3 if enabled else 0)
        assert "\x00" not in text and "\xff" not in text
        if not enabled:
            assert "panic" not in text and "END" not in text
    assert snapshots[-1].parser_frames == snapshots[-1].regular_frames == 3
    assert snapshots[-1].captured_bytes == len(data)
    assert snapshots[-1].sequence.observed_frames == 3


def test_partial_frame_is_not_console_text_before_it_completes() -> None:
    parser = _text_parser()
    data = frame(b"normal payload\n")
    for byte in data[:-1]:
        assert parser.feed(bytes([byte])).events == ()
    batch = parser.feed(data[-1:])
    assert batch.parsed_frames == 1
    assert [type(event) for event in batch.events] == [RedirEvent]
    assert parser.finalize().events == ()


def test_unfinished_frame_bytes_become_the_eof_tail_exactly_once() -> None:
    parser = _text_parser()
    data = b"tail text " + frame(b"never finished\n")[:-3]
    batch = parser.feed(data, received_at_ms=5)
    assert all("never" not in event.text for event in batch.events if isinstance(event, UndecodedEvent))

    summary = parser.finalize()

    text = "".join(event.text for event in summary.events)
    shown = "".join(event.text for event in batch.events if isinstance(event, UndecodedEvent)) + text
    assert shown.startswith("tail text")
    assert "never finished" in shown
    assert [event.end for event in summary.events][-1] is True
    assert sum(event.end for event in summary.events) == 1
    assert parser.finalize().events == ()


def test_binary_only_gap_has_no_empty_boundary() -> None:
    parser = _text_parser()
    assert parser.feed(b"\x00\xff" * 40).events == ()
    assert parser.finalize().events == ()


def test_bad_checksum_text_is_shown_without_counting_a_frame() -> None:
    bad = bytearray(frame(b"panic: checksum failed\n"))
    bad[-1] ^= 1
    parser = _text_parser()
    batch = parser.feed(bytes(bad) + frame(b"valid\n"))
    assert batch.parsed_frames == 1
    assert [event.text for event in batch.events if isinstance(event, RedirEvent)] == ["valid\n"]
    text = "".join(event.text for event in batch.events if isinstance(event, UndecodedEvent))
    assert "panic: checksum failed" in text
    assert "valid" not in text.replace("checksum failed", "")
    assert sum(event.end for event in batch.events if isinstance(event, UndecodedEvent)) == 1


def test_colored_rom_line_keeps_sgr_for_the_ui_and_plain_text_in_the_file(tmp_path: Path) -> None:
    parser = _text_parser()
    batch = parser.feed(b"\x1b[0;32mI (24) boot: chip revision: v1.0\x1b[0m\r\n", received_at_ms=7)
    presenter = CaptureEventPresenter(tmp_path / "recording.bin")
    ui, saved = _present(presenter, [AggregatorUpdate(console_events=batch.events)])

    assert "I (24) boot: chip revision: v1.0" in saved
    assert "\x1b" not in saved and "[0;32m" not in saved
    assert "\x1b[0;32mI (24) boot" in ui


def test_long_undecoded_text_is_bounded_and_every_byte_is_kept(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "recording.bin")
    text = "x" * (REDIR_LINE_BUFFER_LIMIT * 2 + 10)

    live = list(presenter.handle_event(AggregatorUpdate(console_events=(UndecodedEvent(text, 123),))))

    live_x = sum(message.text.count("x") for message in live if isinstance(message, LogLine))
    assert live_x >= len(text) - REDIR_LINE_BUFFER_LIMIT
    final = presenter.finish()
    assert presenter.finish() == ()
    saved = presenter.state.saved_console_log_paths[0].read_text()
    ui = "\n".join(message.text for message in [*live, *final] if isinstance(message, LogLine))
    for output in (ui, saved):
        assert output.count("x") == len(text)
        assert output.count(tr(BEGIN)) == 1
        assert output.count(tr(END)) == 1


def test_crlf_split_across_events_is_one_line_break(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / "recording.bin")
    events = (UndecodedEvent("one\r", 1), UndecodedEvent("\ntwo\r\n", 2), UndecodedEvent("", 2, end=True))

    ui, saved = _present(presenter, [AggregatorUpdate(console_events=events)])

    body = saved.split(tr(BEGIN) + "\n", 1)[1]
    assert [line.split("] ", 1)[-1] for line in body.splitlines()][:2] == ["one", "two"]
    assert "\n\n" not in body
    assert "one" in ui and "two" in ui


@pytest.mark.parametrize(
    ("mode", "shows_text"),
    [
        (TransportMode.UART, True),
        (TransportMode.USJ, True),
        (TransportMode.SPI_USB_BRIDGE, False),
        (TransportMode.USB_OUTPUT, False),
    ],
)
def test_pipeline_shows_text_only_for_console_text_modes_and_saves_exact_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: TransportMode, shows_text: bool
) -> None:
    stop = Event()
    data = frame() + b"\xffpanic\x00\nEND"
    reader = FakeReader([data[:10], data[10:]], stop)
    status = reader.status
    monkeypatch.setattr(reader, "status", lambda: replace(status(), mode=mode))
    events: list[Any] = []
    result_from_events = controller._result_from_events

    def collect(received: list[Any]) -> controller.CapturePipelineResult:
        events.extend(received)
        return result_from_events(received)

    monkeypatch.setattr(controller, "_result_from_events", collect)
    output = tmp_path / "recording.bin"

    result = controller.run_capture_pipeline_inprocess(reader, WriterConfig(output), stop_requested=stop)

    assert result.completed
    assert output.read_bytes() == data
    assert result.raw_bytes == len(data)
    assert result.parser_frames == 1
    ui, saved = _present(CaptureEventPresenter(output), events)
    for text in (ui, saved):
        assert "redirected" in text
        assert ("panic" in text) is shows_text
        assert ("END" in text) is shows_text
    identity = result.final_snapshot.stream_identity if result.final_snapshot else None
    assert (identity is not None) is shows_text


COLOR_LINE = b"\x1b[0;32mI (24) boot: chip revision: v1.0\x1b[0m\r\n"
COLOR_TEXT = "I (24) boot: chip revision: v1.0"


def _record_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes, chunk_size: int
) -> tuple[list[str], str]:
    """Replay bytes through the in-process pipeline in UART mode; return the UI lines and console.log."""
    stop = Event()
    reader = FakeReader([data[start : start + chunk_size] for start in range(0, len(data), chunk_size)], stop)
    status = reader.status
    monkeypatch.setattr(reader, "status", lambda: replace(status(), mode=TransportMode.UART))
    events: list[Any] = []
    result_from_events = controller._result_from_events

    def collect(received: list[Any]) -> controller.CapturePipelineResult:
        events.extend(received)
        return result_from_events(received)

    monkeypatch.setattr(controller, "_result_from_events", collect)
    output = tmp_path / f"recording_{chunk_size}.bin"
    controller.run_capture_pipeline_inprocess(reader, WriterConfig(output), stop_requested=stop)
    assert output.read_bytes() == data

    presenter = CaptureEventPresenter(output)
    messages = [*presenter.handle_events(events), *presenter.finish()]
    paths = presenter.state.saved_console_log_paths
    text_lines = [
        message.text
        for message in messages
        if isinstance(message, LogLine) and not message.text.startswith("Saving to ")
    ]
    return text_lines, paths[0].read_text() if paths else ""


def _render(lines: list[str]) -> list[Strip]:
    """Write UI lines into a mounted LogView, as the app does, and return the rendered rows."""

    class LogApp(App[None]):
        def compose(self) -> ComposeResult:
            yield LogView()

    async def run() -> list[Strip]:
        app = LogApp()
        async with app.run_test(size=(120, 20)) as pilot:
            view = app.query_one(LogView)
            for line in lines:
                view.write_ascii(line)
            await pilot.pause()
            return list(view.lines)

    return asyncio.run(run())


def _rendered_text(rows: list[Strip]) -> str:
    return "\n".join(segment.text for row in rows for segment in row)


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 4096])
def test_colored_line_split_at_any_chunk_size_renders_green_and_saves_plain_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_size: int
) -> None:
    ui, saved = _record_text(tmp_path, monkeypatch, COLOR_LINE * 2, chunk_size)

    rows = _render(ui)
    rendered = _rendered_text(rows)
    assert rendered.count(COLOR_TEXT) == 2
    assert "[0;32m" not in rendered and "[0m" not in rendered and "\x1b" not in rendered
    green = [segment for row in rows for segment in row if COLOR_TEXT in segment.text]
    assert [segment.style.color.number if segment.style and segment.style.color else None for segment in green] == [
        2,
        2,
    ], "ANSI SGR 32 (green)"
    assert [line.split("] ", 1)[-1] for line in saved.splitlines()[1:3]] == [COLOR_TEXT, COLOR_TEXT]
    assert "\x1b" not in saved and "[0;32m" not in saved


@pytest.mark.parametrize(
    ("data", "shown"),
    [
        (b"tail text\x1b", "tail text"),
        (b"before frame\x1b" + frame(b"redirected\n"), "before frame"),
        (b"reset \x1bcterminal\n", "reset cterminal"),
    ],
    ids=["esc-at-eof", "esc-before-frame", "esc-c-in-text"],
)
@pytest.mark.parametrize("chunk_size", [1, 4096])
def test_isolated_escape_never_reaches_the_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes, shown: str, chunk_size: int
) -> None:
    ui, saved = _record_text(tmp_path, monkeypatch, data, chunk_size)

    rendered = _rendered_text(_render(ui))
    assert shown in rendered
    assert "\x1b" not in rendered
    assert shown in saved and "\x1b" not in saved


@pytest.mark.parametrize("chunk_size", [1, 4096])
def test_escape_only_gap_between_frames_opens_no_text_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_size: int
) -> None:
    ui, saved = _record_text(tmp_path, monkeypatch, frame(b"one\n") + b"\x1b\x00\x1b" + frame(b"two\n"), chunk_size)

    assert [line.split("  ", 1)[-1] for line in ui] == ["one", "two"]
    assert tr(BEGIN) not in saved
