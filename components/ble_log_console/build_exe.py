# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Build a PyInstaller executable for BLE Log Console.

Usage:
    pip install pyinstaller
    python build_exe.py
    python build_exe.py --bump-patch
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys

APP_NAME = 'ble_log_console'
PROJECT_DIR = Path(__file__).parent
VERSION_FILE = PROJECT_DIR / 'VERSION'
ARTIFACT_NAME_FILE = 'artifact_name.txt'
VERSION_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
DOCUMENT_FILES = (
    PROJECT_DIR / 'README.md',
    PROJECT_DIR / 'README_CN.md',
    PROJECT_DIR / 'docs' / 'User-Guide-CN.md',
    PROJECT_DIR / 'docs' / 'User-Guide-EN.md',
)
PROJECT_FILE = PROJECT_DIR / 'pyproject.toml'
DOCUMENT_VERSION_RE = re.compile(
    r'(?P<prefix>ble_log_console_(?:windows|ubuntu)_v)\d+\.\d+\.\d+'
    r'|(?P<header>^(?:版本：v|Version: v))\d+\.\d+\.\d+',
    re.MULTILINE,
)
PROJECT_VERSION_RE = re.compile(r'^version = "\d+\.\d+\.\d+"$', re.MULTILINE)


def _read_version() -> tuple[int, int, int]:
    if not VERSION_FILE.exists():
        return (1, 0, 0)

    text = VERSION_FILE.read_text(encoding='utf-8').strip()
    match = VERSION_RE.match(text)
    if match is None:
        raise ValueError(f'Invalid version in {VERSION_FILE}: {text!r}. Expected MAJOR.MINOR.PATCH.')
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _format_version(version: tuple[int, int, int]) -> str:
    return '.'.join(str(part) for part in version)


def _next_patch_version() -> str:
    major, minor, patch = _read_version()
    return _format_version((major, minor, patch + 1))


def _write_version(version: str) -> None:
    VERSION_FILE.write_text(f'{version}\n', encoding='utf-8')


def _replace_document_versions(text: str, version: str) -> str:
    return DOCUMENT_VERSION_RE.sub(
        lambda match: f'{match.group("prefix") or match.group("header")}{version}',
        text,
    )


def _sync_version_references(version: str) -> None:
    for path in DOCUMENT_FILES:
        text = path.read_text(encoding='utf-8')
        updated = _replace_document_versions(text, version)
        if updated != text:
            path.write_text(updated, encoding='utf-8')

    project_text = PROJECT_FILE.read_text(encoding='utf-8')
    updated_project = PROJECT_VERSION_RE.sub(f'version = "{version}"', project_text, count=1)
    if updated_project != project_text:
        PROJECT_FILE.write_text(updated_project, encoding='utf-8')


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build BLE Log Console executable.')
    version_group = parser.add_mutually_exclusive_group()
    version_group.add_argument(
        '--bump-patch',
        action='store_true',
        help='Build the next patch version, then update VERSION and documentation after a successful build.',
    )
    version_group.add_argument(
        '--version',
        default=None,
        help='Build this exact version, then update VERSION and documentation after a successful build.',
    )
    return parser.parse_args()


def _platform_suffix() -> str:
    if sys.platform == 'win32':
        return 'windows'
    if sys.platform == 'darwin':
        return 'macos'
    return 'ubuntu'


def _artifact_base_name(version: str) -> str:
    return f'{APP_NAME}_{_platform_suffix()}_v{version}'


def main() -> None:
    args = _parse_args()
    if args.version is not None:
        if VERSION_RE.match(args.version) is None:
            raise ValueError(f'Invalid --version: {args.version!r}. Expected MAJOR.MINOR.PATCH.')
        version = args.version
    elif args.bump_patch:
        version = _next_patch_version()
    else:
        version = _format_version(_read_version())

    artifact_base_name = _artifact_base_name(version)
    artifact_name = f'{artifact_base_name}.exe' if sys.platform == 'win32' else artifact_base_name
    cmd = [
        sys.executable,
        '-m',
        'PyInstaller',
        'console.py',
        '--onefile',
        '--name',
        artifact_base_name,
        '--hidden-import',
        'click',
        '--hidden-import',
        'rich',
        '--hidden-import',
        'textual',
        '--hidden-import',
        'textual.drivers',
        '--hidden-import',
        'textual.css',
        '--hidden-import',
        'textual_fspicker',
        '--hidden-import',
        'usb',
        '--hidden-import',
        'usb.core',
        '--hidden-import',
        'usb.util',
        '--hidden-import',
        'serial',
        '--hidden-import',
        'serial.tools',
        '--hidden-import',
        'serial.tools.list_ports',
        '--hidden-import',
        'serial.tools.list_ports_common',
        '--hidden-import',
        'serial.tools.list_ports_linux',
        '--hidden-import',
        'serial.tools.list_ports_windows',
        '--hidden-import',
        'serial.tools.list_ports_osx',
        '--hidden-import',
        'ble_log_frame_decoder._native',
        '--collect-data',
        'textual',
        '--collect-data',
        'textual_fspicker',
        '--noconfirm',
    ]

    print(f'Packaging version: {version}')
    print(f'Running: {" ".join(cmd)}')
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f'\nBuild failed (exit code {result.returncode}).', file=sys.stderr)
        print('If you see hidden import errors, add the missing module to the cmd list above.', file=sys.stderr)
        sys.exit(result.returncode)

    _write_version(version)
    _sync_version_references(version)

    artifact_name_path = Path('dist') / ARTIFACT_NAME_FILE
    artifact_name_path.write_text(f'{artifact_name}\n', encoding='utf-8')

    print(f'\nBuild complete. Version: {version}')
    print(f'Artifact: dist/{artifact_name}')


if __name__ == '__main__':
    main()
