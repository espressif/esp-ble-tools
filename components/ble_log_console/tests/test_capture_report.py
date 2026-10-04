# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.models import (
    CaptureSegmentSummary,
    CaptureVerdict,
    FirmwareCounterSource,
    FirmwareLossSummary,
    FrameStats,
    SequenceSourceSummary,
    SequenceSummary,
    TransportConfig,
    TransportMode,
)
from src.backend.pipeline.controller import CapturePipelineResult
from src.frontend.capture_report import (
    CaptureReportScreen,
    build_capture_report,
    format_capture_report,
    format_capture_summary,
)


def _result(
    *,
    raw_bytes: int = 100,
    regular_frames: int = 2,
    missing_frames: int = 0,
    duplicate_frames: int = 0,
    writer_error: str | None = None,
    parser_error: str | None = None,
    parse_backlog: bool = False,
    parser_raw_bytes: int | None = None,
    parse_dropped_bytes: int = 0,
    firmware_loss: int = 0,
    firmware_written_bytes: int = 0,
    firmware_lost_bytes: int = 0,
    firmware_loss_source: int = 5,
    firmware_loss_rows: tuple[FirmwareLossSummary, ...] | None = None,
    sequence_uncertain: bool = False,
    contract_known: bool = True,
) -> CapturePipelineResult:
    parser_raw_bytes = raw_bytes if parser_raw_bytes is None else parser_raw_bytes
    sequence = SequenceSummary(
        observed_frames=regular_frames,
        first_sn=1 if regular_frames else None,
        last_sn=regular_frames if regular_frames else None,
        missing_frames=missing_frames,
        segments=1 if regular_frames else 0,
        duplicate_frames=duplicate_frames,
        uncertain=sequence_uncertain,
        sources=(
            SequenceSourceSummary(
                source=5,
                observed_frames=regular_frames,
                first_sn=1 if regular_frames else None,
                last_sn=regular_frames if regular_frames else None,
            ),
        )
        if regular_frames
        else (),
    )
    snapshot = AggregatorSnapshot(
        stats=FrameStats(),
        funnel_snapshots=(),
        buf_util_snapshots=(),
        captured_bytes=raw_bytes,
        parser_raw_bytes=parser_raw_bytes,
        parser_frames=regular_frames,
        parser_carried_bytes=0,
        regular_frames=regular_frames,
        sequence=sequence,
        capture_firmware_loss=(
            firmware_loss_rows
            if firmware_loss_rows is not None
            else (
                (
                    FirmwareLossSummary(
                        source=firmware_loss_source,
                        frames=firmware_loss,
                        bytes=firmware_lost_bytes or 64,
                        written_bytes=firmware_written_bytes,
                    ),
                )
                if firmware_loss
                else ()
            )
        ),
        capture_firmware_written_bytes=firmware_written_bytes,
        capture_firmware_lost_bytes=firmware_lost_bytes,
        firmware_contract_known=contract_known,
    )
    return CapturePipelineResult(
        raw_paths=(Path("capture.bin"),) if raw_bytes else (),
        reader_error=None,
        writer_error=writer_error,
        parser_error=parser_error,
        aggregator_error=None,
        parse_backlog=parse_backlog,
        raw_bytes=raw_bytes,
        parser_raw_bytes=parser_raw_bytes,
        parser_frames=regular_frames,
        parser_carried_bytes=0,
        completed=writer_error is None and parser_error is None and not parse_backlog,
        parse_dropped_chunks=1 if parse_dropped_bytes else 0,
        parse_dropped_bytes=parse_dropped_bytes,
        parser_lag_bytes=max(0, raw_bytes - parser_raw_bytes),
        writer_finalized=writer_error is None,
        aggregator_finalized=parser_error is None,
        final_snapshot=snapshot,
    )


def _report(result: CapturePipelineResult):
    return build_capture_report(
        result,
        TransportConfig(TransportMode.UART, "COM3", "COM3", 921600),
        started_at=datetime(2026, 1, 1, 12, 0, 0).astimezone(),
        ended_at=datetime(2026, 1, 1, 12, 0, 10).astimezone(),
        duration_sec=10.0,
        console_log_paths=(Path("capture_console.log"),),
        report_path=Path("capture_report.txt"),
    )


