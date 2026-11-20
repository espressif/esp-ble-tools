# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

from pytest_bdd import given, scenarios, then, when
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.frontend.capture_report import _firmware_source_rates

from tests.helpers import build_frame, enh_stat_payload, snapshot_payload, xor_checksum

scenarios("features/parser_core.feature")


def recording(payloads):
    parser, aggregator = BleLogParser(), CaptureAggregator()
    for sn, payload in enumerate(payloads):
        aggregator.consume_parser_batch(parser.feed(build_frame(payload, 0, sn, xor_checksum)))
    return SimpleNamespace(parser=parser, aggregator=aggregator)


@given("Console 接收到两次固件计数上报", target_fixture="state")
def counters():
    return recording(
        [
            enh_stat_payload(1, 5, 100, 10, 10000, 1000),
            enh_stat_payload(2, 5, 110, 11, 11000, 1100),
        ]
    )


@given("Console 接收到 v8 固件快照", target_fixture="state")
def snapshot():
    return recording([snapshot_payload()])


@then("实时统计显示累计写入 11000 字节")
def latest(state):
    assert state.aggregator.snapshot(1).funnel_snapshots[0].written.bytes == 11000


@when("录制结束并完成解析")
def finish(state):
    state.aggregator.consume_parser_summary(state.parser.finalize())
    state.final = state.aggregator.snapshot(1)


@then("本次录制统计写入 1000 字节且丢弃 100 字节")
def observed(state):
    assert state.final.capture_firmware_written_bytes == 1000
    assert state.final.capture_firmware_lost_bytes == 100


@then("最终完整性结果可供报告使用")
def integrity(state):
    assert state.final.integrity is not None
    assert state.final.integrity.checked_intervals


@then("丢弃字节数和字节丢弃比例均为未知")
def unknown(state):
    assert state.final.capture_firmware_lost_bytes is None
    assert all(row.bytes is None for row in state.final.capture_firmware_loss)
    assert _firmware_source_rates(state.final.capture_firmware_loss) == ()
