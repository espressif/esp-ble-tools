# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Build, format, and persist the final capture quality report."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button
from textual.widgets import Static

from src.backend.models import CaptureReport
from src.backend.models import CaptureVerdict
from src.backend.models import SequenceSummary
from src.backend.models import TransportConfig
from src.backend.models import format_bitrate
from src.backend.models import format_bytes
from src.backend.models import resolve_source_name
from src.backend.pipeline.controller import CapturePipelineResult
from src.frontend.rendering import terminal_border_style
from src.i18n import get_language
from src.i18n import tr

_QUALITY_RECAPTURE_THRESHOLD = 0.05


def report_path_for_capture(output_path: Path) -> Path:
    return output_path.with_name(f'{output_path.stem}_report.txt')


def build_capture_report(
    result: CapturePipelineResult,
    transport_config: TransportConfig,
    *,
    started_at: datetime,
    ended_at: datetime,
    duration_sec: float,
    console_log_paths: tuple[Path, ...],
    report_path: Path,
) -> CaptureReport:
    snapshot = result.final_snapshot
    regular_frames = snapshot.regular_frames if snapshot is not None else 0
    sequence = snapshot.sequence if snapshot is not None else SequenceSummary()
    firmware_loss = snapshot.capture_firmware_loss if snapshot is not None else ()
    firmware_written_bytes = snapshot.capture_firmware_written_bytes if snapshot is not None else 0
    firmware_lost_bytes = snapshot.capture_firmware_lost_bytes if snapshot is not None else 0
    raw_complete = bool(
        result.raw_bytes > 0
        and result.raw_paths
        and result.writer_error is None
        and result.writer_finalized
    )
    parser_complete = bool(
        snapshot is not None
        and result.aggregator_finalized
        and result.parser_error is None
        and result.aggregator_error is None
        and not result.parse_backlog
        and result.parse_dropped_chunks == 0
        and result.parse_dropped_bytes == 0
        and result.parser_lag_bytes == 0
        and result.parser_raw_bytes == result.raw_bytes
    )
    firmware_total_bytes = firmware_written_bytes + firmware_lost_bytes
    firmware_write_loss_rate = (
        firmware_lost_bytes / firmware_total_bytes if parser_complete and firmware_total_bytes else None
    )
    sequence_loss_rate = None
    if parser_complete and sequence.sources and not sequence.uncertain:
        sequence_total = regular_frames + sequence.total_missing_frames
        sequence_loss_rate = sequence.total_missing_frames / sequence_total if sequence_total else None

    errors = tuple(
        f'{label}: {message}'
        for label, message in (
            ('Reader', result.reader_error),
            ('Writer', result.writer_error),
            ('Parser', result.parser_error),
            ('Aggregator', result.aggregator_error),
        )
        if message
    )
    reasons: list[str] = []
    warnings: list[str] = []

    if result.raw_bytes <= 0 or not result.raw_paths:
        reasons.append('No raw capture data was saved.')
        verdict = CaptureVerdict.RECAPTURE
    elif result.writer_error is not None or not result.writer_finalized:
        reasons.append('Raw capture could not be finalized safely.')
        verdict = CaptureVerdict.RECAPTURE
    elif parser_complete and regular_frames == 0:
        reasons.append('No regular BLE Log frames were decoded; check mode, wiring, and firmware configuration.')
        verdict = CaptureVerdict.RECAPTURE
    else:
        if not parser_complete:
            warnings.append('Live parsing did not cover all saved raw data; sequence integrity is not fully verified.')
        if result.reader_error:
            warnings.append('The transport ended unexpectedly; the files saved before disconnection are retained.')
        if parser_complete and sequence.uncertain:
            warnings.append('Sequence continuity could not be verified within the bounded tracker.')
        elif parser_complete and sequence.total_missing_frames > 0:
            warnings.append(
                f'Observed sequence discontinuity: {sequence.total_missing_frames} missing frame number(s).'
            )
        firmware_lost_frames = sum(item.frames for item in firmware_loss if item.source > 0)
        firmware_loss_observed_bytes = sum(item.bytes for item in firmware_loss if item.source > 0)
        if firmware_lost_frames > 0 or firmware_loss_observed_bytes > 0:
            warnings.append(
                'Observed firmware buffer loss during capture: '
                f'{firmware_lost_frames} frame(s), {format_bytes(firmware_loss_observed_bytes)}.'
            )
        if result.parser_error or result.aggregator_error:
            warnings.append('The raw capture was saved, but live verification failed; retain the raw files for support.')

        threshold_reasons: list[str] = []
        if firmware_write_loss_rate is not None and firmware_write_loss_rate > _QUALITY_RECAPTURE_THRESHOLD:
            threshold_reasons.append('Firmware write failure rate exceeded the 5% recapture threshold.')
        if sequence_loss_rate is not None and sequence_loss_rate > _QUALITY_RECAPTURE_THRESHOLD:
            threshold_reasons.append('Sequence discontinuity rate exceeded the 5% recapture threshold.')

        if parser_complete and threshold_reasons:
            verdict = CaptureVerdict.RECAPTURE
            reasons.extend(threshold_reasons)
        elif warnings or errors:
            verdict = CaptureVerdict.WARNING
            reasons.extend(warnings)
        else:
            verdict = CaptureVerdict.READY
            reasons.append('Raw data was finalized, BLE Log frames were decoded, and no continuity loss was observed.')

    peak_bits_per_sec = snapshot.stats.transport.max_rx_bits_per_sec if snapshot is not None else 0.0
    return CaptureReport(
        verdict=verdict,
        reasons=tuple(reasons),
        transport_config=transport_config,
        started_at=started_at,
        ended_at=ended_at,
        duration_sec=max(0.0, duration_sec),
        raw_paths=result.raw_paths,
        console_log_paths=console_log_paths,
        report_path=report_path,
        raw_bytes=result.raw_bytes,
        raw_complete=raw_complete,
        parser_frames=result.parser_frames,
        regular_frames=regular_frames,
        parser_complete=parser_complete,
        parser_raw_bytes=result.parser_raw_bytes,
        parser_carried_bytes=result.parser_carried_bytes,
        parse_dropped_chunks=result.parse_dropped_chunks,
        parse_dropped_bytes=result.parse_dropped_bytes,
        parser_lag_bytes=result.parser_lag_bytes,
        average_bytes_per_sec=result.raw_bytes / duration_sec if duration_sec > 0 else 0.0,
        peak_bits_per_sec=peak_bits_per_sec,
        sequence=sequence,
        firmware_loss=firmware_loss,
        firmware_written_bytes=firmware_written_bytes,
        firmware_lost_bytes=firmware_lost_bytes,
        firmware_write_loss_rate=firmware_write_loss_rate,
        sequence_loss_rate=sequence_loss_rate,
        errors=errors,
        warnings=tuple(warnings),
    )


