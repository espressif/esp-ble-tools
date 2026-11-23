# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import struct
from queue import Queue
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from pytest_bdd import given, parsers, scenarios, then, when
from src.app import BLELogApp
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.worker import run_analysis_process
from src.backend.io import WriterConfig, run_io_loop
from src.backend.models import LogLine, UserNotice
from src.backend.support.transport.base import PortScan
from src.frontend.capture_events import CaptureEventPresenter
from textual.widgets import Input, Select

from tests.helpers import BytesReader, snapshot_payload
from tests.test_host_logs import encoded, frame, make_database

scenarios("features/host_logs.feature")


@given("当前工作目录存在匹配的 Host 字典", target_fixture="world")
def local_database(tmp_path, monkeypatch):
    database = make_database(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_scan", lambda mode: PortScan(options=[("test", "test")])
    )
    return SimpleNamespace(tmp_path=tmp_path, database=database, default=database)


@given("当前工作目录没有字典但其他目录有匹配字典", target_fixture="world")
def remote_database(tmp_path, monkeypatch):
    world = local_database(tmp_path, monkeypatch)
    cwd = tmp_path / "working"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    world.default = None
    return world


@given("压缩日志格式末尾包含转义换行")
def escaped_line_ending(world):
    path = world.database / "BLE_HOST_logs.json"
    database = json.loads(path.read_text())
    database["logs"]["2"]["format"] = '"hello compressed\\r\\n"'
    path.write_text(json.dumps(database))


@when(parsers.parse("用户{selection}字典路径开始录制"))
def start(world, selection):
    async def setup():
        with patch("src.frontend.capture_session.CapturePipeline") as pipeline:
            pipeline.return_value.drain_events.return_value = []
            pipeline.return_value.check_io_shutdown.return_value = []
            pipeline.return_value.io_is_alive.return_value = True
            app = BLELogApp(log_dir=world.tmp_path)
            async with app.run_test(size=(120, 55)) as pilot:
                field = app.screen.query_one("#database-input", Input)
                assert field.value == (str(world.default) if world.default else "")
                if selection == "指定":
                    field.value = str(world.database)
                elif selection == "清空":
                    field.value = ""
                else:
                    assert selection == "保留默认"
                app.screen.query_one("#port-select", Select).value = "test"
                await pilot.click("#connect-btn")
                await pilot.pause()
                pipeline.return_value.start.assert_called_once()
                return pipeline.call_args.kwargs["log_database"]

    selected = asyncio.run(setup())
    world.raw = (
        frame(0, 0, snapshot_payload())
        + frame(5, 1, struct.pack("<I", 10) + b"plain host\n")
        + encoded(2, log_id=2)
        + frame(2, 3, b"LL hidden")
        + frame(3, 4, b"ISR hidden")
        + frame(4, 5, b"LL HCI hidden")
        + frame(6, 6, b"HCI hidden")
    )
    incoming, counters, outgoing = Queue(), Queue(), Queue()
    stop = Event()
    output = world.tmp_path / "recording.bin"
    run_io_loop(BytesReader(world.raw, stop), WriterConfig(output), incoming, counters, outgoing, stop)
    run_analysis_process(incoming, counters, outgoing, log_database=selected)
    events = []
    while not outgoing.empty():
        events.append(outgoing.get_nowait())
    presenter = CaptureEventPresenter(output)
    world.messages = presenter.handle_events(events) + presenter.finish()
    world.text = presenter.state.saved_console_log_paths[0].read_text()
    world.output = output


@then("Host 明文和压缩文本均显示并保存")
def decoded(world):
    for text in ("plain host", "hello compressed"):
        assert text in world.text
        assert any(isinstance(msg, LogLine) and text in msg.text for msg in world.messages)


@then("压缩 Host 日志显示和保存时没有尾部转义换行文字")
def clean_line_ending(world):
    assert '"hello compressed"\n' in world.text
    lines = [msg.text for msg in world.messages if isinstance(msg, LogLine) and "hello compressed" in msg.text]
    assert len(lines) == 1 and lines[0].endswith('"hello compressed"')
    assert "\\n" not in world.text and "\\r" not in world.text


@then("只显示 Host 明文且提示跳过压缩日志")
def skipped(world):
    assert "plain host" in world.text and "hello compressed" not in world.text
    assert any(
        isinstance(msg, UserNotice) and ("compressed Host" in msg.text or "压缩 Host" in msg.text)
        for msg in world.messages
    )


@then("LL_TASK 和 LL_ISR 不显示而原始数据完整保留")
def preserved(world):
    assert "hidden" not in world.text
    assert world.output.read_bytes() == world.raw
    assert not list(world.tmp_path.glob("*btsnoop*"))
    assert not list(world.tmp_path.glob("*ll*.bin*"))


