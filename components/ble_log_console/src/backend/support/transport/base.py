# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Common transport abstractions for BLE log byte streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.models import TransportBitrate


@dataclass(frozen=True)
class TransportStatus:
    """Minimal reader status surfaced to capture controllers."""

    mode: TransportMode
    display_name: str
    opened: bool
    healthy: bool
    rx_bytes: int = 0
    rx_chunks: int = 0
    last_error: str | None = None


class TransportReader(Protocol):
    """Openable reader for raw BLE log bytes.

    A reader owns the device handle. In the process-based capture pipeline it
    must be created and opened inside ReaderProcess, not passed across
    process boundaries.
    """

    @property
    def display_name(self) -> str:
        ...

    @property
    def block_size(self) -> int:
        ...

    @property
    def bitrate_config(self) -> TransportBitrate:
        ...

    def open(self) -> None:
        ...

    def read(self, size: int | None = None) -> bytes:
        ...

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        ...

    def close(self) -> None:
        ...

    def reset_target(self) -> bool:
        ...

    def status(self) -> TransportStatus:
        ...

class TransportProvider(Protocol):
    """Factory/enumerator for one transport backend."""

    @property
    def label(self) -> str:
        ...

    @property
    def mode(self) -> TransportMode:
        ...

    def list_options(self) -> list[tuple[str, str]]:
        ...

    def create_reader(self, config: TransportConfig) -> TransportReader:
        ...
