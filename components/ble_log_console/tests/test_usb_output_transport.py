# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import serial
from src.backend.models import TransportConfig, TransportMode
from src.backend.support.transport.usb_output_transport import (
    PRODUCT_ID,
    PROVIDER,
    USB_OUTPUT_BLOCK_SIZE,
    USB_OUTPUT_READ_TIMEOUT,
    VENDOR_ID,
    UsbOutputTransport,
    list_usb_output_ports,
)

from tests.helpers import SerialHandleStub

_COM_PORT = "src.backend.support.transport.usb_output_transport.serial.tools.list_ports.comports"


def _port(
    device: str = "/dev/ttyACM0",
    vid: int | None = VENDOR_ID,
    pid: int | None = PRODUCT_ID,
    product: str | None = "BLE-Log-Port (esp32s31)",
    **extra: object,
) -> SimpleNamespace:
    return SimpleNamespace(device=device, vid=vid, pid=pid, product=product, **extra)


class TestEnumeration:
    @patch(_COM_PORT)
    def test_only_the_usb_output_identity_is_listed(self, mock_comports: MagicMock) -> None:
        mock_comports.return_value = [
            _port(device="/dev/ttyACM0"),
            _port(device="/dev/ttyACM1", vid=0x1001, product="USB-Serial-JTAG"),
            _port(device="/dev/ttyACM2", pid=0x4001, product="USB-SPI-BRIDGE"),
        ]

        assert [value for _, value in list_usb_output_ports()] == ["/dev/ttyACM0"]

    @patch(_COM_PORT)
    def test_the_label_names_the_target_when_the_descriptor_is_readable(self, mock_comports: MagicMock) -> None:
        mock_comports.return_value = [_port(product="BLE-Log-Port (esp32s3)")]

        label, _ = list_usb_output_ports()[0]

        assert label.endswith(" /dev/ttyACM0 (esp32s3)")

    @patch(_COM_PORT)
    def test_label_names_the_mode_and_the_device(self, mock_comports: MagicMock) -> None:
        mock_comports.return_value = [_port()]

        label, value = list_usb_output_ports()[0]

        assert value == "/dev/ttyACM0"
        assert label.startswith("USB  /dev/ttyACM0")
        assert "/dev/ttyACM0" in label

    @patch(_COM_PORT)
    def test_product_suffix_tracks_the_target(self, mock_comports: MagicMock) -> None:
        """The firmware appends '(<IDF_TARGET>)', so matching is a prefix."""
        mock_comports.return_value = [
            _port(device="/dev/ttyACM0", product="BLE-Log-Port (esp32s3)"),
            _port(device="/dev/ttyACM1", product="BLE-Log-Port (esp32s31)"),
        ]

        assert [value for _, value in list_usb_output_ports()] == ["/dev/ttyACM0", "/dev/ttyACM1"]

    @patch(_COM_PORT)
    def test_an_unreadable_or_foreign_product_string_still_lists_the_port(self, mock_comports: MagicMock) -> None:
        """Identity is VID:PID; the descriptor only carries the chip hint."""
        mock_comports.return_value = [
            _port(device="/dev/ttyACM0", product=None),
            _port(device="/dev/ttyACM1", product="Some Other CDC App"),
        ]

        labels = list_usb_output_ports()

        assert [value for _, value in labels] == ["/dev/ttyACM0", "/dev/ttyACM1"]
        assert all("(" not in label for label, _ in labels)

    @patch(_COM_PORT)
    def test_a_bare_product_name_gets_no_chip_hint(self, mock_comports: MagicMock) -> None:
        mock_comports.return_value = [_port(product="BLE-Log-Port")]

        label, _ = list_usb_output_ports()[0]

        assert label.endswith("  /dev/ttyACM0")

    @patch(_COM_PORT)
    def test_windows_friendly_name_is_not_mistaken_for_the_product(self, mock_comports: MagicMock) -> None:
        """On Windows only `description` is filled, with the driver FriendlyName."""
        mock_comports.return_value = [
            _port(product=None, description="USB Serial Device (COM3)", device="COM3"),
        ]

        labels = list_usb_output_ports()

        assert [value for _, value in labels] == ["COM3"]
        assert labels[0][0] == "USB  COM3"


