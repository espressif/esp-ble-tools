# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Recording-start recovery through mounted app entry points, without device access."""

import asyncio
import builtins
import errno
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.app import BLELogApp, unique_capture_path
from src.backend.analysis.aggregator import AggregatorUpdate
from src.backend.analysis.parser_events import RedirEvent
from src.backend.io.writer import WriterEvent, WriterStatus
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport.registry import list_transport_port_options
from src.frontend.capture_report import CaptureReportScreen
from src.frontend.capture_session import CaptureSession
from src.frontend.launch_screen import LaunchScreen
from src.frontend.log_view import LogView
from src.frontend.status_panel import StatusPanel
from textual.widgets import Button, Input, Label, Select
from usb.core import NoBackendError

from tests.test_capture_lifecycle import _completed_result

scenarios("features/recording_start.feature")


@pytest.fixture
def start_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setattr("src.i18n._language", "en")
    monkeypatch.setattr("src.frontend.launch_screen.list_transport_port_options", lambda mode: [("other", "other")])
    runner = asyncio.Runner()
    world = SimpleNamespace(tmp_path=tmp_path, runner=runner, run=None, app=None)
    with (
        patch("src.app.CaptureSession", wraps=CaptureSession) as session_type,
        patch("src.frontend.capture_session.CapturePipeline") as pipeline_type,
    ):
        world.session_type = session_type
        world.pipeline_type = pipeline_type
        pipeline_type.return_value.io_is_alive.return_value = True
        pipeline_type.return_value.drain_events.return_value = []
        try:
            yield world
        finally:
            try:
                if world.run is not None:
                    runner.run(world.run.__aexit__(None, None, None))
            finally:
                runner.close()


@given(parsers.parse("通过「{entry}」使用 {mode} 模式开始录制"))
def choose_entry(start_world: SimpleNamespace, entry: str, mode: str) -> None:
    start_world.entry = entry
    baud = (921600 if mode == "UART" else 3000000) if entry == "Connect" else 1234567
    start_world.config = TransportConfig(TransportMode[mode], "attempted", "attempted", baud)
    start_world.bad_dir = start_world.tmp_path / "refused [directory]"
    start_world.good_dir = start_world.tmp_path / "writable"


@given(parsers.parse("日志目录在{boundary}时返回 {error} 错误"))
def refuse_storage(start_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, boundary: str, error: str) -> None:
    code = getattr(errno, error)
    start_world.reason = f"[Errno {code}] storage [refused]"
    start_world.refusals = []
    if boundary == "预留文件":

        def open_file(path, mode="r", *args, **kwargs):
            if mode == "xb" and Path(path).parent == start_world.bad_dir:
                start_world.refusals.append(Path(path))
                raise OSError(code, "storage [refused]")
            return builtins.open(path, mode, *args, **kwargs)

        monkeypatch.setattr("src.app.open", open_file, raising=False)
    else:
        real_mkdir = Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path == start_world.bad_dir:
                start_world.refusals.append(path)
                raise OSError(code, "storage [refused]")
            return real_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mkdir)


