# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Common transport abstractions for BLE log byte streams."""

from __future__ import annotations

from src.backend.models import TransportConfig
from src.backend.models import TransportMode
from src.backend.models import TransportBitrate
from typing import Protocol

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

    def open(self, config: TransportConfig) -> 'LogTransport':
        ...



class LogTransport(Protocol):
    """Readable source of raw BLE log bytes."""

    @property
    def display_name(self) -> str:
        ...

    @property
    def block_size(self) -> int:
        ...

    @property
    def bitrate_config(self) -> TransportBitrate:
        ...

    def read(self, size: int | None = None) -> bytes:
        ...

    def close(self) -> None:
        ...

    def reset_target(self) -> bool:
        ...
