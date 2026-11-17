# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
import runpy
import struct
from queue import Queue
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from pytest_bdd import given, parsers, scenarios, then, when
from src import i18n
from src.app import BLELogApp
from src.backend.analysis.aggregator import AggregatorUpdate
from src.backend.analysis.parser_events import HciLogEvent, HostLogEvent, RedirEvent
from src.backend.analysis.worker import run_analysis_process
from src.backend.io import WriterConfig, run_io_loop
from src.backend.models import LogLine, UserNotice
from src.backend.support.transport.base import PortScan
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.log_view import LogView
from textual.widgets import Button, Checkbox, Input, Label, Select

from tests.helpers import BytesReader, snapshot_payload
from tests.test_host_logs import encoded, frame, make_database

scenarios("features/log_display.feature")

TEXT = {"host": "hello compressed", "hci": "TX HCI type=1", "console": "device console"}


@given("已准备包含 Host、HCI 和设备控制台文本的录制", target_fixture="world")
def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_scan", lambda mode: PortScan(options=[("test", "test")])
    )
    return SimpleNamespace(tmp_path=tmp_path, database=make_database(tmp_path))


@when(parsers.parse("在启动界面选择显示 {categories} 并开始录制"))
def select_and_record(world, categories):
    world.selected = set() if categories == "无" else set(categories.split(","))
    world.raw = (
        frame(0, 0, snapshot_payload())
        + encoded(1, log_id=2)
        + frame(6, 2, struct.pack("<IB", 1000000, 1) + b"\x03\x0c\x00")
        + frame(8, 3, struct.pack("<I", 10) + b"device console\n")
    )
    incoming, counters, outgoing = Queue(), Queue(), Queue()
    world.output = world.tmp_path / "recording.bin"
    stop = Event()
    run_io_loop(BytesReader(world.raw, stop), WriterConfig(world.output), incoming, counters, outgoing, stop)
    run_analysis_process(incoming, counters, outgoing, log_database=world.database)
    events = []
    while not outgoing.empty():
        events.append(outgoing.get_nowait())
    presenter = CaptureEventPresenter(world.output)
    messages = presenter.handle_events(events) + presenter.finish()

    async def preview():
        app = BLELogApp(log_dir=world.tmp_path, log_database=world.database)
        with patch.object(app, "_start_capture"):
            async with app.run_test(size=(100, 55)) as pilot:
                for category in TEXT:
                    checkbox = app.screen.query_one(f"#show-{category}", Checkbox)
                    assert not checkbox.value
                    checkbox.value = category in world.selected
                app.screen.query_one("#port-select", Select).value = "test"
                button = app.screen.query_one("#connect-btn")
                button.scroll_visible(animate=False)
                await pilot.pause()
                await pilot.click("#connect-btn")
                await pilot.pause()
                view = app.query_one(LogView)
                with patch.object(view, "write_ascii") as write, patch.object(view, "write_warning") as warn:
                    for message in messages:
                        if isinstance(message, LogLine):
                            app.on_log_line(message)
                    app.on_user_notice(UserNotice("recording warning", level="warning"))
                    world.visible = "\n".join(call.args[0] for call in write.call_args_list)
                    world.warnings = [call.args[0] for call in warn.call_args_list]
                # Record Again retains the selected display categories.
                app._on_report_result("again")
                assert app._show_logs == world.selected

    asyncio.run(preview())


@then("只有所选类别出现在实时日志区")
def visible(world):
    for category, text in TEXT.items():
        assert (text in world.visible) == (category in world.selected)


@then("全部原始数据和解码日志仍被保存")
def saved(world):
    assert world.output.read_bytes() == world.raw
    console = world.output.with_name("recording_console.log").read_text()
    assert TEXT["host"] in console and TEXT["console"] in console
    assert TEXT["hci"] in world.output.with_name("recording_hci.log").read_text()


@then("录制警告仍然显示")
def warnings(world):
    assert world.warnings == ["recording warning"]


