# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Textual App wiring backend Worker to frontend widgets.

See Spec Section 6.
"""

import os
import struct
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO
from typing import Any
from typing import cast

from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message

from src.backend.frame_parser import FrameParser
from src.backend.internal_decoder import decode_internal_frame
from src.backend.models import FRAME_OVERHEAD
from src.backend.models import LL_TS_OFFSET
from src.backend.models import BackendStopped
from src.backend.models import BleLogSource
from src.backend.models import BufUtilEntry
from src.backend.models import BufUtilResult
from src.backend.models import EnhStatResult
from src.backend.models import FrameLossDetected
from src.backend.models import FunnelSnapshot
from src.backend.models import InfoResult
from src.backend.models import InternalFrameDecoded
from src.backend.models import InternalSource
from src.backend.models import LaunchConfig
from src.backend.models import LogLine
from src.backend.models import LossType
from src.backend.models import ParsedFrame
from src.backend.models import SourcePeakWrite
from src.backend.models import StatsUpdated
from src.backend.models import SyncState
from src.backend.models import SyncStateChanged
from src.backend.models import TrafficSpikeDetected
from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.models import UserNotice
from src.backend.models import format_bitrate
from src.backend.models import format_bytes
from src.backend.models import has_os_ts
from src.backend.models import is_ll_source
from src.backend.models import resolve_source_name
from src.backend.stats import StatsAccumulator
from src.backend.transport import LogTransport
from src.backend.transport import open_transport
from src.frontend.launch_screen import LaunchScreen
from src.frontend.log_view import LogView
from src.frontend.shortcut_screen import ShortcutScreen
from src.frontend.stats_screen import BufUtilScreen
from src.frontend.stats_screen import StatsScreen
from src.frontend.status_panel import StatusPanel

STATS_INTERVAL = 0.25  # seconds
CAPTURE_PART_MAX_BYTES = 200 * 1024 * 1024
NO_DATA_WARNING_SEC = 10.0
NO_DATA_WARNING_COOLDOWN_SEC = 60.0
NO_FRAME_WARNING_SEC = 10.0
NO_FRAME_WARNING_COOLDOWN_SEC = 60.0
REDIR_LINE_BUFFER_LIMIT = 16 * 1024
CAPTURE_NOTICE_THRESHOLDS = (
    100 * 1024,
    500 * 1024,
    1 * 1024 * 1024,
    10 * 1024 * 1024,
    50 * 1024 * 1024,
    100 * 1024 * 1024,
)
CAPTURE_NOTICE_STEP = 100 * 1024 * 1024
QUIT_DRAIN_SECONDS = 0.3
QUIT_DRAIN_EMPTY_READS = 2
QUIT_DRAIN_MAX_SECONDS = 1.0


def _next_capture_notice_threshold(current: int) -> int:
    for threshold in CAPTURE_NOTICE_THRESHOLDS:
        if current < threshold:
            return threshold
    return current + CAPTURE_NOTICE_STEP


def _capture_part_path(base_path: Path, part_index: int) -> Path:
    if part_index <= 1:
        return base_path
    return base_path.with_name(f'{base_path.stem}_part{part_index:03d}{base_path.suffix}')


def _console_part_path(base_path: Path, part_index: int) -> Path:
    suffix = '' if part_index <= 1 else f'_part{part_index:03d}'
    return base_path.with_name(f'{base_path.stem}_console{suffix}.log')


def _flush_and_close_file(file_obj: IO[Any]) -> None:
    try:
        file_obj.flush()
        try:
            os.fsync(file_obj.fileno())
        except OSError:
            pass
    finally:
        file_obj.close()


class BLELogApp(App):
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
        self._saved_capture_path: Path | None = None
        self._saved_capture_paths: list[Path] = []
        self._saved_console_log_path: Path | None = None
        self._saved_console_log_paths: list[Path] = []
        self._transport: LogTransport | None = None
        self._stop_requested = threading.Event()
        self._exit_after_backend_stop = False
        # All-time per-source chip write peak (updated from StatsUpdated messages)
        self._max_per_source_peak: dict[int, SourcePeakWrite] | None = None
        self._ll_max_per_source_peak: dict[int, SourcePeakWrite] | None = None
        # Console-side per-source received bytes (from StatsUpdated snapshots)
        self._per_source_rx_bytes: dict[int, int] | None = None
        self._funnel_snapshots: list[FunnelSnapshot] = []
        self._buf_util_snapshots: list[BufUtilEntry] = []
        # Wall-clock capture start (set when backend loop begins)
        self._capture_start_time: float = 0.0
        self._transport_lock = threading.Lock()

    def compose(self) -> ComposeResult:
        yield LogView()
        yield StatusPanel()

    def on_mount(self) -> None:
        if self._transport_config is not None:
            self._resolve_output_path()
            self.run_worker(self._backend_loop, thread=True, exclusive=True)
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
        """Handle Launch Screen dismissal."""
        if config is None:
            self.exit()
            return
        self._transport_config = config.transport_config
        self._log_dir = config.log_dir
        self._resolve_output_path()
        self.run_worker(self._backend_loop, thread=True, exclusive=True)

    def _resolve_output_path(self) -> None:
        """Generate timestamped output file path in the log directory."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._output_path = self._log_dir / f'ble_log_{ts}.bin'
        self._saved_capture_path = None
        self._saved_capture_paths = []
        self._saved_console_log_path = None
        self._saved_console_log_paths = []
        self._stop_requested.clear()
        self._exit_after_backend_stop = False

    def _post(self, msg: Message) -> None:
        """Thread-safe message posting from backend worker."""
        self.call_from_thread(self.post_message, msg)

    def _emit_stats(self, stats: StatsAccumulator, parser: FrameParser, last_time: float) -> float:
        """Emit a stats snapshot if the interval has elapsed. Returns updated timestamp."""
        now = time.perf_counter()
        if now - last_time < STATS_INTERVAL:
            return last_time

        elapsed = now - last_time
        snapshot = stats.snapshot(
            elapsed,
            sync_state=parser.sync_state,
            checksum_mode=parser.checksum_mode,
        )
        funnel = stats.funnel_snapshot(elapsed)
        buf_util = stats.buf_util_snapshot()
        self._post(StatsUpdated(snapshot, funnel, buf_util))
        return now

    def _backend_loop(self) -> None:
        """Background worker: transport read -> parse -> stats -> messages."""
        transport_config = self._transport_config
        if transport_config is None or self._output_path is None:
            self._post(LogLine('Backend started without port/output configuration'))
            self._post(BackendStopped('Configuration missing'))
            return
        parser = FrameParser()
        stats = StatsAccumulator()
        redir_line_buf = ''
        prev_sync_state = SyncState.SEARCHING
        last_snapshot_time = time.perf_counter()
        captured_bytes = 0
        next_capture_notice = CAPTURE_NOTICE_THRESHOLDS[0]

        try:
            transport = open_transport(transport_config)
        except Exception as e:
            self._post(BackendStopped(f'Failed to open {transport_config.mode.value}: {e}'))
            return

        self._transport = transport
        stats.set_transport_bitrate(transport.bitrate_config)
        show_console_redirect = transport_config.mode is TransportMode.UART
        self._capture_start_time = time.perf_counter()
        last_data_time = self._capture_start_time
        last_frame_time = self._capture_start_time
        last_idle_warning_time = 0.0
        last_frame_warning_time = 0.0
        drain_started_at: float | None = None
        drain_empty_reads = 0
        if self._debug:
            self._post(LogLine(f'Connected to {transport.display_name}'))
        else:
            self._post(UserNotice(f'Connected to {transport.display_name}'))

        # Lazy file handles — created on first data arrival
        output_file = None
        capture_part_index = 1
        capture_part_bytes = 0
        output_path = _capture_part_path(self._output_path, capture_part_index)
        console_log_file = None
        console_part_index = 1
        console_part_bytes = 0
        console_log_path = _console_part_path(self._output_path, console_part_index)

        try:
            while True:
                if self._stop_requested.is_set() and drain_started_at is None:
                    drain_started_at = time.perf_counter()
                    drain_empty_reads = 0

                with self._transport_lock:
                    block = transport.read()
                if not block:
                    now = time.perf_counter()
                    if drain_started_at is not None:
                        drain_elapsed = now - drain_started_at
                        if drain_elapsed >= QUIT_DRAIN_MAX_SECONDS:
                            self._post(
                                UserNotice(
                                    'Capture finished after drain timeout; transport data was still active.',
                                    level='warning',
                                )
                            )
                            break
                        if drain_elapsed >= QUIT_DRAIN_SECONDS:
                            drain_empty_reads += 1
                            if drain_empty_reads >= QUIT_DRAIN_EMPTY_READS:
                                self._post(UserNotice('Capture finished; remaining transport data has been saved.'))
                                break
                        last_snapshot_time = self._emit_stats(stats, parser, last_snapshot_time)
                        continue
                    if (
                        not self._debug
                        and now - last_data_time >= NO_DATA_WARNING_SEC
                        and now - last_idle_warning_time >= NO_DATA_WARNING_COOLDOWN_SEC
                    ):
                        self._post(
                            UserNotice(
                                'No data received for 10s. Check transport mode, port, cable, and firmware logging.',
                                level='warning',
                            )
                        )
                        last_idle_warning_time = now
                    last_snapshot_time = self._emit_stats(stats, parser, last_snapshot_time)
                    continue
                if drain_started_at is not None:
                    drain_empty_reads = 0
                last_data_time = time.perf_counter()
                block_len = len(block)

                # 1. Save raw binary (lazy-open on first block)
                if output_file is None:
                    output_file = open(output_path, 'wb')  # noqa: SIM115
                    self._saved_capture_paths.append(output_path)
                    self._saved_capture_path = output_path
                    self._post(LogLine(f'Saving to {output_path}'))
                elif capture_part_bytes >= CAPTURE_PART_MAX_BYTES:
                    _flush_and_close_file(output_file)
                    capture_part_index += 1
                    output_path = _capture_part_path(self._output_path, capture_part_index)
                    output_file = open(output_path, 'wb')  # noqa: SIM115
                    capture_part_bytes = 0
                    self._saved_capture_paths.append(output_path)
                    self._saved_capture_path = output_path
                    self._post(UserNotice(f'Capture file rotated to {output_path}'))
                output_file.write(block)
                capture_part_bytes += block_len
                output_file.flush()
                # 2. Track bytes
                stats.record_bytes(block_len)
                captured_bytes += block_len

                # 3. Parse frames
                results = parser.feed(block)

                # 4. Check sync state transition
                if parser.sync_state != prev_sync_state:
                    self._post(SyncStateChanged(parser.sync_state))
                    prev_sync_state = parser.sync_state

                # 5. Process results
                frame_count_before = stats.frame_count
                for item in results:
                    if isinstance(item, ParsedFrame):
                        decoded = None
                        if item.source_code == BleLogSource.INTERNAL:
                            decoded = decode_internal_frame(item.payload)
                            if decoded is None:
                                continue

                            int_src = decoded['int_src']

                            # Reject false INIT_DONE from misaligned data:
                            # real firmware always has version >= 1.
                            if int_src == InternalSource.INIT_DONE:
                                info = cast(InfoResult, decoded)
                                if info['version'] == 0:
                                    continue

                        frame_size = len(item.payload) + FRAME_OVERHEAD
                        if item.source_code != BleLogSource.INTERNAL:
                            stats.record_frame(frame_size, item.source_code, item.frame_sn)
                            stats.record_frame_traffic(frame_size, item.source_code)
                        else:
                            stats.record_frame()  # count frame for transport metrics, no SN tracking
                        if has_os_ts(item.source_code) and item.source_code != BleLogSource.INTERNAL:
                            stats.record_frame_ts(item.os_ts_ms, frame_size, item.source_code)
                        elif is_ll_source(item.source_code) and len(item.payload) >= 6:
                            (lc_ts_us,) = struct.unpack_from('<I', item.payload, LL_TS_OFFSET)
                            stats.record_ll_frame_ts(lc_ts_us, frame_size, item.source_code)
                        elif item.source_code == BleLogSource.REDIR:
                            wall_ms = int(time.perf_counter() * 1000) & 0xFFFFFFFF
                            stats.record_frame_wall_ts(wall_ms, frame_size, item.source_code)

                        # Decode internal frames
                        if item.source_code == BleLogSource.INTERNAL:
                            if decoded:
                                int_src = decoded['int_src']

                                self._post(InternalFrameDecoded(int_src, decoded))

                                if int_src in (InternalSource.INIT_DONE, InternalSource.INFO):
                                    info = cast(InfoResult, decoded)
                                    stats.set_firmware_version(info['version'])
                                if int_src == InternalSource.INIT_DONE:
                                    stats.reset('init')
                                elif int_src == InternalSource.FLUSH:
                                    stats.reset('flush')
                                elif int_src == InternalSource.ENH_STAT:
                                    enh = cast(EnhStatResult, decoded)
                                    new_frames, new_bytes = stats.record_enh_stat(
                                        src_code=enh['src_code'],
                                        written_frames=enh['written_frame_cnt'],
                                        lost_frames=enh['lost_frame_cnt'],
                                        written_bytes=enh['written_bytes_cnt'],
                                        lost_bytes=enh['lost_bytes_cnt'],
                                    )
                                    if new_frames > 0:
                                        source_name = resolve_source_name(enh['src_code'])
                                        self._post(
                                            FrameLossDetected(
                                                source_name,
                                                loss_type=LossType.BUFFER,
                                                lost_frames=new_frames,
                                                lost_bytes=new_bytes,
                                            )
                                        )
                                elif int_src == InternalSource.BUF_UTIL:
                                    buf = cast(BufUtilResult, decoded)
                                    stats.record_buf_util(
                                        lbm_id=buf['lbm_id'],
                                        trans_cnt=buf['trans_cnt'],
                                        inflight_peak=buf['inflight_peak'],
                                    )

                        # Decode UART redirect frames (raw ASCII, no os_ts prefix).
                        # A single log line may span multiple frames due to
                        # batch sealing, so buffer partial lines until '\n'.
                        elif item.source_code == BleLogSource.REDIR and show_console_redirect:
                            payload_text = item.payload.decode('ascii', errors='replace')

                            # Write raw payload to console log (independent of line buffering)
                            if console_log_file is None:
                                console_log_file = open(console_log_path, 'w')  # noqa: SIM115
                                self._saved_console_log_paths.append(console_log_path)
                                self._saved_console_log_path = console_log_path
                            elif console_part_bytes >= CAPTURE_PART_MAX_BYTES:
                                _flush_and_close_file(console_log_file)
                                console_part_index += 1
                                console_log_path = _console_part_path(self._output_path, console_part_index)
                                console_log_file = open(console_log_path, 'w')  # noqa: SIM115
                                console_part_bytes = 0
                                self._saved_console_log_paths.append(console_log_path)
                                self._saved_console_log_path = console_log_path
                                self._post(UserNotice(f'Console log rotated to {console_log_path}'))
                            console_log_file.write(payload_text)
                            console_part_bytes += len(payload_text.encode(errors='replace'))
                            console_log_file.flush()

                            redir_line_buf += payload_text
                            while '\n' in redir_line_buf:
                                line, redir_line_buf = redir_line_buf.split('\n', 1)
                                if line:
                                    self._post(LogLine(line))
                            while len(redir_line_buf) > REDIR_LINE_BUFFER_LIMIT:
                                self._post(LogLine(redir_line_buf[:REDIR_LINE_BUFFER_LIMIT]))
                                redir_line_buf = redir_line_buf[REDIR_LINE_BUFFER_LIMIT:]

                    elif isinstance(item, str) and show_console_redirect:
                        self._post(LogLine(item))

                now = time.perf_counter()
                if stats.frame_count > frame_count_before:
                    last_frame_time = now
                elif (
                    captured_bytes > 0
                    and now - last_frame_time >= NO_FRAME_WARNING_SEC
                    and now - last_frame_warning_time >= NO_FRAME_WARNING_COOLDOWN_SEC
                ):
                    self._post(
                        UserNotice(
                            'Data is arriving, but no BLE log frames were decoded for 10s. '
                            'Check transport mode, wiring, and firmware log configuration.',
                            level='warning',
                        )
                    )
                    last_frame_warning_time = now

                if not self._debug:
                    while captured_bytes >= next_capture_notice:
                        self._post(
                            UserNotice(f'Have captured {format_bytes(captured_bytes)}, {stats.frame_count} frames')
                        )
                        next_capture_notice = _next_capture_notice_threshold(next_capture_notice)

                # 6. Traffic spike detection
                spike = stats.check_traffic()
                if spike is not None:
                    self._post(
                        TrafficSpikeDetected(
                            throughput_bits_per_sec=spike.throughput_bits_per_sec,
                            wire_max_bits_per_sec=spike.wire_max_bits_per_sec,
                            utilization_pct=spike.utilization_pct,
                            duration_ms=spike.duration_ms,
                            per_source=spike.per_source,
                        )
                    )

                # 7. Periodic stats snapshot
                last_snapshot_time = self._emit_stats(stats, parser, last_snapshot_time)
                if drain_started_at is not None and time.perf_counter() - drain_started_at >= QUIT_DRAIN_MAX_SECONDS:
                    self._post(
                        UserNotice(
                            'Capture finished after drain timeout; transport data was still active.',
                            level='warning',
                        )
                    )
                    break

        except Exception as e:
            if self._debug:
                self._post(LogLine(f'Error: {e}'))
            else:
                self._post(UserNotice(f'Error: {e}', level='warning'))
        finally:
            close_error: Exception | None = None
            try:
                transport.close()
            except Exception as e:
                close_error = e
            finally:
                self._transport = None
                if output_file is not None:
                    _flush_and_close_file(output_file)
                if console_log_file is not None:
                    _flush_and_close_file(console_log_file)
            if close_error is not None:
                self._post(UserNotice(f'Error while closing transport: {close_error}', level='warning'))
            self._post(BackendStopped('Transport connection closed, please restart this app.'))

    # --- Message handlers ---

    def on_sync_state_changed(self, msg: SyncStateChanged) -> None:
        if not self._debug:
            return
        log_view = self.query_one(LogView)
        log_view.write_sync(f'State: {msg.state.value}')

    def on_stats_updated(self, msg: StatsUpdated) -> None:
        panel = self.query_one(StatusPanel)
        panel.stats = msg.stats
        self._funnel_snapshots = msg.funnel_snapshots
        self._buf_util_snapshots = msg.buf_util_snapshots
        # Preserve all-time per-source peak for the stats screen
        if msg.stats.os_peak.max_per_source is not None:
            self._max_per_source_peak = msg.stats.os_peak.max_per_source
        if msg.stats.ll_peak.max_per_source is not None:
            self._ll_max_per_source_peak = msg.stats.ll_peak.max_per_source
        if msg.stats.per_source_rx_bytes is not None:
            self._per_source_rx_bytes = msg.stats.per_source_rx_bytes

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
        log_view = self.query_one(LogView)
        log_view.write_ascii(msg.text)

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
            log_view.write_warning(
                f'High log traffic: {format_bitrate(msg.throughput_bits_per_sec)} '
                f'for {msg.duration_ms:.0f}ms. Logs may be dropped.'
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
        """Reset target if the active transport supports it."""
        transport = self._transport
        if transport is None:
            return
        with self._transport_lock:
            reset_done = transport.reset_target()
        log_view = self.query_one(LogView)
        if reset_done:
            log_view.write_info('Chip reset triggered')
        else:
            log_view.write_warning('Reset is not supported by this transport')

    def action_quit(self) -> None:
        """Drain pending transport data before exiting the app."""
        if self._transport is None:
            self.exit()
            return
        if self._stop_requested.is_set():
            return

        self._exit_after_backend_stop = True
        self._stop_requested.set()
        self.post_message(UserNotice('Finishing capture: saving remaining transport data before exit.'))
