# BLE Log Console

[English](./README.md) | [中文](./README_CN.md)

BLE Log Console is a PC tool for receiving, displaying, and saving ESP BLE logs in real time.

It supports:

- **UART**: receive BLE logs from a serial port.
- **SPI Bridge**: receive BLE logs through a BLE Log SPI USB Bridge device.
- **USJ**: receive BLE logs through the chip's built-in USB Serial/JTAG port.
- **USB Output**: receive BLE logs through a firmware-provided TinyUSB CDC-ACM port.

In interactive setup, select **USB** for either USB OTG or USJ, then choose the device. Port labels identify the type; chip names appear only when supplied by the USB descriptor. Listing ports does not open them or send probe commands. CLI `--mode usb` (OTG) and `--mode usj` remain available.

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

3. The default language is English. Switch language at the top right; the setup page updates immediately and keeps your current settings. Select the transport mode, port, UART baud rate, and log save directory. Optionally select **Host**, **HCI**, or **Console** (UART only) under **Live display**, then click **Connect**. All display categories default to off; recording, saved logs, status, and warnings are unaffected.
4. Click **Stop & Review** when recording is complete. The tool saves the data and displays a quality result.

SPI Bridge, USB OTG and USJ use CDC serial reception on every platform. If no Bridge CDC port is found, reconnect the device and refresh the port list; the tool does not switch to direct USB Bulk.

Release executables exclude the Bulk reference implementation and PyUSB. The development-only reference is in `tools/spi_bulk_transport.py`; its dependency is included in the `test` extra.

On Linux, CDC access uses the serial port permissions (typically the `dialout` group). Run normally when your user can read and write the port. Close other programs using the Bridge first; if a previous Bulk receiver detached the serial driver, reconnect the Bridge after closing it.

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

On Windows, install Visual Studio Build Tools with **Desktop development with C++**
(MSVC and Windows SDK), then open a Developer Command Prompt in the source directory.
The bundled BLFD source package is compiled locally; Python 3.11 x64 is the reference
build target. These compiler tools are not needed to run a packaged executable.
Prepare the environment on first use:

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
| `--log-dir` | `-d` | Last used directory, or `./logs` | Recording file save directory; an explicit value overrides the remembered directory |
| `--debug` | none | off | Show extra debugging information |
| `--show-log` | none | none | Display `host`, `hci`, or `console`; repeat to select multiple categories, e.g. `--show-log host --show-log hci`. Does not change saved logs |

Subcommands:

| Command | Description |
| --- | --- |
| `ports` | List UART, SPI Bridge, USB Output, and USJ ports, and show CDC port permission issues. Use `--mode` to filter |
| `ls` | List `ble_log_*.bin` recording files in the specified directory |

`--output/-o` is still kept as a hidden option for compatibility with older versions. `--log-dir` is recommended.

### USJ Mode

USJ mode receives BLE Log through the chip's built-in USB Serial/JTAG port (USB ID `303A:1001`). `ports --mode usj` lists only ports with that USB ID. Interactive setup lists them alongside USB OTG ports under **USB**. The baud rate setting does not apply. The firmware must route BLE Log output to USB Serial/JTAG, which requires an ESP-IDF that offers `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG`; see [USJ configuration](./docs/Config-Guide-EN.md#usj).

On this port, the DTR and RTS lines control the chip's reset and boot mode. While opening the port, BLE Log Console releases RTS before DTR, the same order ESP-IDF Monitor uses to avoid a reset, then leaves both lines released and never changes them afterwards, so the `r` shortcut does not reset the target. The operating system or its USB driver can still change these lines while opening the device. Check on your own host whether opening the port resets the board.

The **Host dictionary** directory is remembered after recording starts successfully, including an explicitly cleared field. `--log-database` overrides the remembered choice. A missing dictionary falls back to automatic discovery. Source and standalone launches use the same per-user application settings.

### Opening Backlog and Analysis Files

Console observes opening snapshots during normal parsing in all transport modes; live logs and saved decoded logs retain the original stream. Within the first five seconds of received data, valid v8 snapshots must show a compressed device-time jump, advancing sequence/anchor counters, and then two stable intervals before old backlog is separated. Ambiguous evidence, unsupported metadata, a reset or a clock wrap prevents selection. Later gaps are never reclassified as opening backlog.

All received bytes remain in the original `.bin` files. During live parsing, the same decoded frames feed the full-recording check and a separate candidate-interval check. After the boundary is confirmed and raw saving finishes, Console uses the fresh interval result. The verdict and loss metrics then describe that interval, while byte/frame totals and parser coverage still describe the complete recording. The report gives the byte offset, timing evidence and original-stream missing-sequence count. Real losses after the boundary still affect the verdict. If the selected interval cannot be checked completely, the report falls back to the original-stream assessment with a warning.

Host task bindings no longer disable detection. The complete raw recording remains the analysis input, and the report records the selected offset. Console no longer creates an additional `_analysis.bin`. Stopping finalizes the checkers without rereading or copying the recording. Task bindings and log context remain intact. A fresh interval containing only snapshots reports zero ordinary log frames; this alone does not require another recording.

Detection uses clock and sequence evidence, not a device-provided queue boundary. An abnormal forward device-clock jump can look similar; short backlogs, missing snapshots or insufficient observation time may prevent detection. Original data and original-stream gap counts remain available for review.

### UART and USJ Console Text

UART and USJ ports can also carry plain console text, such as ROM boot messages or a panic dump. In these modes, bytes that cannot be decoded as BLE Log frames are shown in the log area and saved to `_console.log`, between `Undecoded data` markers (translated for the selected language). Printable ASCII is kept, colors are removed from the file, and line endings are normalized. A text line appears in the log area when it ends, when BLE Log data follows it, or when it reaches 16 KiB, so a line is never split by a screen refresh. A partial frame is not shown while it may still complete; any remaining undecoded tail is shown once when recording stops. This text is not counted as BLE Log frames. The raw `.bin` file keeps every byte the tool receives; if a transport or save failure is reported, the file may be incomplete. In every mode, if `_console.log` cannot be written or synchronized to storage, the tool warns once and stops writing that file. Enabled log categories continue displaying text. This error does not itself stop raw recording. The quality report states that the console log is incomplete and separately reports any raw recording failure.

The tool also identifies what the port carries:

- **Plain text:** The status bar shows `PLAIN TEXT` and a warning appears at once, then every 10 seconds while it continues. Recording continues. Plain text usually means that the firmware does not send BLE Log to this port.
- **BLE Log:** The status bar shows `BLE LOG` after one firmware identity record or three valid frames from known BLE Log sources. Text before that point, such as boot messages, is expected. Identification does not change back when the port is quiet or prints text later.

The quality report states the identified content and how much data arrived outside BLE Log frames. A frame that is cut off when recording stops is normal: its bytes are listed as trailing carried bytes and do not add this warning. Bytes outside BLE Log frames are written to the `.bin` file rather than to the console log, which holds at most their printable text; a write failure can leave them out of the file, and the quality report states whether the raw recording was confirmed complete. Identification alone does not make a recording ready for analysis: a recording that contains only identity records still requires a configuration check. SPI Bridge and USB Output modes do not show undecoded data or identification.

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

### Parser Core integration build

This branch uses the unified BLFD 1.0.0.dev0 package for streaming integrity checks and firmware statistics.
Linux x86_64 / CPython 3.11 uses the supplied wheel; Windows and other targets build the supplied source package from the same revision. See [vendor/README.md](vendor/README.md) for compiler requirements. Windows build and hardware validation remain pending.
