# BLE Log Console

[English](./README.md) | [中文](./README_CN.md)

BLE Log Console is a PC tool for receiving, displaying, and saving ESP BLE logs in real time.

It supports:

- **UART**: receive BLE logs from a serial port.
- **SPI Bridge**: receive BLE logs through a BLE Log SPI USB Bridge device.

## Supported Platforms

- Windows (`x86_64`)
- Linux (`x86_64`)
- macOS (`x86_64`, `arm64`)

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
ble_log_console_windows_v1.0.5.exe

# Linux
chmod +x ./ble_log_console_ubuntu_v1.0.5
./ble_log_console_ubuntu_v1.0.5
```

3. Select the language, transport mode, port, UART baud rate, and log save directory, then click **Connect**.
4. Click **Stop & Review** when recording is complete. The tool saves the data and displays a quality result.

If you use SPI Bridge on Linux for the first time, run the tool once with `sudo`, then replug the Bridge device:

```bash
sudo ./ble_log_console_ubuntu_v1.0.5
```

Logs are saved to the selected directory. For wiring, firmware configuration, and basic operation, see the [User Guide](./docs/User-Guide-EN.md).

## Run from Source

The tool also provides source code. Users who need local debugging, temporary tool changes, or feature verification can follow this chapter to run from source.

### Get the Source

The source code is located in the BLE Log Console source directory. Enter this directory before use.

```bash
cd <ble_log_console source directory>
```

The main files and directories are:

| File or Directory | Description |
| --- | --- |
| `console.py` | Application entry point |
| `install.sh` | Linux source environment setup script |
| `run.sh` | Linux source startup script |
| `install.bat` | Windows source environment setup script |
| `run.bat` | Windows source startup script |
| `src/` | Tool source code |
| `tests/` | Unit tests |
| `logs/` | Default log save directory, created automatically after running |

> Notes:
> - For normal use, the packaged executable is recommended.
> - Source startup is mainly intended for local debugging, temporary logic changes, or new feature verification.

### Use the Source

Source startup is basically the same as using the packaged program. The tool is based on Python and uses `uv` to manage dependencies. On first use, run the install script to prepare the local environment, then use the startup script to run `console.py`.

#### Windows System

On Windows, enter the source directory and prepare the environment on first use:

```bat
.\install.bat
```

Then run:

```bat
.\run.bat
```

Running without parameters opens the interactive interface, where you can select the transport mode, port, baud rate, and log save directory.

You can also start a specified mode directly with command-line parameters:

```bat
.\run.bat --mode uart --port COM3 --baudrate 3000000
.\run.bat --mode spi --port <PORT>
```

#### Linux System

On Linux, enter the source directory and prepare the environment on first use:

```bash
./install.sh
```

Then run:

```bash
./run.sh
```

If the script does not have execute permission, run:

```bash
chmod +x ./install.sh ./run.sh
```

Command-line startup examples:

```bash
./run.sh --mode uart --port /dev/ttyUSB0 --baudrate 3000000
./run.sh --mode spi --port <PORT>
```

#### Run `console.py` Directly

If you have already prepared the required Python environment manually, you can run `console.py` directly:

```bash
cd <ble_log_console source directory>
python console.py
```

You can also install the dependencies in a normal Python environment and then run the tool:

```bash
python -m pip install .
python console.py
```

Common commands:

```bash
python console.py --mode uart --port /dev/ttyUSB0 --baudrate 3000000
python console.py --mode spi --port <PORT>
```

> Notes:
> - Running `console.py` directly requires all Python dependencies to be installed.
> - If you only need normal use, run `install.sh` or `install.bat` once first, then use `run.sh` or `run.bat`.

## Command-Line Reference

This section provides additional command-line usage for the tool package. Common commands are listed below.

| Operation | Linux | Windows |
| --- | --- | --- |
| View help | `./ble_log_console_ubuntu_v1.0.5 --help` | `ble_log_console_windows_v1.0.5.exe --help` |
| List ports | `./ble_log_console_ubuntu_v1.0.5 ports` | `ble_log_console_windows_v1.0.5.exe ports` |
| Start interactive mode | `./ble_log_console_ubuntu_v1.0.5` | `ble_log_console_windows_v1.0.5.exe` |
| Start UART mode | `./ble_log_console_ubuntu_v1.0.5 --mode uart --port /dev/ttyUSB0` | `ble_log_console_windows_v1.0.5.exe --mode uart --port COM3` |
| Start SPI Bridge mode | `./ble_log_console_ubuntu_v1.0.5 --mode spi --port <PORT>` | `ble_log_console_windows_v1.0.5.exe --mode spi --port <PORT>` |
| View saved logs | `./ble_log_console_ubuntu_v1.0.5 ls` | `ble_log_console_windows_v1.0.5.exe ls` |

### Command-Line Options

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--mode` | `-m` | `uart` | Transport mode: `uart` or `spi` |
| `--port` | `-p` | optional | Serial or SPI Bridge port. Omit to open the interactive interface |
| `--baudrate` | `-b` | `3000000` | UART baud rate, which must match the firmware configuration |
| `--log-dir` | `-d` | `./logs` | Recording file save directory |
| `--debug` | none | off | Show extra debugging information |

Subcommands:

| Command | Description |
| --- | --- |
| `ports` | List UART serial ports and SPI Bridge ports. Use `--mode` to filter |
| `ls` | List `ble_log_*.bin` recording files in the specified directory |

`--output/-o` is still kept as a hidden option for compatibility with older versions. `--log-dir` is recommended.

## Shortcuts

The following shortcuts are commonly used while the application is running. They can be used to view statistics, reset the device, exit the application, and more.

| Key | Function |
| --- | --- |
| `q` | Stop and review while recording; exit from the report |
| `Ctrl+C` | Stop and review while recording; exit from the report |
| `c` | Clear the log area |
| `s` | Toggle auto-scroll |
| `d` | View received log statistics |
| `m` | View buffer usage |
| `h` | Show shortcut help |
| `r` | Reset the target device; not supported in SPI Bridge mode |

## Troubleshooting

For connection issues, log display, quality check limitations, source environment setup, and Bridge version checks, see [Troubleshooting at the end of the user guide](./docs/User-Guide-EN.md#faq-no-port).
