# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

from ble_log_frame_decoder import FrameDecoder, is_snapshot
from pytest_bdd import given, scenarios, then, when
from src.frontend.capture_report import format_capture_report, format_capture_summary

from tests.test_startup_recording import record

scenarios("features/startup_recording.feature")


@given("开录时先收到旧快照随后设备时间前跳并恢复稳定", target_fixture="world")
def stale_start():
    return SimpleNamespace(options={})


@given("开录时间连续且没有积压证据", target_fixture="world")
def normal_start():
    return SimpleNamespace(options={"stale": False})


@given("开录积压已确认但分析队列遗漏最后一块数据", target_fixture="world")
def missing_tail():
    return SimpleNamespace(options={"dropped_tail": True})


@when("完成开录数据检查与保存")
def finish(world, tmp_path):
    world.items, world.result, world.report = record(tmp_path, **world.options)


@then("原始文件仍包含收到的全部字节")
def raw_preserved(world):
    assert b"".join(p.read_bytes() for p in world.report.raw_paths) == b"".join(c.data for c in world.items)
    assert world.report.raw_complete


@then("分析文件从新的完整快照开始")
def independent_suffix(world):
    data = b"".join(p.read_bytes() for p in world.report.analysis_paths)
    frame = FrameDecoder().feed(data)[0]
    assert is_snapshot(frame.payload)
    assert frame.sequence_number == 300
    assert data == b"".join(c.data for c in world.items[1:])


@then("报告区分原始流统计和未单独评估的分析副本")
def explicit_scope(world):
    assert "质量指标描述原始录制" in format_capture_summary(world.report, "zh_CN")
    assert "切分后的文件尚未单独评估" in format_capture_summary(world.report, "zh_CN")
    assert "原始数据切分偏移（字节）" in format_capture_report(world.report, "zh_CN")
    assert "capture_analysis.bin" in format_capture_summary(world.report, "en")


@then("不生成额外分析文件")
def raw_only(world):
    assert not world.report.analysis_paths
    assert not list(world.report.report_path.parent.glob("*analysis*"))


@then("报告提示保留原始录制")
def failed_copy_notice(world):
    assert "分析副本未能完整保存，请保留原始录制文件" in format_capture_report(world.report, "zh_CN")
