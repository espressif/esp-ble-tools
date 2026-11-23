# ESP BLE Tools

ESP BLE Tools is a collection of host-side utilities that support ESP BLE development, debugging, validation, and log capture. Tools in this repository are organized under `components/` so each tool can keep its own source code, documentation, tests, and packaging scripts.

## Tools

### BLE Log Console

`components/ble_log_console` provides a terminal UI for receiving, displaying, and saving ESP BLE Log data in real time. For direct USB capture, connect the board’s USB OTG or USB Serial/JTAG (USJ) port. Console also supports SPI Bridge and UART. Each recording includes the raw data and a quality report.

See [components/ble_log_console/README.md](components/ble_log_console/README.md) for usage and development details.
