# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Shared contracts for BLE Log Console backend and frontend layers.

This module is intentionally kept as a single contract surface for now. The
sections below mirror the runtime pipeline layers so the data ownership is easy
to read before we split the contracts into smaller modules.
"""

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path
import struct
from typing import TypedDict

from textual.message import Message


# --- Common formatting helpers ---


def format_bytes(cnt: int) -> str:
    """Format byte count as human-readable string (B / KB / MB)."""
    if cnt < 1024:
        return f'{cnt} B'
    if cnt < 1024 * 1024:
        return f'{cnt / 1024:.1f} KB'
    return f'{cnt / 1024 / 1024:.2f} MB'


def format_throughput(bytes_per_sec: float) -> str:
    """Format throughput as human-readable string with auto KB/s or MB/s switching."""
    kb_per_sec = bytes_per_sec / 1024
    if kb_per_sec < 1024:
        return f'{kb_per_sec:.1f} KB/s'
    return f'{kb_per_sec / 1024:.2f} MB/s'


def format_bitrate(bits_per_sec: float) -> str:
    """Format bit rate as human-readable string with SI units."""
    if bits_per_sec < 1000:
        return f'{bits_per_sec:.0f} bps'
    kbps = bits_per_sec / 1000
    if kbps < 1000:
        return f'{kbps:.1f} Kbps'
    return f'{kbps / 1000:.2f} Mbps'


# --- Parser/frame contract ---


FRAME_HEADER_SIZE = 6  # 2B payload_len + 4B frame_meta
FRAME_TAIL_SIZE = 4  # 4B checksum
FRAME_OVERHEAD = FRAME_HEADER_SIZE + FRAME_TAIL_SIZE  # 10
MAX_FRAME_SIZE = 2048  # Max payload_len sanity check
MAX_REMAINDER_SIZE = 131072  # 128KB bounded buffer
HEADER_FMT = '<HI'  # payload_len (uint16), frame_meta (uint32)
CHECKSUM_FMT = '<I'  # checksum (uint32)
HEADER_STRUCT = struct.Struct(HEADER_FMT)
CHECKSUM_STRUCT = struct.Struct(CHECKSUM_FMT)


class SyncState(str, Enum):
    SEARCHING = 'SEARCHING'
    CONFIRMING_SYNC = 'CONFIRMING'
    SYNCED = 'SYNCED'
    CONFIRMING_LOSS = 'CONFIRMING_LOSS'


class ChecksumAlgorithm(str, Enum):
    XOR = 'XOR'
    SUM = 'Sum'


class ChecksumScope(str, Enum):
    FULL = 'Header+Payload'
    HEADER_ONLY = 'Header'


@dataclass(slots=True)
class ChecksumMode:
    algorithm: ChecksumAlgorithm
    scope: ChecksumScope


class BleLogSource(int, Enum):
    INTERNAL = 0
    CUSTOM = 1
    LL_TASK = 2
    LL_HCI = 3
    LL_ISR = 4
    HOST = 5
    HCI = 6
    ENCODE = 7
    REDIR = 8  # BLE_LOG_SRC_REDIR in firmware ble_log.h (UART PORT 0 only)


# Source code values may be known BleLogSource members or unknown firmware codes.
SourceCode = int


class InternalSource(int, Enum):
    INIT_DONE = 0
    TS = 1
    ENH_STAT = 2
    INFO = 3
    FLUSH = 4
    BUF_UTIL = 5
    FINAL_STAT = 6

@dataclass(slots=True)
class ParsedFrame:
    source_code: int
    frame_sn: int
    payload: bytes  # includes os_ts prefix for ble_log_write_hex() frames
    os_ts_ms: int  # extracted from first 4 bytes of payload; only valid when has_os_ts(source_code) is True


class InfoResult(TypedDict):
    int_src: InternalSource
    version: int
    os_ts_ms: int


class EnhStatResult(TypedDict):
    int_src: InternalSource
    src_code: int
    written_frame_cnt: int
    lost_frame_cnt: int
    written_bytes_cnt: int
    lost_bytes_cnt: int
    os_ts_ms: int


class BufUtilResult(TypedDict):
    int_src: InternalSource
    lbm_id: int
    pool: int
    index: int
    trans_cnt: int
    inflight_peak: int
    os_ts_ms: int


InternalDecoderResult = InfoResult | EnhStatResult | BufUtilResult


# Sources written via ble_log_write_hex_ll() or stream_write have no 4-byte os_ts prefix.
_NO_OS_TS_SOURCES: frozenset[int] = frozenset(
    {BleLogSource.LL_TASK, BleLogSource.LL_HCI, BleLogSource.LL_ISR, BleLogSource.REDIR}
)
_LL_SOURCES: frozenset[int] = frozenset({BleLogSource.LL_TASK, BleLogSource.LL_HCI, BleLogSource.LL_ISR})

LL_TS_OFFSET = 2  # lc_ts starts at payload[2:6]
LL_TS_SIZE = 4


def has_os_ts(source_code: int) -> bool:
    """Return True if frames from this source carry a valid os_ts prefix."""
    return source_code not in _NO_OS_TS_SOURCES


def is_ll_source(source_code: int) -> bool:
    """Return True if this is a Link Layer source with lc_ts timestamp."""
    return source_code in _LL_SOURCES


def resolve_source_name(src_code: int) -> str:
    """Resolve source code to BleLogSource name, with fallback for unknown codes."""
    try:
        return str(BleLogSource(src_code).name)
    except ValueError:
        return f'SRC_{src_code}'


# --- Transport contract ---


class TransportMode(str, Enum):
    UART = 'uart'
    SPI_USB_BRIDGE = 'spi_usb_bridge'


@dataclass(frozen=True)
class TransportConfig:
    """Final transport configuration created when the user connects."""

    mode: TransportMode
    label: str
    port: str
    baudrate: int = 3_000_000


@dataclass(frozen=True)
class TransportBitrate:
    """Transport-specific conversion between payload bytes and wire bits."""

    bits_per_payload_byte: float = 8.0
    wire_bits_per_sec: float | None = None

    def payload_bytes_to_wire_bits(self, byte_count: int | float) -> float:
        return byte_count * self.bits_per_payload_byte

    @property
    def max_payload_bytes_per_sec(self) -> float | None:
        if self.wire_bits_per_sec is None or self.bits_per_payload_byte <= 0:
            return None
        return self.wire_bits_per_sec / self.bits_per_payload_byte


@dataclass(slots=True)
class TransportSnapshot:
    """Snapshot of transport-layer metrics for the current stats interval."""

    rx_bytes: int = 0
    rx_frames: int = 0
    rx_bits_per_sec: float = 0.0
    max_rx_bits_per_sec: float = 0.0
    fps: float = 0.0


# --- Stats/aggregator contract ---


class BufUtilPool(int, Enum):
    COMMON_TASK = 0
    COMMON_ISR = 1
    LL = 2
    REDIR = 3


class LossType(str, Enum):
    BUFFER = 'buffer'  # firmware buffer full, frame dropped
    TRANSPORT = 'transport'  # UART/link loss


@dataclass(frozen=True)
class BufUtilEntry:
    """Single LBM buffer utilization snapshot."""

    lbm_id: int
    pool: int
    index: int
    trans_cnt: int
    inflight_peak: int


@dataclass(slots=True)
class LossSnapshot:
    """Snapshot of firmware-reported cumulative loss."""

    total_frames: int = 0
    total_bytes: int = 0


@dataclass(frozen=True)
class FrameByteCount:
    """A (frames, bytes) pair."""

    frames: int
    bytes: int


@dataclass(frozen=True)
class ThroughputInfo:
    """Rate metrics (frames/s and wire bits/s)."""

    throughput_fps: float  # current console receive rate (rolling 1s window)
    throughput_bits_per_sec: float  # current console receive rate converted to wire bits
    peak_write_frames: int  # raw frame count in densest burst window
    peak_write_bits_per_sec: float  # densest burst converted to wire bit rate
    peak_window_ms: int  # burst window size in ms


@dataclass(frozen=True)
class FunnelSnapshot:
    """Per-source three-layer funnel snapshot."""

    source: int  # SourceCode
    produced: FrameByteCount  # Layer 0: written + buffer_loss
    written: FrameByteCount  # Layer 1: from ENH_STAT
    received: FrameByteCount  # Layer 2: console-side counting
    buffer_loss: FrameByteCount  # from ENH_STAT lost counts
    transport_loss: FrameByteCount  # max(0, written - received)
    throughput: ThroughputInfo


@dataclass(slots=True)
class FrameStats:
    """Periodic stats snapshot with metrics grouped by dimension."""

    transport: TransportSnapshot = field(default_factory=TransportSnapshot)
    loss: LossSnapshot = field(default_factory=LossSnapshot)
    per_source_rx_bytes: dict[SourceCode, int] | None = None


_LBM_NAMES: dict[tuple[int, int], str] = {
    (0, 0): 'spin',
    (1, 0): 'spin',
    (2, 0): 'll_task',
    (2, 1): 'll_hci',
    (3, 0): 'redir',
}


def resolve_pool_name(pool: int) -> str:
    """Resolve pool code to BufUtilPool name, with fallback for unknown codes."""
    try:
        return BufUtilPool(pool).name
    except ValueError:
        return f'POOL_{pool}'


def resolve_lbm_name(pool: int, index: int) -> str:
    """Resolve pool + index to human-readable LBM name."""
    key = (pool, index)
    if key in _LBM_NAMES:
        return _LBM_NAMES[key]
    if pool in (0, 1) and index >= 1:
        return f'atomic[{index - 1}]'
    return f'lbm_{pool}_{index}'


# --- UI/control contract ---


@dataclass(slots=True)
class LaunchConfig:
    """Configuration returned by the Launch Screen."""

    transport_config: TransportConfig
    log_dir: Path


class StatsUpdated(Message):
    def __init__(
        self,
        stats: FrameStats,
        funnel_snapshots: list[FunnelSnapshot] | None = None,
        buf_util_snapshots: list[BufUtilEntry] | None = None,
    ) -> None:
        super().__init__()
        self.stats = stats
        self.funnel_snapshots = funnel_snapshots or []
        self.buf_util_snapshots = buf_util_snapshots or []


class InternalFrameDecoded(Message):
    def __init__(self, int_src: InternalSource, payload: InternalDecoderResult) -> None:
        super().__init__()
        self.int_src = int_src
        self.payload = payload


class LogLine(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class UserNotice(Message):
    def __init__(self, text: str, level: str = 'info') -> None:
        super().__init__()
        self.text = text
        self.level = level


class FrameLossDetected(Message):
    def __init__(
        self,
        source_name: str,
        loss_type: LossType,
        lost_frames: int,
        lost_bytes: int,
        sn_range: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self.source_name = source_name
        self.loss_type = loss_type
        self.lost_frames = lost_frames
        self.lost_bytes = lost_bytes
        self.sn_range = sn_range


class BackendStopped(Message):
    def __init__(self, reason: str = '') -> None:
        super().__init__()
        self.reason = reason
