# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Step bindings for tests/features/sequence_continuity.feature."""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.io.writer import WriterConfig
from src.backend.models import (
    BleLogSource,
    CaptureVerdict,
    FirmwareCounterSource,
    InternalSource,
    TransportConfig,
    TransportMode,
)
from src.backend.pipeline import run_capture_pipeline_inprocess
from src.frontend.capture_report import CaptureReport, build_capture_report

from tests.helpers import (
    BytesReader,
    _int_value,
    build_frame,
    enh_stat_payload,
    final_stat_payload,
    internal_payload,
    snapshot_payload,
    version_info_payload,
    xor_checksum,
)

scenarios("features/sequence_continuity.feature", "features/sequence_continuity_per_source.feature")

_ORDINARY_SOURCES = {
    "LL_TASK": BleLogSource.LL_TASK,
    "ENCODE": BleLogSource.ENCODE,
    "INTERNAL": BleLogSource.INTERNAL,
}

# A segment's firmware numbers come from FINAL_STAT interval totals or from the
# segment's own ENH_STAT deltas; the report labels which one.
_COUNTER_SOURCES = {
    "FINAL_STAT": FirmwareCounterSource.FINAL_STAT,
    "ENH_STAT": FirmwareCounterSource.ENH_STAT,
    "无": FirmwareCounterSource.NONE,
}

# Payloads for the INTERNAL frames a scenario names. TASK_BINDING's number comes
# from the firmware's private counter, which is why the parser drops it.
# A periodic SNAPSHOT carries no INIT flag, so it does not start a new epoch.
_INTERNAL_PAYLOADS = {
    "SNAPSHOT": lambda: snapshot_payload(reason_flags=0b1010),
    "INIT SNAPSHOT": lambda: snapshot_payload(),
    "TASK_BINDING": lambda: internal_payload(0, InternalSource.TASK_BINDING, b""),
    "INIT_DONE": lambda: internal_payload(0, InternalSource.INIT_DONE, bytes([4])),
    "FLUSH": lambda: internal_payload(0, InternalSource.FLUSH, bytes([5])),
    "INFO": lambda: internal_payload(0, InternalSource.INFO, bytes([5])),
    "TIMESTAMP": lambda: internal_payload(0, InternalSource.TIMESTAMP, struct.pack("<BIII", 1, 100, 200, 300)),
    "FINAL_STAT": lambda: final_stat_payload(0, (2, 0, 200, 0)),
}


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(frames=[], report=None, tmp_path=tmp_path)


@given("一个正在录制 BLE Log 的设备", target_fixture="world")
def recording_device(world: SimpleNamespace) -> SimpleNamespace:
    return world


@when(parsers.parse("设备按序号 {sns} 发送普通帧"))
def send_ordinary_frames(world: SimpleNamespace, sns: str) -> None:
    for sn in _parse_sns(sns):
        world.frames.append(_frame("LL_TASK", sn))


@when(parsers.parse("设备交替发送序号 {first:d} 到 {last:d} 的 LL_TASK 与 ENCODE 帧"))
def send_alternating_frames(world: SimpleNamespace, first: int, last: int) -> None:
    for index, sn in enumerate(range(first, last + 1)):
        world.frames.append(_frame("ENCODE" if index % 2 else "LL_TASK", sn))


@when(parsers.parse("设备发送一帧 {kind}，序号为 {sn:d}"))
def send_internal_frame(world: SimpleNamespace, kind: str, sn: int) -> None:
    world.frames.append(_frame(kind, sn))


@when(parsers.parse("设备发送一帧 INIT SNAPSHOT，序号为 {sn:d}"))
def send_init_snapshot(world: SimpleNamespace, sn: int) -> None:
    world.frames.append(_frame("INIT SNAPSHOT", sn))


@when(parsers.parse("设备以序号 {sn:d} 发送固件版本 {version:d} 的 VERSION_INFO"))
def send_version_info(world: SimpleNamespace, version: int, sn: int) -> None:
    payload = version_info_payload(0, version=version)
    world.frames.append(build_frame(payload, _int_value(BleLogSource.INTERNAL), sn, xor_checksum))


