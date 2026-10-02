# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from src.app import BLELogApp
from src.backend.analysis.aggregator import CaptureAggregator
from src.backend.analysis.parser import BleLogParser
from src.backend.models import BleLogSource
from src.frontend.capture_events import CaptureEventPresenter
from src.frontend.status_panel import StatusPanel

from tests.helpers import build_frame, snapshot_payload, xor_checksum

scenarios("features/status_bar.feature")

# The scenario names its chip by the name a person reads; these tables are the wire encoding.
_CHIP_MODELS = {"ESP32C6": 13, "ESP32S3": 9}
_CHIP_REVISIONS = {"v3.02": 302, "v1.00": 100}
_CORRUPT_VERSION_BLOCK = b"\x00" * 58


@pytest.fixture
def console(tmp_path: Path) -> Iterator[SimpleNamespace]:
    """A mounted console with the transport stubbed out, so no device is opened.

    One `asyncio.Runner` owns the whole scenario: its tasks share one context, which is
    what `App.run_test()` needs to enter and leave its context variables from two calls.
    """
    runner = asyncio.Runner()
    with patch.object(BLELogApp, "_start_capture", lambda self: None):
        app = BLELogApp(port="bdd-stub", log_dir=tmp_path)
        run = app.run_test()
        pilot = runner.run(run.__aenter__())
    try:
        yield SimpleNamespace(
            app=app, runner=runner, pilot=pilot, presenter=CaptureEventPresenter(tmp_path / "capture.log")
        )
    finally:
        try:
            runner.run(run.__aexit__(None, None, None))
        finally:
            runner.close()


def _deliver(console: SimpleNamespace, payload: bytes) -> None:
    """Feed one frame through the console's own parser, aggregator and presenter."""
    frame = build_frame(payload, BleLogSource.INTERNAL, 1, xor_checksum)
    update = CaptureAggregator().consume_parser_batch(BleLogParser().feed(frame))
    messages = console.presenter.handle_event(update)
    assert messages, "the frame did not reach the console UI"
    for message in messages:
        console.app.post_message(message)
    console.runner.run(console.pilot.pause())
    if console.app._exception is not None:
        # Report a handler crash against the step that caused it, not fixture teardown.
        raise console.app._exception


async def _read_status_bar(console: SimpleNamespace) -> tuple[str, str]:
    panel = console.app.query_one(StatusPanel)
    return panel.chip_label, panel.render().plain


def _observe(console: SimpleNamespace) -> tuple[str, str]:
    return console.runner.run(_read_status_bar(console))


@given("一个已挂载并连接的 BLE Log Console", target_fixture="console")
def running_console(console: SimpleNamespace) -> SimpleNamespace:
    return console


def _deliver_snapshot(console: SimpleNamespace, chip: str, revision: str) -> None:
    _deliver(console, snapshot_payload(0x1234, _CHIP_MODELS[chip], _CHIP_REVISIONS[revision]))


@given(parsers.parse('控制台已从一帧 SNAPSHOT 显示 chip "{chip}"、revision "{revision}"'))
def console_already_shows_chip(console: SimpleNamespace, chip: str, revision: str) -> None:
    _deliver_snapshot(console, chip, revision)
    assert _observe(console)[0], "precondition: the console never showed a chip"


@when(parsers.parse('控制台从设备收到一帧 SNAPSHOT，其中 chip 为 "{chip}"、revision 为 "{revision}"'))
def receive_snapshot(console: SimpleNamespace, chip: str, revision: str) -> None:
    _deliver_snapshot(console, chip, revision)


@when("控制台从设备收到一帧版本信息块无法解读的 SNAPSHOT")
def receive_snapshot_with_unreadable_version_block(console: SimpleNamespace) -> None:
    _deliver(console, snapshot_payload(version_block=_CORRUPT_VERSION_BLOCK))


@then(parsers.parse('状态栏显示 "{label}"'))
def status_bar_shows(console: SimpleNamespace, label: str) -> None:
    chip_label, status_line = _observe(console)
    assert chip_label == label
    assert label in status_line


@then("状态栏不显示 chip")
def status_bar_shows_no_chip(console: SimpleNamespace) -> None:
    chip_label, status_line = _observe(console)
    assert chip_label == ""
    assert "Status: CONNECTED" in status_line


class _StubCaptureSession:
    """A capture session that starts nothing: this scenario observes the UI path only."""

    def __init__(self, config: object, output_path: object, debug: bool = False) -> None:
        self.finished = False
        self.report = None
        self.saved_capture_path: Path | None = None
        self.saved_capture_paths: list[Path] = []
        self.saved_console_log_path: Path | None = None
        self.saved_console_log_paths: list[Path] = []

    def start(self) -> tuple[()]:
        return ()

    def poll(self) -> tuple[()]:
        """The app's poll timer calls this while the session is installed."""

        return ()


@when("控制台开始新的录制")
def start_a_new_recording(console: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.app.CaptureSession", _StubCaptureSession)
    console.app._start_capture()
    # Tick the session once through the path the app's poll timer uses, so the
    # stub stands in for the whole contract rather than only for start().
    console.app._poll_pipeline()
