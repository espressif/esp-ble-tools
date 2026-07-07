# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Textual application backed by the capture pipeline."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import cast

from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message

from src.backend.pipeline import CapturePipeline
from src.backend.writer import RawWriterConfig
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
from src.backend.models import TrafficSpikeDetected
from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.models import UserNotice
from src.backend.models import format_bitrate
from src.backend.models import resolve_source_name
from src.frontend.capture_view import CaptureView
from src.frontend.launch_screen import LaunchScreen
from src.frontend.log_view import LogView
from src.frontend.shortcut_screen import ShortcutScreen
from src.frontend.stats_screen import BufUtilScreen
from src.frontend.stats_screen import StatsScreen
from src.frontend.status_panel import StatusPanel

PIPELINE_POLL_INTERVAL_SEC = 0.05
PIPELINE_JOIN_TIMEOUT_SEC = 2.0


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
        self._pipeline: CapturePipeline | None = None
        self._capture_view: CaptureView | None = None
        self._pipeline_finished = False
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
        self._pipeline_finished = False

    def _start_capture(self) -> None:
        if self._transport_config is None or self._output_path is None:
            self.post_message(BackendStopped('Configuration missing'))
            return

        self._capture_start_time = time.perf_counter()
        self._capture_view = CaptureView(self._output_path, debug=self._debug)
        self._pipeline = CapturePipeline(self._transport_config, RawWriterConfig(self._output_path))

        try:
            self._pipeline.start()
        except Exception as e:
            self._publish_view_messages((UserNotice(f'Failed to start capture: {e}', level='warning'),))
            self.post_message(BackendStopped(str(e)))
            self._pipeline_finished = True
            return

        self.set_interval(PIPELINE_POLL_INTERVAL_SEC, self._poll_pipeline)

    def _poll_pipeline(self) -> None:
        pipeline = self._pipeline
        capture_view = self._capture_view
        if pipeline is None or capture_view is None or self._pipeline_finished:
            return

        self._publish_view_messages(capture_view.handle_events(pipeline.drain_events()))
        if pipeline.is_alive():
            return

        self._finish_pipeline(pipeline, capture_view)

    def _finish_pipeline(self, pipeline: CapturePipeline, capture_view: CaptureView) -> None:
        self._pipeline_finished = True
        events, result = pipeline.wait_with_events(PIPELINE_JOIN_TIMEOUT_SEC)
        self._publish_view_messages(capture_view.handle_events(events))
        self._publish_view_messages(capture_view.handle_result(result))
        self._pipeline = None
        self._capture_view = None

    def _publish_view_messages(self, messages: tuple[Message, ...]) -> None:
        self._sync_capture_state()
        for message in messages:
            self.post_message(message)

    def _sync_capture_state(self) -> None:
        if self._capture_view is None:
            return
        state = self._capture_view.state
        self._saved_capture_path = state.saved_capture_path
        self._saved_capture_paths = list(state.saved_capture_paths)
        self._saved_console_log_path = state.saved_console_log_path
        self._saved_console_log_paths = list(state.saved_console_log_paths)

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

    def on_traffic_spike_detected(self, msg: TrafficSpikeDetected) -> None:
        log_view = self.query_one(LogView)
        if not self._debug:
            log_view.write_info(
                f'High realtime log traffic: {format_bitrate(msg.throughput_bits_per_sec)} '
                f'for {msg.duration_ms:.0f}ms. Raw capture continues; live stats may lag.'
            )
            return

        top_sources = sorted(msg.per_source.items(), key=lambda x: x[1], reverse=True)
        src_parts = ', '.join(f'{resolve_source_name(s)} {p:.0f}%' for s, p in top_sources if p >= 1.0)
        if msg.utilization_pct >= 100.0:
            util_str = 'saturated'
        else:
            util_str = f'{msg.utilization_pct:.0f}% wire'
        log_view.write_traffic(
            f'{format_bitrate(msg.throughput_bits_per_sec)} ({util_str}) over {msg.duration_ms:.0f}ms | {src_parts}'
        )

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
        pipeline = self._pipeline
        if pipeline is None or self._pipeline_finished:
            self.query_one(LogView).write_warning('Reset is not available because capture is not running')
            return
        pipeline.reset_target()

    def action_quit(self) -> None:
        pipeline = self._pipeline
        if pipeline is None or self._pipeline_finished:
            self.exit()
            return

        self._exit_after_backend_stop = True
        pipeline.stop()
        self.post_message(UserNotice('Finishing capture: saving remaining transport data before exit.'))
