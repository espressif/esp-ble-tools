# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Build, format, and persist the final capture quality report."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from src.backend.analysis.stream_identification import StreamIdentity, StreamKind
from src.backend.models import (
    CaptureReport,
    CaptureSegmentSummary,
    CaptureVerdict,
    CompressedHostStatus,
    FirmwareCounterSource,
    FirmwareLossSummary,
    SequenceSummary,
    TransportConfig,
    TransportMode,
    format_bitrate,
    format_bytes,
    resolve_source_name,
)
from src.backend.pipeline.controller import CapturePipelineResult
from src.frontend.rendering import terminal_border_style
from src.i18n import get_language, tr

_QUALITY_RECAPTURE_THRESHOLD = 0.05

_STREAM_KIND_LABELS = {
    StreamKind.NO_INPUT: "No data",
    StreamKind.UNRECOGNIZED: "Unrecognized data",
    StreamKind.LIKELY_TEXT: "Plain console text",
    StreamKind.BLE_LOG: "BLE Log",
}


def _content_warnings(identity: StreamIdentity | None, regular_frames: int, *, raw_complete: bool) -> list[str]:
    """What the identified stream content means for this recording; empty where no identity is kept.

    ``raw_complete`` decides whether the wording may state that the counted frame-external bytes
    reached the raw file: a recording whose writer failed, or whose transport ended unexpectedly,
    cannot say that.
    """

    if identity is None:
        return []
    if identity.kind is StreamKind.LIKELY_TEXT:
        return [
            "Received data looks like plain console text, not BLE Log frames; check that the firmware sends BLE Log to this port."
        ]
    if identity.kind is not StreamKind.BLE_LOG:
        return []
    warnings = []
    if regular_frames == 0:
        warnings.append(
            "BLE Log was identified, but no regular log frames were decoded; check the firmware log configuration."
        )
    if identity.evidence.gap_bytes_after_ble > 0:
        if raw_complete:
            warnings.append(
                "Data outside BLE Log frames arrived after BLE Log was identified; those bytes are written to "
                "the raw file, and the console log holds at most their displayable text."
            )
        else:
            warnings.append(
                "Data outside BLE Log frames arrived after BLE Log was identified; the raw recording could not "
                "be confirmed complete, so those bytes may not all be in the raw file, and the console log "
                "holds at most their displayable text."
            )
    return warnings


def _loss_bytes(rows: tuple[FirmwareLossSummary, ...], language: str = "en") -> str:
    if any(row.bytes is None for row in rows if row.source > 0):
        return tr("Unknown", language=language)
    return format_bytes(sum(row.bytes or 0 for row in rows if row.source > 0))


def _firmware_source_rates(firmware_loss: tuple[FirmwareLossSummary, ...]) -> tuple[tuple[int, float], ...]:
    """Loss rate of each source that reported firmware counters, worst last."""

    rates = []
    for row in firmware_loss:
        if row.bytes is None:
            continue
        total = row.written_bytes + row.bytes
        if total:
            rates.append((row.source, row.bytes / total))
    return tuple(sorted(rates, key=lambda item: item[1]))


