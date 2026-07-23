# BLE Log Console

[English](./README.md) | [中文](./README_CN.md)

BLE Log Console is a PC tool for receiving, displaying, and saving ESP BLE logs in real time.

It supports:

- **UART**: receive BLE logs from a serial port.
- **SPI Bridge**: receive BLE logs through a BLE Log SPI USB Bridge device.

## Download

Download the latest stable tool package from GitHub Release:

[BLE Log Console stable release](https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable)

## User Guide

We recommend reading the user guide before first use.

[User Guide](./docs/User-Guide-EN.md) | [中文用户指南](./docs/User-Guide-CN.md)

## Quick Start

1. Download the tool package for your operating system from the stable release page.
2. Start the tool:

```bash
# Windows
ble_log_console_windows_v1.0.3.exe

# Linux
chmod +x ./ble_log_console_ubuntu_v1.0.3
./ble_log_console_ubuntu_v1.0.3
```

3. Select the transport mode, port, baud rate if using UART, and log save directory, then click **Connect**.

If you use SPI Bridge on Linux for the first time, run the tool once with `sudo`, then replug the Bridge device:

```bash
sudo ./ble_log_console_ubuntu_v1.0.3
```

Logs are saved to the selected directory. For wiring, firmware configuration, command-line usage, and troubleshooting, see the [User Guide](./docs/User-Guide-EN.md).
