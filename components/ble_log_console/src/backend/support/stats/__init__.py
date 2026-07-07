# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Stats package -- re-exports for backward-compatible imports."""

from src.backend.support.stats.accumulator import StatsAccumulator
from src.backend.support.stats.firmware_loss import FirmwareLossTracker
from src.backend.support.stats.firmware_written import FirmwareWrittenTracker
from src.backend.support.stats.peak_burst import WRITE_RATE_WINDOW_MS
from src.backend.support.stats.peak_burst import PeakBurstTracker
from src.backend.support.stats.sn_gap import REORDER_WINDOW
from src.backend.support.stats.sn_gap import SN_MAX
from src.backend.support.stats.sn_gap import SNGapTracker
from src.backend.support.stats.traffic_spike import TRAFFIC_ALERT_COOLDOWN_SEC
from src.backend.support.stats.traffic_spike import TRAFFIC_THRESHOLD_PCT
from src.backend.support.stats.traffic_spike import TRAFFIC_WINDOW_SEC
from src.backend.support.stats.traffic_spike import TrafficSpikeDetector
from src.backend.support.stats.traffic_spike import TrafficSpikeResult
from src.backend.support.stats.transport import TransportMetrics

__all__ = [
    'FirmwareLossTracker',
    'FirmwareWrittenTracker',
    'PeakBurstTracker',
    'REORDER_WINDOW',
    'SN_MAX',
    'SNGapTracker',
    'StatsAccumulator',
    'TRAFFIC_ALERT_COOLDOWN_SEC',
    'TRAFFIC_THRESHOLD_PCT',
    'TRAFFIC_WINDOW_SEC',
    'TrafficSpikeDetector',
    'TrafficSpikeResult',
    'TransportMetrics',
    'WRITE_RATE_WINDOW_MS',
]