def _localized_reasons(report: CaptureReport, language: str) -> list[str]:
    reasons: list[str] = []
    for reason in report.reasons:
        if reason.startswith('Observed sequence discontinuity:'):
            reasons.append(
                tr(
                    'Observed sequence discontinuity: {count} missing frame number(s).',
                    language=language,
                    count=report.sequence.total_missing_frames,
                )
            )
        elif reason.startswith('Observed firmware buffer loss during capture:'):
            reasons.append(
                tr(
                    'Observed firmware buffer loss during capture: {frames} frame(s), {bytes}.',
                    language=language,
                    frames=sum(item.frames for item in report.firmware_loss if item.source > 0),
                    bytes=format_bytes(sum(item.bytes for item in report.firmware_loss if item.source > 0)),
                )
            )
        else:
            reasons.append(tr(reason, language=language))
    return reasons


def _localized_error(error: str, language: str) -> str:
    label, separator, message = error.partition(': ')
    return f'{tr(label, language=language)}{separator}{tr(message, language=language)}'


def _coverage_text(report: CaptureReport, language: str) -> str:
    percent = min(report.parser_raw_bytes / report.raw_bytes, 1.0) if report.raw_bytes else 0.0
    left, right = ('（', '）') if language == 'zh_CN' else ('(', ')')
    space = '' if language == 'zh_CN' else ' '
    return f'{format_bytes(report.parser_raw_bytes)} / {format_bytes(report.raw_bytes)}{space}{left}{percent:.1%}{right}'