def test_ready_report_contains_sequence_and_file_evidence() -> None:
    report = _report(_result())

    assert report.verdict is CaptureVerdict.READY
    text = format_capture_report(report)
    assert "READY FOR ANALYSIS" in text
    assert "HOST" in text
    assert "1 -> 2" in text
    assert "capture.bin" in text


def test_report_can_be_rendered_in_chinese() -> None:
    text = format_capture_report(_report(_result()), language="zh_CN")

    assert "BLE Log 录制质量报告" in text
    assert "结论：可用于分析" in text
    assert "序列号连续性" in text
    assert "原始数据：capture.bin" in text


def test_screen_summary_only_shows_customer_decision_fields() -> None:
    report = _report(
        _result(
            regular_frames=100,
            missing_frames=2,
            firmware_loss=1,
            firmware_written_bytes=999,
            firmware_lost_bytes=1,
        )
    )
    text = format_capture_summary(report, language="zh_CN")

    assert "建议：数据可以提交分析，但录制质量存在警告。" in text
    assert "已保存数据（可信）" in text
    assert "持续时间：10.0 s" in text
    assert "原始数据：100 B，共 1 个文件" in text
    assert "有效日志帧：100" in text
    assert "自动质量检查（覆盖全部已保存数据）" in text
    assert "解析覆盖：100 B / 100 B（100.0%）" in text
    assert "序列号疑似缺失：2 帧" in text
    assert "固件日志写入失败" not in text
    assert "详细报告：capture_report.txt" in text
    assert "原始数据文件：capture.bin" in text
    assert "解析覆盖情况" not in text


def test_detailed_report_lists_final_stat_segments() -> None:
    result = _result(firmware_written_bytes=200)
    assert result.final_snapshot is not None
    result = replace(
        result,
        final_snapshot=replace(
            result.final_snapshot,
            capture_segments=(
                CaptureSegmentSummary(1, False, True, 2, 200, 10, 1000, 1, 50, 0, True, FirmwareCounterSource.ENH_STAT),
                CaptureSegmentSummary(2, True, True, 2, 200, 2, 200, 0, 0, 0, False, FirmwareCounterSource.FINAL_STAT),
                CaptureSegmentSummary(3, False, False, 1, 100, 0, 0, 0, 0, 0, False),
            ),
        ),
    )

    text = format_capture_report(_report(result), language="zh_CN")

    assert "分段统计" in text
    assert "第 1 段（开头不完整）" in text
    assert "第 2 段（完整）" in text
    assert "第 3 段（结尾不完整）" in text
    assert "固件写入 10 帧" not in text
    assert "接收 2 帧 /" not in text
    # The segment's own ENH_STAT accrual is labelled as such, and a segment with
    # neither counter source says so instead of claiming a FINAL_STAT it has not seen.
    assert "固件缓冲丢帧（ENH_STAT）1 帧" in text
    assert "固件写入失败 0 帧" in text
    assert "无固件统计" in text


def test_sequence_gap_and_firmware_loss_produce_warning() -> None:
    report = _report(
        _result(
            regular_frames=100,
            missing_frames=2,
            firmware_loss=1,
            firmware_written_bytes=999,
            firmware_lost_bytes=1,
        )
    )

    assert report.verdict is CaptureVerdict.WARNING
    assert any("sequence discontinuity" in reason for reason in report.reasons)
    assert any("firmware buffer loss" in reason for reason in report.reasons)


def test_uncertain_sequence_does_not_report_an_exact_loss() -> None:
    report = _report(_result(missing_frames=999_999, sequence_uncertain=True))

    assert report.verdict is CaptureVerdict.WARNING
    assert "Unable to verify" in format_capture_summary(report)
    assert "999999" not in format_capture_report(report)


def test_no_decoded_regular_frames_recommends_recapture() -> None:
    report = _report(_result(regular_frames=0))

    assert report.verdict is CaptureVerdict.CHECK_CONFIGURATION
    assert "Verdict: CHECK CONFIGURATION" in format_capture_report(report)
    assert "结论：检查配置" in format_capture_report(report, language="zh_CN")
    assert (
        "No valid BLE Log frames were recorded. Check the transport mode, port, baud rate, wiring, and firmware log "
        "configuration, then record again." in format_capture_summary(report)
    )
    assert "没有录到有效 BLE Log 帧。请检查传输模式、端口、波特率、接线和固件日志配置后重新录制。" in (
        format_capture_summary(report, language="zh_CN")
    )


