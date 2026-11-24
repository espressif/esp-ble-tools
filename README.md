# ESP BLE Tools

ESP BLE Tools is a collection of host-side utilities that support ESP BLE development, debugging, validation, and log capture. Tools in this repository are organized under `components/` so each tool can keep its own source code, documentation, tests, and packaging scripts.

## Tools

### BLE Log Console

`components/ble_log_console` provides a terminal UI for receiving, displaying, and saving ESP BLE Log data in real time. It supports UART and SPI Bridge transports, endpoint discovery, raw capture storage, decoded log display, loss/statistics views, and standalone executable packaging.

See [components/ble_log_console/README.md](components/ble_log_console/README.md) for usage and development details.

### BLE Log Configuration Assistant

Use the [configuration assistant](components/ble_log_config_assistant/README.md) to select a BLE Log transport and review the settings before applying them to an ESP-IDF project.