def _firmware_write_evidence(report: CaptureReport, language: str) -> str:
    rate = report.firmware_write_loss_rate
    if rate is None:
        return tr('Not enough data', language=language)
    total = report.firmware_written_bytes + report.firmware_lost_bytes
    left, right = ('（', '）') if language == 'zh_CN' else ('(', ')')
    space = '' if language == 'zh_CN' else ' '
    return (
        f'{format_bytes(report.firmware_lost_bytes)} / {format_bytes(total)}'
        f'{space}{left}{rate:.2%}{right}'
    )


def format_capture_summary(report: CaptureReport, language: str | None = None) -> str:
    language = language or get_language()
    separator = '：' if language == 'zh_CN' else ': '
    frames = tr('frames', language=language)
    advice = {
        CaptureVerdict.READY: 'This capture is ready to submit for analysis.',
        CaptureVerdict.WARNING: 'The data can be submitted for analysis, but capture quality warnings were detected.',
        CaptureVerdict.RECAPTURE: 'Check the connection and configuration, then capture again.',
    }[report.verdict]
    report_path = (
        f'{tr("NOT SAVED", language=language)} ({report.report_write_error})'
        if report.report_write_error
        else report.report_path
    )
    raw_path = report.raw_paths[0] if report.raw_paths else tr('NOT SAVED', language=language)
    parser_scope = 'all saved data' if report.parser_complete else 'parsed portion only'
    scope_left, scope_right = ('（', '）') if language == 'zh_CN' else ('(', ')')
    scope_space = '' if language == 'zh_CN' else ' '
    sequence_result = (
        tr('Unable to verify', language=language)
        if not report.parser_complete or report.sequence.uncertain
        else f'{report.sequence.total_missing_frames} {frames}'
    )
    return '\n'.join(
        (
            f'{tr("Recommendation", language=language)}{separator}{tr(advice, language=language)}',
            '',
            f'{tr("Saved data (reliable)" if report.raw_complete else "Saved data (incomplete)", language=language)}{separator.rstrip()}',
            f'  {tr("Duration", language=language)}{separator}{report.duration_sec:.1f} s',
            f'  {tr("Raw", language=language)}{separator}'
            f'{tr("{size}, {count} file(s)", language=language, size=format_bytes(report.raw_bytes), count=len(report.raw_paths))}',
            '',
            f'{tr("Automated quality check", language=language)}{scope_space}'
            f'{scope_left}{tr(parser_scope, language=language)}{scope_right}{separator.rstrip()}',
            f'  {tr("Parser coverage summary", language=language)}{separator}'
            f'{_coverage_text(report, language)}',
            f'  {tr("Regular BLE Log frames" if report.parser_complete else "Frames found in parsed portion", language=language)}'
            f'{separator}{report.regular_frames}',
            f'  {tr("Possible sequence loss" if report.parser_complete else "Full-recording sequence continuity", language=language)}'
            f'{separator}{sequence_result}',
            f'  {tr("Firmware log write failures (failed / total)" if report.parser_complete else "Firmware write failures in parsed portion (failed / total)", language=language)}{separator}'
            f'{_firmware_write_evidence(report, language)}',
            '',
            f'{tr("Detailed report", language=language)}{separator}{report_path}',
            f'{tr("Raw data file", language=language)}{separator}{raw_path}',
        )
    )


