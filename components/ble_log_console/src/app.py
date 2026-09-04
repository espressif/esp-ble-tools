# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Textual application backed by the capture pipeline."""

from __future__ import annotations

from contextlib import contextmanager
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator
from typing import cast
from typing import TextIO

from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message

from src.backend.models import BackendStopped
from src.backend.models import BufUtilEntry
from src.backend.models import FrameLossDetected
from src.backend.models import FunnelSnapshot
from src.backend.models import InfoResult
from src.backend.models import InternalFrameDecoded
from src.backend.models import InternalSource
from src.backend.models import LaunchConfig
from src.backend.models import LogLine
from src.backend.models import StatsUpdated
from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.models import UserNotice
from src.frontend.capture_session import CaptureSession
from src.frontend.launch_screen import LaunchScreen
from src.frontend.log_view import LogView
from src.frontend.shortcut_screen import ShortcutScreen
from src.frontend.stats_screen import BufUtilScreen
from src.frontend.stats_screen import StatsScreen
from src.frontend.status_panel import StatusPanel

PIPELINE_POLL_INTERVAL_SEC = 0.05


@contextmanager
def _spawn_stderr_with_real_fileno() -> Iterator[None]:
    """Expose a real stderr fd while multiprocessing processes are spawned.

    Textual replaces sys.stderr with an in-memory capture wrapper whose
    fileno() returns -1.  multiprocessing's resource tracker (only used by
    the spawn start method, the macOS default) passes sys.stderr.fileno()
    to the tracker child; a negative fd makes _posixsubprocess reject the
    fd list with 'bad value(s) in fds_to_keep', failing every process
    spawn.  While a pipeline is starting, keep routing writes to the
    capture wrapper but report the real stderr fd instead.
    """

    stream = sys.stderr
    fileno = getattr(stream, 'fileno', None)
    if not callable(fileno):
        yield
        return
    try:
        reported_fd = fileno()
    except Exception:
        reported_fd = -1
    if reported_fd >= 0:
        yield
        return

    real_stderr = sys.__stderr__
    if real_stderr is None or not callable(getattr(real_stderr, 'fileno', None)):
        yield  # no real fd available anywhere; leave the spawn to fail as-is
        return

    class _SpawnStderr:
        """Delegate all writes to the Textual capture wrapper, but report a real fd."""

        __slots__ = ('_capture', '_real')

        def __init__(self, capture: TextIO, real: TextIO) -> None:
            self._capture = capture
            self._real = real

        def fileno(self) -> int:
            return self._real.fileno()

        def __getattr__(self, name: str) -> object:
            return getattr(self._capture, name)

    sys.stderr = _SpawnStderr(stream, real_stderr)  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.stderr = stream  # type: ignore[assignment]


