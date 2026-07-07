# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Parser event aggregation stage."""

from src.backend.aggregator.event_aggregator import AggregatorSnapshot
from src.backend.aggregator.event_aggregator import AggregatorUpdate
from src.backend.aggregator.event_aggregator import CaptureAggregator
from src.backend.aggregator.event_aggregator import FrameLossUpdate
from src.backend.aggregator.event_aggregator import InternalFrameUpdate
from src.backend.aggregator.event_aggregator import frame_size_from_payload
from src.backend.aggregator.worker import AggregatorProcessEvent
from src.backend.aggregator.worker import drain_aggregator_events
from src.backend.aggregator.worker import run_aggregator_loop
from src.backend.aggregator.worker import run_aggregator_process

__all__ = [
    'AggregatorProcessEvent',
    'AggregatorSnapshot',
    'AggregatorUpdate',
    'CaptureAggregator',
    'FrameLossUpdate',
    'InternalFrameUpdate',
    'drain_aggregator_events',
    'frame_size_from_payload',
    'run_aggregator_loop',
    'run_aggregator_process',
]
