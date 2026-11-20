# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Normalize live HCI and legacy controller HCI to the same display and export."""

import struct

from ble_log_frame_decoder.analysis.hci import encode_hci_payload

from src.backend.analysis.parser_events import HciLogEvent

# Same controller IDs as Log Parser V2's ll_hci_log adapter.
_LL_TYPES = {0: 1, 1: 2, 2: 0x84, 3: 0x82, 9: 0x84}


def hci_event(payload: bytes, timestamp_us: int | None, received_at_ms: int) -> HciLogEvent:
    if len(payload) < 6 or payload[4] & 0x7F not in (1, 2, 3, 4, 5):
        return HciLogEvent(f"HCI undecodable: {payload.hex(' ')}", received_at_ms, reason="invalid_payload")
    packet_type = payload[4] & 0x7F
    incoming = packet_type == 4 or (packet_type != 1 and bool(payload[4] & 0x80))
    clock = (
        f"{timestamp_us} us"
        if timestamp_us is not None
        else f"raw clock={int.from_bytes(payload[:4], 'little')} (unit unknown)"
    )
    text = f"{clock} {'RX' if incoming else 'TX'} HCI type={packet_type} {payload[5:].hex(' ')}"
    return HciLogEvent(
        text,
        received_at_ms,
        encode_hci_payload(payload, timestamp_us) if timestamp_us is not None else b"",
        "unknown_clock_unit" if timestamp_us is None else "",
    )


def ll_hci_event(payload: bytes, chip_name: str | None, received_at_ms: int) -> HciLogEvent:
    def invalid(reason):
        return HciLogEvent(f"HCI undecodable: {payload.hex(' ')}", received_at_ms, reason=reason)

    if len(payload) <= 10:
        return invalid("short_payload")
    length, timestamp, identifier = struct.unpack_from("<HII", payload)
    if length < len(payload):
        return invalid("invalid_length")
    log_id, module = identifier & 0xFFFF, (identifier >> 16) & 0x1F
    if chip_name == "ESP32C2":
        module, log_id = (log_id >> 12) & 0xF, log_id & 0xFFF
        timestamp = timestamp * 1_000_000 // 32768
        if module != 11:
            return invalid("unknown_module")
    elif module != 10:
        return invalid("unknown_module_or_chip")
    if log_id not in _LL_TYPES:
        return invalid("unknown_hci_id")
    # Timestamp is passed separately; C2's converted clock may exceed uint32.
    event = hci_event(b"\x00" * 4 + bytes([_LL_TYPES[log_id]]) + payload[10:], timestamp, received_at_ms)
    if length != len(payload):
        event = event._replace(
            btsnoop=struct.pack("!I", length - 10 + 1) + event.btsnoop[4:], reason="truncated_packet"
        )
    return event