def format_capture_report(report: CaptureReport, language: str | None = None) -> str:
    language = language or get_language()
    cfg = report.transport_config
    separator = '：' if language == 'zh_CN' else ': '

    def field(label: str, value: object) -> str:
        return f'{tr(label, language=language)}{separator}{value}'

    lines = [
        tr('BLE Log Capture Report', language=language),
        '=' * 72,
        field('Verdict', tr(report.verdict.value, language=language)),
        '',
        f'{tr("Reasons", language=language)}{separator.rstrip()}',
        *(f'  - {reason}' for reason in _localized_reasons(report, language)),
        '',
        f'{tr("Reliability", language=language)}{separator.rstrip()}',
        f'  {field("Saved raw data", tr("Complete and reliable" if report.raw_complete else "Incomplete", language=language))}',
        f'  {field("Automated quality check", tr("all saved data" if report.parser_complete else "parsed portion only", language=language))}',
        f'  {field("Parser coverage summary", _coverage_text(report, language))}',
        '',
        f'{tr("Capture", language=language)}{separator.rstrip()}',
        f'  {field("Mode", cfg.mode.value)}',
        f'  {field("Port", cfg.port)}',
        f'  {field("Baud rate", cfg.baudrate if cfg.mode.value == "uart" else tr("N/A", language=language))}',
        f'  {field("Started", report.started_at.astimezone().isoformat(sep=" ", timespec="seconds"))}',
        f'  {field("Ended", report.ended_at.astimezone().isoformat(sep=" ", timespec="seconds"))}',
        f'  {field("Duration", f"{report.duration_sec:.1f} s")}',
        f'  {field("Raw bytes", format_bytes(report.raw_bytes))}',
        f'  {field("Decoded frames", report.parser_frames)}',
        f'  {field("Regular frames", report.regular_frames)}',
        f'  {field("Average receive rate", f"{format_bytes(int(report.average_bytes_per_sec))}/s")}',
        f'  {field("Peak receive rate", format_bitrate(report.peak_bits_per_sec))}',
        '',
        f'{tr("Parser coverage", language=language)}{separator.rstrip()}',
        f'  {field("Complete", tr("YES" if report.parser_complete else "NO", language=language))}',
        f'  {field("Parsed raw bytes", report.parser_raw_bytes)}',
        f'  {field("Dropped chunks/bytes", f"{report.parse_dropped_chunks}/{report.parse_dropped_bytes}")}',
        f'  {field("Parser lag bytes", report.parser_lag_bytes)}',
        f'  {field("Trailing carried bytes", report.parser_carried_bytes)}',
        '',
        f'{tr("Experimental quality metrics", language=language)}{separator.rstrip()}',
        f'  {field("Firmware written bytes", format_bytes(report.firmware_written_bytes))}',
        f'  {field("Firmware lost bytes", format_bytes(report.firmware_lost_bytes))}',
        f'  {field("Firmware observed total bytes", format_bytes(report.firmware_written_bytes + report.firmware_lost_bytes))}',
        f'  {field("Firmware write failure rate", _format_rate(report.firmware_write_loss_rate, language))}',
        f'  {field("Sequence discontinuity rate", _format_rate(report.sequence_loss_rate, language))}',
        f'  {field("Recapture threshold", "5%")}',
        '',
        f'{tr("Sequence continuity", language=language)}{separator.rstrip()}',
    ]
    if report.sequence.sources:
        if language == 'zh_CN':
            for source in report.sequence.sources:
                lines.append(
                    f'  {resolve_source_name(source.source)}：'
                    f'{tr("Observed", language=language)} {source.observed_frames}，'
                    f'{tr("SN range", language=language)} {source.first_sn} -> {source.last_sn}，'
                    f'{tr("Missing", language=language)} '
                    f'{tr("Unable to verify", language=language) if source.uncertain else source.missing_frames}，'
                    f'{tr("Segments", language=language)} {source.segments}，'
                    f'{tr("Late", language=language)} {source.late_frames}，'
                    f'{tr("Duplicates", language=language)} {source.duplicate_frames}，'
                    f'{tr("Wraps", language=language)} {source.wraps}，'
                    f'{tr("UNCERTAIN" if source.uncertain else "GAPS DETECTED" if source.missing_frames else "CONTINUOUS", language=language)}'
                )
        else:
            lines.extend(
                (
                    '  Source       Observed  SN range                 Missing  Segments  Late  Duplicates  Wraps  Status',
                    '  -----------  --------  -----------------------  -------  --------  ----  ----------  -----  -------------',
                )
            )
            for source in report.sequence.sources:
                sn_range = f'{source.first_sn} -> {source.last_sn}'
                status = 'UNCERTAIN' if source.uncertain else 'GAPS DETECTED' if source.missing_frames else 'CONTINUOUS'
                missing = 'N/A' if source.uncertain else str(source.missing_frames)
                lines.append(
                    f'  {resolve_source_name(source.source):<11}  {source.observed_frames:>8}  '
                    f'{sn_range:<23}  {missing:>7}  {source.segments:>8}  '
                    f'{source.late_frames:>4}  {source.duplicate_frames:>10}  {source.wraps:>5}  {status}'
                )
    else:
        lines.append(f'  {tr("No regular source frames were available for sequence verification.", language=language)}')

    lines.extend(('', f'{tr("Firmware buffer loss observed during this capture", language=language)}{separator.rstrip()}'))
    if report.firmware_loss:
        for loss in report.firmware_loss:
            if language == 'zh_CN':
                lines.append(f'  {resolve_source_name(loss.source)}：{loss.frames} 帧，{format_bytes(loss.bytes)}')
            else:
                lines.append(f'  {resolve_source_name(loss.source)}: {loss.frames} frame(s), {format_bytes(loss.bytes)}')
    else:
        lines.append(f'  {tr("None observed after baseline.", language=language)}')

    lines.extend(('', f'{tr("Files", language=language)}{separator.rstrip()}'))
    lines.extend(f'  {field("Raw", path)}' for path in report.raw_paths)
    lines.extend(f'  {field("Console log", path)}' for path in report.console_log_paths)
    if report.report_write_error:
        not_saved = f'{tr("NOT SAVED", language=language)} ({report.report_write_error})'
        lines.append(f'  {field("Report", not_saved)}')
    else:
        lines.append(f'  {field("Report", report.report_path)}')
    if report.errors:
        lines.extend(
            ('', f'{tr("Errors", language=language)}{separator.rstrip()}', *(
                f'  - {_localized_error(error, language)}' for error in report.errors
            ))
        )
    lines.append('')
    return '\n'.join(lines)


