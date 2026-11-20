# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Normalize live HCI and legacy controller HCI to the same display and export."""

from ble_log_frame_decoder.analysis.hci import describe_hci
from ble_log_frame_decoder.analysis.ll_hci import describe_ll_hci

from src.backend.analysis.parser_events import HciLogEvent


def hci_event(payload: bytes, timestamp_us: int | None, received_at_ms: int) -> HciLogEvent:
    packet = describe_hci(payload, timestamp_us)
    return HciLogEvent(packet.text, received_at_ms, packet.btsnoop, packet.reason)


def ll_hci_event(payload: bytes, chip_name: str | None, received_at_ms: int) -> HciLogEvent:
    packet = describe_ll_hci(payload, chip_name)
    return HciLogEvent(packet.text, received_at_ms, packet.btsnoop, packet.reason)
