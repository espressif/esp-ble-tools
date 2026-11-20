# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import struct

import pytest
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.analysis.parser_events import HciLogEvent
from src.backend.models import LogLine, TransportMode
from src.frontend.capture_events import CaptureEventPresenter

from tests.helpers import snapshot_payload, version_info_payload
from tests.test_host_logs import frame


def hci_stream(source, *, c2=False):
    packet = b"\x03\x0c\x00"
    if source == 6:
        payload = struct.pack("<IB", 1000000, 1) + packet
    else:
        identifier = 11 << 12 if c2 else 10 << 16
        payload = struct.pack("<HII", 13, 32768 if c2 else 1000000, identifier) + packet
    return frame(source, 1, payload)


@pytest.mark.parametrize("source", [3, 6])
@pytest.mark.parametrize("chunk_size", [1, 65536])
def test_hci_sources_share_display_and_btsnoop(tmp_path, source, chunk_size):
    parser, aggregator = BleLogParser(), CaptureAggregator()
    presenter = CaptureEventPresenter(tmp_path / "recording.bin", mode=TransportMode.SPI_USB_BRIDGE)
    data = frame(0, 0, snapshot_payload()) + hci_stream(source)
    messages = []
    for offset in range(0, len(data), chunk_size):
        messages.extend(
            presenter.handle_event(aggregator.consume_parser_batch(parser.feed(data[offset : offset + chunk_size])))
        )
    parser.finalize()
    messages.extend(presenter.finish())
    assert any(isinstance(m, LogLine) and "1000000 us TX HCI type=1 03 0c 00" in m.text for m in messages)
    text = (tmp_path / "recording_hci.log").read_text()
    assert "TX HCI type=1 03 0c 00" in text and "LL_HCI" not in text
    binary = (tmp_path / "recording_hci_btsnoop.log").read_bytes()
    assert binary[:16] == b"btsnoop\x00" + struct.pack("!II", 1, 1002)
    assert struct.unpack("!IIIIQ", binary[16:40]) == (4, 4, 2, 0, 0x00DCDDB30F2F8000 + 1000000)
    assert binary[40:] == b"\x01\x03\x0c\x00"
    assert aggregator.snapshot(1).stats.transport.rx_frames == 2


def test_c2_clock_and_layout():
    parser = BleLogParser()
    metadata = version_info_payload(0, version=6, chip_model=12)
    events = parser.feed(frame(0, 0, metadata) + hci_stream(3, c2=True)).events
    hci = [e for e in events if isinstance(e, HciLogEvent)]
    assert len(hci) == 1 and hci[0].text.startswith("1000000 us TX HCI")
    parser.finalize()


@pytest.mark.parametrize("payload", [b"", b"\x03\x00\x00", b"\x09\x00" + b"\x00" * 7])
def test_short_ll_hci_does_not_abort_following_host(payload):
    parser = BleLogParser()
    batch = parser.feed(frame(3, 0, payload) + frame(5, 1, b"\x00" * 4 + b"still alive"))
    assert any(getattr(e, "text", "") == "still alive\n" for e in batch.events)
    assert parser.finalize().parsed_frames == (2 if payload else 1)


@pytest.mark.parametrize("log_id,packet_type,flags", [(0, 1, 2), (1, 2, 0), (2, 4, 3), (3, 2, 1), (9, 4, 3)])
def test_ll_hci_packet_mapping_and_truncation(log_id, packet_type, flags):
    from src.backend.analysis.hci import ll_hci_event

    payload = struct.pack("<HII", 16, 10, (10 << 16) | log_id) + b"\x01\x02"
    event = ll_hci_event(payload, "ESP32C3", 0)
    original, included, actual_flags, drops, timestamp = struct.unpack("!IIIIQ", event.btsnoop[:24])
    assert (original, included, actual_flags, drops) == (7, 3, flags, 0)
    assert timestamp == 0x00DCDDB30F2F8000 + 10
    assert event.btsnoop[24:] == bytes([packet_type, 1, 2])
    assert event.reason == "truncated_packet"


def test_unknown_hci_clock_keeps_text_without_fabricating_btsnoop(tmp_path):
    parser, aggregator = BleLogParser(), CaptureAggregator()
    presenter = CaptureEventPresenter(tmp_path / "recording.bin")
    presenter.handle_event(aggregator.consume_parser_batch(parser.feed(hci_stream(6))))
    presenter.finish()
    parser.finalize()
    assert "unit unknown" in (tmp_path / "recording_hci.log").read_text()
    assert not (tmp_path / "recording_hci_btsnoop.log").exists()


@pytest.mark.parametrize("failure", ["open", "write", "flush", "fsync"])
def test_hci_save_failure_keeps_display_and_is_reported(tmp_path, monkeypatch, failure):
    from pathlib import Path

    from src.backend.analysis.aggregator import AggregatorUpdate
    from src.backend.analysis.hci import hci_event
    from src.backend.models import UserNotice

    event = hci_event(struct.pack("<IB", 1, 1) + b"\x03\x0c\x00", 1, 0)
    presenter = CaptureEventPresenter(tmp_path / "recording.bin")
    original_open = Path.open

    class FailingFile:
        def __init__(self, file):
            self.file = file

        def __getattr__(self, name):
            return getattr(self.file, name)

        def write(self, content):
            if failure == "write":
                raise OSError("disk full")
            return self.file.write(content)

        def flush(self):
            if failure == "flush":
                raise OSError("flush failed")
            return self.file.flush()

    def open_file(path, *args, **kwargs):
        if path.name.endswith("_hci.log"):
            if failure == "open":
                raise OSError("read only")
            return FailingFile(original_open(path, *args, **kwargs))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    if failure == "fsync":

        def fail_sync(fd):
            raise OSError("sync failed")

        monkeypatch.setattr("src.frontend.capture_events.os.fsync", fail_sync)
    messages = presenter.handle_event(AggregatorUpdate(0, (event,))) + presenter.finish()
    assert any(isinstance(m, LogLine) and "TX HCI" in m.text for m in messages)
    assert any(isinstance(m, UserNotice) for m in messages)
    assert presenter.state.hci_error
    assert not presenter._hci_files
    assert presenter.finish() == ()
