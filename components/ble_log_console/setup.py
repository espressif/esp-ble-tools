# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Optional native extensions for BLE Log Console.

Normal installs can run without a C compiler. The checksum extension is built
only when build_ext is requested explicitly.
"""

from __future__ import annotations

import sys
from pathlib import Path

from setuptools import Extension
from setuptools import setup


def _build_ext_requested() -> bool:
    return any(arg == 'build_ext' or arg.endswith('build_ext') for arg in sys.argv)


def _extension_modules() -> list[Extension]:
    if not _build_ext_requested():
        return []
    try:
        from Cython.Build import cythonize
    except Exception:
        return []

    source = Path('src/backend/support/parser_core/checksum_fast.pyx')
    return cythonize(
        [
            Extension(
                'src.backend.support.parser_core.checksum_fast',
                [str(source)],
            )
        ],
        compiler_directives={'language_level': '3'},
    )


setup(ext_modules=_extension_modules())
