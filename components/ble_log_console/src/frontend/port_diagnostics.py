# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""User-facing wording for ports that enumerated but cannot be opened.

The transport layer reports a :class:`PortIssue` (a kind plus the device it
belongs to); this module turns that into the one line the user needs and the
action that fixes it. Keeping the text here, rather than in the transport, lets
the TUI and the CLI share it and lets the i18n catalog translate it.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.backend.support.transport.base import PortIssue, PortIssueKind
from src.i18n import tr


def _describe_port_issue(issue: PortIssue) -> str:
    if issue.kind is PortIssueKind.PERMISSION_DENIED:
        return tr(
            "SPI Bridge (bus {bus}, addr {address}): no USB access permission. "
            "Run this tool once with sudo (no arguments), then replug the bridge.",
            bus=issue.bus,
            address=issue.address,
        )
    if issue.kind is PortIssueKind.LIBUSB_MISSING:
        return tr("libusb-1.0 not found. Install it first: sudo apt install libusb-1.0-0")
    return tr(
        "SPI Bridge (bus {bus}, addr {address}) cannot be opened: {detail}",
        bus=issue.bus,
        address=issue.address,
        detail=issue.detail,
    )


def describe_port_issues(issues: Sequence[PortIssue]) -> list[str]:
    """One user-facing line per issue, in the selected UI language."""
    return [_describe_port_issue(issue) for issue in issues]
