# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Common transport abstractions for BLE log byte streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from src.backend.models import TransportBitrate, TransportConfig, TransportMode


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


class PortIssueKind(str, Enum):
    """Why an enumerated device cannot be opened.

    The kind carries the decision; the wording shown to the user belongs to
    the frontend, which can translate it.
    """

    PERMISSION_DENIED = "permission_denied"
    DEVICE_ERROR = "device_error"


@dataclass(frozen=True)
class PortIssue:
    """A device that enumerated but cannot be used, and the reason it cannot."""

    kind: PortIssueKind
    port: str
    label: str
    detail: str = ""


@dataclass
class PortScan:
    """One enumeration pass over a transport backend's ports.

    ``options`` is what the user can select; ``issues`` explains the devices
    that are present but did not make it into ``options``, so an empty list is
    never silent. Both are empty when no device of that backend is attached.
    """

    options: list[tuple[str, str]] = field(default_factory=list)
    issues: list[PortIssue] = field(default_factory=list)


class TransportReader(Protocol):
    """Openable reader for raw BLE log bytes.

    A reader owns the device handle. In the process-based capture pipeline it
    must be created and opened inside ReaderProcess, not passed across
    process boundaries.
    """

    @property
    def display_name(self) -> str: ...

    @property
    def block_size(self) -> int: ...

    @property
    def bitrate_config(self) -> TransportBitrate: ...

    def open(self) -> None: ...

    def read(self, size: int | None = None) -> bytes: ...

    def drain(self, max_rounds: int = 10) -> list[bytes]: ...

    def close(self) -> None: ...

    def reset_target(self) -> bool: ...

    def status(self) -> TransportStatus: ...


class TransportProvider(Protocol):
    """Factory/enumerator for one transport backend."""

    @property
    def label(self) -> str: ...

    @property
    def mode(self) -> TransportMode: ...

    def scan_ports(self) -> PortScan: ...

    def create_reader(self, config: TransportConfig) -> TransportReader: ...
