# BLFD integration packages

The public `esp-blfd==1.0.0` wheel unifies framing, integrity checking,
streaming parsing and firmware statistics. Console uses the canonical
`ble_log_frame_decoder` API and does not install separate Core/Checker packages.
It enables integrity checking, firmware counters, and Host/HCI content decoding.

Target: Linux x86_64, CPython 3.11, glibc >= 2.17. The wheel includes all three
native engines; installation needs no C/C++ compiler or private registry login.
Other platforms and Python versions use the accompanying public source distribution
from the same revision. `uv` selects the wheel only for its compatible target;
Windows never attempts to install the Linux wheel.

On Windows, source installation requires Visual Studio Build Tools with the
**Desktop development with C++** workload (MSVC and Windows SDK). Run
`install.bat` from a Developer Command Prompt. Python 3.11 x64 is the reference
build target. End users of a packaged executable do not need these build tools.
The build checks that all three native engines load before packaging.

The Windows dependency selection is checked on Linux; MSVC compilation,
Windows executable startup and hardware reception still require Windows testing.

Source file hashes are recorded in the Parser repository in `ble_log_parser_v2/vendor/blfd.json`.
The bundled files are in `089a5a6/`, named for the BLFD source revision.
Built with manylinux2014 and repaired with auditwheel.

SHA256 of `esp_blfd-1.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`:
`97853d2fbdcce486ff93f6b46f6d4e0f31b26a3cc0a9644a03c78a1471f0f1a9`

SHA256 of `esp_blfd-1.0.0.tar.gz`:
`2338d1086563204cb3f4b51b051b6072df815e6c9da24216ce29dc2ef0f79d1d`

The source distribution was built with `python -m build --sdist` from the same source tree.
It contains the three native engine sources and excludes the internal package.