def test_incomplete_parser_with_no_frames_keeps_warning_advice() -> None:
    report = _report(_result(regular_frames=0, parse_backlog=True, parser_raw_bytes=60, parse_dropped_bytes=40))

    assert report.verdict is CaptureVerdict.WARNING
    assert "recording quality warnings were detected" in format_capture_summary(report)
    assert "Check the transport mode" not in format_capture_summary(report)


def test_parser_backlog_preserves_raw_but_marks_report_warning() -> None:
    report = _report(_result(parse_backlog=True, parser_raw_bytes=60, parse_dropped_bytes=40))

    assert report.verdict is CaptureVerdict.WARNING
    assert report.raw_bytes == 100
    assert not report.parser_complete
    text = format_capture_summary(report, language="zh_CN")
    assert "已保存数据（可信）" in text
    assert "解析覆盖：60 B / 100 B（60.0%）" in text
    assert "已解析部分识别到的有效日志帧：2" in text
    assert "整份录制的序列号连续性：无法确认" in text


def test_writer_failure_recommends_recapture() -> None:
    report = _report(_result(writer_error="disk full"))

    assert report.verdict is CaptureVerdict.RECAPTURE


def test_experimental_quality_threshold_is_detailed_only() -> None:
    report = _report(
        _result(
            regular_frames=100,
            firmware_loss=6,
            firmware_written_bytes=940,
            firmware_lost_bytes=60,
        )
    )

    assert report.verdict is CaptureVerdict.RECAPTURE
    assert report.firmware_write_loss_rate == 0.06
    assert any("Firmware write failure rate exceeded" in reason for reason in report.reasons)
    assert "Firmware write failure rate: 6.0000%" in format_capture_report(report)
    assert "固件日志写入失败" not in format_capture_summary(report, language="zh_CN")


def test_internal_firmware_loss_is_scored_on_its_own_row() -> None:
    """INTERNAL (source 0) loss is scored on its own rate, never as customer data."""

    report = _report(
        _result(
            firmware_loss=7,
            firmware_loss_source=0,
            firmware_written_bytes=2000,
            firmware_lost_bytes=7,
        )
    )

    assert report.verdict is CaptureVerdict.READY  # 7 of 2007 bytes is 0.35% of INTERNAL's own traffic
    assert "Firmware log write failures" not in format_capture_summary(report)
    assert "INTERNAL: 7 frame(s)" in format_capture_report(report)
    assert "INTERNAL: 0.3488%" in format_capture_report(report)


def test_a_source_that_lost_nothing_still_yields_a_rate() -> None:
    """A clean source is a 0% data point, not a missing one.

    The aggregator emits a row for every source that reported counters, so a
    source with written frames and no loss keeps the capture's rate a number.
    When only lossy sources produced rows, a clean capture reported
    "Not enough data" instead of 0.0000%.
    """

    report = _report(
        _result(
            firmware_loss_rows=(
                FirmwareLossSummary(source=5, frames=0, bytes=0, written_frames=1000, written_bytes=100_000),
            ),
        )
    )

    assert report.firmware_write_loss_rate == 0.0
    assert report.verdict is CaptureVerdict.READY
    assert "0.0000%" in format_capture_report(report)
    # The loss list itself still lists only the sources that lost something.
    assert "None observed after baseline." in format_capture_report(report)


def test_one_source_over_the_threshold_fails_on_its_own_evidence() -> None:
    """A nearly clean customer source does not excuse an INTERNAL source over 5%.

    The blended rate is exactly 5%, which single-rate scoring accepted; per-source
    scoring fails the capture on the INTERNAL row alone.
    """

    report = _report(
        _result(
            firmware_loss_rows=(
                FirmwareLossSummary(source=2, frames=1, bytes=10, written_frames=1000, written_bytes=100_000),
                FirmwareLossSummary(source=0, frames=100, bytes=9_990, written_frames=900, written_bytes=90_000),
            ),
            firmware_written_bytes=190_000,
            firmware_lost_bytes=10_000,
        )
    )

    assert report.firmware_write_loss_rate == 9_990 / 99_990
    assert report.verdict is CaptureVerdict.RECAPTURE
    assert "LL_TASK: 0.0100%" in format_capture_report(report)
    assert "INTERNAL: 9.9910%" in format_capture_report(report)


