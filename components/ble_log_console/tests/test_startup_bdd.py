# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

from ble_log_frame_decoder import FrameDecoder, is_snapshot
from pytest_bdd import given, scenarios, then, when
from src.backend.models import CaptureVerdict
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


@then("报告中的新数据区间从完整快照开始")
def independent_suffix(world):
    raw = b"".join(p.read_bytes() for p in world.report.raw_paths)
    data = raw[world.report.quality_start_offset :]
    frame = FrameDecoder().feed(data)[0]
    assert is_snapshot(frame.payload)
    assert frame.sequence_number == 300
    assert data == b"".join(c.data for c in world.items[1:])


@then("报告按新数据区间给出结论并保留原始流断档信息")
def explicit_scope(world):
    assert "质量指标仅评估已确认的新数据区间" in format_capture_summary(world.report, "zh_CN")
    assert "原始流缺失序号数" in format_capture_summary(world.report, "zh_CN")
    assert world.report.verdict is CaptureVerdict.READY
    assert world.report.sequence.missing_frames == 0
    assert "原始数据切分偏移（字节）" in format_capture_report(world.report, "zh_CN")
    assert "capture.bin" in format_capture_summary(world.report, "en")


@then("不生成额外分析文件")
def raw_only(world):
    assert not list(world.report.report_path.parent.glob("*analysis*"))


@then("报告保守回退到原始录制检查")
def failed_copy_notice(world):
    assert world.report.quality_start_offset == 0
    assert "新数据区间未能完成检查" in format_capture_report(world.report, "zh_CN")


@given("开录积压之前包含 Host 任务映射", target_fixture="world")
def bindings_start():
    return SimpleNamespace(options={"bindings": True})


@given("已确认的开录积压之后还有序号缺失", target_fixture="world")
def subsequent_loss():
    return SimpleNamespace(options={"fresh_gap": True})


@then("新数据区间通过检查且保留任务映射提示")
def context_retained(world):
    assert world.report.verdict is CaptureVerdict.READY
    assert world.report.quality_start_offset > 0
    assert "保留 Host 任务映射" in format_capture_summary(world.report, "zh_CN")


@then("新数据区间的丢包仍触发重录建议")
def real_loss_retained(world):
    assert world.report.quality_start_offset > 0
    assert world.report.verdict is CaptureVerdict.RECAPTURE
    assert world.report.sequence.missing_frames > 0


@given("原始文件禁止重新读取并监视帧解码器创建")
def no_second_pass(world, monkeypatch):
    from pathlib import Path

    from src.backend.analysis import parser

    original_open = Path.open
    original_decoder = parser._decoder_for_mode
    world.decoders = []

    def open_path(path, mode="r", *args, **kwargs):
        if path.suffix == ".bin" and "r" in mode:
            raise AssertionError("Raw recordings must not be rescanned")
        return original_open(path, mode, *args, **kwargs)

    def decoder(mode):
        world.decoders.append(mode)
        return original_decoder(mode)

    monkeypatch.setattr(Path, "open", open_path)
    monkeypatch.setattr(parser, "_decoder_for_mode", decoder)


@then("只使用一条帧解码通路且没有分析副本")
def one_decoder(world):
    assert len(world.decoders) == 1
    assert world.result.opening_quality.error is None
    assert not list(world.report.report_path.parent.glob("*analysis*"))