def _format_rate(rate: float | None, language: str) -> str:
    return f'{rate:.4%}' if rate is not None else tr('Not enough data', language=language)


def write_capture_report(report: CaptureReport, language: str | None = None) -> None:
    report.report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report.report_path, 'w', encoding='utf-8', newline='\n') as file_obj:
        file_obj.write(format_capture_report(report, language))
        file_obj.flush()
        try:
            os.fsync(file_obj.fileno())
        except OSError:
            pass


class CaptureReportScreen(ModalScreen[str]):
    """Final capture report with one-click same-configuration recording."""

    DEFAULT_CSS = """
    CaptureReportScreen {
        align: center middle;
    }

    #capture-report-container {
        width: 94%;
        max-width: 120;
        height: 90%;
        background: $surface;
        padding: 1 2;
        border: __BORDER_STYLE__ $accent;
    }

    #capture-report-scroll {
        height: 1fr;
    }

    #capture-report-verdict {
        height: 2;
        text-align: center;
        text-style: bold;
    }

    #capture-report-verdict.ready {
        color: $success;
    }

    #capture-report-verdict.warning {
        color: ansi_bright_yellow;
    }

    #capture-report-verdict.recapture {
        color: $error;
    }

    #capture-report-actions {
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    #capture-report-actions Button {
        margin: 0 1;
    }

    """.replace('__BORDER_STYLE__', terminal_border_style())

    BINDINGS = [
        Binding('q', 'exit_report', 'Exit'),
        Binding('Q', 'exit_report', show=False),
        Binding('ctrl+c', 'exit_report', show=False, priority=True),
    ]

    def __init__(self, report: CaptureReport) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        language = get_language()
        separator = '：' if language == 'zh_CN' else ': '
        with Vertical(id='capture-report-container'):
            yield Static(
                f'{tr("Verdict", language=language)}{separator}'
                f'{tr(self.report.verdict.value, language=language)}',
                id='capture-report-verdict',
                classes=self.report.verdict.name.lower(),
            )
            with VerticalScroll(id='capture-report-scroll'):
                yield Static(format_capture_summary(self.report), markup=False)
            with Center():
                with Horizontal(id='capture-report-actions'):
                    yield Button('Record Again', variant='primary', id='record-again')
                    yield Button('Exit', id='exit-report')

    @on(Button.Pressed, '#record-again')
    def record_again(self) -> None:
        self.dismiss('again')

    @on(Button.Pressed, '#exit-report')
    def exit_report(self) -> None:
        self.dismiss('exit')

    def action_exit_report(self) -> None:
        self.dismiss('exit')
