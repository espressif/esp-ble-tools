# BLFD integration wheel

The public `esp-blfd==1.0.0.dev0` wheel unifies framing, integrity checking,
streaming parsing and firmware statistics. Console uses the canonical
`ble_log_frame_decoder` API and does not install separate Core/Checker packages.
It enables checking and firmware counters, with content decoding disabled.

Target: Linux x86_64, CPython 3.11, glibc >= 2.17. The wheel includes all three
native engines; installation needs no C/C++ compiler or private registry login.
Other platforms and Python versions need matching wheels before packaging.

Source revision: `424f9e54112da5104d40ec21fa8cdd6c385ddf12`.
Built with manylinux2014 and repaired with auditwheel.

SHA256 of `esp_blfd-1.0.0.dev0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`:
`b3fc3670b649063d6455e6629899263ef96567ac292f1bb73c03b8ee0d81fe41`
