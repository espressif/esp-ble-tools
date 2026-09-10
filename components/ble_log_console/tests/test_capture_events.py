# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.backend.analysis.worker import AggregatorProcessEvent
from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.analysis.aggregator import AggregatorUpdate
from src.backend.analysis.aggregator import InternalFrameUpdate
from src.backend.io.writer import WriterEvent
from src.backend.io.writer import WriterStatus
from src.backend.io.reader import ReaderProcessEvent
from src.backend.analysis.worker import ParserStatus
from src.backend.analysis.parser_events import RedirEvent
from src.backend.models import FrameStats
from src.backend.models import InternalFrameDecoded
from src.backend.models import InternalSource
from src.backend.models import LogLine
from src.backend.models import StatsUpdated
from src.backend.models import TransportMode
from src.backend.models import UserNotice
from src.backend.support.transport import TransportStatus
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.capture_events import console_log_part_path
from src.i18n import set_language


def _redir(text: str, received_at_ms: int = 0) -> RedirEvent:
    return RedirEvent(
        frame_size=len(text) + 10,
        source_code=8,
        frame_sn=0,
        text=text,
        received_at_ms=received_at_ms,
    )


def _timestamp(received_at_ms: int) -> str:
    return datetime.fromtimestamp(received_at_ms / 1000).astimezone().isoformat(sep=' ', timespec='milliseconds')


def _short_timestamp(received_at_ms: int) -> str:
    return datetime.fromtimestamp(received_at_ms / 1000).astimezone().strftime('%H:%M:%S.%f')[:-3]


def test_snapshot_event_becomes_stats_updated(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin')
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=0,
        parser_raw_bytes=0,
        parser_frames=0,
        parser_carried_bytes=0,
    )

    messages = presenter.handle_event(snapshot)

    assert len(messages) == 1
    assert isinstance(messages[0], StatsUpdated)
    assert messages[0].stats is snapshot.stats


def test_capture_progress_notice_is_emitted_every_ten_seconds(tmp_path: Path) -> None:
    now = [100.0]
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin', clock=lambda: now[0])

    def snapshot(captured_bytes: int, parser_frames: int) -> AggregatorSnapshot:
        return AggregatorSnapshot(
            stats=FrameStats(),
            funnel_snapshots=(),
            buf_util_snapshots=(),
            captured_bytes=captured_bytes,
            parser_raw_bytes=captured_bytes,
            parser_frames=parser_frames,
            parser_carried_bytes=0,
            regular_frames=parser_frames,
        )

    now[0] = 109.0
    assert not any(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot(600_000, 10)))

    now[0] = 110.0
    notices = [
        message for message in presenter.handle_event(snapshot(700_000, 20)) if isinstance(message, UserNotice)
    ]
    assert [notice.text for notice in notices] == ['Recorded 683.6 KB, 20 frames']

    now[0] = 119.0
    assert not any(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot(2_000_000, 30)))

    now[0] = 120.0
    notices = [
        message for message in presenter.handle_event(snapshot(2_100_000, 40)) if isinstance(message, UserNotice)
    ]
    assert [notice.text for notice in notices] == ['Recorded 2.00 MB, 40 frames']


def test_no_data_warning_repeats_every_ten_seconds(tmp_path: Path) -> None:
    now = [100.0]
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin', clock=lambda: now[0])
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=0,
        parser_raw_bytes=0,
        parser_frames=0,
        parser_carried_bytes=0,
    )

    now[0] = 110.0
    assert sum(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot)) == 1
    now[0] = 119.0
    assert not any(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot))
    now[0] = 120.0
    assert sum(isinstance(message, UserNotice) for message in presenter.handle_event(snapshot)) == 1


def test_internal_frames_do_not_hide_repeated_no_valid_frame_warning(tmp_path: Path) -> None:
    now = [100.0]
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin', clock=lambda: now[0])

    def snapshot(captured_bytes: int, parser_frames: int) -> AggregatorSnapshot:
        return AggregatorSnapshot(
            stats=FrameStats(),
            funnel_snapshots=(),
            buf_util_snapshots=(),
            captured_bytes=captured_bytes,
            parser_raw_bytes=captured_bytes,
            parser_frames=parser_frames,
            parser_carried_bytes=0,
            regular_frames=0,
        )

    now[0] = 110.0
    notices = [
        message for message in presenter.handle_event(snapshot(700_000, 20)) if isinstance(message, UserNotice)
    ]
    assert len(notices) == 1
    assert notices[0].level == 'warning'
    assert notices[0].text == (
        'No valid BLE Log frames were decoded for 10s. '
        'Check transport mode, wiring, and firmware log configuration.'
    )

    now[0] = 120.0
    notices = [
        message for message in presenter.handle_event(snapshot(1_400_000, 40)) if isinstance(message, UserNotice)
    ]
    assert len(notices) == 1
    assert notices[0].level == 'warning'