class BLELogApp(App):
    """BLE Log Console UI using the process-based capture pipeline."""

    CSS = """
    Screen {
        layout: vertical;
    }
    """

    BINDINGS = [
        Binding('q', 'quit', 'Quit'),
        Binding('Q', 'quit', show=False),
        Binding('ctrl+c', 'quit', show=False, priority=True),
        Binding('c', 'clear_log', 'Clear'),
        Binding('C', 'clear_log', show=False),
        Binding('s', 'toggle_scroll', 'Auto-scroll'),
        Binding('S', 'toggle_scroll', show=False),
        Binding('d', 'dump_stats', 'Stats'),
        Binding('D', 'dump_stats', show=False),
        Binding('m', 'show_buf_util', 'BufUtil'),
        Binding('M', 'show_buf_util', show=False),
        Binding('h', 'show_help', 'Help'),
        Binding('H', 'show_help', show=False),
        Binding('r', 'reset_chip', 'Reset'),
        Binding('R', 'reset_chip', show=False),
    ]

    def __init__(
        self,
        mode: TransportMode = TransportMode.UART,
        port: str | None = None,
        baudrate: int = 3_000_000,
        log_dir: Path | None = None,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self._debug = debug
        self._transport_config: TransportConfig | None = (
            TransportConfig(mode=mode, label=port, port=port, baudrate=baudrate) if port is not None else None
        )
        self._log_dir = log_dir or Path.cwd() / 'logs'
        self._output_path: Path | None = None
        self._capture_start_time = 0.0
        self._exit_after_backend_stop = False
        self._capture_session: CaptureSession | None = None
        self._saved_capture_path: Path | None = None
        self._saved_capture_paths: list[Path] = []
        self._saved_console_log_path: Path | None = None
        self._saved_console_log_paths: list[Path] = []
        self._funnel_snapshots: list[FunnelSnapshot] = []
        self._buf_util_snapshots: list[BufUtilEntry] = []

    def compose(self) -> ComposeResult:
        yield LogView()
        yield StatusPanel()

    def on_mount(self) -> None:
        if self._transport_config is not None:
            self._resolve_output_path()
            self._start_capture()
        else:
            self.push_screen(LaunchScreen(default_log_dir=self._log_dir), callback=self._on_launch_result)

    @property
    def funnel_snapshots(self) -> list[FunnelSnapshot]:
        return self._funnel_snapshots

    @property
    def buf_util_snapshots(self) -> list[BufUtilEntry]:
        return self._buf_util_snapshots

    @property
    def saved_capture_path(self) -> Path | None:
        return self._saved_capture_path

    @property
    def saved_capture_paths(self) -> list[Path]:
        return list(self._saved_capture_paths)

    @property
    def saved_console_log_path(self) -> Path | None:
        return self._saved_console_log_path

    @property
    def saved_console_log_paths(self) -> list[Path]:
        return list(self._saved_console_log_paths)

    def _on_launch_result(self, config: LaunchConfig | None) -> None:
        if config is None:
            self.exit()
            return
        self._transport_config = config.transport_config
        self._log_dir = config.log_dir
        self._resolve_output_path()
        self._start_capture()

    def _resolve_output_path(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._output_path = self._log_dir / f'ble_log_{ts}.bin'
        self._saved_capture_path = None
        self._saved_capture_paths = []
        self._saved_console_log_path = None
        self._saved_console_log_paths = []
        self._exit_after_backend_stop = False
        self._capture_session = None

    def _start_capture(self) -> None:
        if self._transport_config is None or self._output_path is None:
            self.post_message(BackendStopped('Configuration missing'))
            return

        self._capture_start_time = time.perf_counter()
        self._capture_session = CaptureSession(
            self._transport_config,
            self._output_path,
            debug=self._debug,
        )
        with _spawn_stderr_with_real_fileno():
            start_messages = self._capture_session.start()
        self._publish_view_messages(start_messages)
        if self._capture_session.finished:
            return

        self.set_interval(PIPELINE_POLL_INTERVAL_SEC, self._poll_pipeline)

    def _poll_pipeline(self) -> None:
        capture_session = self._capture_session
        if capture_session is None or capture_session.finished:
            return

        self._publish_view_messages(capture_session.poll())

    def _publish_view_messages(self, messages: tuple[Message, ...]) -> None:
        self._sync_capture_state()
        for message in messages:
            self.post_message(message)

    def _sync_capture_state(self) -> None:
        if self._capture_session is None:
            return
        self._saved_capture_path = self._capture_session.saved_capture_path
        self._saved_capture_paths = self._capture_session.saved_capture_paths
        self._saved_console_log_path = self._capture_session.saved_console_log_path
        self._saved_console_log_paths = self._capture_session.saved_console_log_paths

    # --- Message handlers ---

    def on_stats_updated(self, msg: StatsUpdated) -> None:
        panel = self.query_one(StatusPanel)
        panel.stats = msg.stats
        self._funnel_snapshots = msg.funnel_snapshots
        self._buf_util_snapshots = msg.buf_util_snapshots

    def on_internal_frame_decoded(self, msg: InternalFrameDecoded) -> None:
        if not self._debug:
            return
        if msg.int_src == InternalSource.INIT_DONE:
            info = cast(InfoResult, msg.payload)
            log_view = self.query_one(LogView)
            log_view.write_info(f'BLE Log v{info["version"]} initialized - statistics reset')
        elif msg.int_src == InternalSource.FLUSH:
            log_view = self.query_one(LogView)
            log_view.write_info('Firmware flush - SN counters reset')

    def on_log_line(self, msg: LogLine) -> None:
        self.query_one(LogView).write_ascii(msg.text)

    def on_user_notice(self, msg: UserNotice) -> None:
        log_view = self.query_one(LogView)
        if msg.level == 'warning':
            log_view.write_warning(msg.text)
        else:
            log_view.write_info(msg.text)

    def on_frame_loss_detected(self, msg: FrameLossDetected) -> None:
        log_view = self.query_one(LogView)
        log_view.write_warning(
            f'Frame loss [{msg.source_name}] ({msg.loss_type.value}): {msg.lost_frames} frames, {msg.lost_bytes} bytes'
        )

    def on_backend_stopped(self, msg: BackendStopped) -> None:
        log_view = self.query_one(LogView)
        log_view.write_warning(f'Backend stopped: {msg.reason}')
        panel = self.query_one(StatusPanel)
        panel.disconnected = True
        if self._exit_after_backend_stop:
            self.exit()

    # --- Actions ---

    def action_clear_log(self) -> None:
        self.query_one(LogView).clear()

    def action_toggle_scroll(self) -> None:
        log_view = self.query_one(LogView)
        log_view.auto_scroll = not log_view.auto_scroll

    def action_dump_stats(self) -> None:
        self.push_screen(StatsScreen(start_time=self._capture_start_time))

    def action_show_buf_util(self) -> None:
        self.push_screen(BufUtilScreen())

    def action_show_help(self) -> None:
        self.push_screen(ShortcutScreen())

    def action_reset_chip(self) -> None:
        capture_session = self._capture_session
        if capture_session is None or not capture_session.reset_target():
            self.query_one(LogView).write_warning('Reset is not available because capture is not running')
            return

    def action_quit(self) -> None:
        capture_session = self._capture_session
        if capture_session is None or capture_session.finished:
            self.exit()
            return

        self._exit_after_backend_stop = True
        capture_session.stop()
        self.post_message(UserNotice('Finishing capture: saving remaining transport data before exit.'))
