# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import tarfile
import tomllib
from pathlib import Path

import pytest
from packaging.markers import Marker, default_environment

PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("platform", "machine", "python_version", "suffix"),
    [
        ("linux", "x86_64", "3.11", ".whl"),
        ("win32", "AMD64", "3.11", ".tar.gz"),
        ("win32", "AMD64", "3.12", ".tar.gz"),
        ("linux", "x86_64", "3.12", ".tar.gz"),
        ("darwin", "arm64", "3.11", ".tar.gz"),
    ],
)
def test_dependency_source_matches_target(platform, machine, python_version, suffix):
    config = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    sources = config["tool"]["uv"]["sources"]["esp-blfd"]
    if isinstance(sources, dict):
        sources = [sources]
    env = default_environment() | {
        "sys_platform": platform,
        "platform_machine": machine,
        "python_version": python_version,
        "implementation_name": "cpython",
    }
    selected = [s for s in sources if Marker(s.get("marker", "python_version >= '3.11'")).evaluate(env)]
    assert len(selected) == 1
    path = PROJECT / selected[0]["path"]
    assert path.name.endswith(suffix)
    assert path.is_file()


def test_public_source_distribution_contains_all_native_engines():
    with tarfile.open(PROJECT / "vendor/esp_blfd-1.0.0.tar.gz") as archive:
        names = {name.partition("/")[2] for name in archive.getnames()}
    assert {
        "setup.py",
        "pyproject.toml",
        "src/ble_log_frame_decoder/_native.pyx",
        "src/ble_log_frame_decoder/checking/_native.pyx",
        "src/ble_log_frame_decoder/analysis/ordering/_linearize_native.pyx",
    } <= names
    assert "src/ble_log_frame_decoder/analysis/startup.py" not in names
    assert not any(name.startswith("internal/") or "/_internal/" in name for name in names)
