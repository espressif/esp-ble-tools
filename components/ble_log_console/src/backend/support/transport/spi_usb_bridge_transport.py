# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""USB-SPI bridge transport for BLE log byte streams."""

from __future__ import annotations

import serial
import serial.tools.list_ports

from src.backend.models import TransportBitrate, TransportConfig
from src.backend.support.transport.base import PortScan, TransportMode, TransportProvider
from src.backend.support.transport.serial_reader import SerialReader, serial_open_hint, serial_port_issue

VENDOR_ID = 0x303A
PRODUCT_ID = 0x4001
DEVICE_DESCRIPTION = "SPI-BRIDGE"

SPI_BITS_PER_BYTE = 8
SPI_USB_RX_BUFFER_SIZE = 20 * 1024
SPI_WIRE_BPS = 20_000_000
USB_TIMEOUT_MS = 100
CDC_ENDPOINT_PREFIX = "cdc:"


def _is_spi_usb_bridge_port(port: object) -> bool:
    vid = getattr(port, "vid", None)
    pid = getattr(port, "pid", None)
    if vid == VENDOR_ID and pid == PRODUCT_ID:
        return True

    text_parts = (
        getattr(port, "description", ""),
        getattr(port, "hwid", ""),
        getattr(port, "manufacturer", ""),
        getattr(port, "product", ""),
        getattr(port, "interface", ""),
    )
    text = " ".join(str(part) for part in text_parts if part).lower()
    return "303a" in text and "4001" in text


def list_spi_usb_bridge_cdc_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for port in serial.tools.list_ports.comports():
        if not _is_spi_usb_bridge_port(port):
            continue
        device = str(port.device)
        label = f"{DEVICE_DESCRIPTION} CDC {device}"
        options.append((label, f"{CDC_ENDPOINT_PREFIX}{device}"))
    return options


def scan_spi_usb_bridge_ports() -> PortScan:
    scan = PortScan()
    for label, key in list_spi_usb_bridge_cdc_options():
        issue = serial_port_issue(_cdc_port_from_key(key), "SPI Bridge")
        if issue is None:
            scan.options.append((label, key))
        else:
            scan.issues.append(issue)
    return scan


class SpiUsbBridgeCdcTransport(SerialReader):
    mode = TransportMode.SPI_USB_BRIDGE
    block_size = SPI_USB_RX_BUFFER_SIZE
    timeout = USB_TIMEOUT_MS / 1000
    open_exclusive = True
    not_open_message = "USB-SPI bridge CDC transport is not open"

    @property
    def display_name(self) -> str:
        return f"{DEVICE_DESCRIPTION} CDC {self._port}"

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate(
            bits_per_payload_byte=SPI_BITS_PER_BYTE,
            wire_bits_per_sec=float(SPI_WIRE_BPS),
        )

    def _open_error(self, error: Exception) -> Exception:
        if not isinstance(error, serial.SerialException):
            return error
        message = f"Failed to connect to the USB-SPI bridge CDC port {self._port}: {error}"
        hint = serial_open_hint(error)
        return RuntimeError(f"{message}\n{hint}" if hint else message)


def _cdc_port_from_key(port_key: str) -> str:
    if port_key.startswith(CDC_ENDPOINT_PREFIX):
        return port_key[len(CDC_ENDPOINT_PREFIX) :]
    return port_key


class SpiUsbBridgeTransportProvider:
    @property
    def label(self) -> str:
        return "SPI USB Bridge"

    @property
    def mode(self) -> TransportMode:
        return TransportMode.SPI_USB_BRIDGE

    def scan_ports(self) -> PortScan:
        return scan_spi_usb_bridge_ports()

    def create_reader(self, config: TransportConfig) -> SpiUsbBridgeCdcTransport:
        port = _cdc_port_from_key(config.port)
        parts = port.split(":")
        if not port or (len(parts) == 4 and all(part.isdecimal() for part in parts)):
            raise ValueError("SPI Bridge requires a CDC serial port, such as cdc:/dev/ttyACM0 or COM7.")
        return SpiUsbBridgeCdcTransport(port, config.baudrate)


PROVIDER: TransportProvider = SpiUsbBridgeTransportProvider()
