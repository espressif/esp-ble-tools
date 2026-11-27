# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Publish a recording's report immediately and archive its dictionary afterwards."""

from dataclasses import replace
from pathlib import Path
from threading import Thread

from src.backend.io.database import save_database_copy
from src.backend.models import CaptureReport
from src.frontend.capture_report import write_capture_report
from src.i18n import get_language


class RecordingFiles:
    """Each recording owns its files, even after the user starts another one."""

    def __init__(self, report: CaptureReport, recording: Path, database: Path | None) -> None:
        self._language = get_language()
        self.report = self._save(replace(report, pending_database=database))
        if database is not None:
            try:
                Thread(target=self._archive, args=(report, recording, database), daemon=True).start()
            except RuntimeError as error:
                self._update(replace(report, database_copy_error=str(error)))

    def _archive(self, report: CaptureReport, recording: Path, database: Path) -> None:
        try:
            report = replace(report, database_copy=save_database_copy(database, recording))
        except OSError as error:
            report = replace(report, database_copy_error=str(error))
        self._update(report)

    def _update(self, report: CaptureReport) -> None:
        latest = self._save(report)
        if latest.report_write_error and not self.report.report_write_error:
            # The first report is still on disk because replacement is atomic.
            latest = replace(report, report_update_error=latest.report_write_error)
        self.report = latest

    def _save(self, report: CaptureReport) -> CaptureReport:
        try:
            write_capture_report(report, self._language)
        except OSError as error:
            report = replace(report, report_write_error=str(error))
        return report
