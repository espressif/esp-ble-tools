# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/console_text.feature."""

from __future__ import annotations

import asyncio
import errno
import multiprocessing
import os
import random
import re
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.app import BLELogApp
from src.backend.analysis.aggregator import AggregatorSnapshot, CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.stream_identification import DEFAULT_IDENTIFICATION_RULES, IdentificationRules
from src.backend.io.reader import ReaderProcessEvent
from src.backend.io.writer import WriterConfig
from src.backend.models import (
    BleLogSource,
    CaptureVerdict,
    LogLine,
    TransportConfig,
    TransportMode,
    UserNotice,
)
from src.backend.pipeline import CapturePipeline, controller
from src.backend.support.transport import TransportStatus
from src.backend.support.transport.spi_usb_bridge_transport import CDC_ENDPOINT_PREFIX
from src.frontend.capture_events import CaptureEventPresenter, _default_text_file_factory
from src.frontend.capture_report import build_capture_report, format_capture_report, format_capture_summary
from src.frontend.log_view import LogView
from src.frontend.status_panel import StatusPanel
from src.i18n import tr
from textual.widgets import Button

from tests.helpers import BytesReader, build_frame, snapshot_payload, xor_checksum

scenarios("features/console_text.feature")

BOOT_TEXT = b"".join(
    b"\x1b[0;32mI (%d) boot: loading partition table entry %d\x1b[0m\r\n" % (index * 7, index) for index in range(12)
)
CRASH_TEXT = b"Guru Meditation Error: Core 0 panic'ed (Load access fault)\r\n" + b"MEPC    : 0x4200a1b2\r\n" * 8
HOST_LINE = "HOST TEXT BEFORE BLE"
TAIL_TEXT = "TAIL WITHOUT NEWLINE"
REDIR_LINE = b"I (900) app: forwarded through BLE Log\n"
BEGIN = "--- Undecoded data ---"
END = "--- End of undecoded data ---"
TEXT_WARNING = "looks like plain console text"
GENERIC_NO_FRAME_WARNING = "No valid BLE Log frames were decoded for 10s"
BLE_NO_FRAME_WARNING = "BLE Log was identified on this port, but no regular log frames"
MODES = {mode.name: mode for mode in TransportMode}


def _frame(payload: bytes, source: int, sn: int) -> bytes:
    return build_frame(payload, source, sn, xor_checksum)


def _redir_frames(count: int) -> bytes:
    return b"".join(_frame(REDIR_LINE, BleLogSource.REDIR, sn) for sn in range(count))


def _host_frames(count: int, first_sn: int = 0) -> bytes:
    return b"".join(_frame(b"\x00\x00\x00\x00hci", BleLogSource.HOST, sn) for sn in range(first_sn, first_sn + count))


class ModeBytesReader(BytesReader):
    """Byte replay that reports the transport mode under test."""

    def __init__(self, data: bytes, stop_event: Event, mode: TransportMode) -> None:
        super().__init__(data, stop_event, block_size=512)
        self._mode = mode

    def status(self) -> TransportStatus:
        return replace(super().status(), mode=self._mode)


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(tmp_path=tmp_path, mode=TransportMode.UART, chunks=[], live=[], records=[])


@pytest.fixture
def mounted_app(tmp_path: Path) -> Iterator[SimpleNamespace]:
    """A mounted console with the transport stubbed out, so no device is opened."""
    runner = asyncio.Runner()
    with patch.object(BLELogApp, "_start_capture", lambda self: None):
        app = BLELogApp(port="bdd-stub", log_dir=tmp_path)
        run = app.run_test()
        pilot = runner.run(run.__aenter__())
    try:
        yield SimpleNamespace(app=app, runner=runner, pilot=pilot)
    finally:
        try:
            runner.run(run.__aexit__(None, None, None))
        finally:
            runner.close()


def _set_stream(world: SimpleNamespace, mode: str, chunks: list[bytes]) -> SimpleNamespace:
    world.mode = MODES[mode]
    world.chunks = chunks
    world.data = b"".join(chunks)
    return world


