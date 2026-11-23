# BLFD integration packages

The public `esp-blfd==1.0.0.dev5` wheel unifies framing, integrity checking,
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
Built with manylinux2014 and repaired with auditwheel.

SHA256 of `esp_blfd-1.0.0.dev5-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`:
`30918e3b8c8d5fbba9d7bbb36ae09566cbacbb94d53ce93f79fd19a52e1832f1`

SHA256 of `esp_blfd-1.0.0.dev5.tar.gz`:
`ea8ca882afc20191520848f11b006096539d65708ed96660e8d18b6be874c3ce`

The source distribution was built with `python -m build --sdist` from the same source tree.
It contains the three native engine sources and excludes the internal package.