def test_warning_verdict_uses_bright_yellow() -> None:
    assert "color: ansi_bright_yellow;" in CaptureReportScreen.DEFAULT_CSS


def test_check_configuration_verdict_uses_error_color() -> None:
    assert "#capture-report-verdict.check_configuration" in CaptureReportScreen.DEFAULT_CSS


def test_duplicate_frames_do_not_dilute_the_loss_rate() -> None:
    """The duplicate frames are not extra sequence numbers, so 10 of 190 stays 5.26%."""
    result = _result(regular_frames=230, missing_frames=10, duplicate_frames=50)

    report = _report(result)

    assert report.sequence_loss_rate == 10 / 190
    assert report.verdict is CaptureVerdict.RECAPTURE


def test_sequence_rate_counts_lost_frames_in_the_denominator() -> None:
    """Lost frames belong in the denominator: 10 of (100 + 10), not of 100."""
    result = _result(regular_frames=100, missing_frames=10)

    report = _report(result)

    assert report.sequence_loss_rate == 10 / 110
    assert report.verdict is CaptureVerdict.RECAPTURE


def _per_source_snapshot(result: CapturePipelineResult) -> AggregatorSnapshot:
    """A capture whose firmware numbered each source from its own counter."""

    sequence = SequenceSummary(
        per_source=True,
        observed_frames=4,
        missing_frames=1,
        segments=2,
        sources=(
            SequenceSourceSummary(
                source=5,
                observed_frames=3,
                first_sn=0,
                last_sn=3,
                missing_frames=1,
                segments=2,
                late_frames=0,
                duplicate_frames=0,
                wraps=0,
            ),
            SequenceSourceSummary(source=7, observed_frames=1, first_sn=0, last_sn=0),
        ),
    )
    return replace(result.final_snapshot, sequence=sequence, firmware_version=5)


def _shared_counter_snapshot(result: CapturePipelineResult) -> AggregatorSnapshot:
    """A capture whose firmware numbered every source from one counter."""

    return replace(result.final_snapshot, firmware_version=8)


def _sequence_section(text: str) -> str:
    return text[text.index("Sequence continuity:") :]


def test_shared_counter_report_keeps_one_totals_row_and_a_source_table() -> None:
    text = format_capture_report(_report(replace(_result(), final_snapshot=_shared_counter_snapshot(_result()))))
    section = _sequence_section(text)

    assert "Firmware protocol: v8 (one shared counter)" in text
    assert "All frames" in section and "All sources" not in section
    # One counter means one continuity verdict, and the sources are only an
    # observation table: their SN ranges belong to different streams.
    assert "Missing  Segments" not in section
    assert "Frames by source" in section


def test_per_source_report_gives_every_source_its_own_continuity_row() -> None:
    report = _report(replace(_result(), final_snapshot=_per_source_snapshot(_result())))
    text = format_capture_report(report)

    assert "Firmware protocol: v5 (per-source counters)" in text
    section = _sequence_section(text)
    assert "All sources" in section and "All frames" not in section
    assert "Frames by source" not in section
    source_rows = (line for line in section.splitlines() if line.startswith(("  HOST", "  ENCODE")))
    rows = {line.split()[0]: line.rstrip() for line in source_rows}
    assert set(rows) == {"HOST", "ENCODE"}
    assert rows["HOST"].endswith("GAPS DETECTED")
    assert rows["ENCODE"].endswith("CONTINUOUS")


def test_an_unproven_counter_contract_marks_the_numbers_it_still_reports() -> None:
    """A capture without any firmware record cannot prove how SNs are numbered.

    The report keeps the numbers (they are the best available reading) and says
    where they came from, instead of presenting the assumed contract as a fact.
    """
    result = _result(regular_frames=2, missing_frames=1, contract_known=False)
    report = _report(result)
    text = format_capture_report(report)

    assert report.sequence.missing_frames == 1
    assert "Firmware protocol: not identified (one shared counter, counter contract unproven)" in text
    assert "Counter contract unproven: continuity is accounted with one shared counter." in text


def test_a_proven_counter_contract_carries_no_such_remark() -> None:
    text = format_capture_report(_report(_result()))

    assert "unproven" not in text