@when(parsers.parse("在已勾选控制台文本后切换到 {mode} 模式"))
def change_mode(world, mode):
    async def select_mode():
        app = BLELogApp(log_dir=world.tmp_path)
        with patch.object(app, "_start_capture"):
            async with app.run_test(size=(100, 55)) as pilot:
                screen = app.screen
                screen.query_one("#show-console", Checkbox).value = True
                screen.query_one("#show-host", Checkbox).value = True
                screen.query_one("#mode-select", Select).value = mode
                await pilot.pause()
                world.console_visible = screen.query_one("#show-console", Checkbox).display
                screen.query_one("#port-select", Select).value = "test"
                screen.query_one("#connect-btn").scroll_visible(animate=False)
                await pilot.pause()
                await pilot.click("#connect-btn")
                await pilot.pause()
                world.show_logs = app._show_logs

    world.mode = mode
    asyncio.run(select_mode())


@then("控制台文本选项仅在 UART 可见且隐藏时不提交选择")
def console_only_on_uart(world):
    assert world.console_visible == (world.mode == "uart")
    assert world.show_logs == ({"host", "console"} if world.mode == "uart" else {"host"})


@when(parsers.parse("在 {width:d}x{height:d} 终端以 {language} 操作 {mode} 启动页"))
def use_compact_setup(world, monkeypatch, width, height, language, mode):
    monkeypatch.setattr("src.i18n._language", language)

    async def operate():
        app = BLELogApp(log_dir=world.tmp_path)
        with patch.object(app, "_start_capture") as start:
            async with app.run_test(size=(width, height)) as pilot:
                screen = app.screen
                screen.query_one("#mode-select", Select).value = mode
                await pilot.pause()
                title = screen.query_one("#launch-title")
                language_select = screen.query_one("#language-select")
                assert title.region.y == language_select.region.y
                assert title.region.right <= language_select.region.x
                world.rows = []
                for row in screen.query(".field-row"):
                    if row.display:
                        label = row.query_one(Label)
                        control = row.children[1]
                        world.rows.append((label.region, control.region))
                options = [item for item in screen.query(Checkbox) if item.display]
                world.option_regions = [item.region for item in options]
                assert all(item.region in screen.query_one("#display-row").region for item in options)
                if height >= 40:
                    assert screen.query_one("#launch-container").max_scroll_y == 0

                checkbox = screen.query_one("#show-host", Checkbox)
                checkbox.scroll_visible(animate=False)
                await pilot.pause()
                assert await pilot.click(checkbox, offset=(1, 0))
                world.padding_click_selected = checkbox.value
                await pilot.press("space")
                assert not checkbox.value
                await pilot.press("space")
                screen.query_one("#connect-btn").focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                world.started = start.call_count
                world.show_logs = app._show_logs

    asyncio.run(operate())


@then("字段与标签对齐且日志选项不重叠")
def aligned_compact_fields(world):
    assert len({label.x for label, _ in world.rows}) == 1
    for label, control in world.rows:
        assert label.y == control.y and label.right <= control.x
    for left, right in zip(world.option_regions, world.option_regions[1:]):
        assert left.right < right.x


@then("可以点击日志选项的留白并用键盘开始录制")
def compact_setup_operable(world):
    assert world.padding_click_selected
    assert world.started == 1
    assert world.show_logs == {"host"}


