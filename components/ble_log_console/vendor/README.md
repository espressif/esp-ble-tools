# BLFD integration packages

The public `esp-blfd==1.0.0.dev1` wheel unifies framing, integrity checking,
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

Source revision: `dca35bf06fb2dbc877fd46774585f98864ac88c6`.
Built with manylinux2014 and repaired with auditwheel.

SHA256 of `esp_blfd-1.0.0.dev1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`:
`89f13dbe9642fbaa101c5504432248129202b9f3a3e59370b265e5ee77fa3b6c`

SHA256 of `esp_blfd-1.0.0.dev1.tar.gz`:
`f517e8ff668922d6a053384030fd9f8cd25c8c42cb731a503bb7d939a7ac759e`

The source distribution was built with `python -m build --sdist` from the revision above.
It contains the three native engine sources and excludes the internal package.
