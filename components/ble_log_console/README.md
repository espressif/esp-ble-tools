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

## Guides

| Guide | What it covers | Languages |
| --- | --- | --- |
| BLE Log Configuration Guide | Transport selection, sdkconfig, wiring, capture verification, and required deliverables. | [English](./docs/Config-Guide-EN.md) / [中文](./docs/Config-Guide-CN.md) |
| Console User Guide | Tool setup, connection, recording, quality reports, and troubleshooting. | [English](./docs/Console-User-Guide-EN.md) / [中文](./docs/Console-User-Guide-CN.md) |

Start with the Configuration Guide if the hardware and firmware setup has not been determined. If questions remain after reading it, contact technical support. If the setup is ready, go directly to the Console User Guide.

### Collect Setup Information with AI

The [BLE Log intake skill](./docs/skills/ble-log-intake/SKILL.md) provides a questionnaire and a workflow for mapping confirmed information to configuration settings. With an AI tool that can read local files, provide the file path and your existing materials, for example:

> Read `components/ble_log_console/docs/skills/ble-log-intake/SKILL.md`. Use my sdkconfig and board information to fill in the intake questionnaire and list what still needs confirmation.

## Quick Start

1. Download the tool package for your operating system from the stable release page.
2. Start the tool:

```bash
# Windows
ble_log_console_windows_v1.1.0.exe

# Linux
chmod +x ./ble_log_console_ubuntu_v1.1.0
./ble_log_console_ubuntu_v1.1.0
```

3. Select the language, transport mode, port, UART baud rate, and log save directory, then click **Connect**.
4. Click **Stop & Review** when recording is complete. The tool saves the data and displays a quality result.

If you use SPI Bridge on Linux for the first time, run the tool once with `sudo`, then replug the Bridge device:

```bash
sudo ./ble_log_console_ubuntu_v1.1.0
```

Logs are saved to the selected directory. For wiring, firmware configuration, and basic operation, see the [User Guide](./docs/Console-User-Guide-EN.md).

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
| View help | `./ble_log_console_ubuntu_v1.1.0 --help` | `ble_log_console_windows_v1.1.0.exe --help` |
| List ports | `./ble_log_console_ubuntu_v1.1.0 ports` | `ble_log_console_windows_v1.1.0.exe ports` |
| Start interactive mode | `./ble_log_console_ubuntu_v1.1.0` | `ble_log_console_windows_v1.1.0.exe` |
| Start UART mode | `./ble_log_console_ubuntu_v1.1.0 --mode uart --port /dev/ttyUSB0` | `ble_log_console_windows_v1.1.0.exe --mode uart --port COM3` |
| Start SPI Bridge mode | `./ble_log_console_ubuntu_v1.1.0 --mode spi --port <PORT>` | `ble_log_console_windows_v1.1.0.exe --mode spi --port <PORT>` |
| Start USJ mode | `./ble_log_console_ubuntu_v1.1.0 --mode usj --port /dev/ttyACM0` | `ble_log_console_windows_v1.1.0.exe --mode usj --port COM5` |
| View saved logs | `./ble_log_console_ubuntu_v1.1.0 ls` | `ble_log_console_windows_v1.1.0.exe ls` |

### Command-Line Options

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--mode` | `-m` | `uart` | Transport mode: `uart`, `spi`, `usb` (USB Output), or `usj` (USB Serial/JTAG) |
| `--port` | `-p` | optional | Serial, SPI Bridge, USB Output, or USJ port. Omit to open the interactive interface |
| `--baudrate` | `-b` | `3000000` | UART baud rate, which must match the firmware configuration |
| `--log-dir` | `-d` | `./logs` | Recording file save directory |
| `--debug` | none | off | Show extra debugging information |

Subcommands:

| Command | Description |
| --- | --- |
| `ports` | List UART, SPI Bridge, USB Output, and USJ ports. Use `--mode` to filter |
| `ls` | List `ble_log_*.bin` recording files in the specified directory |

`--output/-o` is still kept as a hidden option for compatibility with older versions. `--log-dir` is recommended.

### USJ Mode

USJ mode receives BLE Log through the chip's built-in USB Serial/JTAG port (USB ID `303A:1001`). The `ports` subcommand and the interactive interface list only ports with that USB ID. The baud rate setting does not apply. The firmware must route BLE Log output to USB Serial/JTAG, which requires an ESP-IDF that offers `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG`; see [USJ configuration](./docs/Config-Guide-EN.md#usj).

On this port, the DTR and RTS lines control the chip's reset and boot mode. While opening the port, BLE Log Console releases RTS before DTR, the same order ESP-IDF Monitor uses to avoid a reset, then leaves both lines released and never changes them afterwards, so the `r` shortcut does not reset the target. The operating system or its USB driver can still change these lines while opening the device. Check on your own host whether opening the port resets the board.

### UART and USJ Console Text

UART and USJ ports can also carry plain console text, such as ROM boot messages or a panic dump. In these modes, bytes that cannot be decoded as BLE Log frames are shown in the log area and saved to `_console.log`, between `Undecoded data` markers (translated for the selected language). Printable ASCII is kept, colors are removed from the file, and line endings are normalized. A text line appears in the log area when it ends, when BLE Log data follows it, or when it reaches 16 KiB, so a line is never split by a screen refresh. A partial frame is not shown while it may still complete; any remaining undecoded tail is shown once when recording stops. This text is not counted as BLE Log frames. The raw `.bin` file always keeps every received byte. In every mode, if `_console.log` cannot be written or synchronized to storage, the tool warns once and stops writing that file. The log area continues displaying text. This error does not itself stop raw recording. The quality report states that the console log is incomplete and separately reports any raw recording failure.

The tool also identifies what the port carries:

- **Plain text:** The status bar shows `PLAIN TEXT` and a warning appears at once, then every 10 seconds while it continues. Recording and raw saving continue. Plain text usually means that the firmware does not send BLE Log to this port.
- **BLE Log:** The status bar shows `BLE LOG` after one firmware identity record or three valid frames from known BLE Log sources. Text before that point, such as boot messages, is expected. Identification does not change back when the port is quiet or prints text later.

The quality report states the identified content and how much data arrived outside BLE Log frames. A frame that is cut off when recording stops is normal: its bytes are listed as trailing carried bytes and do not add this warning. All original bytes stay in the `.bin` file; `_console.log` holds at most their printable text. Identification alone does not make a recording ready for analysis: a recording that contains only identity records still requires a configuration check. SPI Bridge and USB Output modes do not show undecoded data or identification.

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
| `r` | Reset the target device; not supported in SPI Bridge, USB Output, or USJ mode |

## Troubleshooting

For connection issues, log display, quality check limitations, source environment setup, and Bridge version checks, see [Troubleshooting at the end of the user guide](./docs/Console-User-Guide-EN.md#faq-no-port).
