# BLE Log Console

BLE Log Console is a Textual-based TUI tool for real-time capture, parsing, display, and storage of ESP BLE logs.

It supports two transport modes:

- **UART** for serial BLE Log output.
- **SPI Bridge** for BLE Log data forwarded by a BLE Log SPI USB Bridge device.

**User Guide**: [English](./docs/User-Guide-EN) | [中文](./docs/User-Guide-CN.md)

## Features

- Interactive Launch Screen for transport mode, port, baud rate, and log directory.
- UART and SPI Bridge capture support.
- Endpoint discovery with `python console.py ports`.
- Real-time BLE Log frame parsing.
- Raw `.bin` capture saved before parsing.
- UART PORT 0 `ESP_LOG` redirect display and optional `_console.log` output.
- Live status panel with connection, captured RX bytes, speed, frame rate, and firmware-reported loss statistics.
- Per-source frame statistics and buffer-utilization views.
- Versioned standalone executable packaging.

## Firmware and Hardware Setup

### UART

Recommended target firmware configuration:

```text
CONFIG_BT_LOG_CRITICAL_ONLY=y
CONFIG_BLE_LOG_PRPH_UART_DMA=y
CONFIG_BLE_LOG_PRPH_UART_DMA_PORT=0
CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE=3000000
CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM=0
```

`CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` sets the GPIO for the UART TX signal. The baud rate selected in BLE Log Console must match `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE`.

Basic wiring:

```text
ESP32 TX GPIO  ->  USB-Serial RX
ESP32 GND      ->  USB-Serial GND
```

### SPI Bridge

SPI Bridge mode requires an additional BLE Log SPI USB Bridge device. The Bridge forwards BLE SPI Log data from the target device to the PC and is currently supported by `ESP32P4`.

Bridge device options:

- Flash an `ESP32P4` development board on the [Bridge firmware download](https://espressif.github.io/esp-launchpad/?flashConfigURL=https://dl.espressif.com/ble/ble_log/spi_bridge_bin/launchpad.toml&crossDomain=true) page.
- Purchase or apply for a Bridge device through official channels.

The Bridge device cannot be the same device that generates BLE Log data.

Target firmware configuration:

```text
CONFIG_BLE_LOG_ENABLED=y
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA=y
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM=<target MOSI GPIO>
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM=<target SCLK GPIO>
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM=<target CS GPIO>
```

Default Bridge wiring:

| Target signal | Bridge pin |
| --- | --- |
| MOSI | IO 4 |
| SCLK | IO 5 |
| CS | IO 6 |
| GND | GND |

## Running

### Launcher scripts

Prepare the source environment once, then use the launcher script.

```bash
# Linux / macOS
./install.sh
./run.sh

# Windows
.\install.bat
.\run.bat
```

### Command line

```bash
# List endpoints
python console.py ports
python console.py ports --mode uart
python console.py ports --mode spi

# UART
python console.py --mode uart --port /dev/ttyUSB0 --baudrate 3000000

# SPI Bridge
python console.py --mode spi --port <PORT>
```

`spi` selects the SPI Bridge transport.

## CLI Reference

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--mode` | `-m` | `uart` | Transport mode: `uart` or `spi` |
| `--port` | `-p` | optional | Transport endpoint. Omit to use Launch Screen |
| `--baudrate` | `-b` | `3000000` | UART baud rate |
| `--log-dir` | `-d` | `./logs` | Capture output directory |
| `--debug` | none | off | Show extra parser, traffic, and firmware-state debug events |

Subcommands:

- `ports`: list UART and SPI Bridge endpoints
- `ls`: list saved `ble_log_*.bin` captures

## Saved Files

Default capture files:

```text
logs/ble_log_YYYYMMDD_HHMMSS.bin
logs/ble_log_YYYYMMDD_HHMMSS_part002.bin
```

When UART PORT 0 `REDIR` text logs are present:

```text
logs/ble_log_YYYYMMDD_HHMMSS_console.log
logs/ble_log_YYYYMMDD_HHMMSS_console_part002.log
```

Raw `.bin` capture is saved before realtime parsing. High realtime traffic notices mean live parsing or UI display may lag behind raw capture; if raw saving itself cannot keep up, the app reports a raw writer or reader backpressure error.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` / `Ctrl+C` | Quit |
| `c` | Clear log view |
| `s` | Toggle auto-scroll |
| `d` | Show received log statistics |
| `m` | Show buffer utilization |
| `h` | Show shortcut help |
| `r` | Reset target device; not supported in SPI Bridge mode |

## Building Executable

Run `install.sh` or `install.bat` once before building.

```bash
# Linux / macOS
./build.sh

# Windows
.\build.bat
```

The build scripts reuse the prepared local environment, run `build_exe.py` with the current `VERSION`, move the standalone executable to the caller's working directory, and clean up intermediate files.

Output executable names include platform and version:

```text
ble_log_console_ubuntu_v1.0.2
ble_log_console_macos_v1.0.2
ble_log_console_windows_v1.0.2.exe
```

Direct `build_exe.py` usage:

```bash
python build_exe.py
python build_exe.py --bump-patch
python build_exe.py --version 1.2.3
```

## Development

```bash
./install.sh
uv run --extra test pytest tests/ -v
```

## Troubleshooting

### Device is not shown in port list

- Check power, wiring, and whether the port is occupied.
- For SPI Bridge, check SPI wiring and shared GND.
- On Linux, install the SPI Bridge USB permission rule once, then replug the Bridge device.

### No logs appear

- Check transport mode and port selection.
- Check BLE Log firmware configuration.
- In UART mode, check baud rate.
- In SPI Bridge mode, check MOSI/SCLK/CS GPIO configuration and wiring.