@when("设备发送一轮覆盖全部来源的 ENH_STAT，序号从 1 开始")
def send_periodic_enh_stats(world: SimpleNamespace) -> None:
    """Legacy firmware emits VERSION_INFO before one ENH_STAT per source."""
    for source in range(9):
        payload = enh_stat_payload(0, source, 0, 0, 0, 0)
        world.frames.append(build_frame(payload, _int_value(BleLogSource.INTERNAL), source + 1, xor_checksum))


@when(parsers.parse("设备启动，固件版本为 {version:d}"))
def start_firmware(world: SimpleNamespace, version: int) -> None:
    """INIT_DONE carries the firmware's BLE_LOG_VERSION in its info record."""

    world.frames.append(_frame_internal("INIT_DONE", 0, bytes([version])))


@when(
    parsers.parse(
        "设备发送一帧 ENH_STAT，累计写入 {written_frames:d} 帧 {written_bytes:d} 字节、丢失 {lost_frames:d} 帧 {lost_bytes:d} 字节"
    )
)
def send_enh_stat(
    world: SimpleNamespace, written_frames: int, written_bytes: int, lost_frames: int, lost_bytes: int
) -> None:
    send_enh_stat_from(
        world,
        source="LL_TASK",
        written_frames=written_frames,
        written_bytes=written_bytes,
        lost_frames=lost_frames,
        lost_bytes=lost_bytes,
    )


@when(
    parsers.parse(
        "设备从 {source} 来源发送一帧 ENH_STAT，累计写入 {written_frames:d} 帧 {written_bytes:d} 字节、丢失 {lost_frames:d} 帧 {lost_bytes:d} 字节"
    )
)
def send_enh_stat_from(
    world: SimpleNamespace,
    source: str,
    written_frames: int,
    written_bytes: int,
    lost_frames: int,
    lost_bytes: int,
) -> None:
    payload = enh_stat_payload(0, _ORDINARY_SOURCES[source], written_frames, lost_frames, written_bytes, lost_bytes)
    world.frames.append(build_frame(payload, _int_value(BleLogSource.INTERNAL), 0, xor_checksum))


@when(
    parsers.parse(
        "设备发送一帧 FINAL_STAT，写入 {written_frames:d} 帧 {written_bytes:d} 字节、丢失 {lost_frames:d} 帧 {lost_bytes:d} 字节"
    )
)
def send_final_stat(
    world: SimpleNamespace, written_frames: int, written_bytes: int, lost_frames: int, lost_bytes: int
) -> None:
    payload = final_stat_payload(0, (written_frames, lost_frames, written_bytes, lost_bytes))
    world.frames.append(build_frame(payload, _int_value(BleLogSource.INTERNAL), 2, xor_checksum))


@when(
    parsers.parse(
        "设备发送同一帧 FINAL_STAT 两次，写入 {written_frames:d} 帧 {written_bytes:d} 字节、丢失 {lost_frames:d} 帧 {lost_bytes:d} 字节"
    )
)
def send_duplicate_final_stat(
    world: SimpleNamespace, written_frames: int, written_bytes: int, lost_frames: int, lost_bytes: int
) -> None:
    """A byte-identical repeat, as a transport duplicate would deliver it."""

    payload = final_stat_payload(0, (written_frames, lost_frames, written_bytes, lost_bytes))
    frame = build_frame(payload, _int_value(BleLogSource.INTERNAL), 2, xor_checksum)
    world.frames.append(frame)
    world.frames.append(frame)


@when(parsers.parse("设备从 {source} 来源按序号 {sns} 发送帧"))
def send_frames_from_source(world: SimpleNamespace, source: str, sns: str) -> None:
    for sn in _parse_sns(sns):
        world.frames.append(_frame(source, sn))


@when(parsers.parse("设备按序号 {sns} 发送 REDIR 帧"))
def send_redir_frames(world: SimpleNamespace, sns: str) -> None:
    for sn in _parse_sns(sns):
        world.frames.append(_frame("REDIR", sn))


@when(parsers.parse('回放真机抓包片段 "{path}"'))
def replay_capture_slice(world: SimpleNamespace, path: str) -> None:
    world.frames = [Path(path).read_bytes()]