@given(parsers.parse("一个 {mode} 端口持续输出 ESP 启动文本"), target_fixture="world")
def boot_text(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    return _set_stream(world, mode, [BOOT_TEXT] * 26)


@given(parsers.parse("一个 {mode} 端口先输出启动文本再输出 BLE Log 帧"), target_fixture="world")
def text_then_ble(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    return _set_stream(world, mode, [BOOT_TEXT, BOOT_TEXT, _redir_frames(3)])


@given(parsers.parse("一个 {mode} 端口只输出周期 SNAPSHOT"), target_fixture="world")
def periodic_snapshots(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    payload = snapshot_payload(reason_flags=0b1010)
    return _set_stream(world, mode, [_frame(payload, BleLogSource.INTERNAL, sn) for sn in range(12)])


@given(parsers.parse("一个 {mode} 端口只输出一个 SNAPSHOT 帧"), target_fixture="world")
def one_snapshot(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    return _set_stream(world, mode, [_frame(snapshot_payload(), BleLogSource.INTERNAL, 0)])


@given(parsers.parse("一个 {mode} 端口输出夹带 ASCII 片段的损坏二进制"), target_fixture="world")
def corrupt_binary(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    noise = bytearray(random.Random(11).randbytes(600 * 12))
    for offset in range(0, len(noise) - 16, 89):
        noise[offset : offset + 13] = b"ASSERT failed"
    return _set_stream(world, mode, [bytes(noise[start : start + 600]) for start in range(0, len(noise), 600)])


@given(parsers.parse("一个 {mode} 端口只输出来源未知的有效帧"), target_fixture="world")
def unknown_source_frames(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    return _set_stream(world, mode, [_frame(b"\x00\x00\x00\x00raw", 0x55, sn) for sn in range(10)])


@given(parsers.parse("一个 {mode} 端口先输出 BLE Log 帧，安静一段时间后输出崩溃文本"), target_fixture="world")
def ble_quiet_then_crash(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    return _set_stream(world, mode, [_host_frames(3), b"", b"", b"", CRASH_TEXT, b""])


@given(parsers.parse("一个 {mode} 端口以文本加半个帧结尾"), target_fixture="world")
def text_and_half_frame(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    unfinished = _frame(b"never completed payload\n", BleLogSource.REDIR, 0)[:-4]
    return _set_stream(world, mode, [_redir_frames(1), b"boot tail line\r\nEND-OF-TEXT " + unfinished])


@given(
    parsers.parse("一个 {mode} 端口输出的文本行在两次快照之间断开，随后输出 BLE Log 帧和不换行的结尾文本"),
    target_fixture="world",
)
def split_lines_then_ble(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    host_lines = f"{HOST_LINE}\n".encode() * 127 + HOST_LINE[:-3].encode()
    return _set_stream(
        world, mode, [host_lines, HOST_LINE[-3:].encode() + b"\n" + _redir_frames(3), TAIL_TEXT.encode()]
    )


@given(
    parsers.parse("一个 {mode} 端口在多次快照之间输出一行 {length:d} 字符、最后才换行的文本"),
    target_fixture="world",
)
def long_line(world: SimpleNamespace, mode: str, length: int) -> SimpleNamespace:
    return _set_stream(world, mode, [b"Z" * 10_000, b"Z" * 10_000, b"Z" * (length - 20_000) + b"\n"])


@given(parsers.parse("一个 {mode} 端口输出两行短文本"), target_fixture="world")
def two_short_lines(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    return _set_stream(world, mode, [b"ok\r\nok\r\n"])


def _record(
    world: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_sync: bool = False,
    rules: IdentificationRules = DEFAULT_IDENTIFICATION_RULES,
) -> None:
    if fail_sync:

        def refuse_sync(fd: int) -> None:
            raise OSError("fsync failed")

        monkeypatch.setattr("src.backend.io.writer.os.fsync", refuse_sync)
    events: list[Any] = []
    result_from_events = controller._result_from_events

    def collect(received: list[Any]) -> controller.CapturePipelineResult:
        events.extend(received)
        return result_from_events(received)

    monkeypatch.setattr(controller, "_result_from_events", collect)
    output = world.tmp_path / f"recording_{len(world.records)}.bin"
    stop = Event()
    result = controller.run_capture_pipeline_inprocess(
        ModeBytesReader(world.data, stop, world.mode),
        WriterConfig(output),
        stop_requested=stop,
        identification_rules=rules,
    )
    monkeypatch.setattr(controller, "_result_from_events", result_from_events)
    _finish_recording(world, output, events, result)


def _finish_recording(world: SimpleNamespace, output: Path, events: list[Any], result: Any) -> None:
    presenter = CaptureEventPresenter(output)
    messages = [*presenter.handle_events(events), *presenter.finish()]
    report = build_capture_report(
        result,
        TransportConfig(mode=world.mode, label="replay", port="replay"),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        duration_sec=1.0,
        console_log_paths=presenter.state.saved_console_log_paths,
        report_path=output.with_name(f"{output.stem}_report.txt"),
    )
    console_logs = presenter.state.saved_console_log_paths
    world.recording = SimpleNamespace(
        output=output,
        result=result,
        presenter=presenter,
        ui="\n".join(message.text for message in messages if isinstance(message, LogLine)),
        console_log=console_logs[0].read_text() if console_logs else "",
        report=report,
        report_text=format_capture_report(report, language="en"),
        report_text_zh=format_capture_report(report, language="zh_CN"),
        summary_text=format_capture_summary(report, language="en"),
        summary_text_zh=format_capture_summary(report, language="zh_CN"),
    )
    world.records.append(world.recording)


@when("Console 录制这段数据直到结束")
def record_until_end(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _record(world, monkeypatch)


@when("Console 用默认规则录制这段数据直到结束")
def record_with_default_rules(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _record(world, monkeypatch)


@when("Console 用最少 8 字节的文本规则录制这段数据直到结束")
def record_with_custom_rules(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _record(world, monkeypatch, rules=IdentificationRules(window_bytes=64, min_text_bytes=8))


@when("Console 录制这段数据，结束时文件同步失败")
def record_with_sync_failure(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _record(world, monkeypatch, fail_sync=True)


def _post(mounted_app: SimpleNamespace, messages: list[Any]) -> None:
    for message in messages:
        mounted_app.app.post_message(message)
    mounted_app.runner.run(mounted_app.pilot.pause())
    if mounted_app.app._exception is not None:
        raise mounted_app.app._exception


def _live(world: SimpleNamespace, mounted_app: SimpleNamespace, seconds: int) -> None:
    """Feed one chunk per virtual second through parser, aggregator, presenter and the mounted UI, then end input."""
    now = [0.0]
    parser = BleLogParser(identification=controller._parser_identification(world.mode, DEFAULT_IDENTIFICATION_RULES))
    aggregator = CaptureAggregator()
    presenter = CaptureEventPresenter(world.tmp_path / "live.bin", clock=lambda: now[0])
    panel = mounted_app.app.query_one(StatusPanel)
    for second in range(seconds):
        now[0] = float(second)
        chunk = world.chunks[second] if second < len(world.chunks) else b""
        messages: list[Any] = []
        if chunk:
            aggregator.record_raw_bytes(len(chunk))
            messages.extend(presenter.handle_event(aggregator.consume_parser_batch(parser.feed(chunk))))
        messages.extend(presenter.handle_event(aggregator.snapshot(1.0)))
        _post(mounted_app, messages)
        world.live.append(SimpleNamespace(second=second, messages=messages, status=panel.render().plain))
    # Same end-of-input order as the analysis worker: the summary's undecoded tail precedes the final snapshot.
    summary = parser.finalize()
    final: list[Any] = list(presenter.handle_event(aggregator.consume_events(summary.events)))
    aggregator.consume_parser_summary(summary)
    final.extend(presenter.handle_event(aggregator.snapshot(1.0)))
    final.extend(presenter.finish())
    _post(mounted_app, final)
    world.rendered = [strip.text.rstrip() for strip in mounted_app.app.query_one(LogView).lines]


@when(parsers.parse("实时界面每秒收到一次快照，共 {seconds:d} 秒"))
def live_for(world: SimpleNamespace, mounted_app: SimpleNamespace, seconds: int) -> None:
    _live(world, mounted_app, seconds)


@when("实时界面每秒收到一次快照")
def live_for_stream(world: SimpleNamespace, mounted_app: SimpleNamespace) -> None:
    _live(world, mounted_app, len(world.chunks))


@when("实时界面每秒收到一次数据和快照，最后结束录制")
def live_until_end(world: SimpleNamespace, mounted_app: SimpleNamespace) -> None:
    _live(world, mounted_app, len(world.chunks))


def _rows_with(world: SimpleNamespace, text: str) -> list[int]:
    return [index for index, row in enumerate(world.rendered) if text in row]


@then(parsers.parse('界面中 {count:d} 行 "{line}" 都完整显示，没有被拆开'))
def rendered_lines_intact(world: SimpleNamespace, count: int, line: str) -> None:
    rows = [world.rendered[index] for index in _rows_with(world, line.split()[0])]
    assert [row for row in rows if not row.endswith(line)] == []
    assert len(rows) == count


@then("界面中转发日志显示在未解码数据结束标记之后")
def rendered_redir_after_span(world: SimpleNamespace) -> None:
    redir_rows = _rows_with(world, "forwarded through BLE Log")
    end_rows = _rows_with(world, tr(END))
    assert len(redir_rows) == 3
    assert _rows_with(world, HOST_LINE)[-1] < end_rows[0] < redir_rows[0]


@then("不换行的结尾文本在界面中完整显示一次，未解码数据标记成对")
def rendered_tail_once(world: SimpleNamespace) -> None:
    tail_rows = _rows_with(world, TAIL_TEXT.split()[0])
    begin_rows, end_rows = _rows_with(world, tr(BEGIN)), _rows_with(world, tr(END))
    assert [world.rendered[index].endswith(TAIL_TEXT) for index in tail_rows] == [True]
    assert len(begin_rows) == len(end_rows) == 2
    assert begin_rows[-1] < tail_rows[0] < end_rows[-1]


@then(parsers.parse("界面中这行文本只在第 {limit:d} 个字符处断开一次，共显示 {length:d} 个字符"))
def rendered_long_line_bounded(world: SimpleNamespace, limit: int, length: int) -> None:
    # Joining rows merges the wrapped rows of one write; the timestamp of the next write separates the runs.
    runs = [len(run) for run in re.findall("Z+", "".join(world.rendered))]
    assert runs == [limit, length - limit]


def _notices(world: SimpleNamespace, text: str) -> list[int]:
    return [
        tick.second
        for tick in world.live
        for message in tick.messages
        if isinstance(message, UserNotice) and text in message.text
    ]


@then("原始数据文件与收到的字节完全一致")
def raw_is_exact(world: SimpleNamespace) -> None:
    recording = world.recording
    assert recording.output.read_bytes() == world.data
    assert recording.result.raw_bytes == len(world.data)
    assert recording.report.raw_complete


@then("界面和 console.log 都按原顺序显示这段文本")
def text_shown_in_order(world: SimpleNamespace) -> None:
    for text in (world.recording.ui, world.recording.console_log):
        assert text.count("loading partition table entry 11") == 26
        assert text.index("entry 0") < text.index("entry 11")
        assert text.count(tr(BEGIN)) == text.count(tr(END)) == 1
    assert "\x1b" not in world.recording.console_log


def _verdict_from_label(label: str) -> CaptureVerdict:
    return next(verdict for verdict in CaptureVerdict if tr(verdict.value, language="zh_CN") == label)


@then(parsers.parse("报告判定为「{label}」并说明收到的是普通文本"))
def report_says_text(world: SimpleNamespace, label: str) -> None:
    recording = world.recording
    assert recording.report.verdict is _verdict_from_label(label)
    assert f"结论：{label}" in recording.report_text_zh
    assert "Received data looks like plain console text" in recording.report_text
    assert "Identified as: Plain console text" in recording.report_text
    assert "Stream content: Plain console text" in recording.summary_text


@then(parsers.parse("纯文本警告在第 {seconds} 秒各出现一次"))
def text_warning_cadence(world: SimpleNamespace, seconds: str) -> None:
    expected = [int(second) for second in seconds.split("、")]
    assert _notices(world, TEXT_WARNING) == expected
    assert world.live[-1].second >= expected[-1]


@then("没有出现通用的「未解析到有效帧」警告")
def no_generic_warning(world: SimpleNamespace) -> None:
    assert _notices(world, GENERIC_NO_FRAME_WARNING) == []


@then("出现通用的「未解析到有效帧」警告")
def generic_warning(world: SimpleNamespace) -> None:
    assert _notices(world, GENERIC_NO_FRAME_WARNING) == [10]


@then("没有出现纯文本警告")
def no_text_warning(world: SimpleNamespace) -> None:
    assert _notices(world, TEXT_WARNING) == []


@then(parsers.parse('状态栏显示 "{label}"'))
def status_shows(world: SimpleNamespace, label: str) -> None:
    assert label in world.live[-1].status


@then(parsers.parse('状态栏先显示 "{first}" 后显示 "{second}"'))
def status_transitions(world: SimpleNamespace, first: str, second: str) -> None:
    labels = [first if first in tick.status else second if second in tick.status else "" for tick in world.live]
    assert labels == [first, first, second]


@then(parsers.parse('状态栏一直显示 "{label}"'))
def status_always(world: SimpleNamespace, label: str) -> None:
    assert all(label in tick.status for tick in world.live)
    assert all("PLAIN TEXT" not in tick.status for tick in world.live)


@then("状态栏不显示数据内容标签")
def status_without_content(world: SimpleNamespace) -> None:
    assert all("PLAIN TEXT" not in tick.status and "BLE LOG" not in tick.status for tick in world.live)


@then("界面提示一次已识别到 BLE Log 帧")
def ble_notice_once(world: SimpleNamespace) -> None:
    assert _notices(world, "BLE Log frames identified") == [2]


@then("无普通帧警告说明已识别到 BLE Log 并提示检查固件日志配置")
def ble_specific_no_frame_warning(world: SimpleNamespace) -> None:
    assert _notices(world, BLE_NO_FRAME_WARNING) == [10]
    assert _notices(world, GENERIC_NO_FRAME_WARNING) == []


@then("console.log 中启动文本位于未解码数据标记之间，转发日志在其后")
def text_then_redir_in_console_log(world: SimpleNamespace) -> None:
    log = world.recording.console_log
    begin, end = log.index(tr(BEGIN)), log.index(tr(END))
    assert begin < log.index("entry 0") < log.rindex("entry 11") < end < log.index("forwarded through BLE Log")
    assert log.count("forwarded through BLE Log") == 3


@then(parsers.parse("报告判定为「{label}」且没有内容警告"))
def report_without_content_warning(world: SimpleNamespace, label: str) -> None:
    report = world.recording.report
    assert report.verdict is _verdict_from_label(label)
    assert report.warnings == ()
    assert "Identified as: BLE Log" in world.recording.report_text


@then(parsers.parse("报告判定为「{label}」并说明已识别 BLE Log 但没有普通日志帧"))
def report_internal_only(world: SimpleNamespace, label: str) -> None:
    report = world.recording.report
    assert report.verdict is _verdict_from_label(label)
    assert report.regular_frames == 0
    assert (
        report.reasons[0] == "No regular BLE Log frames were decoded; check mode, wiring, and firmware configuration."
    )
    assert "BLE Log was identified, but no regular log frames were decoded" in world.recording.report_text
    assert f"Firmware identity records: {len(world.chunks)}" in world.recording.report_text


def _recommendations(world: SimpleNamespace) -> tuple[str, str]:
    recording = world.recording
    return recording.summary_text.splitlines()[0], recording.summary_text_zh.splitlines()[0]


@then("摘要建议确认固件把 BLE Log 输出到这个端口，不要求检查波特率")
def summary_advises_text_port(world: SimpleNamespace) -> None:
    english, chinese = _recommendations(world)
    assert english == (
        "Recommendation: Received data looks like plain console text, not BLE Log frames; "
        "check that the firmware sends BLE Log to this port."
    )
    assert chinese == "建议：收到的数据像是普通控制台文本，而不是 BLE Log 帧；请确认固件把 BLE Log 输出到这个端口。"


@then("摘要建议检查固件日志配置，不说没有录到有效帧，也不要求检查波特率")
def summary_advises_firmware_log_configuration(world: SimpleNamespace) -> None:
    english, chinese = _recommendations(world)
    assert world.recording.result.parser_frames > 0
    assert english == (
        "Recommendation: BLE Log was identified, but no regular log frames were decoded; "
        "check the firmware log configuration."
    )
    assert chinese == "建议：已识别到 BLE Log，但没有解析到普通日志帧；请检查固件日志配置。"


@then("UART 摘要仍建议检查传输模式、端口、波特率、接线和固件日志配置")
def uart_summary_keeps_baud_advice(world: SimpleNamespace) -> None:
    english, chinese = _recommendations(world)
    assert english == (
        "Recommendation: No valid BLE Log frames were recorded. Check the transport mode, port, baud rate, wiring, "
        "and firmware log configuration, then record again."
    )
    assert chinese == "建议：没有录到有效 BLE Log 帧。请检查传输模式、端口、波特率、接线和固件日志配置后重新录制。"


@then("这些帧都被解码")
def unknown_frames_decoded(world: SimpleNamespace) -> None:
    assert world.recording.result.parser_frames == 10
    assert world.recording.report.regular_frames == 10


@then(parsers.parse("报告的数据内容为「{label}」"))
def report_content(world: SimpleNamespace, label: str) -> None:
    english = {"无法识别的数据": "Unrecognized data", "普通控制台文本": "Plain console text"}[label]
    assert f"Identified as: {english}" in world.recording.report_text
    assert f"识别结果：{label}" in world.recording.report_text_zh


@then(parsers.parse("报告判定为「{label}」并说明识别后仍收到帧外数据"))
def report_gap_after_ble(world: SimpleNamespace, label: str) -> None:
    recording = world.recording
    assert recording.report.verdict is _verdict_from_label(label)
    assert "Data outside BLE Log frames arrived after BLE Log was identified" in recording.report_text
    # The decoder still holds the last few crash-text bytes at EOF: they are shown, reported as carried
    # bytes, and not counted as data outside frames.
    carried = recording.report.parser_carried_bytes
    assert 0 < carried < 6
    assert f"Of which after BLE Log was identified: {len(CRASH_TEXT) - carried}" in recording.report_text
    assert f"Trailing carried bytes: {carried}" in recording.report_text


@then("界面和 console.log 都显示了崩溃文本")
def crash_text_shown(world: SimpleNamespace) -> None:
    for text in (world.recording.ui, world.recording.console_log):
        assert "Guru Meditation Error" in text
        assert text.count("MEPC    : 0x4200a1b2") == 8


@then("结尾文本在界面和 console.log 中各出现一次，未解码数据标记成对")
def tail_once(world: SimpleNamespace) -> None:
    for text in (world.recording.ui, world.recording.console_log):
        assert text.count("END-OF-TEXT") == 1
        assert text.count("never completed payload") == 1
        assert text.count(tr(BEGIN)) == text.count(tr(END)) == 1


@then("再次结束不再输出任何内容")
def finish_is_idempotent(world: SimpleNamespace) -> None:
    before = world.recording.console_log
    assert world.recording.presenter.finish() == ()
    assert world.recording.presenter.state.saved_console_log_paths[0].read_text() == before


@then("界面和 console.log 都没有这段文本")
def no_text_for_other_modes(world: SimpleNamespace) -> None:
    for text in (world.recording.ui, world.recording.console_log):
        assert "partition table" not in text
        assert tr(BEGIN) not in text


@then("报告不包含数据内容一节，也没有内容警告")
def report_without_content_section(world: SimpleNamespace) -> None:
    recording = world.recording
    assert recording.report.stream_identity is None
    assert "Stream content" not in recording.report_text
    assert "Stream content" not in recording.summary_text
    assert "plain console text" not in recording.report_text


@then(parsers.parse("报告判定为「{label}」，首要原因仍是原始数据未能安全封存"))
def report_recapture_first(world: SimpleNamespace, label: str) -> None:
    report = world.recording.report
    assert report.verdict is _verdict_from_label(label)
    assert report.reasons[0] == "Raw recording could not be finalized safely."
    assert not report.raw_complete
    assert any("fsync failed" in error for error in report.errors)


@then("报告同时说明收到的是普通文本")
def report_also_text(world: SimpleNamespace) -> None:
    assert "Received data looks like plain console text" in world.recording.report_text
    assert world.recording.report.reasons[1].startswith("Received data looks like plain console text")


@then("文本字节下限大于窗口时规则被拒绝")
def rules_rejected() -> None:
    with pytest.raises(ValueError, match="must not exceed window_bytes"):
        IdentificationRules(window_bytes=64, min_text_bytes=65)


def _wait_for(pipeline: CapturePipeline, events: list[Any], predicate: Any, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events.extend(pipeline.drain_events())
        if any(predicate(event) for event in events):
            return
        time.sleep(0.02)
    raise AssertionError("the capture process did not reach the expected state")


@when("CapturePipeline 在独立进程中从虚拟串口录制这段数据")
def record_from_pty(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    pty = pytest.importorskip("pty", reason="POSIX-only virtual terminal")
    master_fd, slave_fd = pty.openpty()
    output = world.tmp_path / "process.bin"
    config = TransportConfig(mode=world.mode, label="pty", port=os.ttyname(slave_fd), baudrate=115_200)
    pipeline = CapturePipeline(config, WriterConfig(output))
    events: list[Any] = []
    try:
        pipeline.start()
        _wait_for(pipeline, events, lambda event: isinstance(event, ReaderProcessEvent) and event.kind == "opened")
        os.write(master_fd, world.data)
        _wait_for(
            pipeline,
            events,
            lambda event: isinstance(event, AggregatorSnapshot) and event.parser_raw_bytes >= len(world.data),
        )
        pipeline.stop()
        final_events, result = pipeline.wait_with_events(5.0)
        events.extend(final_events)
    finally:
        pipeline.stop()
        os.close(slave_fd)
        os.close(master_fd)
    _finish_recording(world, output, events, result)
    _record(world, monkeypatch)
    world.recording = world.records[0]


@then("最终识别结果与进程内重放相同")
def process_matches_inprocess(world: SimpleNamespace) -> None:
    process, inprocess = world.records
    assert process.result.completed
    assert process.report.stream_identity is not None
    assert process.report.stream_identity == inprocess.report.stream_identity
    assert process.report.verdict is inprocess.report.verdict


@given(
    parsers.parse("一个 {mode} 端口输出 {count:d} 个 BLE Log 帧和下一帧的前 {prefix:d} 个字节"), target_fixture="world"
)
def frames_then_cut_frame(world: SimpleNamespace, mode: str, count: int, prefix: int) -> SimpleNamespace:
    cut = _frame(b"\x00\x00\x00\x00hci", BleLogSource.HOST, count)[:prefix]
    world.carried = prefix
    world.phases = [
        (_host_frames(count) + cut, lambda app: app.query_one(StatusPanel).stats.transport.rx_frames >= count)
    ]
    return _set_stream(world, mode, [_host_frames(count), cut])


@given(parsers.parse("一个 {mode} 端口在 BLE Log 帧之间输出 {count:d} 字节二进制数据"), target_fixture="world")
def binary_between_frames(world: SimpleNamespace, mode: str, count: int) -> SimpleNamespace:
    world.binary_gap = count
    return _set_stream(world, mode, [_host_frames(3), b"\xff" * count, _host_frames(3, first_sn=3)])


AFTER_FAILURE_TEXT = b"AFTER FAILURE line\r\n" * 3


def _rendered_rows(app: BLELogApp) -> list[str]:
    return [strip.text.rstrip() for strip in app.query_one(LogView).lines]


@given(parsers.parse("一个 {mode} 端口先输出启动文本，再输出更多文本和 BLE Log 帧"), target_fixture="world")
def text_then_more_text_and_frames(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    world.phases = [
        (
            BOOT_TEXT,
            lambda app: (
                "PLAIN TEXT" in app.query_one(StatusPanel).render().plain
                and any("entry 10" in row for row in _rendered_rows(app))
            ),
        ),
        (
            AFTER_FAILURE_TEXT + _redir_frames(3),
            lambda app: sum("forwarded through BLE Log" in row for row in _rendered_rows(app)) == 3,
        ),
    ]
    return _set_stream(world, mode, [BOOT_TEXT, AFTER_FAILURE_TEXT + _redir_frames(3)])


class _DiskFullConsoleFile:
    """A real console.log that stops accepting text after a byte budget, like a disk that fills up."""

    def __init__(self, path: Path, budget: int) -> None:
        self._file = _default_text_file_factory(path)
        self._budget = budget

    def write(self, text: str) -> int:
        if len(text) > self._budget:
            raise OSError(errno.ENOSPC, "No space left on device")
        self._budget -= len(text)
        return self._file.write(text)

    def flush(self) -> None:
        self._file.flush()

    def fileno(self) -> int:
        return self._file.fileno()

    def close(self) -> None:
        self._file.close()


@given(parsers.parse("一个 {mode} 端口分两次输出转发日志帧"), target_fixture="world")
def redir_in_two_phases(world: SimpleNamespace, mode: str) -> SimpleNamespace:
    first = b"".join(_frame(b"BEFORE SYNC\n", BleLogSource.REDIR, sn) for sn in range(3))
    later = b"".join(_frame(b"AFTER SYNC\n", BleLogSource.REDIR, sn) for sn in range(3, 6))
    world.phases = [
        (first, lambda app: sum("BEFORE SYNC" in row for row in _rendered_rows(app)) == 3),
        (later, lambda app: sum("AFTER SYNC" in row for row in _rendered_rows(app)) == 3),
    ]
    return _set_stream(world, mode, [first, later])


@given(parsers.parse("console.log 在{operation}时同步返回 I/O 错误"))
def console_sync_fails(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    parent_pid = os.getpid()
    real_fsync = os.fsync
    world.sync_files = []
    world.sync_paths = []
    world.sync_hits = []
    world.sync_error = "[Errno 5] console sync refused"
    world.rotating = operation == "切换分片"
    world.child_pids = {process.pid for process in multiprocessing.active_children()}

    def factory(path):
        world.sync_paths.append(path)
        file = _default_text_file_factory(path)
        world.sync_files.append(file)
        return file

    def sync(fd):
        if os.getpid() == parent_pid and any(not file.closed and file.fileno() == fd for file in world.sync_files):
            world.sync_hits.append(fd)
            raise OSError(errno.EIO, "console sync refused")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(
        "src.frontend.capture_session.CaptureEventPresenter",
        partial(CaptureEventPresenter, text_file_factory=factory, console_part_max_bytes=1 if world.rotating else 1024),
    )


@given("console.log 写入一部分后磁盘写满")
def console_disk_fills(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def disk_full(path: Path) -> _DiskFullConsoleFile:
        return _DiskFullConsoleFile(path, budget=300)

    monkeypatch.setattr(
        "src.frontend.capture_session.CaptureEventPresenter",
        partial(CaptureEventPresenter, text_file_factory=disk_full),
    )


@when("Console 界面通过独立进程从虚拟串口录制这段数据，然后停止并查看报告")
def record_in_app(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    pty = pytest.importorskip("pty", reason="POSIX-only virtual terminal")
    import tty

    monkeypatch.setattr("src.i18n._language", "en")
    master_fd, slave_fd = pty.openpty()
    tty.setraw(slave_fd)
    port = os.ttyname(slave_fd)
    if world.mode is TransportMode.SPI_USB_BRIDGE:
        port = f"{CDC_ENDPOINT_PREFIX}{port}"
    app = BLELogApp(mode=world.mode, port=port, baudrate=115_200, log_dir=world.tmp_path / "app")

    async def drive() -> None:
        async with app.run_test(size=(140, 40)) as pilot:

            async def wait_for(predicate: Any, what: str, timeout: float = 15.0) -> None:
                deadline = time.monotonic() + timeout
                while not predicate():
                    if app._exception is not None:
                        raise app._exception
                    if time.monotonic() > deadline:
                        raise AssertionError(f"timed out waiting for {what}: {_rendered_rows(app)[-12:]}")
                    await pilot.pause(0.05)

            stop = app.query_one("#stop-review", Button)
            try:
                await wait_for(lambda: not stop.disabled, "recording start")
                for index, (data, ready) in enumerate(world.phases):
                    os.write(master_fd, data)
                    await wait_for(lambda ready=ready: ready(app), f"phase {index}")
            finally:
                world.running_before_stop = (
                    app._capture_session.is_running and app._capture_session._pipeline.io_is_alive()
                )
                if app._exception is None:
                    if not stop.disabled:
                        await pilot.click("#stop-review")
                    await wait_for(lambda: app.saved_report_path is not None, "report after Stop & Review", 40.0)
            world.rendered = _rendered_rows(app)
            world.session = app._capture_session

    try:
        asyncio.run(drive())
    finally:
        os.close(master_fd)
        os.close(slave_fd)
    world.app = SimpleNamespace(
        raw=b"".join(path.read_bytes() for path in app.saved_capture_paths),
        console_log_paths=app.saved_console_log_paths,
        report_text=app.saved_report_path.read_text(encoding="utf-8"),
    )


@then(parsers.parse("报告判定为「{label}」，没有内容警告"))
def report_without_any_warning(world: SimpleNamespace, label: str) -> None:
    report = world.recording.report
    assert report.verdict is _verdict_from_label(label)
    assert report.warnings == ()


@then(parsers.parse("报告记录结尾有 {count:d} 个未完成帧的字节，不计为识别后的帧外数据"))
def report_counts_eof_carry(world: SimpleNamespace, count: int) -> None:
    recording = world.recording
    assert recording.report.parser_carried_bytes == count
    assert f"Trailing carried bytes: {count}" in recording.report_text
    identity = recording.report.stream_identity
    if identity is not None:
        assert identity.kind.value == "ble_log"
        assert identity.evidence.gap_bytes_after_ble == 0


@then(parsers.parse("报告判定为「{label}」并说明全部原始字节都在原始数据文件中"))
def report_binary_gap_kept_in_raw(world: SimpleNamespace, label: str) -> None:
    recording = world.recording
    assert recording.report.verdict is _verdict_from_label(label)
    assert recording.report.stream_identity.evidence.gap_bytes_after_ble == world.binary_gap
    assert recording.report.reasons == (
        (
            "Data outside BLE Log frames arrived after BLE Log was identified; all original bytes are kept in the raw "
            "file, and the console log holds at most their displayable text."
        ),
    )
    assert (
        "识别出 BLE Log 之后仍收到不属于 BLE Log 帧的数据；全部原始字节都保存在原始数据文件中，"
        "串口转发日志最多只包含其中可显示的文本。"
    ) in recording.report_text_zh


@then("没有生成 console.log")
def no_console_log(world: SimpleNamespace) -> None:
    assert world.recording.report.console_log_paths == ()
    assert list(world.tmp_path.glob("*_console*.log")) == []
    assert "Console log:" not in world.recording.report_text


@then("界面录制保存的原始数据与发送的字节完全一致")
def app_raw_exact(world: SimpleNamespace) -> None:
    assert world.app.raw == world.data


@then(parsers.parse("界面报告判定为「{label}」，没有内容警告"))
def app_report_ready(world: SimpleNamespace, label: str) -> None:
    text = world.app.report_text
    assert f"Verdict: {_verdict_from_label(label).value}" in text
    assert "Data outside BLE Log frames" not in text
    assert (
        "Reasons:\n  - Raw data was finalized, BLE Log frames were decoded, and no continuity loss was observed.\n"
        in text
    )


CONSOLE_FAILURE_NOTICE = "Console log could not be saved: [Errno 28] No space left on device."


@then("界面只提示一次 console.log 保存失败，之后的文本和转发日志仍然显示")
def app_console_failure_notice_once(world: SimpleNamespace) -> None:
    rows = world.rendered
    notices = [index for index, row in enumerate(rows) if "Console log could not be saved" in row]
    assert len(notices) == 1, rows
    assert CONSOLE_FAILURE_NOTICE in rows[notices[0]]
    after = rows[notices[0] :]
    assert sum("AFTER FAILURE line" in row for row in after) == 3
    assert sum("forwarded through BLE Log" in row for row in after) == 3


@then("识别出 BLE Log 时，界面说明之前的文本保存在原始数据文件中，不再提到 console.log")
def app_transition_notice_without_console_log(world: SimpleNamespace) -> None:
    transition = [row for row in world.rendered if "BLE Log frames identified" in row]
    assert transition == ["[INFO] BLE Log frames identified; earlier text is kept in the raw file."]


@then(parsers.parse("界面报告判定为「{label}」，说明 console.log 不完整且此错误本身不会停止原始录制"))
def app_report_console_incomplete(world: SimpleNamespace, label: str) -> None:
    text = world.app.report_text
    assert f"Verdict: {_verdict_from_label(label).value}" in text
    assert (
        "Reasons:\n  - The console log could not be saved completely; this error does not itself stop raw recording.\n"
        in text
    )
    assert "Saved raw data: Complete and reliable" in text
    assert "Console log error: [Errno 28] No space left on device" in text
    assert "Writer:" not in text


@then("同步失败只警告一次，保留首个错误且不再打开日志分片")
def app_sync_failure_visible_once(world: SimpleNamespace) -> None:
    notices = [index for index, row in enumerate(world.rendered) if "Console log could not be saved" in row]
    assert len(notices) == 1 and world.sync_error in world.rendered[notices[0]]
    assert len(world.sync_hits) == 1 and len(world.sync_paths) == 1
    assert all(file.closed for file in world.sync_files)
    if world.rotating:
        assert sum("AFTER SYNC" in row for row in world.rendered[notices[0] :]) == 3
    report = world.session.report
    assert report.console_log_error == world.sync_error
    assert report.verdict is CaptureVerdict.WARNING and report.raw_complete and report.parser_complete
    assert report.errors == ()
    assert world.running_before_stop
    assert world.session.finished and not world.session._pipeline.is_alive()
    assert world.session._event_presenter.finish() == ()
    assert world.session._event_presenter.state.console_log_error == world.sync_error
    assert {process.pid for process in multiprocessing.active_children()} == world.child_pids
    assert "Console log error: " + world.sync_error in world.app.report_text
    assert "this error does not itself stop raw recording" in world.app.report_text
    saved = world.sync_paths[0].read_text(encoding="utf-8")
    assert "BEFORE SYNC" in saved
    assert ("AFTER SYNC" in saved) is not world.rotating


@then("console.log 保留失败前写入的内容")
def console_log_keeps_prefix(world: SimpleNamespace) -> None:
    (path,) = world.app.console_log_paths
    saved = path.read_text(encoding="utf-8")
    assert 0 < len(saved) <= 300
    assert tr(BEGIN) in saved and "entry 0" in saved