def report_path_for_capture(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_report.txt")


def build_capture_report(
    result: CapturePipelineResult,
    transport_config: TransportConfig,
    *,
    started_at: datetime,
    ended_at: datetime,
    duration_sec: float,
    console_log_paths: tuple[Path, ...],
    report_path: Path,
    console_log_error: str | None = None,
    hci_paths: tuple[Path, ...] = (),
    hci_error: str | None = None,
) -> CaptureReport:
    snapshot = result.final_snapshot
    regular_frames = snapshot.regular_frames if snapshot is not None else 0
    sequence = snapshot.sequence if snapshot is not None else SequenceSummary()
    segments = snapshot.capture_segments if snapshot is not None else ()
    firmware_loss = snapshot.capture_firmware_loss if snapshot is not None else ()
    firmware_written_bytes = snapshot.capture_firmware_written_bytes if snapshot is not None else 0
    firmware_lost_bytes = snapshot.capture_firmware_lost_bytes if snapshot is not None else 0
    # Writer finalization alone does not prove that the file holds every recorded byte: a transport can
    # lose bytes before the writer sees them, whether or not that loss surfaces as a reader error. Either
    # failure must clear the completeness claim that the report and its summary make.
    raw_complete = bool(
        result.raw_bytes > 0
        and result.raw_paths
        and result.writer_error is None
        and result.writer_finalized
        and result.reader_error is None
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
    excluded = result.startup.offset_bytes if result.startup is not None else 0
    quality_snapshot = snapshot
    quality_start_offset = 0
    original_sequence = None
    quality_error = False
    if excluded:
        quality = result.opening_quality
        if (
            raw_complete
            and parser_complete
            and quality is not None
            and quality.error is None
            and quality.offset_bytes == excluded
            and quality.snapshot is not None
            and quality.snapshot.parser_raw_bytes == result.raw_bytes - excluded
        ):
            quality_snapshot = quality.snapshot
            quality_start_offset = excluded
            original_sequence = sequence
            sequence = quality_snapshot.sequence
            segments = quality_snapshot.capture_segments
            firmware_loss = quality_snapshot.capture_firmware_loss
            firmware_written_bytes = quality_snapshot.capture_firmware_written_bytes
            firmware_lost_bytes = quality_snapshot.capture_firmware_lost_bytes
        else:
            quality_error = True
    firmware_source_rates = _firmware_source_rates(firmware_loss)
    # Every source is scored on its own loss rate, so a source that lost more
    # than 5% of its own bytes fails the capture on its own evidence: INTERNAL
    # loss never dilutes, and is never diluted by, the customer log's number.
    firmware_write_loss_rate = (
        max(rate for _, rate in firmware_source_rates) if parser_complete and firmware_source_rates else None
    )
    sequence_loss_rate = None
    if parser_complete and sequence.observed_frames and not sequence.uncertain:
        sequence_loss_rate = sequence.missing_frames / sequence.total_frames if sequence.total_frames else None

    errors = tuple(
        f"{label}: {message}"
        for label, message in (
            ("Reader", result.reader_error),
            ("Writer", result.writer_error),
            ("Parser", result.parser_error),
            ("Aggregator", result.aggregator_error),
        )
        if message
    )
    reasons: list[str] = []
    warnings: list[str] = []
    stream_identity = snapshot.stream_identity if snapshot is not None else None
    findings = _content_warnings(stream_identity, regular_frames, raw_complete=raw_complete)
    if console_log_error is not None:
        findings.append("The console log could not be saved completely; this error does not itself stop raw recording.")
    if hci_error is not None:
        findings.append("HCI files could not be saved completely; retain the original raw recording.")
    host_status = result.products.compressed_host_status if result.products else CompressedHostStatus.UNVERIFIED
    if result.products and result.products.error:
        findings.append("Ordered parser products could not be saved completely.")
    if quality_error:
        findings.append("The fresh interval could not be verified; quality metrics describe the original recording.")

    if result.writer_error is not None or not result.writer_finalized:
        reasons.append("Raw recording could not be finalized safely.")
        verdict = CaptureVerdict.RECAPTURE
    elif parser_complete and regular_frames == 0:
        if result.raw_bytes <= 0 or not result.raw_paths:
            reasons.append("No raw recording data was saved.")
        reasons.append("No regular BLE Log frames were decoded; check mode, wiring, and firmware configuration.")
        verdict = CaptureVerdict.CHECK_CONFIGURATION
    elif result.raw_bytes <= 0 or not result.raw_paths:
        reasons.append("No raw recording data was saved.")
        verdict = CaptureVerdict.RECAPTURE
    else:
        warnings.extend(findings)
        if quality_snapshot is not None and quality_snapshot.integrity is not None:
            if quality_snapshot.integrity.conclusion == "failed":
                warnings.append("Checker detected missing or duplicate sequence numbers in the checked ranges.")
            if any(row.snapshot_conflict for row in quality_snapshot.integrity.intervals):
                warnings.append("Firmware snapshot anchors conflict; retain the original recording for review.")
        if not parser_complete:
            warnings.append("Live parsing did not cover all saved raw data; sequence integrity is not fully verified.")
        if result.reader_error:
            warnings.append("The transport ended unexpectedly; the files saved before disconnection are retained.")
        if parser_complete and sequence.uncertain:
            warnings.append("Sequence continuity could not be verified within the bounded tracker.")
        elif parser_complete and sequence.missing_frames > 0:
            warnings.append(f"Observed sequence discontinuity: {sequence.missing_frames} missing frame number(s).")
        firmware_lost_frames = sum(item.frames for item in firmware_loss if item.source > 0)
        firmware_loss_observed_bytes = sum(item.bytes or 0 for item in firmware_loss if item.source > 0)
        if firmware_lost_frames > 0 or firmware_loss_observed_bytes > 0:
            warnings.append(
                "Observed firmware buffer loss during recording: "
                f"{firmware_lost_frames} frame(s), {_loss_bytes(firmware_loss)}."
            )
        if result.parser_error or result.aggregator_error:
            warnings.append(
                "The raw recording was saved, but live verification failed; retain the raw files for support."
            )

        threshold_reasons: list[str] = []
        if firmware_write_loss_rate is not None and firmware_write_loss_rate > _QUALITY_RECAPTURE_THRESHOLD:
            threshold_reasons.append("Firmware write failure rate exceeded the 5% record-again threshold.")
        if sequence_loss_rate is not None and sequence_loss_rate > _QUALITY_RECAPTURE_THRESHOLD:
            threshold_reasons.append("Sequence discontinuity rate exceeded the 5% record-again threshold.")

        if parser_complete and threshold_reasons:
            verdict = CaptureVerdict.RECAPTURE
            reasons.extend(threshold_reasons)
        elif warnings or errors:
            verdict = CaptureVerdict.WARNING
            reasons.extend(warnings)
        else:
            verdict = CaptureVerdict.READY
            reasons.append("Raw data was finalized, BLE Log frames were decoded, and no continuity loss was observed.")
    # Content and console.log findings accompany every verdict without deciding one that a raw save or parse
    # failure already decided.
    for warning in findings:
        if warning not in warnings:
            warnings.append(warning)
        if warning not in reasons:
            reasons.append(warning)

    peak_bits_per_sec = snapshot.stats.transport.max_rx_bits_per_sec if snapshot is not None else 0.0
    binary_hci = tuple(
        path
        for path in (result.products.paths if result.products else ())
        if "_btsnoop" in path.name.removeprefix(result.raw_paths[0].stem if result.raw_paths else "")
    )
    return CaptureReport(
        verdict=verdict,
        reasons=tuple(reasons),
        transport_config=transport_config,
        started_at=started_at,
        ended_at=ended_at,
        duration_sec=max(0.0, duration_sec),
        raw_paths=result.raw_paths,
        console_log_paths=console_log_paths,
        parsed_paths=tuple(
            path for path in (result.products.paths if result.products else ()) if path not in binary_hci
        ),
        product_error=result.products.error if result.products else None,
        compressed_host_status=host_status,
        host_text_entries=result.products.host_text_entries if result.products else 0,
        host_missing_id_frames=result.products.host_missing_id_frames if result.products else 0,
        hci_paths=(*hci_paths, *binary_hci),
        hci_error=hci_error,
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
        segments=segments,
        firmware_loss=firmware_loss,
        firmware_written_bytes=firmware_written_bytes,
        firmware_lost_bytes=firmware_lost_bytes,
        firmware_write_loss_rate=firmware_write_loss_rate,
        sequence_loss_rate=sequence_loss_rate,
        errors=errors,
        warnings=tuple(warnings),
        firmware_version=snapshot.firmware_version if snapshot is not None else None,
        firmware_contract_known=snapshot.firmware_contract_known if snapshot is not None else True,
        stream_identity=stream_identity,
        console_log_error=console_log_error,
        startup=result.startup,
        quality_regular_frames=quality_snapshot.regular_frames if quality_start_offset else None,
        quality_start_offset=quality_start_offset,
        original_sequence=original_sequence,
        integrity=quality_snapshot.integrity if quality_snapshot is not None else None,
        firmware=quality_snapshot.firmware if quality_snapshot is not None else None,
    )


def _localized_reasons(report: CaptureReport, language: str) -> list[str]:
    reasons: list[str] = []
    for reason in report.reasons:
        if reason.startswith("Observed sequence discontinuity:"):
            reasons.append(
                tr(
                    "Observed sequence discontinuity: {count} missing frame number(s).",
                    language=language,
                    count=report.sequence.missing_frames,
                )
            )
        elif reason.startswith("Observed firmware buffer loss during recording:"):
            reasons.append(
                tr(
                    "Observed firmware buffer loss during recording: {frames} frame(s), {bytes}.",
                    language=language,
                    frames=sum(item.frames for item in report.firmware_loss if item.source > 0),
                    bytes=_loss_bytes(report.firmware_loss, language),
                )
            )
        else:
            reasons.append(tr(reason, language=language))
    return reasons


def _localized_error(error: str, language: str) -> str:
    label, separator, message = error.partition(": ")
    return f"{tr(label, language=language)}{separator}{tr(message, language=language)}"


def _coverage_text(report: CaptureReport, language: str) -> str:
    percent = min(report.parser_raw_bytes / report.raw_bytes, 1.0) if report.raw_bytes else 0.0
    left, right = ("（", "）") if language == "zh_CN" else ("(", ")")
    space = "" if language == "zh_CN" else " "
    return (
        f"{format_bytes(report.parser_raw_bytes)} / {format_bytes(report.raw_bytes)}{space}{left}{percent:.1%}{right}"
    )


def _no_regular_frames_advice(report: CaptureReport) -> str:
    """Identified content explains the missing frames better than a link check; only UART has a baud rate."""

    content_warnings = _content_warnings(
        report.stream_identity, report.regular_frames, raw_complete=report.raw_complete
    )
    if content_warnings:
        return content_warnings[0]
    if report.transport_config.mode is TransportMode.UART:
        return (
            "No valid BLE Log frames were recorded. Check the transport mode, port, baud rate, wiring, and firmware log "
            "configuration, then record again."
        )
    return (
        "No valid BLE Log frames were recorded. Check the transport mode, port, wiring, and firmware log "
        "configuration, then record again."
    )


def _host_text_summary(report: CaptureReport, language: str, separator: str) -> list[str]:
    status = tr(report.compressed_host_status.value, language=language)
    lines = [f"{tr('Compressed Host text', language=language)}{separator}{status}"]
    if report.host_missing_id_frames and report.compressed_host_status in (
        CompressedHostStatus.PARTIAL,
        CompressedHostStatus.NO_TEXT,
    ):
        lines.append(
            tr(
                "Text entries written: {entries:,}. Frames without a usable dictionary entry: {frames:,}.",
                language=language,
                entries=report.host_text_entries,
                frames=report.host_missing_id_frames,
            )
        )
    if report.compressed_host_status in (CompressedHostStatus.NO_TEXT, CompressedHostStatus.PARTIAL):
        lines.append(tr("Check that BLE_HOST_logs.json comes from the flashed firmware build.", language=language))
    return lines


def _database_copy_lines(report: CaptureReport, language: str) -> list[str]:
    if report.pending_database is not None:
        return [
            tr(
                "Dictionary copy pending. Keep Console open to finish copying from {path}.",
                language=language,
                path=report.pending_database,
            )
        ]
    if report.database_copy_error is not None:
        return [tr("Dictionary copy not saved: {error}", language=language, error=report.database_copy_error)]
    if report.database_copy is not None:
        return [tr("Dictionary copy: {path}", language=language, path=report.database_copy)]
    return []


def format_capture_summary(report: CaptureReport, language: str | None = None) -> str:
    language = language or get_language()
    separator = "：" if language == "zh_CN" else ": "
    frames = tr("frames", language=language)
    advice = {
        CaptureVerdict.READY: "This recording is ready to submit for analysis.",
        CaptureVerdict.WARNING: "The data can be submitted for analysis, but recording quality warnings were detected.",
        CaptureVerdict.CHECK_CONFIGURATION: _no_regular_frames_advice(report),
        CaptureVerdict.RECAPTURE: "Check the connection and configuration, then record again.",
    }[report.verdict]
    report_path = (
        f"{tr('NOT SAVED', language=language)} ({report.report_write_error})"
        if report.report_write_error
        else report.report_path
    )
    raw_path = report.raw_paths[0] if report.raw_paths else tr("NOT SAVED", language=language)
    parser_scope = _quality_scope(report)
    scope_left, scope_right = ("（", "）") if language == "zh_CN" else ("(", ")")
    scope_space = "" if language == "zh_CN" else " "
    sequence_result = (
        tr("Unable to verify", language=language)
        if not report.parser_complete or report.sequence.uncertain
        else f"{report.sequence.missing_frames} {frames}"
    )
    return "\n".join(
        (
            f"{tr('Recommendation', language=language)}{separator}{tr(advice, language=language)}",
            "",
            f"{tr('Saved data (confirmed)' if report.raw_complete else 'Saved data (not confirmed)', language=language)}{separator.rstrip()}",
            f"  {tr('Duration', language=language)}{separator}{report.duration_sec:.1f} s",
            (
                f"  {tr('Raw', language=language)}{separator}"
                f"{tr('{size}, {count} file(s)', language=language, size=format_bytes(report.raw_bytes), count=len(report.raw_paths))}"
            ),
            "",
            (
                f"{tr('Automated quality check', language=language)}{scope_space}"
                f"{scope_left}{tr(parser_scope, language=language)}{scope_right}{separator.rstrip()}"
            ),
            f"  {tr('Parser coverage summary', language=language)}{separator}{_coverage_text(report, language)}",
            (
                f"  {tr('Regular BLE Log frames' if report.parser_complete else 'Frames found in parsed portion', language=language)}"
                f"{separator}{report.quality_regular_frames if report.quality_regular_frames is not None else report.regular_frames}"
            ),
            (
                f"  {tr('Possible sequence loss' if report.parser_complete else 'Full-recording sequence continuity', language=language)}"
                f"{separator}{sequence_result}"
            ),
            *_stream_content_summary(report, language, separator),
            *_startup_summary(report, language),
            "",
            *_host_text_summary(report, language, separator),
            "",
            f"{tr('Detailed report', language=language)}{separator}{report_path}",
            f"{tr('Raw data file', language=language)}{separator}{raw_path}",
            *_database_copy_lines(report, language),
            *(
                (tr("Could not update the saved report: {error}", language=language, error=report.report_update_error),)
                if report.report_update_error
                else ()
            ),
        )
    )


def _quality_scope(report: CaptureReport) -> str:
    if report.quality_start_offset:
        return "confirmed fresh interval"
    return "all saved data" if report.parser_complete else "parsed portion only"


def _startup_summary(report: CaptureReport, language: str) -> list[str]:
    if report.startup is None or not report.startup.offset_bytes:
        return []
    lines = [
        tr(
            "Opening backlog detected. Suggested raw file offset: {bytes} bytes. Original data is retained.",
            language=language,
            bytes=report.startup.offset_bytes,
        ),
        tr(
            "Quality metrics cover the confirmed fresh interval; parser coverage includes all saved data."
            if report.quality_start_offset
            else "The fresh interval could not be verified; quality metrics describe the original recording.",
            language=language,
        ),
    ]
    if report.original_sequence is not None:
        lines.append(
            tr(
                "Original stream missing sequence numbers (including opening backlog): {count}.",
                language=language,
                count=report.original_sequence.missing_frames,
            )
        )
    if report.startup.preserve_prefix:
        lines.append(tr("Use the original raw file to retain Host task bindings.", language=language))
    return lines


def format_capture_report(report: CaptureReport, language: str | None = None) -> str:
    language = language or get_language()
    cfg = report.transport_config
    separator = "：" if language == "zh_CN" else ": "

    def field(label: str, value: object) -> str:
        return f"{tr(label, language=language)}{separator}{value}"

    lines = [
        tr("BLE Log Recording Report", language=language),
        "=" * 72,
        field(
            "Verdict",
            tr(report.verdict.value, language=language),
        ),
        "",
        f"{tr('Reasons', language=language)}{separator.rstrip()}",
        *(f"  - {reason}" for reason in _localized_reasons(report, language)),
        "",
        f"{tr('Reliability', language=language)}{separator.rstrip()}",
        f"  {field('Saved raw data', tr('Confirmed' if report.raw_complete else 'Not confirmed', language=language))}",
        f"  {field('Automated quality check', tr(_quality_scope(report), language=language))}",
        f"  {field('Parser coverage summary', _coverage_text(report, language))}",
        "",
        *_host_text_summary(report, language, separator),
        "",
        f"{tr('Recording', language=language)}{separator.rstrip()}",
        f"  {field('Mode', cfg.mode.value)}",
        f"  {field('Port', cfg.port)}",
        f"  {field('Firmware protocol', _protocol_text(report, language))}",
        f"  {field('Baud rate', cfg.baudrate if cfg.mode.value == 'uart' else tr('N/A', language=language))}",
        f"  {field('Started', report.started_at.astimezone().isoformat(sep=' ', timespec='seconds'))}",
        f"  {field('Ended', report.ended_at.astimezone().isoformat(sep=' ', timespec='seconds'))}",
        f"  {field('Duration', f'{report.duration_sec:.1f} s')}",
        f"  {field('Raw bytes', format_bytes(report.raw_bytes))}",
        f"  {field('Decoded frames', report.parser_frames)}",
        f"  {field('Regular frames', report.regular_frames)}",
        f"  {field('Average receive rate', f'{format_bytes(int(report.average_bytes_per_sec))}/s')}",
        f"  {field('Peak receive rate', format_bitrate(report.peak_bits_per_sec))}",
        "",
        f"{tr('Parser coverage', language=language)}{separator.rstrip()}",
        f"  {field('Complete', tr('YES' if report.parser_complete else 'NO', language=language))}",
        f"  {field('Parsed raw bytes', report.parser_raw_bytes)}",
        f"  {field('Dropped chunks/bytes', f'{report.parse_dropped_chunks}/{report.parse_dropped_bytes}')}",
        f"  {field('Parser lag bytes', report.parser_lag_bytes)}",
        f"  {field('Trailing carried bytes', report.parser_carried_bytes)}",
        "",
        f"{tr('Experimental quality metrics', language=language)}{separator.rstrip()}",
        f"  {field('Firmware write failure rate', _format_rate(report.firmware_write_loss_rate, language))}",
        *(
            f"    {resolve_source_name(source)}: {_format_rate(rate, language)}"
            for source, rate in _firmware_source_rates(report.firmware_loss)
        ),
        f"  {field('Sequence discontinuity rate', _format_rate(report.sequence_loss_rate, language))}",
        f"  {field('Record-again threshold', '5%')}",
        "",
    ]
    if report.integrity is None:
        lines.append(tr("Recording segments", language=language) + separator.rstrip())
    if report.integrity is None and report.segments:
        lines.extend(_format_segment(segment, language) for segment in report.segments)
    elif report.integrity is None:
        lines.append(f"  {tr('No FINAL_STAT segments were decoded.', language=language)}")

    lines.extend(
        [
            "",
            f"{tr('Sequence continuity', language=language)}{separator.rstrip()}",
        ]
    )
    if report.sequence.observed_frames:
        lines.extend(_format_sequence(report.sequence, language, contract_known=report.firmware_contract_known))
    else:
        lines.append(
            f"  {tr('No frames carrying a sequence number were available for sequence verification.', language=language)}"
        )

    lines.extend(
        ("", f"{tr('Firmware buffer loss observed during this recording', language=language)}{separator.rstrip()}")
    )
    observed_loss = tuple(row for row in report.firmware_loss if row.frames or row.bytes)
    if observed_loss:
        for loss in observed_loss:
            row = tr(
                "{source}: {frames} frame(s), {bytes}",
                language=language,
                source=resolve_source_name(loss.source),
                frames=loss.frames,
                bytes=tr("Unknown", language=language) if loss.bytes is None else format_bytes(loss.bytes),
            )
            lines.append(f"  {row}")
    else:
        lines.append(f"  {tr('None observed after baseline.', language=language)}")

    if report.firmware is not None:
        lines.extend(("", tr("Firmware counters observed during recording", language=language) + ":"))
        for row in report.firmware.sources:
            counters = row.observed
            lost = (
                tr("Unknown", language=language)
                if counters.lost_bytes_cnt is None
                else format_bytes(counters.lost_bytes_cnt)
            )
            lines.append(
                f"  {resolve_source_name(row.source)}: "
                + tr(
                    "written {frames} frame(s), {bytes}; lost {lost_frames} frame(s), {lost_bytes}",
                    language=language,
                    frames=counters.written_frame_cnt,
                    bytes=format_bytes(counters.written_bytes_cnt),
                    lost_frames=counters.lost_frame_cnt,
                    lost_bytes=lost,
                )
                + ("; " + tr("partial counter coverage", language=language) if row.partial else "")
            )
        if any(row.observed.lost_bytes_cnt is None for row in report.firmware.sources):
            lines.append(
                "  " + tr("Firmware does not report lost bytes; its byte loss rate is unknown.", language=language)
            )
    if report.integrity is not None:
        lines.extend(("", tr("Checker integrity (selected ranges)", language=language) + ":"))
        lines.append(f"  {report.integrity.conclusion}")
        for interval in report.integrity.checked_intervals:
            lines.append(
                f"  epoch={interval.epoch} scope={interval.scope} status={interval.status} "
                f"SN={interval.sn_range or interval.source_sn_ranges} "
                f"expected={interval.expected_sn_count} received={interval.received_unique_sn_count} "
                f"missing={interval.missing_sn_count} duplicates={interval.duplicate_frames}"
            )
        # Preserve all excluded ranges and diagnostics in the saved report, not just the UI summary.
        lines.append(json.dumps(report.integrity.to_dict(), ensure_ascii=False, indent=2))
    lines.extend(_stream_content_section(report, language, separator))
    if report.startup is not None:
        lines.extend(("", f"{tr('Opening data selection', language=language)}{separator.rstrip()}"))
        lines.append(f"  {field('Selection result', tr(report.startup.reason, language=language))}")
        lines.extend(_startup_summary(report, language))
        if report.startup.offset_bytes:
            lines.extend(
                (
                    f"  {field('Raw suffix offset (bytes)', report.startup.offset_bytes)}",
                    f"  {field('Confirming snapshot SN', report.startup.anchor_sn)}",
                    f"  {field('Device time span (s)', f'{report.startup.device_jump_sec:.6f}')}",
                    f"  {field('Host receive span (s)', f'{report.startup.host_elapsed_sec:.6f}')}",
                )
            )

    lines.extend(("", f"{tr('Files', language=language)}{separator.rstrip()}"))
    lines.extend(f"  {field('Raw', path)}" for path in report.raw_paths)
    lines.extend(f"  {line}" for line in _database_copy_lines(report, language))
    lines.extend(f"  {field('Console log', path)}" for path in report.console_log_paths)
    lines.extend(f"  {field('HCI log', path)}" for path in report.hci_paths)
    lines.extend(f"  {field('Parser output', path)}" for path in report.parsed_paths)
    if report.product_error:
        lines.append(f"  {field('Parser output error', report.product_error)}")
    if report.hci_error:
        lines.append(f"  {field('HCI file error', report.hci_error)}")
    if report.console_log_error:
        lines.append(f"  {field('Console log error', report.console_log_error)}")
    if report.report_write_error:
        not_saved = f"{tr('NOT SAVED', language=language)} ({report.report_write_error})"
        lines.append(f"  {field('Report', not_saved)}")
    else:
        lines.append(f"  {field('Report', report.report_path)}")
    if report.errors:
        lines.extend(
            (
                "",
                f"{tr('Errors', language=language)}{separator.rstrip()}",
                *(f"  - {_localized_error(error, language)}" for error in report.errors),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _stream_content_summary(report: CaptureReport, language: str, separator: str) -> tuple[str, ...]:
    identity = report.stream_identity
    if identity is None:
        return ()
    label = tr(_STREAM_KIND_LABELS[identity.kind], language=language)
    return (f"  {tr('Stream content', language=language)}{separator}{label}",)


def _stream_content_section(report: CaptureReport, language: str, separator: str) -> list[str]:
    """Identification evidence; it describes only the bytes the parser saw, so its scope is stated."""

    identity = report.stream_identity
    if identity is None:
        return []
    evidence = identity.evidence

    def field(label: str, value: object) -> str:
        return f"  {tr(label, language=language)}{separator}{value}"

    scope = "all saved data" if report.parser_complete else "parsed portion only"
    return [
        "",
        f"{tr('Stream content', language=language)}{separator.rstrip()}",
        field("Identified as", tr(_STREAM_KIND_LABELS[identity.kind], language=language)),
        field("Evidence scope", tr(scope, language=language)),
        field("Parsed bytes outside BLE Log frames", evidence.gap_bytes),
        field("Of which after BLE Log was identified", evidence.gap_bytes_after_ble),
        field("Frames from known BLE Log sources", evidence.known_frames),
        field("Firmware identity records", evidence.identity_records),
    ]


def _status(sequence: SequenceSummary) -> str:
    if sequence.uncertain:
        return "UNCERTAIN"
    return "GAPS DETECTED" if sequence.missing_frames else "CONTINUOUS"


def _protocol_text(report: CaptureReport, language: str) -> str:
    """Firmware version and the counter contract the sequence numbers were read with."""

    model = tr("per-source counters" if report.sequence.per_source else "one shared counter", language=language)
    version = (
        tr("not identified", language=language) if report.firmware_version is None else f"v{report.firmware_version}"
    )
    if not report.firmware_contract_known:
        # The numbers below still rest on the assumed shared counter; say so where
        # the assumption is stated instead of presenting it as a fact.
        return f"{version} ({model}, {tr('counter contract unproven', language=language)})"
    return f"{version} ({model})"


def _sequence_totals(sequence: SequenceSummary, language: str) -> str:
    missing: int | str = tr("Unable to verify", language=language) if sequence.uncertain else sequence.missing_frames
    fields = (
        ("Observed", sequence.observed_frames),
        ("Missing", missing),
        ("Segments", sequence.segments),
        ("Late", sequence.late_frames),
        ("Duplicates", sequence.duplicate_frames),
        ("Wraps", sequence.wraps),
        ("Status", tr(_status(sequence), language=language)),
    )
    joiner = "，" if language == "zh_CN" else "  "
    return joiner.join(f"{tr(label, language=language)} {value}" for label, value in fields)


def _format_sequence(sequence: SequenceSummary, language: str, *, contract_known: bool = True) -> list[str]:
    """Render continuity the way the firmware's counter contract reads.

    One shared counter makes the capture a single stream, so one totals row and
    a per-source observation table describe it. Per-source
    counters make every source a stream of its own, so each source gets a row
    with its own continuity counters.
    """

    if language == "zh_CN":
        totals = f"  {tr('All sources' if sequence.per_source else 'All frames', language=language)}：{_sequence_totals(sequence, language)}"
    else:
        label = "All sources" if sequence.per_source else "All frames"
        totals = f"  {tr(label, language=language)}: {_sequence_totals(sequence, language)}"
    lines = [totals]
    if not contract_known:
        lines.append(
            f"  {tr('Counter contract unproven: continuity is accounted with one shared counter.', language=language)}"
        )
    if not sequence.per_source:
        if language == "zh_CN":
            lines.append(f"  {tr('Frames by source', language=language)}：")
        else:
            lines.extend(
                (
                    "",
                    f"  {tr('Frames by source', language=language)}:",
                    "  Source       Observed",
                    "  -----------  --------",
                )
            )
        for source in sequence.sources:
            if language == "zh_CN":
                lines.append(
                    f"  {resolve_source_name(source.source)}：{tr('Observed', language=language)} "
                    f"{source.observed_frames}"
                )
            else:
                lines.append(f"  {resolve_source_name(source.source):<11}  {source.observed_frames:>8}")
        return lines
    if language != "zh_CN":
        lines.extend(
            (
                "",
                "  Source       Observed  SN range                 Missing  Segments  Late  Duplicates  Wraps  Status",
                "  -----------  --------  -----------------------  -------  --------  ----  ----------  -----  -------------",
            )
        )
        for source in sequence.sources:
            missing = "N/A" if source.uncertain else str(source.missing_frames)
            lines.append(
                f"  {resolve_source_name(source.source):<11}  {source.observed_frames:>8}  "
                f"{f'{source.first_sn} -> {source.last_sn}':<23}  {missing:>7}  {source.segments:>8}  "
                f"{source.late_frames:>4}  {source.duplicate_frames:>10}  {source.wraps:>5}  {_status(source)}"
            )
        return lines
    for source in sequence.sources:
        missing = tr("Unable to verify", language=language) if source.uncertain else source.missing_frames
        lines.append(
            f"  {resolve_source_name(source.source)}："
            f"{tr('Observed', language=language)} {source.observed_frames}，"
            f"{tr('SN range', language=language)} {source.first_sn} -> {source.last_sn}，"
            f"{tr('Missing', language=language)} {missing}，"
            f"{tr('Segments', language=language)} {source.segments}，"
            f"{tr('Late', language=language)} {source.late_frames}，"
            f"{tr('Duplicates', language=language)} {source.duplicate_frames}，"
            f"{tr('Wraps', language=language)} {source.wraps}，"
            f"{tr('Status', language=language)} {tr(_status(source), language=language)}"
        )
    return lines


def _format_rate(rate: float | None, language: str) -> str:
    return f"{rate:.4%}" if rate is not None else tr("Not enough data", language=language)


def _format_segment(segment: CaptureSegmentSummary, language: str) -> str:
    if segment.complete:
        status = tr("complete", language=language)
    elif segment.final_stat_seen:
        status = tr("partial start", language=language)
    else:
        status = tr("partial end", language=language)

    if not segment.received_frames:
        sequence_text = tr("no data", language=language)
    elif segment.sequence_uncertain:
        sequence_text = tr("uncertain", language=language)
    elif segment.sequence_missing_frames:
        sequence_text = tr("{frames} missing", language=language, frames=segment.sequence_missing_frames)
    else:
        sequence_text = tr("continuous", language=language)

    if segment.firmware_counters is FirmwareCounterSource.FINAL_STAT:
        firmware = tr("firmware failed {frames} frame(s)", language=language, frames=segment.firmware_lost_frames)
    elif segment.firmware_counters is FirmwareCounterSource.ENH_STAT:
        firmware = tr(
            "firmware buffer loss (ENH_STAT) {frames} frame(s)", language=language, frames=segment.firmware_lost_frames
        )
    else:
        firmware = tr("no firmware counters", language=language)
    row = tr(
        "Segment {index} ({status}): received {frames} frame(s); {firmware}; SN {sequence}",
        language=language,
        index=segment.index,
        status=status,
        frames=segment.received_frames,
        firmware=firmware,
        sequence=sequence_text,
    )
    return f"  {row}"


def write_capture_report(report: CaptureReport, language: str | None = None) -> None:
    report.report_path.parent.mkdir(parents=True, exist_ok=True)
    # Readers can open the first report while the dictionary result is being saved.
    with TemporaryDirectory(prefix=".ble-report-", dir=report.report_path.parent) as directory:
        staged = Path(directory) / report.report_path.name
        with staged.open("w", encoding="utf-8", newline="\n") as file:
            file.write(format_capture_report(report, language))
            file.flush()
            os.fsync(file.fileno())
        staged.replace(report.report_path)


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

    #capture-report-verdict.check_configuration {
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

    """.replace("__BORDER_STYLE__", terminal_border_style())

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "exit_report", "Exit"),
        Binding("Q", "exit_report", show=False),
        Binding("ctrl+c", "exit_report", show=False, priority=True),
    ]

    def __init__(self, report: CaptureReport) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        language = get_language()
        separator = "：" if language == "zh_CN" else ": "
        with Vertical(id="capture-report-container"):
            yield Static(
                f"{tr('Verdict', language=language)}{separator}{tr(self.report.verdict.value, language=language)}",
                id="capture-report-verdict",
                classes=self.report.verdict.name.lower(),
            )
            with VerticalScroll(id="capture-report-scroll"):
                yield Static(format_capture_summary(self.report), markup=False, id="report-summary")
            with Center(), Horizontal(id="capture-report-actions"):
                yield Button("Record Again", variant="primary", id="record-again")
                yield Button("Exit", id="exit-report")

    def update_report(self, report: CaptureReport) -> None:
        self.report = report
        self.query_one("#report-summary", Static).update(format_capture_summary(report))

    @on(Button.Pressed, "#record-again")
    def record_again(self) -> None:
        self.dismiss("again")

    @on(Button.Pressed, "#exit-report")
    def exit_report(self) -> None:
        self.dismiss("exit")

    def action_exit_report(self) -> None:
        self.dismiss("exit")
