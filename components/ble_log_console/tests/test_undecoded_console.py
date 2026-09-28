# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from dataclasses import replace
from queue import Queue
from threading import Event

import pytest

from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.analysis.aggregator import AggregatorUpdate
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import ReceivedChunk
from src.backend.analysis.parser_events import RedirEvent
from src.backend.analysis.parser_events import UndecodedEvent
from src.backend.analysis.worker import ParserStatus, run_analysis_loop
from src.backend.models import BleLogSource, LogLine, TransportMode
from src.backend.io.writer import WriterConfig
from src.backend.pipeline import controller
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.capture_events import REDIR_LINE_BUFFER_LIMIT
from src.i18n import tr
from tests.helpers import build_frame, xor_checksum
from tests.test_capture_pipeline import FakeReader


def frame(text=b'redirected\n', source=BleLogSource.REDIR):
    return build_frame(text, source, 1, xor_checksum)


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('chunk_size', [1, 7, 4096])
def test_uart_undecoded_text_reaches_ui_and_file_in_order(tmp_path, enabled, chunk_size):
    # Includes a non-REDIR recovery frame and a short tail held until EOF.
    data = (
        frame(b'before\n')
        + b'panic\tA\x00\xff\r\nBacktrace\rline\n'
        + frame(b'host', BleLogSource.HOST)
        + b'boot\n'
        + frame(b'after\n')
        + b'END'
    )
    incoming, counts, outgoing = Queue(), Queue(), Queue()
    for start in range(0, len(data), chunk_size):
        incoming.put(ReceivedChunk(data[start : start + chunk_size], 123))
    incoming.put(None)
    counts.put(len(data))
    counts.put(None)
    run_analysis_loop(incoming, counts, outgoing, emit_undecoded=enabled)
    presenter = CaptureEventPresenter(tmp_path / 'recording.bin')
    messages, snapshots = [], []
    while not outgoing.empty():
        event = outgoing.get_nowait()
        assert not isinstance(event, ParserStatus), event
        if isinstance(event, AggregatorSnapshot):
            snapshots.append(event)
        messages.extend(presenter.handle_event(event))
    messages.extend(presenter.finish())
    ui = '\n'.join(message.text for message in messages if isinstance(message, LogLine))
    saved = presenter.state.saved_console_log_paths[0].read_text()
    begin, end = tr('--- Undecoded data ---'), tr('--- End of undecoded data ---')
    expected = (
        ['before', begin, 'panic A', 'Backtrace', 'line', end, begin, 'boot', end, 'after', begin, 'END', end]
        if enabled
        else ['before', 'after']
    )
    for text in (ui, saved):
        cursor = 0
        for part in expected:
            cursor = text.index(part, cursor) + len(part)
        assert text.count(begin) == (3 if enabled else 0)
        assert text.count(end) == (3 if enabled else 0)
        assert '\x00' not in text and '\xff' not in text
        if not enabled:
            assert 'panic' not in text and 'END' not in text
    assert snapshots[-1].parser_frames == snapshots[-1].regular_frames == 3
    assert snapshots[-1].captured_bytes == len(data)


def test_partial_frame_is_not_console_text():
    parser = BleLogParser(emit_undecoded=True)
    data = frame(b'normal payload\n')
    for byte in data[:-1]:
        assert parser.feed(bytes([byte])).events == ()
    batch = parser.feed(data[-1:])
    assert batch.parsed_frames == 1
    assert len(batch.events) == 1
    assert batch.events[0].text == 'normal payload\n'
    assert parser.finalize().events == ()


def test_binary_only_gap_has_no_empty_boundary():
    parser = BleLogParser(emit_undecoded=True)
    assert parser.feed(b'\x00\xff' * 40).events == ()
    assert parser.finalize().events == ()


def test_bad_checksum_text_is_shown_without_counting_a_frame():
    bad = bytearray(frame(b'panic: checksum failed\n'))
    bad[-1] ^= 1
    parser = BleLogParser(emit_undecoded=True)
    batch = parser.feed(bytes(bad) + frame(b'valid\n'))
    assert batch.parsed_frames == 1
    assert [e.text for e in batch.events if isinstance(e, RedirEvent)] == ['valid\n']
    text = ''.join(e.text for e in batch.events if isinstance(e, UndecodedEvent))
    assert 'panic: checksum failed' in text
    assert 'valid' not in text
    assert sum(e.end for e in batch.events if isinstance(e, UndecodedEvent)) == 1


def test_interrupted_analysis_closes_one_boundary_and_bounds_text(tmp_path):
    presenter = CaptureEventPresenter(tmp_path / 'recording.bin')
    text = 'x' * (REDIR_LINE_BUFFER_LIMIT * 2 + 10)
    messages = list(presenter.handle_event(AggregatorUpdate(console_events=(UndecodedEvent(text, 123),))))
    assert len(presenter._console_line_buf) <= REDIR_LINE_BUFFER_LIMIT
    assert len(presenter._redir_line_buf) <= REDIR_LINE_BUFFER_LIMIT
    messages.extend(presenter.finish())
    assert presenter.finish() == ()
    saved = presenter.state.saved_console_log_paths[0].read_text()
    ui = '\n'.join(m.text for m in messages if isinstance(m, LogLine))
    for output in (ui, saved):
        assert output.count('x') == len(text)
        assert output.count(tr('--- Undecoded data ---')) == 1
        assert output.count(tr('--- End of undecoded data ---')) == 1


@pytest.mark.parametrize('mode', [TransportMode.UART, TransportMode.SPI_USB_BRIDGE])
def test_pipeline_enables_text_only_for_uart_and_preserves_raw_bytes(tmp_path, monkeypatch, mode):
    stop = Event()
    data = frame() + b'\xffpanic\x00\nEND'
    reader = FakeReader([data[:10], data[10:]], stop)
    status = reader.status
    monkeypatch.setattr(reader, 'status', lambda: replace(status(), mode=mode))
    events = []
    result_from_events = controller._result_from_events

    def collect(received):
        events.extend(received)
        return result_from_events(received)

    monkeypatch.setattr(controller, '_result_from_events', collect)
    output = tmp_path / 'recording.bin'
    result = controller.run_capture_pipeline_inprocess(reader, WriterConfig(output), stop_requested=stop)
    assert result.completed
    assert output.read_bytes() == data
    assert result.raw_bytes == len(data)
    presenter = CaptureEventPresenter(output)
    messages = presenter.handle_events(events) + presenter.finish()
    ui = '\n'.join(m.text for m in messages if isinstance(m, LogLine))
    saved = presenter.state.saved_console_log_paths[0].read_text()
    for text in (ui, saved):
        assert 'redirected' in text
        assert ('panic' in text) == (mode is TransportMode.UART)
        assert ('END' in text) == (mode is TransportMode.UART)
    assert result.parser_frames == 1
