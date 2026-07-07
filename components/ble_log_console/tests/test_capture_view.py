# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from src.backend.aggregator.worker import AggregatorProcessEvent
from src.backend.aggregator.event_aggregator import AggregatorSnapshot
from src.backend.aggregator.event_aggregator import AggregatorUpdate
from src.backend.aggregator.event_aggregator import FrameLossUpdate
from src.backend.aggregator.event_aggregator import InternalFrameUpdate
from src.backend.pipeline.controller import CapturePipelineResult
from src.backend.writer.raw_writer import RawWriterProcessEvent
from src.backend.writer.raw_writer import RawWriterStatus
from src.backend.pipeline.reader import ReaderProcessEvent
from src.backend.parser.worker import ParserStatus
from src.backend.models import BackendStopped
from src.backend.models import FrameStats
from src.backend.models import InternalFrameDecoded
from src.backend.models import InternalSource
from src.backend.models import LogLine
from src.backend.models import LossType
from src.backend.models import StatsUpdated
from src.backend.models import TransportMode
from src.backend.models import UserNotice
from src.backend.support.transport import TransportStatus
from src.frontend.capture_view import CaptureView
from src.frontend.capture_view import console_log_part_path


def test_snapshot_event_becomes_stats_updated(tmp_path: Path) -> None:
    adapter = CaptureView(tmp_path / 'ble_log.bin')
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=0,
        parser_raw_bytes=0,
        parser_frames=0,
        parser_carried_bytes=0,
    )

    messages = adapter.handle_event(snapshot)

    assert len(messages) == 1
    assert isinstance(messages[0], StatsUpdated)
    assert messages[0].stats is snapshot.stats


def test_redir_text_writes_console_log_and_emits_complete_lines(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    adapter = CaptureView(output_path)

    first = adapter.handle_event(AggregatorUpdate(redir_texts=('hello ',)))
    second = adapter.handle_event(AggregatorUpdate(redir_texts=('world\npartial',)))

    assert first == ()
    assert len(second) == 1
    assert isinstance(second[0], LogLine)
    assert second[0].text == 'hello world'
    assert console_log_part_path(output_path, 1).read_text() == 'hello world\npartial'
    assert adapter.state.saved_console_log_paths == (console_log_part_path(output_path, 1),)


def test_redir_console_log_rotates_with_legacy_name(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    adapter = CaptureView(output_path, console_part_max_bytes=3)

    adapter.handle_event(AggregatorUpdate(redir_texts=('abc',)))
    adapter.handle_event(AggregatorUpdate(redir_texts=('de',)))
    adapter.close()

    assert console_log_part_path(output_path, 1).read_text() == 'abc'
    assert console_log_part_path(output_path, 2).read_text() == 'de'
    assert adapter.state.saved_console_log_paths == (
        console_log_part_path(output_path, 1),
        console_log_part_path(output_path, 2),
    )


def test_aggregator_update_maps_to_existing_ui_messages(tmp_path: Path) -> None:
    adapter = CaptureView(tmp_path / 'ble_log.bin')

    messages = adapter.handle_event(
        AggregatorUpdate(
            internal_frames=(
                InternalFrameUpdate(
                    int_src=InternalSource.INFO,
                    decoded={'int_src': InternalSource.INFO, 'version': 4, 'os_ts_ms': 1},
                ),
            ),
            frame_losses=(
                FrameLossUpdate(
                    source_name='HOST',
                    loss_type=LossType.BUFFER,
                    lost_frames=2,
                    lost_bytes=128,
                ),
            ),
        )
    )

    assert isinstance(messages[0], InternalFrameDecoded)
    assert messages[0].int_src == InternalSource.INFO
    assert messages[0].payload['version'] == 4
    assert messages[1].source_name == 'HOST'
    assert messages[1].lost_frames == 2


def test_raw_writer_events_update_capture_paths_and_messages(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    part2 = tmp_path / 'ble_log_part002.bin'
    adapter = CaptureView(output_path)

    opened = adapter.handle_event(
        RawWriterProcessEvent(
            kind='opened',
            status=RawWriterStatus(
                base_path=output_path,
                paths=(output_path,),
                bytes_written=3,
                chunks_written=1,
                current_part=1,
                finalized=False,
            ),
        )
    )
    rotated = adapter.handle_event(
        RawWriterProcessEvent(
            kind='rotated',
            status=RawWriterStatus(
                base_path=output_path,
                paths=(output_path, part2),
                bytes_written=10,
                chunks_written=2,
                current_part=2,
                finalized=False,
            ),
        )
    )

    assert isinstance(opened[0], LogLine)
    assert str(output_path) in opened[0].text
    assert isinstance(rotated[0], UserNotice)
    assert str(part2) in rotated[0].text
    assert adapter.state.saved_capture_paths == (output_path, part2)


def test_process_errors_become_warning_notices(tmp_path: Path) -> None:
    adapter = CaptureView(tmp_path / 'ble_log.bin')

    events = [
        ReaderProcessEvent(kind='error', message='reader failed'),
        ParserStatus(kind='error', message='parser failed'),
        AggregatorProcessEvent(kind='error', message='aggregator failed'),
        RawWriterProcessEvent(kind='error', message='disk full'),
    ]

    messages = [adapter.handle_event(event)[0] for event in events]

    assert [message.level for message in messages] == ['warning'] * 4
    assert [message.text for message in messages] == [
        'Reader error: reader failed',
        'Parser error: parser failed',
        'Aggregator error: aggregator failed',
        'Raw writer error: disk full',
    ]


def test_reader_opened_becomes_connected_notice(tmp_path: Path) -> None:
    adapter = CaptureView(tmp_path / 'ble_log.bin')
    messages = adapter.handle_event(
        ReaderProcessEvent(
            kind='opened',
            status=TransportStatus(
                mode=TransportMode.UART,
                display_name='fake reader',
                opened=True,
                healthy=True,
            ),
        )
    )

    assert isinstance(messages[0], UserNotice)
    assert messages[0].text == 'Connected to fake reader'


def test_final_result_closes_console_log_and_marks_disconnected(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    adapter = CaptureView(output_path)
    adapter.handle_event(AggregatorUpdate(redir_texts=('hello\n',)))

    messages = adapter.handle_result(
        CapturePipelineResult(
            raw_paths=(output_path,),
            reader_error=None,
            writer_error=None,
            parser_error=None,
            aggregator_error=None,
            parse_backlog=False,
            raw_bytes=6,
            parser_raw_bytes=6,
            parser_frames=1,
            parser_carried_bytes=0,
            completed=True,
        )
    )

    assert console_log_part_path(output_path, 1).read_text() == 'hello\n'
    assert isinstance(messages[0], BackendStopped)
    assert messages[0].reason == 'Capture completed'
    assert adapter.state.disconnected


def test_failed_result_emits_notice_and_backend_stopped(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    adapter = CaptureView(output_path)

    messages = adapter.handle_result(
        CapturePipelineResult(
            raw_paths=(),
            reader_error='reader failed',
            writer_error=None,
            parser_error=None,
            aggregator_error=None,
            parse_backlog=False,
            raw_bytes=0,
            parser_raw_bytes=0,
            parser_frames=0,
            parser_carried_bytes=0,
            completed=False,
        )
    )

    assert isinstance(messages[0], UserNotice)
    assert messages[0].level == 'warning'
    assert messages[0].text == 'Capture failed: reader failed'
    assert isinstance(messages[1], BackendStopped)
    assert messages[1].reason == 'reader failed'