@then(parsers.parse("报告显示缺失 {count:d} 个序号"))
def report_shows_missing(world: SimpleNamespace, count: int) -> None:
    assert _report(world).sequence.missing_frames == count


@then(parsers.parse("报告显示固件缓冲丢帧 {count:d} 帧"))
def report_shows_firmware_loss(world: SimpleNamespace, count: int) -> None:
    report = _report(world)
    assert sum(item.frames for item in report.firmware_loss if item.source > 0) == count


@then(parsers.parse("报告显示固件写入 {count:d} 字节"))
def report_shows_firmware_written_bytes(world: SimpleNamespace, count: int) -> None:
    assert _report(world).firmware_written_bytes == count


@then(parsers.parse("报告显示第 {index:d} 段固件统计来自 {counters}"))
def report_segment_firmware_counters(world: SimpleNamespace, index: int, counters: str) -> None:
    assert _report(world).segments[index - 1].firmware_counters is _COUNTER_SOURCES[counters]


@then(parsers.parse("报告显示第 {index:d} 段固件丢帧 {count:d} 帧"))
def report_segment_firmware_loss(world: SimpleNamespace, index: int, count: int) -> None:
    assert _report(world).segments[index - 1].firmware_lost_frames == count


@then("报告按来源统计序号")
def report_uses_per_source_counters(world: SimpleNamespace) -> None:
    assert _report(world).sequence.per_source


@then("报告按共用序号统计")
def report_uses_shared_counter(world: SimpleNamespace) -> None:
    assert not _report(world).sequence.per_source


@then("报告的序号契约已证明")
def report_contract_is_proven(world: SimpleNamespace) -> None:
    assert _report(world).firmware_contract_known


@then(parsers.parse("报告显示固件版本 {version:d}"))
def report_shows_firmware_version(world: SimpleNamespace, version: int) -> None:
    assert _report(world).firmware_version == version


@then("报告判定为可分析")
def report_is_ready(world: SimpleNamespace) -> None:
    assert _report(world).verdict is CaptureVerdict.READY


@then("报告判定为需要重录")
def report_needs_recapture(world: SimpleNamespace) -> None:
    assert _report(world).verdict is CaptureVerdict.RECAPTURE


@then("报告判定不为可分析")
def report_is_not_ready(world: SimpleNamespace) -> None:
    assert _report(world).verdict is not CaptureVerdict.READY


def _parse_sns(sns: str) -> list[int]:
    return [int(part) for part in sns.replace("，", "、").split("、")]


def _frame(kind: str, sn: int) -> bytes:
    if kind in _ORDINARY_SOURCES:
        payload: bytes = b"log"
        source = _int_value(_ORDINARY_SOURCES[kind])
    elif kind == "REDIR":
        payload = b"console line\n"
        source = _int_value(BleLogSource.REDIR)
    else:
        payload = _INTERNAL_PAYLOADS[kind]()
        source = _int_value(BleLogSource.INTERNAL)
    return build_frame(payload, source, sn, xor_checksum)


def _frame_internal(kind: str, sn: int, info: bytes) -> bytes:
    """An INTERNAL frame whose record body is not the scenario's default."""

    payload = internal_payload(0, InternalSource[kind], info)
    return build_frame(payload, _int_value(BleLogSource.INTERNAL), sn, xor_checksum)


def _report(world: SimpleNamespace) -> CaptureReport:
    if world.report is None:
        world.report = _build_report(b"".join(world.frames), world.tmp_path)
    return world.report


def _build_report(stream: bytes, tmp_path: Path) -> CaptureReport:
    stop_event = Event()
    output_path = tmp_path / "replay.bin"
    result = run_capture_pipeline_inprocess(
        BytesReader(stream, stop_event),
        WriterConfig(output_path),
        stop_requested=stop_event,
    )
    return build_capture_report(
        result,
        TransportConfig(mode=TransportMode.USB_OUTPUT, label="replay", port="/dev/cu.replay"),
        started_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        duration_sec=1.0,
        console_log_paths=(),
        report_path=output_path.with_name("replay_report.txt"),
    )