def test_redir_text_writes_console_log_and_emits_complete_lines(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    presenter = CaptureEventPresenter(output_path)

    first = presenter.handle_event(AggregatorUpdate(redir_events=(_redir('hello ', 1000),)))
    second = presenter.handle_event(AggregatorUpdate(redir_events=(_redir('world\npartial', 2000),)))

    assert first == ()
    assert len(second) == 1
    assert isinstance(second[0], LogLine)
    assert second[0].text == f'[{_short_timestamp(2000)}]  hello world'
    presenter.close()
    stamp = _timestamp(2000)
    assert console_log_part_path(output_path, 1).read_text() == f'[{stamp}] hello world\npartial'
    assert presenter.state.saved_console_log_paths == (console_log_part_path(output_path, 1),)


def test_redir_console_log_is_plain_text_across_chunks(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    presenter = CaptureEventPresenter(output_path)

    presenter.handle_event(AggregatorUpdate(redir_events=(_redir('\x1b[0;', 1000),)))
    presenter.handle_event(AggregatorUpdate(redir_events=(_redir('32mgreen\x1b[0m\r\nnext\rline\t\x01', 2000),)))
    presenter.close()

    stamp = _timestamp(2000).encode()
    assert console_log_part_path(output_path, 1).read_bytes() == (
        b'[' + stamp + b'] green\nnext\nline    '
    )


def test_redir_text_batches_complete_lines_for_ui(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    presenter = CaptureEventPresenter(output_path)

    messages = presenter.handle_event(AggregatorUpdate(redir_events=(_redir('one\ntwo\nthree\n', 2000),)))

    assert len(messages) == 1
    assert isinstance(messages[0], LogLine)
    assert messages[0].text == f'[{_short_timestamp(2000)}]  one\ntwo\nthree'


def test_redir_text_without_newline_is_shown_on_next_snapshot(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin')
    assert presenter.handle_event(AggregatorUpdate(redir_events=(_redir('prompt> ', 2000),))) == ()

    messages = presenter.handle_event(
        AggregatorSnapshot(
            stats=FrameStats(),
            funnel_snapshots=(),
            buf_util_snapshots=(),
            captured_bytes=17,
            parser_raw_bytes=17,
            parser_frames=1,
            parser_carried_bytes=0,
        )
    )

    assert isinstance(messages[1], LogLine)
    assert messages[1].text == f'[{_short_timestamp(2000)}]  prompt> '


def test_redir_console_log_rotates_with_legacy_name(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    presenter = CaptureEventPresenter(output_path, console_part_max_bytes=3)

    presenter.handle_event(AggregatorUpdate(redir_events=(_redir('abc\n'),)))
    presenter.handle_event(AggregatorUpdate(redir_events=(_redir('de\n'),)))
    presenter.close()

    assert console_log_part_path(output_path, 1).read_text().endswith('abc\n')
    assert console_log_part_path(output_path, 2).read_text().endswith('de\n')
    assert presenter.state.saved_console_log_paths == (
        console_log_part_path(output_path, 1),
        console_log_part_path(output_path, 2),
    )


def test_aggregator_update_maps_to_existing_ui_messages(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin')

    messages = presenter.handle_event(
        AggregatorUpdate(
            internal_frames=(
                InternalFrameUpdate(
                    int_src=InternalSource.INFO,
                    decoded={'int_src': InternalSource.INFO, 'version': 4, 'os_ts_ms': 1},
                ),
            ),
        )
    )

    assert isinstance(messages[0], InternalFrameDecoded)
    assert messages[0].int_src == InternalSource.INFO
    assert messages[0].payload['version'] == 4


def test_writer_events_update_capture_paths_and_messages(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    part2 = tmp_path / 'ble_log_part002.bin'
    presenter = CaptureEventPresenter(output_path)

    opened = presenter.handle_event(
        WriterEvent(
            kind='opened',
            status=WriterStatus(
                base_path=output_path,
                paths=(output_path,),
                bytes_written=3,
                chunks_written=1,
                current_part=1,
                finalized=False,
            ),
        )
    )
    rotated = presenter.handle_event(
        WriterEvent(
            kind='rotated',
            status=WriterStatus(
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
    assert presenter.state.saved_capture_paths == (output_path, part2)


def test_process_errors_become_warning_notices(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin')

    events = [
        ReaderProcessEvent(kind='error', message='reader failed'),
        ParserStatus(kind='error', message='parser failed'),
        AggregatorProcessEvent(kind='error', message='aggregator failed'),
        WriterEvent(kind='error', message='disk full'),
    ]

    messages = [presenter.handle_event(event)[0] for event in events]

    assert [message.level for message in messages] == ['warning'] * 4
    assert [message.text for message in messages] == [
        'Reader error: reader failed',
        'Parser error: parser failed',
        'Aggregator error: aggregator failed',
        'Writer error: disk full',
    ]


def test_process_errors_follow_selected_language(tmp_path: Path) -> None:
    set_language('zh_CN')
    try:
        presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin')
        message = presenter.handle_event(ReaderProcessEvent(kind='error', message='device lost'))[0]
        assert message.text == '读取器错误：device lost'
    finally:
        set_language('en')


def test_reader_opened_becomes_connected_notice(tmp_path: Path) -> None:
    presenter = CaptureEventPresenter(tmp_path / 'ble_log.bin')
    messages = presenter.handle_event(
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
    presenter = CaptureEventPresenter(output_path)
    presenter.handle_event(AggregatorUpdate(redir_events=(_redir('hello\n'),)))

    presenter.finish()

    assert console_log_part_path(output_path, 1).read_text() == f'[{_timestamp(0)}] hello\n'
    assert presenter.state.disconnected


def test_finish_without_console_log_marks_disconnected(tmp_path: Path) -> None:
    output_path = tmp_path / 'ble_log.bin'
    presenter = CaptureEventPresenter(output_path)

    presenter.finish()

    assert presenter.state.disconnected
    assert presenter.state.saved_console_log_paths == ()
