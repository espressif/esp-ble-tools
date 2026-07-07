# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""ParserProcess entrypoints for capture pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty
from typing import Any

from src.backend.parser.ble_log_parser import BleLogParser
from src.backend.parser.events import ParseBatch
from src.backend.parser.events import ParseSummary


@dataclass(frozen=True)
class ParserStatus:
    """Process-level parser status or error."""

    kind: str
    message: str = ''


def _put_event(event_queue: Any, event: ParseBatch | ParseSummary | ParserStatus) -> None:
    if event_queue is not None:
        event_queue.put(event)


def run_parser_loop(parse_queue: Any, event_queue: Any) -> None:
    """Parse raw chunks from parse_queue until a None sentinel is received."""

    parser = BleLogParser()
    try:
        while True:
            item = parse_queue.get()
            if item is None:
                break
            if not item:
                continue
            _put_event(event_queue, parser.feed(item))
        _put_event(event_queue, parser.finalize())
    except Exception as e:
        _put_event(event_queue, ParserStatus(kind='error', message=str(e)))


def run_parser_process(parse_queue: Any, event_queue: Any) -> None:
    """Process entrypoint for BLE log parser."""

    run_parser_loop(parse_queue, event_queue)


def drain_parser_events(event_queue: Any) -> list[ParseBatch | ParseSummary | ParserStatus]:
    """Drain currently available parser events."""

    events: list[ParseBatch | ParseSummary | ParserStatus] = []
    while True:
        try:
            events.append(event_queue.get_nowait())
        except Empty:
            return events
