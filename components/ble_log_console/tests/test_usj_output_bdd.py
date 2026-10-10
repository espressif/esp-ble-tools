# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/usj_output.feature."""

from __future__ import annotations

import asyncio
import errno
import os
import struct
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial
from click.testing import CliRunner
from console import _parse_transport_mode, cli
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.models import LaunchConfig, TransportMode
from src.backend.support.transport.usj_transport import UsjTransport, list_usj_ports
from src.frontend.launch_screen import LaunchScreen
from textual.app import App
from textual.widgets import Select

scenarios("features/usj_output.feature")

_COMPORTS = "serial.tools.list_ports.comports"


class ModemLineModel:
    """DTR/RTS of one device node, driven by the real pyserial ioctls on a virtual tty.

    A pty has no modem lines, so this model owns them: every open of the node
    starts from ``opened_state`` (Linux CDC-ACM asserts both lines on open), and
    each TIOCMBIS/TIOCMBIC moves the state. ``opened_state=None`` passes the
    ioctls through, so the pty answers as a tty without modem lines does.
    """

    def __init__(self, path: str, opened_state: dict[str, bool] | None, monkeypatch: pytest.MonkeyPatch) -> None:
        fcntl = pytest.importorskip("fcntl", reason="POSIX-only modem-line model")
        termios = pytest.importorskip("termios", reason="POSIX-only modem-line model")
        line_bits = {termios.TIOCM_DTR: "DTR", termios.TIOCM_RTS: "RTS"}
        line_requests = (termios.TIOCMBIS, termios.TIOCMBIC)
        self.path = path
        self.opened_state = opened_state
        self.real_open = os.open
        self.sessions: list[list[str]] = []
        self.line_ioctls: list[str] = []
        self.opened_fds: list[int] = []
        self.closed_fds: list[int] = []
        self.writes = 0
        self.fail_on: str | None = None
        self._states: dict[int, dict[str, bool]] = {}
        real_ioctl, real_close, real_write = fcntl.ioctl, os.close, os.write

        def model_open(path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
            fd = self.real_open(path, flags, mode, dir_fd=dir_fd)
            if path == self.path:
                self.opened_fds.append(fd)
                if self.opened_state is not None:
                    self._states[fd] = dict(self.opened_state)
                    self.sessions.append([self._label(fd)])
            return fd

        def model_ioctl(fd: int, request: int, arg: object = 0, *rest: object) -> object:
            if fd not in self._states and not (fd in self.opened_fds and request in line_requests):
                return real_ioctl(fd, request, arg, *rest)  # type: ignore[arg-type]
            if request not in line_requests:
                return real_ioctl(fd, request, arg, *rest)  # type: ignore[arg-type]
            line = line_bits[struct.unpack("I", arg)[0]]  # type: ignore[arg-type]
            action = "set" if request == termios.TIOCMBIS else "clear"
            self.line_ioctls.append(f"{action} {line}")
            if self.fail_on == f"{action} {line}":
                raise OSError(errno.EIO, "Input/output error")
            if fd not in self._states:
                return real_ioctl(fd, request, arg, *rest)  # type: ignore[arg-type]
            self._states[fd][line] = request == termios.TIOCMBIS
            self.sessions[-1].append(self._label(fd))
            return arg

        def model_close(fd: int) -> None:
            if fd in self.opened_fds:
                self.closed_fds.append(fd)
                self._states.pop(fd, None)
            real_close(fd)

        def model_write(fd: int, data: bytes) -> int:
            if fd in self.opened_fds and fd not in self.closed_fds:
                self.writes += 1
            return real_write(fd, data)

        monkeypatch.setattr(os, "open", model_open)
        monkeypatch.setattr(os, "close", model_close)
        monkeypatch.setattr(os, "write", model_write)
        monkeypatch.setattr(fcntl, "ioctl", model_ioctl)

    def _label(self, fd: int) -> str:
        state = self._states[fd]
        return f"{int(state['DTR'])}/{int(state['RTS'])}"

    def trajectory(self, session: int = -1) -> list[str]:
        states = self.sessions[session]
        return [state for index, state in enumerate(states) if index == 0 or state != states[index - 1]]


@pytest.fixture
def world() -> Iterator[SimpleNamespace]:
    namespace = SimpleNamespace(ports=[], listed=[], failure=None, held_fd=None, pty_fds=())
    yield namespace
    if namespace.held_fd is not None:
        os.close(namespace.held_fd)
    for fd in namespace.pty_fds:
        os.close(fd)


@given("系统上有这些串口设备", target_fixture="world")
def serial_devices(world: SimpleNamespace, datatable: list[list[str]]) -> SimpleNamespace:
    for device, vid_pid, product in datatable[1:]:
        vendor, product_id = (int(part, 16) for part in vid_pid.split(":"))
        world.ports.append(SimpleNamespace(device=device, vid=vendor, pid=product_id, product=product))
    return world


@when("列出 USJ 端口")
def list_ports(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_COMPORTS, lambda: list(world.ports))
    world.listed = list_usj_ports()


@then("列出的端口是")
def listed_ports_are(world: SimpleNamespace, datatable: list[list[str]]) -> None:
    assert [value for _, value in world.listed] == [row[0] for row in datatable]


@then(parsers.parse('端口标签是 "{label}"'))
def port_label_is(world: SimpleNamespace, label: str) -> None:
    assert [port_label for port_label, _ in world.listed] == [label]


def _virtual_usj_port(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, opened: str | None) -> None:
    pty = pytest.importorskip("pty", reason="POSIX-only virtual terminal", exc_type=ImportError)
    master_fd, slave_fd = pty.openpty()
    world.pty_fds = (master_fd, slave_fd)
    path = os.ttyname(slave_fd)
    state = (
        None if opened is None else dict(zip(("DTR", "RTS"), (bit == "1" for bit in opened.split("/")), strict=True))
    )
    world.lines = ModemLineModel(path, state, monkeypatch)
    world.reader = UsjTransport(path, 3_000_000)


@given(parsers.parse("一个 USJ 虚拟串口，设备打开后 DTR/RTS 为 {opened}"))
def virtual_usj_port(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, opened: str) -> None:
    _virtual_usj_port(world, monkeypatch, opened)


@given("一个不支持 DTR/RTS 的 USJ 虚拟串口")
def virtual_usj_port_without_lines(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _virtual_usj_port(world, monkeypatch, None)


@given(parsers.parse('一个 USJ 端口 "{device}"'))
def usj_port(world: SimpleNamespace, device: str) -> None:
    world.reader = UsjTransport(device, 3_000_000)


@given("该端口已被其他程序独占")
def port_is_held(world: SimpleNamespace) -> None:
    fcntl = pytest.importorskip("fcntl", reason="POSIX-only exclusive lock")
    world.held_fd = world.lines.real_open(world.lines.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    fcntl.flock(world.held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


@given("该平台不支持独占打开")
def exclusive_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    fcntl = pytest.importorskip("fcntl", reason="POSIX-only exclusive lock")

    def refuse(fd: int, operation: int) -> None:
        raise ValueError("exclusive access is not supported on this platform")

    monkeypatch.setattr(fcntl, "flock", refuse)


@given("释放 RTS 时设备返回 I/O 错误")
def releasing_rts_fails(world: SimpleNamespace) -> None:
    world.lines.fail_on = "clear RTS"


@when("打开该 USJ 端口")
def open_port(world: SimpleNamespace) -> None:
    world.reader.open()
    world.ioctls_after_open = len(world.lines.line_ioctls)


@when("尝试打开该 USJ 端口")
def try_open_port(world: SimpleNamespace) -> None:
    try:
        world.reader.open()
    except OSError as error:
        world.failure = error


@then(parsers.parse("DTR/RTS 依次经过 {states}"))
def line_trajectory(world: SimpleNamespace, states: str) -> None:
    assert world.lines.trajectory() == states.split("、")


@then("线路从未处于 RTS 有效而 DTR 无效")
def never_reset_state(world: SimpleNamespace) -> None:
    assert world.lines.sessions, "the model saw the port being opened"
    assert all("0/1" not in session for session in world.lines.sessions), world.lines.sessions


@then("打开后 DTR 和 RTS 都无效，且没有写入任何数据")
def lines_released_without_writes(world: SimpleNamespace) -> None:
    assert world.lines.sessions[-1][-1] == "0/0"
    assert world.lines.writes == 0
    assert world.reader.status().opened is True


@then("打开失败并提示端口无法独占")
def open_refused(world: SimpleNamespace) -> None:
    assert isinstance(world.failure, serial.SerialException)
    assert "exclusively lock" in str(world.failure)
    assert world.reader.status().opened is False


@then("只打开过一次设备")
def single_open_attempt(world: SimpleNamespace) -> None:
    assert len(world.lines.opened_fds) == 1


@then("设备被打开两次")
def opened_twice(world: SimpleNamespace) -> None:
    assert len(world.lines.opened_fds) == 2


@then("没有改动 DTR 或 RTS")
def no_line_changes(world: SimpleNamespace) -> None:
    assert world.lines.line_ioctls == []
    assert world.lines.trajectory() == ["1/1"]


@then("打开失败并说明无法释放 DTR/RTS")
def release_failure_reported(world: SimpleNamespace) -> None:
    assert world.failure is not None and not isinstance(world.failure, serial.SerialException)
    assert world.failure.errno == errno.EIO
    assert "DTR/RTS" in str(world.failure) and world.lines.path in str(world.failure)
    assert world.reader.status().opened is False


@then("设备句柄已关闭")
def handle_closed(world: SimpleNamespace) -> None:
    assert world.lines.opened_fds and world.lines.closed_fds == world.lines.opened_fds


@then("该端口已打开")
def port_is_open(world: SimpleNamespace) -> None:
    assert world.reader.status().opened is True
    assert world.lines.line_ioctls[world.ioctls_after_open :] == [], "a reset request writes no line"


@when("请求复位 USJ 目标")
def request_reset(world: SimpleNamespace) -> None:
    world.reset_result = world.reader.reset_target()


@then("复位报告为未执行")
def reset_not_done(world: SimpleNamespace) -> None:
    assert world.reset_result is False
    world.reader.close()


@when("读取该 USJ 端口的速率配置")
def read_bitrate(world: SimpleNamespace) -> None:
    world.bitrate = world.reader.bitrate_config


@then("线速上限为空")
def no_wire_limit(world: SimpleNamespace) -> None:
    assert world.bitrate.wire_bits_per_sec is None
    assert world.bitrate.max_payload_bytes_per_sec is None


@when(parsers.parse('用 "{name}" 选择传输模式'))
def select_mode(world: SimpleNamespace, name: str) -> None:
    world.selected_mode = _parse_transport_mode(name)


@then("得到 USJ 模式")
def got_usj_mode(world: SimpleNamespace) -> None:
    assert world.selected_mode is TransportMode.USJ


@then(parsers.parse('命令行帮助列出模式 "{choices}"'))
def help_lists_modes(choices: str) -> None:
    for args in (["--help"], ["ports", "--help"]):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0
        assert choices in result.output


@then('用 "usb" 选择传输模式仍得到 USB Output 模式')
def usb_still_usb_output() -> None:
    assert _parse_transport_mode("usb") is TransportMode.USB_OUTPUT


@when("在启动界面选择 USJ 模式并连接")
def launch_and_connect(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_COMPORTS, lambda: list(world.ports))
    results: list[LaunchConfig | None] = []

    class LaunchApp(App[None]):
        def on_mount(self) -> None:
            self.push_screen(LaunchScreen(default_log_dir=tmp_path), callback=results.append)

    async def drive() -> None:
        app = LaunchApp()
        async with app.run_test(size=(100, 50)) as pilot:
            await pilot.pause()
            app.screen.query_one("#mode-select", Select).value = "usj"
            await pilot.pause()
            world.baud_visible = app.screen.query_one("#baud-select", Select).display
            await pilot.click("#connect-btn")
            await pilot.pause()

    asyncio.run(drive())
    world.launch_results = results


@then("波特率选项被隐藏")
def baud_hidden(world: SimpleNamespace) -> None:
    assert world.baud_visible is False


@then(parsers.parse('连接配置为 USJ 模式、端口 "{port}"'))
def connected_with_usj(world: SimpleNamespace, port: str) -> None:
    assert len(world.launch_results) == 1
    config = world.launch_results[0]
    assert config is not None
    assert config.transport_config.mode is TransportMode.USJ
    assert config.transport_config.port == port