@when("压缩 Host 帧先于协议版本信息到达后再收到正常 Host 帧")
def host_before_protocol(world):
    parser = BleLogParser(log_database=world.database)
    aggregator = CaptureAggregator()
    presenter = CaptureEventPresenter(world.tmp_path / "protocol.bin")
    raw = encoded(1, log_id=2) + encoded(2, log_id=2) + frame(0, 0, snapshot_payload()) + encoded(3, log_id=2)
    world.messages = []
    for offset in range(0, len(raw), 7):
        world.messages.extend(
            presenter.handle_event(aggregator.consume_parser_batch(parser.feed(raw[offset : offset + 7])))
        )
    world.messages.extend(presenter.handle_event(aggregator.consume_events(parser.finalize().events)))
    world.messages.extend(presenter.finish())


@then("提示首段帧缺少协议信息且后续文本不标记为未完整解码")
def prefix_warning_only(world):
    notices = [message.text for message in world.messages if isinstance(message, UserNotice)]
    assert len(notices) == 1
    assert "waiting for protocol version information" in notices[0]
    assert "Host log decoding incomplete" not in notices[0]
    lines = [message.text for message in world.messages if isinstance(message, LogLine)]
    assert len(lines) == 1 and "hello compressed" in lines[0]
    assert "Incomplete Host log" not in lines[0]


@given(parsers.parse("v8 录制包含 HCI 和 Host 帧，压缩 Host 的输入为「{content}」"), target_fixture="world")
def report_input(tmp_path, content):
    raw = frame(0, 0, snapshot_payload()) + frame(6, 1, struct.pack("<IB", 10, 4) + b"abc")
    raw += frame(5, 2, struct.pack("<I", 20) + b"ordinary host\n")
    if content == "压缩日志":
        raw += encoded(3, log_id=2)
    elif content == "其他编码":
        raw += frame(7, 3, struct.pack("<IBBBH", 30, 1, 1, 0x40, 2))
    return SimpleNamespace(tmp_path=tmp_path, raw=raw)


@when(parsers.parse("用「{choice}」字典生成录制产物和报告"))
def recorded_host_report(world, choice):
    from datetime import UTC, datetime

    from src.backend.models import TransportConfig, TransportMode
    from src.backend.pipeline.controller import _result_from_events
    from src.frontend.capture_report import build_capture_report

    db = make_database(world.tmp_path) if choice != "未选择" else None
    if choice == "损坏":
        (db / "BLE_HOST_logs.json").write_text("{broken")
    incoming, counters, outgoing = Queue(), Queue(), Queue()
    stop = Event()
    config = WriterConfig(world.tmp_path / "recording.bin")
    run_io_loop(BytesReader(world.raw, stop), config, incoming, counters, outgoing, stop)
    run_analysis_process(incoming, counters, outgoing, log_database=db, analysis_output=config)
    now = datetime.now(UTC)
    world.report = build_capture_report(
        _result_from_events(list(outgoing.queue)),
        TransportConfig(TransportMode.USJ, "USJ", "test"),
        started_at=now,
        ended_at=now,
        duration_sec=1,
        console_log_paths=(),
        report_path=world.tmp_path / "report.txt",
    )


@then(parsers.parse("原始录制完整，结论为「{verdict}」，压缩 Host 显示「{status}」"))
def host_report_status(world, verdict, status):
    from src.backend.models import CaptureVerdict
    from src.frontend.capture_report import format_capture_report, format_capture_summary

    report = world.report
    assert report.raw_complete and report.parser_complete
    assert report.raw_paths[0].read_bytes() == world.raw
    assert report.verdict == (CaptureVerdict.WARNING if verdict == "警告" else CaptureVerdict.READY)
    for render in (format_capture_summary, format_capture_report):
        assert status in render(report, "zh_CN")
        assert "Compressed Host text" in render(report, "en")
    files = list(world.tmp_path.glob("*_DECOMPRESSED_BLE_HOST.log"))
    if status == "已生成文本文件":
        assert len(files) == 1 and "hello compressed" in files[0].read_text()
    else:
        assert not files
    if verdict == "警告":
        assert "BLE_HOST_logs.json" in format_capture_summary(report, "zh_CN")


@then("共享序号报告只在总览检查连续性，来源表仅列帧数")
def shared_counts_only(world):
    from src.frontend.capture_report import format_capture_report

    for lang in ("en", "zh_CN"):
        text = format_capture_report(world.report, lang)
        assert "None -> None" not in text
        assert "SN range" not in text and "序号范围" not in text
    assert world.report.sequence.missing_frames == 0
