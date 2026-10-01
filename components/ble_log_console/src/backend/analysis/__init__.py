# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""BLE log analysis stage: parser events, parser, aggregator, and worker."""

from src.backend.analysis.aggregator import (
    AggregatorSnapshot,
    AggregatorUpdate,
    CaptureAggregator,
    InternalFrameUpdate,
    frame_size_from_payload,
)
from src.backend.analysis.parser import DEFAULT_CHECKSUM_MODE, BleLogParser, parse_ble_log_chunk
from src.backend.analysis.parser_events import (
    BleLogEvent,
    EnhStatEvent,
    FinalStatEvent,
    FrameEvent,
    InternalEvent,
    ParseBatch,
    ParseChunkResult,
    ParseSummary,
    ReceivedChunk,
    RedirEvent,
)
from src.backend.analysis.worker import (
    AggregatorProcessEvent,
    ParserStatus,
    drain_aggregator_events,
    drain_parser_events,
    run_aggregator_loop,
    run_analysis_loop,
    run_analysis_process,
    run_parser_loop,
)

__all__ = [
    "DEFAULT_CHECKSUM_MODE",
    "AggregatorProcessEvent",
    "AggregatorSnapshot",
    "AggregatorUpdate",
    "BleLogEvent",
    "BleLogParser",
    "CaptureAggregator",
    "EnhStatEvent",
    "FinalStatEvent",
    "FrameEvent",
    "InternalEvent",
    "InternalFrameUpdate",
    "ParseBatch",
    "ParseChunkResult",
    "ParseSummary",
    "ParserStatus",
    "ReceivedChunk",
    "RedirEvent",
    "drain_aggregator_events",
    "drain_parser_events",
    "frame_size_from_payload",
    "parse_ble_log_chunk",
    "run_aggregator_loop",
    "run_analysis_loop",
    "run_analysis_process",
    "run_parser_loop",
]