class TestSpeedTag:
    @pytest.mark.parametrize(
        ("speed_mbps", "expected_prefix"),
        [("480", "USB HS"), ("12", "USB FS"), ("5", "USB")],
    )
    @patch(_COM_PORT)
    def test_speed_tag_comes_from_the_usb_device_directory(
        self, mock_comports: MagicMock, tmp_path: Path, speed_mbps: str, expected_prefix: str
    ) -> None:
        (tmp_path / "speed").write_text(f"{speed_mbps}\n")
        mock_comports.return_value = [_port(usb_device_path=str(tmp_path))]

        label, _ = list_usb_output_ports()[0]

        assert label.startswith(f"{expected_prefix}  /dev/ttyACM0")

    @pytest.mark.parametrize("extra", [{}, {"usb_device_path": "/nonexistent"}], ids=["no-path", "unreadable"])
    @patch(_COM_PORT)
    def test_speed_tag_falls_back_without_a_readable_path(
        self, mock_comports: MagicMock, extra: dict[str, str]
    ) -> None:
        mock_comports.return_value = [_port(**extra)]

        label, _ = list_usb_output_ports()[0]

        assert label.startswith("USB  /dev/ttyACM0")


class TestDeviceContract:
    def test_reader_declares_usb_expectations(self) -> None:
        reader = UsbOutputTransport("/dev/ttyACM0", 3_000_000)

        assert reader.mode is TransportMode.USB_OUTPUT
        assert reader.block_size == USB_OUTPUT_BLOCK_SIZE
        assert reader.timeout == USB_OUTPUT_READ_TIMEOUT
        assert reader.open_exclusive is True
        assert reader.reset_target() is False

    def test_bitrate_carries_no_wire_rate(self) -> None:
        """A USB link does not clock payload bytes, so the torn-read guard stays off."""
        bitrate = UsbOutputTransport("/dev/ttyACM0", 3_000_000).bitrate_config

        assert bitrate.wire_bits_per_sec is None
        assert bitrate.max_payload_bytes_per_sec is None

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_open_keeps_dtr_asserted(self, mock_serial: MagicMock) -> None:
        handle = SerialHandleStub()
        mock_serial.return_value = handle
        reader = UsbOutputTransport("/dev/ttyACM0", 3_000_000)

        reader.open()

        assert handle.dtr_writes == [True]

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_open_tolerates_a_port_without_modem_lines(self, mock_serial: MagicMock) -> None:
        """A tty that refuses DTR (pty, some CDC stacks) must still open."""
        mock_serial.return_value = SerialHandleStub(reject_dtr=True)
        reader = UsbOutputTransport("/dev/ttyACM0", 3_000_000)

        reader.open()

        assert reader.status().opened is True

    @patch("src.backend.support.transport.serial_reader.serial.Serial")
    def test_reset_target_never_pulses_rts(self, mock_serial: MagicMock) -> None:
        """The USB Output contract has no reset channel, so reset is refused."""
        handle = SerialHandleStub()
        mock_serial.return_value = handle
        reader = UsbOutputTransport("/dev/ttyACM0", 3_000_000)
        reader.open()

        assert reader.reset_target() is False
        assert handle.rts_writes == []


class TestOpenErrors:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (serial.SerialException(errno.EACCES, "Permission denied"), "dialout"),
            (serial.SerialException(errno.EBUSY, "Device or resource busy"), "ModemManager"),
            (serial.SerialException(errno.ENOENT, "No such file or directory"), "Re-plug"),
        ],
    )
    def test_open_error_names_an_action(self, error: serial.SerialException, expected: str) -> None:
        raised = UsbOutputTransport("/dev/ttyACM0", 3_000_000)._open_error(error)

        assert isinstance(raised, RuntimeError)
        assert "/dev/ttyACM0" in str(raised)
        assert expected in str(raised)

    def test_open_error_without_a_known_cause_stays_honest(self) -> None:
        error = serial.SerialException("unexpected failure")

        raised = UsbOutputTransport("/dev/ttyACM0", 3_000_000)._open_error(error)

        assert "/dev/ttyACM0" in str(raised)
        assert "dialout" not in str(raised)

    def test_open_error_leaves_other_exceptions_alone(self) -> None:
        error = ValueError("not a serial failure")

        assert UsbOutputTransport("/dev/ttyACM0", 3_000_000)._open_error(error) is error


class TestProvider:
    def test_provider_exposes_the_usb_output_mode(self) -> None:
        assert PROVIDER.mode is TransportMode.USB_OUTPUT
        assert PROVIDER.label == "USB"

    def test_provider_builds_a_reader_for_the_configured_port(self) -> None:
        config = TransportConfig(mode=TransportMode.USB_OUTPUT, label="dev", port="/dev/ttyACM0")

        reader = PROVIDER.create_reader(config)

        assert isinstance(reader, UsbOutputTransport)
        assert reader.display_name == "USB /dev/ttyACM0"
