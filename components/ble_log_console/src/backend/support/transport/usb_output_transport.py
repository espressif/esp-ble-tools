# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""USB Output (TinyUSB CDC-ACM) transport for BLE log byte streams.

The DUT enumerates a CDC-ACM port that carries the same v8 byte stream as the
UART and SPI transports, so the parser needs no USB-specific path. Two device
facts shape this module:

- the DUT starts sending only while the host holds DTR asserted;
- the USB Output contract offers no reset channel, so the RTS download pulse
  the UART transport may send has no meaning here and is never sent.
"""

from __future__ import annotations

import errno
from pathlib import Path

import serial
import serial.tools.list_ports

from src.backend.models import TransportBitrate, TransportConfig
from src.backend.support.transport.base import TransportMode, TransportProvider
from src.backend.support.transport.serial_reader import SerialReader

VENDOR_ID = 0x303A
PRODUCT_ID = 0x10B1
# The firmware renders the product string as 'BLE-Log-Port (<IDF_TARGET>)' and
# truncates it to 31 ASCII characters. Match the prefix only: the suffix tracks
# the target, so an equality check would break on every new chip.
PRODUCT_PREFIX = "BLE-Log-Port"
MODE_LABEL = "USB"

USB_OUTPUT_BLOCK_SIZE = 64 * 1024
USB_OUTPUT_READ_TIMEOUT = 0.1

_FULL_SPEED_MBPS = 12
_HIGH_SPEED_MBPS = 480
# No tag when the tier cannot be read: it would only repeat the mode name.
_FALLBACK_SPEED_TAG = ""


def _target_hint(port: object) -> str:
    """The '<IDF_TARGET>' suffix of the product descriptor, or '' if unknown.

    Only a label hint for the port list: the descriptor arrives while
    enumerating on Linux and macOS (pyserial fills ``ListPortInfo.product`` from
    the USB descriptor), so the chip can be named before the port is opened.
    Windows fills only the driver FriendlyName in ``description`` and leaves
    ``product`` None; the descriptor sits in the device property store there
    (``DEVPKEY_Device_BusReportedDeviceDesc``), which this module does not read
    — so on Windows the hint is absent rather than an error.
    """
    product = str(getattr(port, "product", None) or "")
    if not product.startswith(PRODUCT_PREFIX):
        return ""
    return product.partition("(")[2].rstrip(") ")


def _is_usb_output_port(port: object) -> bool:
    """VID:PID is the whole identity; the product string is only a chip hint.

    Filtering on the descriptor string would drop the DUT wherever that string
    cannot be read (Windows), which says something about the host, not about
    the device.
    """
    return getattr(port, "vid", None) == VENDOR_ID and getattr(port, "pid", None) == PRODUCT_ID


def _speed_tag(port: object) -> str:
    """USB speed tier from the sysfs USB device directory, else no tag.

    pyserial only exposes that directory on Linux; other platforms leave the tag
    out rather than guessing the tier from the port name.
    """
    device_path = getattr(port, "usb_device_path", None)
    if not device_path:
        return _FALLBACK_SPEED_TAG
    try:
        speed_mbps = int(Path(device_path, "speed").read_text().strip())
    except (OSError, ValueError):
        return _FALLBACK_SPEED_TAG
    return {_FULL_SPEED_MBPS: "FS", _HIGH_SPEED_MBPS: "HS"}.get(speed_mbps, _FALLBACK_SPEED_TAG)


def list_usb_output_ports() -> list[tuple[str, str]]:
    """Enumerate USB Output ports as (label, serial device) pairs."""
    options: list[tuple[str, str]] = []
    for port in serial.tools.list_ports.comports():
        if not _is_usb_output_port(port):
            continue
        device = str(port.device)
        target = _target_hint(port)
        suffix = f" ({target})" if target else ""
        tag = _speed_tag(port)
        prefix = f"{MODE_LABEL} {tag}" if tag else MODE_LABEL
        options.append((f"{prefix}  {device}{suffix}", device))
    return options


def _open_hint(error: Exception) -> str | None:
    """An action the user can take for the errnos this port actually fails with."""
    errno_value = getattr(error, "errno", None)
    text = str(error).lower()

    if errno_value == errno.EACCES or "permission denied" in text:
        return (
            "Permission denied. On Linux, add your user to the dialout group "
            "(or install a udev rule for this device) and open the port again."
        )
    if errno_value in (errno.EBUSY, getattr(errno, "EAGAIN", None)) or "busy" in text or "exclusively lock" in text:
        return "The port is busy. Stop ModemManager or whatever else holds it, then open the port again."
    if errno_value in (errno.ENOENT, getattr(errno, "ENXIO", None)) or "no such file" in text:
        return "The device is no longer present. Re-plug the DUT (or press its reset button) and refresh the ports."
    return None


class UsbOutputTransport(SerialReader):
    mode = TransportMode.USB_OUTPUT
    block_size = USB_OUTPUT_BLOCK_SIZE
    timeout = USB_OUTPUT_READ_TIMEOUT
    open_exclusive = True
    not_open_message = "USB Output transport is not open"

    @property
    def display_name(self) -> str:
        return f"{MODE_LABEL} {self._port}"

    @property
    def bitrate_config(self) -> TransportBitrate:
        """No fixed wire bitrate: a USB link does not clock payload bytes.

        `wire_bits_per_sec=None` also disables the enh-stat torn-read guard,
        whose 2 s window is derived from that rate.
        """
        return TransportBitrate()

    def _open_serial(self) -> serial.Serial:
        handle = super()._open_serial()
        try:
            # pyserial asserts DTR while opening; restate it so the DUT keeps
            # sending even when the port was opened without modem control.
            handle.dtr = True
        except (OSError, serial.SerialException):
            pass
        return handle

    def reset_target(self) -> bool:
        """Never pulse RTS: the USB Output contract has no reset channel.

        The firmware's CDC line-state callback is NULL and nothing on this port
        is documented to reset the target, so a pulse would be a guess at a side
        effect rather than a reset. Report failure instead, so callers do not
        take a reset that did not happen.
        """
        return False

    def _open_error(self, error: Exception) -> Exception:
        if not isinstance(error, serial.SerialException):
            return error
        message = f"Failed to open the USB Output port {self._port}: {error}"
        hint = _open_hint(error)
        return RuntimeError(f"{message}\n{hint}" if hint else message)


class UsbOutputTransportProvider:
    @property
    def label(self) -> str:
        """The mode name in the launch screen, matching the CLI's ``--mode usb``."""

        return "USB"

    @property
    def mode(self) -> TransportMode:
        return TransportMode.USB_OUTPUT

    def list_options(self) -> list[tuple[str, str]]:
        return list_usb_output_ports()

    def create_reader(self, config: TransportConfig) -> UsbOutputTransport:
        return UsbOutputTransport(config.port, config.baudrate)


PROVIDER: TransportProvider = UsbOutputTransportProvider()
