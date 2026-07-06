# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Build a single-file executable for BLE Log Console using PyInstaller.

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
VERSION_FILE = Path(__file__).with_name('VERSION')
ARTIFACT_NAME_FILE = 'artifact_name.txt'
VERSION_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build BLE Log Console executable.')
    parser.add_argument(
        '--bump-patch',
        action='store_true',
        help='Increment VERSION patch before packaging and write the new version back after a successful build.',
    )
    parser.add_argument(
        '--version',
        default=None,
        help='Package this exact version without modifying VERSION.',
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


def _artifact_filename(base_name: str) -> str:
    if sys.platform == 'win32':
        return f'{base_name}.exe'
    return base_name


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
    artifact_filename = _artifact_filename(artifact_base_name)

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

    if args.bump_patch:
        _write_version(version)

    artifact_name_path = Path('dist') / ARTIFACT_NAME_FILE
    artifact_name_path.write_text(f'{artifact_filename}\n', encoding='utf-8')

    print(f'\nBuild complete. Version: {version}')
    print(f'Executable: dist/{artifact_filename}')


if __name__ == '__main__':
    main()
