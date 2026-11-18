# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Exact rendered text for the ports the transport cannot open.

Both surfaces (the launch screen and `console.py ports`) print what
`describe_port_issues` returns, so these strings are the user-visible contract
in both languages.
"""

from collections.abc import Iterator

import pytest
from src import i18n
from src.backend.support.transport.base import PortIssue, PortIssueKind
from src.frontend.port_diagnostics import describe_port_issues

PERMISSION_DENIED = PortIssue(kind=PortIssueKind.PERMISSION_DENIED, bus=1, address=95)
LIBUSB_MISSING = PortIssue(kind=PortIssueKind.LIBUSB_MISSING, detail="No backend available")
DEVICE_ERROR = PortIssue(kind=PortIssueKind.DEVICE_ERROR, bus=1, address=95, detail="[Errno 5] Input/output error")
SERIAL_PERMISSION_DENIED = PortIssue(kind=PortIssueKind.PERMISSION_DENIED, port="/dev/ttyACM1")
SERIAL_DEVICE_ERROR = PortIssue(
    kind=PortIssueKind.DEVICE_ERROR, port="/dev/ttyACM1", detail="[Errno 5] Input/output error"
)

PERMISSION_EN = (
    "SPI Bridge (bus 1, addr 95): no USB access permission. "
    "Run this tool once with sudo (no arguments), then replug the bridge."
)
PERMISSION_ZH = (
    "SPI Bridge（bus 1，addr 95）：没有 USB 访问权限。请用 sudo 运行一次本工具（不带参数），然后重新拔插 Bridge。"
)

LIBUSB_EN = "libusb-1.0 not found. Install it first: sudo apt install libusb-1.0-0"
LIBUSB_ZH = "未找到 libusb-1.0，请先安装：sudo apt install libusb-1.0-0"

DEVICE_ERROR_EN = "SPI Bridge (bus 1, addr 95) cannot be opened: [Errno 5] Input/output error"
DEVICE_ERROR_ZH = "SPI Bridge（bus 1，addr 95）无法打开：[Errno 5] Input/output error"

SERIAL_PERMISSION_EN = (
    "USJ /dev/ttyACM1: no read/write permission. "
    "Add your user to the dialout group (sudo usermod -aG dialout $USER), then log in again."
)
SERIAL_PERMISSION_ZH = (
    "USJ /dev/ttyACM1：没有读写权限。请把当前用户加入 dialout 组（sudo usermod -aG dialout $USER），然后重新登录。"
)
SERIAL_DEVICE_ERROR_EN = "USJ /dev/ttyACM1 cannot be opened: [Errno 5] Input/output error"
SERIAL_DEVICE_ERROR_ZH = "USJ /dev/ttyACM1 无法打开：[Errno 5] Input/output error"


@pytest.fixture(autouse=True)
def restore_language() -> Iterator[None]:
    original = i18n.get_language()
    try:
        yield
    finally:
        i18n.set_language(original)


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (PERMISSION_DENIED, PERMISSION_EN),
        (LIBUSB_MISSING, LIBUSB_EN),
        (DEVICE_ERROR, DEVICE_ERROR_EN),
        (SERIAL_PERMISSION_DENIED, SERIAL_PERMISSION_EN),
        (SERIAL_DEVICE_ERROR, SERIAL_DEVICE_ERROR_EN),
    ],
    ids=["permission", "libusb", "device-error", "usj-permission", "usj-device-error"],
)
def test_english_catalog_renders_one_line(issue: PortIssue, expected: str) -> None:
    i18n.set_language(i18n.ENGLISH)

    assert describe_port_issues([issue]) == [expected]


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (PERMISSION_DENIED, PERMISSION_ZH),
        (LIBUSB_MISSING, LIBUSB_ZH),
        (DEVICE_ERROR, DEVICE_ERROR_ZH),
        (SERIAL_PERMISSION_DENIED, SERIAL_PERMISSION_ZH),
        (SERIAL_DEVICE_ERROR, SERIAL_DEVICE_ERROR_ZH),
    ],
    ids=["permission", "libusb", "device-error", "usj-permission", "usj-device-error"],
)
def test_chinese_catalog_renders_one_line(issue: PortIssue, expected: str) -> None:
    i18n.set_language(i18n.CHINESE)

    assert describe_port_issues([issue]) == [expected]


class TestSystemLanguage:
    """The CLI picks its language from the message locale at import time."""

    @staticmethod
    def _no_message_locale(monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LC_CTYPE", "LANG"):
            monkeypatch.delenv(name, raising=False)

    def test_a_chinese_message_locale_selects_chinese(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._no_message_locale(monkeypatch)
        monkeypatch.setenv("LANG", "zh_CN.UTF-8")

        assert i18n._system_language() == i18n.CHINESE

    def test_an_english_message_locale_keeps_english(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._no_message_locale(monkeypatch)
        monkeypatch.setenv("LANG", "en_US.UTF-8")

        assert i18n._system_language() == i18n.ENGLISH

    def test_lc_messages_wins_over_lang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._no_message_locale(monkeypatch)
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("LC_MESSAGES", "zh_CN.UTF-8")

        assert i18n._system_language() == i18n.CHINESE

    def test_the_language_priority_list_prefers_the_first_shipped_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._no_message_locale(monkeypatch)
        monkeypatch.setenv("LANGUAGE", "fr_FR:zh_CN")
        monkeypatch.setenv("LANG", "en_US.UTF-8")

        assert i18n._system_language() == i18n.CHINESE

    def test_one_unsupported_locale_does_not_fall_through_to_lang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LC_MESSAGES names the message language even when this tool does not ship it."""
        self._no_message_locale(monkeypatch)
        monkeypatch.setenv("LC_MESSAGES", "de_DE.UTF-8")
        monkeypatch.setenv("LANG", "zh_CN.UTF-8")

        assert i18n._system_language() == i18n.ENGLISH

    def test_formatting_categories_do_not_pick_the_language(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Chinese desktop can keep LC_TIME/LC_NUMERIC while reading English messages."""
        self._no_message_locale(monkeypatch)
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("LC_TIME", "zh_CN.UTF-8")
        monkeypatch.setenv("LC_NUMERIC", "zh_CN.UTF-8")
        monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("en_US", "UTF-8"))

        assert i18n._system_language() == i18n.ENGLISH

    def test_the_locale_table_is_the_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows sets no LANG: the C library locale still says the language."""
        self._no_message_locale(monkeypatch)
        monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("Chinese (Simplified)_China", "cp936"))

        assert i18n._system_language() == i18n.CHINESE
