# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""CDC permission diagnostics through the shipped CLI and passive scans."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from console import cli
from src.backend.models import TransportMode
from src.backend.support.transport import list_transport_port_scan
from src.backend.support.transport.base import PortIssue, PortIssueKind
from src.frontend.port_diagnostics import describe_port_issues


@pytest.mark.parametrize(
    "mode,pid,label", [("spi", 0x4001, "SPI Bridge"), ("usb", 0x10B1, "USB OTG"), ("usj", 0x1001, "USJ")]
)
@pytest.mark.parametrize("language,permission", [("en", "no read/write permission"), ("zh_CN", "没有读写权限")])
def test_cli_explains_cdc_permission_without_opening_ports(
    monkeypatch, mode, pid, label, language, permission, linux_serial_platform
):
    monkeypatch.setattr("src.i18n._language", language)
    monkeypatch.setattr(
        "serial.tools.list_ports.comports", lambda: [SimpleNamespace(device="/dev/ttyACM0", vid=0x303A, pid=pid)]
    )
    monkeypatch.setattr("src.backend.support.transport.serial_reader.os.access", lambda device, flags: False)
    opened = Mock(side_effect=AssertionError("Port scanning must be passive"))
    monkeypatch.setattr("serial.Serial", opened)
    result = CliRunner().invoke(cli, ["ports", "--mode", mode])
    assert result.exit_code == 0, result.output
    assert f"{label} /dev/ttyACM0" in result.output
    assert permission in result.output
    assert "dialout" in result.output
    assert "--port" not in result.output
    assert "libusb" not in result.output
    opened.assert_not_called()


@pytest.mark.parametrize(
    "mode,pid",
    [(TransportMode.SPI_USB_BRIDGE, 0x4001), (TransportMode.USB_OUTPUT, 0x10B1), (TransportMode.USJ, 0x1001)],
)
def test_windows_com_ports_are_not_filtered_by_filesystem_permissions(monkeypatch, mode, pid):
    monkeypatch.setattr("src.backend.support.transport.serial_reader.sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        "serial.tools.list_ports.comports", lambda: [SimpleNamespace(device="COM7", vid=0x303A, pid=pid)]
    )
    access = Mock(side_effect=AssertionError("COM names are not filesystem paths"))
    monkeypatch.setattr("src.backend.support.transport.serial_reader.os.access", access)
    scan = list_transport_port_scan(mode)
    assert len(scan.options) == 1
    assert scan.options[0][1] in ("COM7", "cdc:COM7")
    assert not scan.issues
    access.assert_not_called()


@pytest.mark.parametrize(
    "language,expected",
    [
        ("en", "USJ /dev/ttyACM1 cannot be opened: [Errno 5] Input/output error"),
        ("zh_CN", "USJ /dev/ttyACM1 无法打开：[Errno 5] Input/output error"),
    ],
)
def test_diagnostics_preserve_device_error(monkeypatch, language, expected):
    monkeypatch.setattr("src.i18n._language", language)
    issue = PortIssue(
        kind=PortIssueKind.DEVICE_ERROR, port="/dev/ttyACM1", label="USJ", detail="[Errno 5] Input/output error"
    )
    assert describe_port_issues([issue]) == [expected]


def test_default_language_stays_english_in_chinese_locale(monkeypatch):
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setenv("LANGUAGE", "zh_CN")
    result = subprocess.run(
        [sys.executable, "-c", "from src.i18n import get_language; print(get_language())"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "en"
