# BLE Log Configuration Assistant

[English](./README.md) | [中文](./README_CN.md)

A small bilingual terminal wizard that safely enables BLE Log in an existing
ESP-IDF project. It supports USB Serial/JTAG, USB OTG, SPI Bridge, and UART presets.

## Guides

Use the [BLE Log Configuration Guide](../ble_log_console/docs/Config-Guide-EN.md) to select and wire the transport. After flashing, follow the [BLE Log Console User Guide](../ble_log_console/docs/Console-User-Guide-EN.md) to record logs.

## Quick Start

1. Open an ESP-IDF terminal so that `idf.py` is available.
2. Start the assistant from the directory containing the executable, then select your project. You can also pass the project path as an argument.

   **Ubuntu**

   ```bash
   ./ble_log_config_assistant_ubuntu_v0.1.0
   ```

   **Windows PowerShell**

   ```powershell
   .\ble_log_config_assistant_windows_v0.1.0.exe
   ```

3. Select English or 中文 at the top of the wizard. A configured project opens on the transport page. For a new project, run `idf.py reconfigure` first.
4. Select the board interface, review the changes, and choose **Apply configuration**. UART enables critical-only logging to reduce traffic. USJ disables the secondary console to free the port for BLE Log. For SPI, enter the board's pin assignments. USB OTG uses TinyUSB CDC. The preview lists the dependency command if the component is missing.
5. Build and flash using the project's usual workflow, then select the corresponding port in BLE Log Console.

The assistant validates the selection with ESP-IDF's `confserver`. Before saving, it backs up the original file as `sdkconfig.bak.*` and writes the reviewed settings into the existing `sdkconfig`, preserving other settings and comments. The next build handles project reconfiguration.

## Run from Source

Python 3.10+ is required. The application uses the same Textual interface and
directory picker as BLE Log Console.

```bash
python -m pip install -e ".[test]"
pytest
python -m ble_log_config_assistant
```

## Build the Executable

On Ubuntu, run these commands from the assistant source directory. The output is `dist/ble_log_config_assistant_ubuntu_v0.1.0`.

```bash
python -m pip install -e ".[build]"
python build.py
```

On Windows x64, install 64-bit Python 3.11 with the `py` launcher and run `.\build.bat` from the assistant directory. It creates a local virtual environment, runs the tests, builds the executable, and checks its version. The output is `dist\ble_log_config_assistant_windows_v0.1.0.exe`. Users can run this file from an ESP-IDF terminal and select their project in the wizard.
