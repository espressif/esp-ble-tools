# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import struct

from src.backend.parser.ble_log_parser import BleLogParser
from src.backend.parser.ble_log_parser import parse_ble_log_chunk
from src.backend.parser.events import EnhStatEvent
from src.backend.parser.events import FrameEvent
from src.backend.parser.events import InternalEvent
from src.backend.parser.events import RedirEvent
from src.backend.support.parser_core.checksum import sum_checksum
from src.backend.models import BleLogSource
from src.backend.models import InternalSource

from tests.helpers import build_frame


def _make_frame(payload: bytes, src: int, sn: int) -> bytes:
    return build_frame(payload, src, sn, sum_checksum, checksum_scope_full=True)  # type: ignore[no-any-return]


def _sync_frames(src: int = 1) -> bytes:
    payload = b'\x00\x00\x00\x00data'
    return b''.join(_make_frame(payload, src=src, sn=sn) for sn in range(3))


def _internal_payload(os_ts: int, int_src: int, sub_payload: bytes) -> bytes:
    return struct.pack('<I', os_ts) + bytes([int_src]) + sub_payload


def test_feed_emits_batch_with_frame_events() -> None:
    parser = BleLogParser()

    batch = parser.feed(_sync_frames(src=BleLogSource.HOST))

    assert batch.raw_bytes > 0
    assert batch.parsed_frames == 3
    assert batch.carried_bytes == 0
    frame_events = [event for event in batch.events if isinstance(event, FrameEvent)]
    assert len(frame_events) == 3
    assert all(event.frame.source_code == BleLogSource.HOST for event in frame_events)


def test_split_frame_is_buffered_without_emitting_events() -> None:
    parser = BleLogParser()
    chunk = _sync_frames(src=BleLogSource.HOST)
    first_frame_len = len(_make_frame(b'\x00\x00\x00\x00data', src=BleLogSource.HOST, sn=0))
    split = first_frame_len // 2

    first = parser.feed(chunk[:split])
    second = parser.feed(chunk[split:])

    assert first.parsed_frames == 0
    assert first.events == ()
    assert first.carried_bytes == split
    assert second.parsed_frames == 3
    assert second.carried_bytes == 0


def test_parse_chunk_reports_consumed_before_tail() -> None:
    frames = _sync_frames(src=BleLogSource.HOST)
    tail = _make_frame(b'\x00\x00\x00\x00data', src=BleLogSource.HOST, sn=3)[:5]

    result = parse_ble_log_chunk(frames + tail)

    assert result.parsed_frames == 3
    assert result.consumed == len(frames)


def test_feed_decodes_internal_frame_once() -> None:
    parser = BleLogParser()
    payload = _internal_payload(os_ts=1234, int_src=InternalSource.INFO, sub_payload=b'\x03')
    frames = b''.join(_make_frame(payload, src=BleLogSource.INTERNAL, sn=sn) for sn in range(3))

    batch = parser.feed(frames)

    internal_events = [event for event in batch.events if isinstance(event, InternalEvent)]
    assert len(internal_events) == 3
    assert internal_events[0].int_src == InternalSource.INFO
    assert internal_events[0].decoded['version'] == 3


def test_feed_emits_enh_stat_event() -> None:
    parser = BleLogParser()
    enh_payload = struct.pack('<BIIII', 2, 100, 5, 4096, 256)
    payload = _internal_payload(os_ts=1234, int_src=InternalSource.ENH_STAT, sub_payload=enh_payload)
    frames = b''.join(_make_frame(payload, src=BleLogSource.INTERNAL, sn=sn) for sn in range(3))

    batch = parser.feed(frames)

    enh_events = [event for event in batch.events if isinstance(event, EnhStatEvent)]
    assert len(enh_events) == 3
    assert enh_events[0].stat['src_code'] == 2
    assert enh_events[0].stat['written_frame_cnt'] == 100
    assert enh_events[0].stat['lost_frame_cnt'] == 5
    assert enh_events[0].stat['written_bytes_cnt'] == 4096
    assert enh_events[0].stat['lost_bytes_cnt'] == 256


def test_feed_filters_false_init_done_version_zero() -> None:
    parser = BleLogParser()
    payload = _internal_payload(os_ts=1234, int_src=InternalSource.INIT_DONE, sub_payload=b'\x00')
    frames = b''.join(_make_frame(payload, src=BleLogSource.INTERNAL, sn=sn) for sn in range(3))

    batch = parser.feed(frames)

    assert batch.parsed_frames == 3
    assert not [event for event in batch.events if isinstance(event, InternalEvent)]


def test_feed_emits_redir_payload_event() -> None:
    parser = BleLogParser()
    frames = b''.join(_make_frame(b'console line\n', src=BleLogSource.REDIR, sn=sn) for sn in range(3))

    batch = parser.feed(frames)

    redir_events = [event for event in batch.events if isinstance(event, RedirEvent)]
    assert len(redir_events) == 3
    assert redir_events[0].text == 'console line\n'
    assert redir_events[0].wall_ms >= 0


def test_feed_ignores_unstructured_ascii_text() -> None:
    parser = BleLogParser()

    batch = parser.feed(b'Hello world\n')

    assert batch.parsed_frames == 0
    assert batch.events == ()
    assert batch.carried_bytes == len(b'Hello world\n')


def test_feed_bounds_unstructured_garbage_without_warning_event() -> None:
    parser = BleLogParser()

    batch = parser.feed(b'\xfe' * (131072 + 1))

    assert batch.parsed_frames == 0
    assert batch.events == ()
    assert 0 < batch.carried_bytes < batch.raw_bytes


def test_finalize_reports_totals_without_reparsing() -> None:
    parser = BleLogParser()
    chunk = _sync_frames(src=BleLogSource.HOST)
    parser.feed(chunk)

    final = parser.finalize()

    assert final.raw_bytes == len(chunk)
    assert final.parsed_frames == 3
    assert final.carried_bytes == 0
