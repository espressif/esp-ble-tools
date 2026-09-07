from datetime import datetime
from pathlib import Path

from src.backend.analysis.aggregator import AggregatorSnapshot
from src.backend.models import CaptureVerdict
from src.backend.models import FirmwareLossSummary
from src.backend.models import FrameStats
from src.backend.models import SequenceSourceSummary
from src.backend.models import SequenceSummary
from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.pipeline.controller import CapturePipelineResult
from src.frontend.capture_report import build_capture_report
from src.frontend.capture_report import format_capture_report
from src.frontend.capture_report import format_capture_summary
from src.frontend.capture_report import CaptureReportScreen


def _result(
    *,
    raw_bytes: int = 100,
    regular_frames: int = 2,
    missing_frames: int = 0,
    writer_error: str | None = None,
    parser_error: str | None = None,
    parse_backlog: bool = False,
    firmware_loss: int = 0,
    firmware_written_bytes: int = 0,
    firmware_lost_bytes: int = 0,
    firmware_loss_source: int = 5,
    sequence_uncertain: bool = False,
) -> CapturePipelineResult:
    sequence = SequenceSummary(
        sources=(
            SequenceSourceSummary(
                source=5,
                observed_frames=regular_frames,
                first_sn=1 if regular_frames else None,
                last_sn=regular_frames if regular_frames else None,
                missing_frames=missing_frames,
                segments=1 if regular_frames else 0,
                uncertain=sequence_uncertain,
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
        parser_raw_bytes=raw_bytes,
        parser_frames=regular_frames,
        parser_carried_bytes=0,
        regular_frames=regular_frames,
        sequence=sequence,
        capture_firmware_loss=(FirmwareLossSummary(source=firmware_loss_source, frames=firmware_loss, bytes=64),)
        if firmware_loss
        else (),
        capture_firmware_written_bytes=firmware_written_bytes,
        capture_firmware_lost_bytes=firmware_lost_bytes,
    )
    return CapturePipelineResult(
        raw_paths=(Path('capture.bin'),) if raw_bytes else (),
        reader_error=None,
        writer_error=writer_error,
        parser_error=parser_error,
        aggregator_error=None,
        parse_backlog=parse_backlog,
        raw_bytes=raw_bytes,
        parser_raw_bytes=raw_bytes,
        parser_frames=regular_frames,
        parser_carried_bytes=0,
        completed=writer_error is None and parser_error is None and not parse_backlog,
        writer_finalized=writer_error is None,
        aggregator_finalized=parser_error is None,
        final_snapshot=snapshot,
    )


def _report(result: CapturePipelineResult):
    return build_capture_report(
        result,
        TransportConfig(TransportMode.UART, 'COM3', 'COM3', 921600),
        started_at=datetime(2026, 1, 1, 12, 0, 0),
        ended_at=datetime(2026, 1, 1, 12, 0, 10),
        duration_sec=10.0,
        console_log_paths=(Path('capture_console.log'),),
        report_path=Path('capture_report.txt'),
    )


def test_ready_report_contains_sequence_and_file_evidence() -> None:
    report = _report(_result())

    assert report.verdict is CaptureVerdict.READY
    text = format_capture_report(report)
    assert 'READY FOR ANALYSIS' in text
    assert 'HOST' in text
    assert '1 -> 2' in text
    assert 'capture.bin' in text


def test_report_can_be_rendered_in_chinese() -> None:
    text = format_capture_report(_report(_result()), language='zh_CN')

    assert 'BLE Log 录制质量报告' in text
    assert '结论：可用于分析' in text
    assert '序列号连续性' in text
    assert '原始数据：capture.bin' in text


def test_screen_summary_only_shows_customer_decision_fields() -> None:
    report = _report(_result(regular_frames=100, missing_frames=2, firmware_loss=1))
    text = format_capture_summary(report, language='zh_CN')

    assert '建议：数据可以提交分析，但录制质量存在警告。' in text
    assert '录制结果' in text
    assert '持续时间：10.0 s' in text
    assert '原始数据：100 B，共 1 个文件' in text
    assert '有效日志帧：100' in text
    assert '质量检查' in text
    assert '解析覆盖：完整' in text
    assert '序列号疑似缺失：2 帧' in text
    assert '固件报告丢失：1 帧' in text
    assert '详细报告：capture_report.txt' in text
    assert '原始数据文件：capture.bin' in text
    assert '解析覆盖情况' not in text


def test_detailed_report_has_no_disclaimer() -> None:
    text = format_capture_report(_report(_result()))

    assert 'cannot prove' not in text
    assert 'cannot infer' not in text


def test_sequence_gap_and_firmware_loss_produce_warning() -> None:
    report = _report(_result(regular_frames=100, missing_frames=2, firmware_loss=1))

    assert report.verdict is CaptureVerdict.WARNING
    assert any('sequence discontinuity' in reason for reason in report.reasons)
    assert any('firmware buffer loss' in reason for reason in report.reasons)


def test_uncertain_sequence_does_not_report_an_exact_loss() -> None:
    report = _report(_result(missing_frames=999_999, sequence_uncertain=True))

    assert report.verdict is CaptureVerdict.WARNING
    assert 'Unable to verify' in format_capture_summary(report)
    assert '999999' not in format_capture_report(report)


def test_no_decoded_regular_frames_recommends_recapture() -> None:
    report = _report(_result(regular_frames=0))

    assert report.verdict is CaptureVerdict.RECAPTURE


def test_parser_backlog_preserves_raw_but_marks_report_warning() -> None:
    report = _report(_result(parse_backlog=True))

    assert report.verdict is CaptureVerdict.WARNING
    assert report.raw_bytes == 100
    assert not report.parser_complete


def test_writer_failure_recommends_recapture() -> None:
    report = _report(_result(writer_error='disk full'))

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
    assert 'Firmware write failure rate: 6.0000%' in format_capture_report(report)
    assert '6.0000%' not in format_capture_summary(report)


def test_internal_firmware_loss_is_detailed_but_does_not_grade_customer_data() -> None:
    report = _report(_result(firmware_loss=7, firmware_loss_source=0))

    assert report.verdict is CaptureVerdict.READY
    assert 'Firmware-reported loss: 0 frames' in format_capture_summary(report)
    assert 'INTERNAL: 7 frame(s)' in format_capture_report(report)


def test_warning_verdict_uses_bright_yellow() -> None:
    assert 'color: ansi_bright_yellow;' in CaptureReportScreen.DEFAULT_CSS