@when(parsers.parse("填写 {mode} 设置后通过语言菜单来回切换中英文"))
def switch_setup_language(world, monkeypatch, mode):
    monkeypatch.setattr("src.i18n._language", "en")
    world.localized = []
    world.settings = []

    async def switch():
        app = BLELogApp(log_dir=world.tmp_path)
        async with app.run_test(size=(100, 40)) as pilot:
            screen = app.screen
            screen.query_one("#mode-select", Select).value = mode
            await pilot.pause()
            screen.query_one("#port-select", Select).set_options([("first", "first"), ("second", "second")])
            screen.query_one("#port-select", Select).value = "second"
            screen.query_one("#baud-select", Select).value = 921600
            screen.query_one("#dir-input", Input).value = str(world.tmp_path / "chosen")
            screen.query_one("#database-input", Input).value = str(world.database)
            screen.query_one("#show-host", Checkbox).value = True
            screen.query_one("#show-console", Checkbox).value = mode == "uart"

            def settings():
                return (
                    *(screen.query_one(f"#{name}-select", Select).value for name in ("mode", "port", "baud")),
                    *(screen.query_one(f"#{name}-input", Input).value for name in ("dir", "database")),
                    *(screen.query_one(f"#show-{name}", Checkbox).value for name in ("host", "hci", "console")),
                )

            world.original_settings = settings()
            for key in ("end", "home", "end"):
                screen.query_one("#language-select", Select).focus()
                await pilot.pause()
                await pilot.press("enter", key, "enter")
                await pilot.pause()
                world.localized.append(
                    (
                        screen.query_one(".field-label", Label).render().plain,
                        str(screen.query_one("#refresh-btn", Button).label),
                        str(screen.query_one("#connect-btn", Button).label),
                        screen.query_one("#database-input", Input).placeholder,
                        screen.query_one("#display-note", Label).render().plain,
                        str(screen.query_one("#show-console", Checkbox).label),
                        screen.query_one("#port-select", Select).prompt,
                    )
                )
                world.settings.append(settings())

    asyncio.run(switch())


@then("当前标签按钮及提示立即使用所选语言")
def setup_text_matches_language(world):
    chinese = ("接收方式", "刷新", "连接", "留空则不解析压缩 Host 日志", "仅影响显示", "控制台", "请选择端口")
    english = (
        "Transport",
        "Refresh",
        "Connect",
        "Empty: skip compressed Host logs",
        "Display only",
        "Console",
        "Please select a port",
    )
    assert world.localized == [chinese, english, chinese]


@then("已填连接参数路径和日志勾选保持不变")
def language_keeps_settings(world):
    assert world.settings == [world.original_settings] * 3


@when("在中文系统环境全新启动设置页")
def fresh_setup_in_chinese_locale(world, monkeypatch):
    monkeypatch.setattr("locale.getlocale", lambda: ("zh_CN", "UTF-8"))
    initial_language = runpy.run_path(i18n.__file__)["get_language"]()
    monkeypatch.setattr(i18n, "_language", initial_language)

    async def open_setup():
        app = BLELogApp(log_dir=world.tmp_path)
        async with app.run_test(size=(100, 40)):
            world.initial_text = (
                app.screen.query_one("#language-select", Select).value,
                app.screen.query_one("#mode-label", Label).render().plain,
                str(app.screen.query_one("#connect-btn", Button).label),
            )

    asyncio.run(open_setup())


@then("语言选择及设置页文字默认英文")
def setup_defaults_to_english(world):
    assert world.initial_text == ("en", "Transport", "Connect")


def test_partial_console_lines_keep_their_category_across_host_and_hci(tmp_path):
    presenter = CaptureEventPresenter(tmp_path / "recording.bin")
    messages = (
        presenter.handle_event(
            AggregatorUpdate(
                console_events=(
                    RedirEvent(20, 8, 0, "console prefix", 0),
                    HostLogEvent("host line\n", 0),
                    HciLogEvent("hci line", 0),
                    RedirEvent(20, 8, 1, "console tail", 0),
                )
            )
        )
        + presenter.finish()
    )
    assert [(m.category, m.text.split("  ", 1)[-1]) for m in messages if isinstance(m, LogLine)] == [
        ("console", "console prefix"),
        ("host", "host line"),
        ("hci", "hci line"),
        ("console", "console tail"),
    ]


def test_display_selection_survives_storage_error_and_is_keyboard_accessible(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_scan", lambda mode: PortScan(options=[("test", "test")])
    )

    async def recover():
        app = BLELogApp(port="test", log_dir=tmp_path, show_logs=frozenset({"host"}))
        with patch.object(app, "_resolve_output_path", side_effect=OSError("storage unavailable")):
            async with app.run_test(size=(80, 24)) as pilot:
                assert app.screen.query_one("#show-host", Checkbox).value
                assert not app.screen.query_one("#show-hci", Checkbox).value
                checkbox = app.screen.query_one("#show-console", Checkbox)
                checkbox.focus()
                await pilot.pause()
                await pilot.press("space")
                assert checkbox.value

    asyncio.run(recover())