@given("SPI 端口发现没有可用的 USB backend")
def missing_usb_backend(start_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    for backend in ("libusb1", "libusb0", "openusb"):
        monkeypatch.setattr(f"usb.backend.{backend}.get_backend", lambda: None)
    monkeypatch.setattr("src.backend.support.transport.spi_usb_bridge_transport._is_windows", lambda: False)
    monkeypatch.setattr(
        "serial.tools.list_ports.comports", lambda: [SimpleNamespace(device="/dev/ttyACM-stub", vid=0, pid=0)]
    )
    monkeypatch.setattr("src.frontend.launch_screen.list_transport_port_options", list_transport_port_options)
    with pytest.raises(NoBackendError, match="No backend available"):
        list_transport_port_options(TransportMode.SPI_USB_BRIDGE)
    config = start_world.config
    start_world.config = TransportConfig(config.mode, "attempted CDC", "cdc:attempted", config.baudrate)


def _recording_state(app: BLELogApp) -> dict[str, object]:
    button = app.query_one("#stop-review", Button)
    panel = app.query_one(StatusPanel)
    return {
        "output_path": app._output_path,
        "raw_path": app.saved_capture_path,
        "raw_paths": app.saved_capture_paths,
        "console_path": app.saved_console_log_path,
        "console_paths": app.saved_console_log_paths,
        "report_path": app.saved_report_path,
        "report": app._capture_report,
        "session": app._capture_session,
        "finalizing": app._finalizing,
        "log_rows": tuple(row.text for row in app.query_one(LogView).lines),
        "stop_disabled": button.disabled,
        "stop_label": str(button.label),
        "stats": asdict(panel.stats),
        "disconnected": panel.disconnected,
        "panel_finalizing": panel.finalizing,
    }


def _pause(world: SimpleNamespace) -> None:
    world.runner.run(world.pilot.pause())
    if world.app._exception is not None:
        raise world.app._exception


@when("用户尝试开始录制")
def attempt_start(start_world: SimpleNamespace) -> None:
    world = start_world
    config = world.config
    direct = world.entry == "命令行启动"
    prior = world.entry == "Record Again"
    app = BLELogApp(
        mode=config.mode,
        port=config.port if direct or prior else None,
        baudrate=config.baudrate,
        log_dir=world.bad_dir if not prior else world.tmp_path / "previous",
    )
    world.app = app
    world.run = app.run_test(size=(120, 55))
    world.pilot = world.runner.run(world.run.__aenter__())
    _pause(world)
    if prior:
        session = app._capture_session
        output = app._output_path
        output.write_bytes(b"previous raw bytes")
        session._event_presenter.handle_event(
            WriterEvent("opened", status=WriterStatus(output, (output,), 18, 1, 1, False))
        )
        session._event_presenter.handle_event(
            AggregatorUpdate(console_events=(RedirEvent(20, 8, 0, "previous console text\n", 0),))
        )
        session._finished = True
        app._publish_view_messages(session._finish_result(_completed_result(output)))
        _pause(world)
        assert isinstance(app.screen, CaptureReportScreen)
        world.before = _recording_state(app)
        world.files = {
            path: path.read_bytes()
            for path in (*app.saved_capture_paths, *app.saved_console_log_paths, app.saved_report_path)
        }
        app._log_dir = world.bad_dir
        world.runner.run(world.pilot.click("#record-again"))
    elif not direct:
        screen = app.screen
        screen.query_one("#mode-select", Select).value = {
            TransportMode.SPI_USB_BRIDGE: "spi",
            TransportMode.USB_OUTPUT: "usb",
        }.get(config.mode, config.mode.value)
        _pause(world)
        screen.query_one("#port-select", Select).set_options([("attempted", config.port)])
        screen.query_one("#port-select", Select).value = config.port
        screen.query_one("#baud-select", Select).value = config.baudrate
        world.before = _recording_state(app)
        world.files = {}
        world.runner.run(world.pilot.click("#connect-btn"))
    else:
        world.before = _recording_state(app)
        world.files = {}
    world.initial_count = 1 if prior else 0
    _pause(world)


@then("设置页持续显示目录和错误原因，并保留尝试的连接配置")
def setup_retains_attempt(start_world: SimpleNamespace) -> None:
    world = start_world
    _pause(world)
    screen = world.app.screen
    assert isinstance(screen, LaunchScreen)
    label = screen.query_one("#start-error", Label)
    assert label.is_mounted and label.display
    text = label.render().plain
    assert str(world.bad_dir) in text and world.reason in text
    assert "Connect" in text
    assert screen.query_one("#dir-input", Input).value == str(world.bad_dir)
    select_value = {TransportMode.SPI_USB_BRIDGE: "spi", TransportMode.USB_OUTPUT: "usb"}.get(
        world.config.mode, world.config.mode.value
    )
    assert screen.query_one("#mode-select", Select).value == select_value
    assert screen.query_one("#port-select", Select).value == world.config.port
    baud = screen.query_one("#baud-select", Select)
    assert baud.value == world.config.baudrate
    assert baud.display is (world.config.mode is TransportMode.UART)
    world.runner.run(world.pilot.click("#refresh-btn"))
    _pause(world)
    assert screen.query_one("#port-select", Select).value == world.config.port
    assert label.render().plain == text
    assert len([s for s in world.app.screen_stack if isinstance(s, LaunchScreen)]) == 1


@then("没有创建新的录制会话或 pipeline，先前录制状态和文件不变")
def recording_untouched(start_world: SimpleNamespace) -> None:
    world = start_world
    assert world.session_type.call_count == world.pipeline_type.call_count == world.initial_count
    assert world.pipeline_type.return_value.start.call_count == world.initial_count
    assert _recording_state(world.app) == world.before
    assert all(path.read_bytes() == data for path, data in world.files.items())
    assert world.refusals
    assert not list(world.bad_dir.glob("ble_log*"))
    if world.initial_count == 0:
        assert world.app._capture_session is None and world.app._capture_report is None
        assert world.app._output_path is None and world.app.saved_report_path is None


@when("用户保持目录不变再次点击 Connect")
def retry_refused(start_world: SimpleNamespace) -> None:
    start_world.runner.run(start_world.pilot.click("#connect-btn"))
    _pause(start_world)
    assert len(start_world.refusals) == 2


@when("用户改用可写目录并点击 Connect")
def correct_directory(start_world: SimpleNamespace) -> None:
    start_world.app.screen.query_one("#dir-input", Input).value = str(start_world.good_dir)
    start_world.runner.run(start_world.pilot.click("#connect-btn"))
    _pause(start_world)


@then("只创建一个使用原连接配置和新目录的录制会话")
def one_corrected_session(start_world: SimpleNamespace) -> None:
    world = start_world
    assert world.session_type.call_count == world.pipeline_type.call_count == world.initial_count + 1
    config, output = world.session_type.call_args.args
    assert config.mode is world.config.mode and config.port == world.config.port
    assert config.baudrate == world.config.baudrate
    assert output.parent == world.good_dir and output.exists()
    assert world.app._capture_session is not world.before["session"]
    assert not world.app._capture_session.finished
    assert world.app.saved_capture_paths == world.app.saved_console_log_paths == []
    assert world.app.saved_report_path is None and world.app._capture_report is None
    assert world.app.query_one(LogView).lines == []
    assert not isinstance(world.app.screen, LaunchScreen)


@then("先前文件未被覆盖，新文件名已独占预留")
def reserved_without_overwrite(start_world: SimpleNamespace) -> None:
    world = start_world
    assert all(path.read_bytes() == data for path, data in world.files.items())
    reserved = world.app._output_path
    with pytest.raises(FileExistsError):
        reserved.open("xb")
    following = unique_capture_path(world.good_dir)
    assert following != reserved and following.exists()


@when("用户切换到可用的 UART 模式")
def switch_to_uart(start_world: SimpleNamespace) -> None:
    start_world.app.screen.query_one("#mode-select", Select).value = "uart"
    _pause(start_world)


@then("当前端口属于 UART，存储错误仍然可见")
def working_mode_keeps_error(start_world: SimpleNamespace) -> None:
    world = start_world
    screen = world.app.screen
    assert screen.query_one("#port-select", Select).value == "/dev/ttyACM-stub"
    assert world.reason in screen.query_one("#start-error", Label).render().plain
    assert screen.query_one("#dir-input", Input).value == str(world.bad_dir)
    assert screen.query_one("#baud-select", Select).display
    assert world.session_type.call_count == world.pipeline_type.call_count == 0
    world.config = TransportConfig(TransportMode.UART, "/dev/ttyACM-stub", "/dev/ttyACM-stub", world.config.baudrate)


@when("用户在设置页按 q")
def cancel_setup(start_world: SimpleNamespace) -> None:
    start_world.runner.run(start_world.pilot.press("q"))
    _pause(start_world)


@then("程序正常退出，保留先前录制路径和文件")
def cancel_keeps_recording(start_world: SimpleNamespace) -> None:
    world = start_world
    assert world.app._exception is None and not world.app.is_running
    assert world.app.saved_capture_paths == world.before["raw_paths"]
    assert world.app.saved_console_log_paths == world.before["console_paths"]
    assert world.app.saved_report_path == world.before["report_path"]
    assert all(path.read_bytes() == data for path, data in world.files.items())
    assert world.session_type.call_count == world.initial_count


@pytest.mark.parametrize(
    ("mode", "select_value"),
    [("UART", "uart"), ("USJ", "usj"), ("SPI_USB_BRIDGE", "spi"), ("USB_OUTPUT", "usb")],
)
def test_recovery_setup_preserves_seed_and_refresh_selection_across_modes(
    start_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, mode: str, select_value: str
) -> None:
    world = start_world
    monkeypatch.setattr(
        "src.frontend.launch_screen.list_transport_port_options",
        lambda mode: [(mode.value + " other", mode.value + "-other")],
    )
    monkeypatch.setattr("src.i18n._language", "zh_CN")
    choose_entry(world, "命令行启动", mode)
    refuse_storage(world, monkeypatch, "预留文件", "EACCES")
    attempt_start(world)
    screen = world.app.screen
    assert isinstance(screen, LaunchScreen)
    assert screen.query_one("#mode-select", Select).value == select_value
    assert screen.query_one("#port-select", Select).value == "attempted"
    assert screen.query_one("#baud-select", Select).value == 1234567
    error = screen.query_one("#start-error", Label).render().plain
    assert error == (
        f"无法在 {world.bad_dir} 开始录制：[Errno 13] storage [refused]。"
        "请选择其他日志目录或排除存储错误，然后点击 Connect。"
    )
    screen.query_one("#port-select", Select).value = world.config.mode.value + "-other"
    _pause(world)
    world.runner.run(world.pilot.click("#refresh-btn"))
    _pause(world)
    assert screen.query_one("#port-select", Select).value == world.config.mode.value + "-other"
    next_mode = "usj" if mode == "UART" else "uart"
    screen.query_one("#mode-select", Select).value = next_mode
    _pause(world)
    assert screen.query_one("#port-select", Select).value == next_mode + "-other"
    assert screen.query_one("#baud-select", Select).display is (next_mode == "uart")
    assert screen.query_one("#dir-input", Input).value == str(world.bad_dir)
    assert screen.query_one("#start-error", Label).render().plain == error
    assert world.session_type.call_count == world.pipeline_type.call_count == 0


@pytest.mark.parametrize("language", ["en", "zh_CN"])
def test_refresh_discovery_failure_preserves_seed_and_storage_error(
    start_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    world = start_world
    choose_entry(world, "命令行启动", "SPI_USB_BRIDGE")
    refuse_storage(world, monkeypatch, "预留文件", "EACCES")
    attempt_start(world)
    screen = world.app.screen
    error = screen.query_one("#start-error", Label).render().plain
    missing_usb_backend(world, monkeypatch)
    monkeypatch.setattr("src.i18n._language", language)
    world.runner.run(world.pilot.click("#refresh-btn"))
    _pause(world)
    assert screen.query_one("#port-select", Select).value == "attempted"
    assert screen.query_one("#start-error", Label).render().plain == error
    messages = [notification.message for notification in world.app._notifications]
    expected = (
        "Failed to list ports: No backend available" if language == "en" else "无法列出端口：No backend available"
    )
    assert expected in messages
    recording_untouched(world)
    monkeypatch.setattr("usb.core.find", lambda **kwargs: [])
    world.runner.run(world.pilot.click("#refresh-btn"))
    _pause(world)
    assert screen.query_one("#port-select", Select).value == "attempted"
    assert screen.query_one("#start-error", Label).render().plain == error


@given("初始 UART 端口发现被拒绝")
def initial_discovery_refused(start_world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_discovery():
        raise PermissionError(errno.EACCES, "discovery [refused]")

    monkeypatch.setattr("serial.tools.list_ports.comports", refuse_discovery)
    monkeypatch.setattr("src.frontend.launch_screen.list_transport_port_options", list_transport_port_options)


@when("用户打开设置页")
def open_fresh_setup(start_world: SimpleNamespace) -> None:
    world = start_world
    world.app = BLELogApp(log_dir=world.tmp_path)
    world.run = world.app.run_test(size=(120, 55))
    world.pilot = world.runner.run(world.run.__aenter__())
    _pause(world)
    world.before = _recording_state(world.app)
    world.files = {}
    world.initial_count = 0


@when(parsers.parse("用户将显示语言切换为 {language}"))
def select_setup_language(start_world: SimpleNamespace, language: str) -> None:
    start_world.app.screen.query_one("#language-select", Select).value = language
    _pause(start_world)
    start_world.language = language


@then("设置控件已经挂载，Refresh 后空端口仍不能开始录制")
def fresh_setup_rejects_blank_port(start_world: SimpleNamespace) -> None:
    world = start_world
    screen = world.app.screen
    assert isinstance(screen, LaunchScreen)
    assert screen.query_one("#dir-input", Input).value == str(world.tmp_path)
    assert screen.query_one("#port-select", Select).is_blank()
    world.runner.run(world.pilot.click("#refresh-btn"))
    _pause(world)
    assert screen.query_one("#port-select", Select).is_blank()
    world.runner.run(world.pilot.click("#connect-btn"))
    _pause(world)
    assert world.app.screen is screen
    assert world.session_type.call_count == world.pipeline_type.call_count == 0
    expected = {"en": "Please select a port", "zh_CN": "请选择端口"}[world.language]
    assert expected in [notification.message for notification in world.app._notifications]
