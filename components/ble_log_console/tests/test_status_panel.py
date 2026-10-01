# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import struct

from ble_log_frame_decoder import BleLogVersionInfo, Snapshot
from src.app import _chip_label
from src.backend.models import InternalFrameDecoded, InternalLogInfo, InternalSource
from src.frontend.status_panel import StatusPanel
from textual.app import App, ComposeResult

_VERSION_INFO_BLOCK = struct.Struct("<BB12s10s10s10s10sHH")


def _version_info_block(chip_model: int, chip_revision: int) -> bytes:
    return _VERSION_INFO_BLOCK.pack(
        7,  # VERSION_INFO subtype, embedded without the leading os_ts
        8,
        b"a" * 12,
        b"b" * 10,
        b"c" * 10,
        b"d" * 10,
        b"e" * 10,
        chip_model,
        chip_revision,
    )


def test_chip_label_from_version_info_record() -> None:
    info = BleLogVersionInfo(
        log_os_ts=0,
        version=8,
        idf_commit="a",
        controller_commit="b",
        btdm_common_commit="c",
        mesh_commit="d",
        audio_commit="e",
        chip_model=13,
        chip_revision=302,
    )

    assert _chip_label(InternalFrameDecoded(InternalSource.VERSION_INFO, info)) == "ESP32C6 v3.02"


def test_chip_label_from_snapshot_record() -> None:
    snapshot = Snapshot(
        timestamp=1234,
        reason_flags=1,
        anchor_count=0,
        version_info=_version_info_block(9, 100),
        io_level=0,
        lc_ts=0,
        esp_ts=0,
        os_ts=0,
        pool=(0, 0, 0, 0),
        stats=(),
    )

    assert _chip_label(InternalFrameDecoded(InternalSource.SNAPSHOT, snapshot)) == "ESP32S3 v1.00"


def test_chip_label_ignores_other_internal_records() -> None:
    info = InternalLogInfo(log_os_ts=1, source=InternalSource.INFO, version=4)

    assert _chip_label(InternalFrameDecoded(InternalSource.INFO, info)) == ""


def test_chip_label_ignores_snapshot_with_corrupt_embedded_version_block() -> None:
    snapshot = Snapshot(
        timestamp=1234,
        reason_flags=1,
        anchor_count=0,
        version_info=b"\x00" * 58,
        io_level=0,
        lc_ts=0,
        esp_ts=0,
        os_ts=0,
        pool=(0, 0, 0, 0),
        stats=(),
    )

    assert _chip_label(InternalFrameDecoded(InternalSource.SNAPSHOT, snapshot)) == ""


def test_status_panel_renders_chip_label_when_known() -> None:
    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield StatusPanel()

    async def run() -> None:
        async with Host().run_test() as pilot:
            panel = pilot.app.query_one(StatusPanel)
            assert "ESP32C6" not in panel.render().plain

            panel.chip_label = "ESP32C6 v3.02"
            await pilot.pause()

            assert "ESP32C6 v3.02" in panel.render().plain

    asyncio.run(run())
