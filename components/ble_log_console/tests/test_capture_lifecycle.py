import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from textual.app import App

from src.app import BLELogApp
from src.app import unique_capture_path
from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.models import CaptureFinished
from src.backend.models import FrameStats
from src.backend.models import SequenceSourceSummary
from src.backend.models import SequenceSummary
from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.pipeline.controller import CapturePipelineResult
from src.frontend.capture_session import CaptureSession
from src.frontend.capture_report import CaptureReportScreen
from src.frontend.capture_report import build_capture_report


def _completed_result(path: Path) -> CapturePipelineResult:
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=20,
        parser_raw_bytes=20,
        parser_frames=1,
        parser_carried_bytes=0,
        regular_frames=1,
        sequence=SequenceSummary((SequenceSourceSummary(5, 1, 7, 7, 0, 1),)),
    )
    return CapturePipelineResult(
        raw_paths=(path,),
        reader_error=None,
        writer_error=None,
        parser_error=None,
        aggregator_error=None,
        parse_backlog=False,
        raw_bytes=20,
        parser_raw_bytes=20,
        parser_frames=1,
        parser_carried_bytes=0,
        completed=True,
        writer_finalized=True,
        aggregator_finalized=True,
        final_snapshot=snapshot,
    )


def test_unique_capture_path_never_overwrites_same_second(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5)
    first = unique_capture_path(tmp_path, now)
    first.write_bytes(b'old')

    second = unique_capture_path(tmp_path, now)

    assert second.name == 'ble_log_20260102_030405_002.bin'


def test_session_finishes_with_saved_report(tmp_path: Path) -> None:
    output = tmp_path / 'capture.bin'
    config = TransportConfig(TransportMode.UART, 'COM3', 'COM3', 921600)
    with patch('src.frontend.capture_session.CapturePipeline') as pipeline_type:
        pipeline = pipeline_type.return_value
        pipeline.is_alive.return_value = False
        pipeline.drain_events.return_value = []
        pipeline.wait_with_events.return_value = ([], _completed_result(output))
        session = CaptureSession(config, output)
        assert session.start() == ()

        messages = session.poll()

    finished = next(message for message in messages if isinstance(message, CaptureFinished))
    assert finished.report.report_path.read_text(encoding='utf-8').startswith('BLE Log Capture Report')
    assert session.report is finished.report


def test_session_stop_is_idempotent(tmp_path: Path) -> None:
    config = TransportConfig(TransportMode.UART, 'COM3', 'COM3', 921600)
    with patch('src.frontend.capture_session.CapturePipeline') as pipeline_type:
        session = CaptureSession(config, tmp_path / 'capture.bin')
        session.stop()
        session.stop()

    pipeline_type.return_value.stop.assert_called_once_with()


def test_report_write_failure_keeps_capture_result(tmp_path: Path) -> None:
    output = tmp_path / 'capture.bin'
    config = TransportConfig(TransportMode.UART, 'COM3', 'COM3', 921600)
    with (
        patch('src.frontend.capture_session.CapturePipeline') as pipeline_type,
        patch('src.frontend.capture_session.write_capture_report', side_effect=OSError('read only')),
    ):
        pipeline = pipeline_type.return_value
        pipeline.is_alive.return_value = False
        pipeline.drain_events.return_value = []
        pipeline.wait_with_events.return_value = ([], _completed_result(output))
        session = CaptureSession(config, output)
        session.start()

        messages = session.poll()

    finished = next(message for message in messages if isinstance(message, CaptureFinished))
    assert finished.report.raw_paths == (output,)
    assert finished.report.report_write_error == 'read only'


def test_app_ignores_repeated_stop_while_finalizing() -> None:
    app = BLELogApp(port='COM3')
    session = MagicMock()
    session.finished = False
    app._capture_session = session
    panel = MagicMock()
    button = MagicMock()

    def query(selector, widget_type=None):
        del widget_type
        if selector == '#stop-review':
            return button
        return panel

    app.query_one = query  # type: ignore[method-assign]
    app.post_message = MagicMock()  # type: ignore[method-assign]
    app.exit = MagicMock()  # type: ignore[method-assign]

    app.action_quit()
    app._stop_and_review()

    session.stop.assert_called_once_with()
    app.exit.assert_not_called()
    assert app._finalizing


def test_capture_report_screen_mounts_with_actions(tmp_path: Path) -> None:
    config = TransportConfig(TransportMode.UART, 'COM3', 'COM3', 921600)
    report = build_capture_report(
        _completed_result(tmp_path / 'capture.bin'),
        config,
        started_at=datetime(2026, 1, 1, 12, 0, 0),
        ended_at=datetime(2026, 1, 1, 12, 0, 1),
        duration_sec=1.0,
        console_log_paths=(),
        report_path=tmp_path / 'capture_report.txt',
    )

    class ReportHost(App):
        def on_mount(self) -> None:
            self.push_screen(CaptureReportScreen(report))

    async def run() -> None:
        async with ReportHost().run_test() as pilot:
            await pilot.pause()
            assert pilot.app.screen.query_one('#capture-report-verdict')
            assert pilot.app.screen.query_one('#record-again')
            assert pilot.app.screen.query_one('#exit-report')
            assert not pilot.app.screen.query('#capture-report-language')

    asyncio.run(run())
