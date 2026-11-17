# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""User-facing wording for ports that enumerated but cannot be opened.

The transport layer reports a :class:`PortIssue` (a kind plus the device it
belongs to); this module turns that into the one line the user needs and the
action that fixes it. Keeping the text here, rather than in the transport, lets
the TUI and the CLI share it and lets the i18n catalog translate it.
"""

from __future__ import annotations

import errno
from collections.abc import Sequence

from src.backend.support.transport.base import PortIssue, PortIssueKind
from src.backend.support.transport.serial_reader import serial_open_hint
from src.i18n import tr


def describe_port_issues(issues: Sequence[PortIssue]) -> list[str]:
    """One user-facing line per issue, in the selected UI language."""
    messages = []
    for issue in issues:
        if issue.kind is PortIssueKind.PERMISSION_DENIED:
            messages.append(tr("{label} {port}: no read/write permission.", label=issue.label, port=issue.port))
            hint = serial_open_hint(PermissionError(errno.EACCES, "Permission denied"))
            if hint:
                messages[-1] += " " + hint
        else:
            messages.append(
                tr("{label} {port} cannot be opened: {detail}", label=issue.label, port=issue.port, detail=issue.detail)
            )
    return messages
