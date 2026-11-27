# BLE Log Configuration Guide

[中文](Config-Guide-CN.md) | [English](Config-Guide-EN.md)

> **Prefer direct USB** when the board has a connector for the selected USB peripheral or exposes its D+, D−, and GND for a USB connection, and the firmware supports USB OTG or USJ. Otherwise, use SPI Bridge or UART.

Download: [BLE Log Console stable release][ble-log-console] · [BLE Log Configuration Assistant stable release][ble-log-config-assistant]. For PC-side recording, see the [Console User Guide](Console-User-Guide-EN.md).

This guide helps determine a usable BLE Log sdkconfig and wiring setup based on the available hardware and peripheral usage. Start with the project's existing sdkconfig, determine the transport, port, GPIOs, and baud rate where applicable, then verify the setup with a trial recording. Available configuration options depend on the target chip and SDK version.

**Reading order: Select direct USB, SPI Bridge, or UART → Configure and wire → Verify a recording → Submit the files.**

[USJ configuration](#usj) · [USB OTG configuration](#usb) · [SPI configuration](#spi) · [UART configuration](#uart) · [Capture verification](#verification) · [Deliverables](#deliverables) · [Configuration record](#records) · [Buffers and log volume](#advanced)

## Quick Selection

| Priority | Conditions | Selection and next step |
| --- | --- | --- |
| 1. Direct USB (recommended) | The board exposes native USB and the firmware supports BLE Log on that peripheral. | Start with [USJ](#usj) if the board exposes it. Choose [USB OTG](#usb) for TinyUSB CDC. Select **USB** in Console for either. |
| 2. SPI Bridge | A separate Bridge and an available SPI peripheral with accessible MOSI, SCLK, CS, and GND are available. | Connect the two boards as shown in [SPI configuration](#spi). |
| 3. UART | An onboard USB-to-UART converter is available, or UART TX and GND are accessible for an external adapter. | Check the TX pin and matching baud rates in [UART configuration](#uart). |

### Simplify Setup with BLE Log Configuration Assistant (Recommended)

Once you choose a peripheral, you can run an interactive wizard in your project’s **ESP-IDF terminal** instead of editing Kconfig options manually:

1. Download the executable for your OS from the [BLE Log Configuration Assistant release page][ble-log-config-assistant] (on Linux, run `chmod +x` on first use).
2. Open an **ESP-IDF terminal where `idf.py` is available** (for an unconfigured project, run `idf.py reconfigure` once first), launch the assistant, and select your firmware project directory.
3. Choose your target peripheral (USB OTG / USJ / SPI Bridge / UART), review the previewed diff, and click **Apply configuration**:
   - The wizard handles dependent settings automatically (enabling critical-only logs for UART, disabling the secondary console for USJ, checking duplicate SPI pins, and prompting for the TinyUSB dependency on USB OTG).
   - Before saving, it backs up the original file as `sdkconfig.bak.*` while preserving unrelated settings and comments.
4. Build and flash the firmware as usual, complete the physical wiring, and proceed to [Capture verification](#verification).

> If running the assistant is inconvenient, or if you need wiring details and exact macro references, continue to the matching section below.

## 1. Direct USB Configuration (Recommended)

When the target chip supports native USB and the board exposes the matching connector, a single USB data cable delivers full BLE Log throughput without an external Bridge or UART baud-rate limits. When the board exposes both native USB interfaces, prefer **USJ**. For the chip support table and wiring diagram, see the [Console User Guide](Console-User-Guide-EN.md#usb-direct).

### 1.1 Connection Requirements

| Item | Requirement and explanation | Suggested action |
| --- | --- | --- |
| Native USB connector | **The board exposes the native USB connector for the chosen peripheral, or D+, D−, and GND can be wired out.**<br>A USB connector wired to an onboard USB-to-UART chip is for UART only, not direct USB. | Prefer USJ when the board exposes it; if neither is exposed, use [SPI](#spi) or [UART](#uart). |
| Chip and SDK support | **The target chip includes the peripheral, and the current ESP-IDF provides the corresponding output option.**<br>USJ uses `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG`; USB OTG uses `CONFIG_BLE_LOG_PRPH_USB`. | Use [SPI](#spi) or [UART](#uart) if your SDK lacks support. |
| Exclusive port access (for USJ) | **The USJ port is not used by a primary/secondary console, `esp_trace`, or OpenThread RCP, and `CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=y` remains enabled.**<br>Otherwise `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG` is hidden. | Free the USJ port if doing so does not affect issue reproduction; otherwise choose another transport. |
| Component and peripheral (for USB OTG) | **The project can include `espressif/esp_tinyusb` and has no conflicting custom USB OTG device stack.**<br>The PC will not enumerate the CDC port until the firmware initializes BLE Log at runtime. | Add the dependency with `idf.py add-dependency`; choose another transport if USB OTG conflicts. |

Once these requirements are met, update your project’s `sdkconfig` for the selected peripheral.

### 1.2 Configuration and Wiring

<a id="usj"></a>

#### USB Serial/JTAG (USJ)

| Configuration / connection | Value | Wiring / explanation |
| --- | --- | --- |
| `CONFIG_BLE_LOG_ENABLED` | `y` | Enable BLE Log. |
| `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG` | Not enabled | Keep the primary console on default UART0 or another channel. |
| `CONFIG_ESP_CONSOLE_SECONDARY_NONE` | `y` | Disable the secondary console to free the USJ port. |
| `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG` | `y` | Select USJ output (visible when the port is free and supported by the SDK). |
| USB | No configuration option | Chip’s native USJ port → PC (USB data cable, USB ID `303A:1001`). |

<a id="usb"></a>

#### USB OTG

| Configuration / connection | Value | Wiring / explanation |
| --- | --- | --- |
| TinyUSB component dependency | `espressif/esp_tinyusb^2.0.0` | If not yet added, run `idf.py add-dependency "espressif/esp_tinyusb^2.0.0"` from the project root. |
| `CONFIG_BLE_LOG_ENABLED` | `y` | Enable BLE Log. |
| `CONFIG_BLE_LOG_PRPH_USB` | `y` | Select USB OTG output (automatically enables TinyUSB CDC with default buffer sizes). |
| USB | No configuration option | Chip’s native USB OTG port → PC (USB data cable, USB ID `303A:10B1`). |

On older ESP-IDF versions that do not automatically enable CDC or that expose separate BLE Log CDC buffer options, enable `CONFIG_TINYUSB_CDC_ENABLED=y` and adjust buffer sizes per build messages.

### 1.3 Connect the Tool

After building and flashing the firmware, connect the matching native USB port with a data cable. In BLE Log Console, select **USB**, then pick the port labeled **USJ** or **USB OTG**.

**Next: [Capture verification](#verification).**

<a id="spi"></a>

## 2. SPI Log Configuration

SPI offers more bandwidth for larger log volumes, helping capture the information needed to locate problems. Connect the target board to a Bridge using three signal wires and GND, then connect the Bridge to the PC.

### 2.1 Connection Requirements

> **Check wiring access first.** An unused SPI controller does not necessarily mean its signals can be brought out. Check SPI resource availability after confirming that wiring is practical.

| Item | Requirement and explanation | Suggested action |
| --- | --- | --- |
| Wiring access | **Three signal wires and GND can be connected.**<br>Prefer existing connectors or test points. If disassembly or soldering is needed, assess whether this is practical at the capture location. | Use UART if the wiring cannot be added. |
| Bridge device | **A dedicated Bridge or an available ESP32P4 development board is required.**<br>The ESP32P4 board must run the matching Bridge firmware. The Bridge and target must be separate devices. | Prepare a Bridge; technical support may help with availability. Use UART if a Bridge cannot be prepared. |
| SPI resources | **Existing peripherals must not conflict, and disabling or changing them must not prevent reproduction of the problem.**<br>If the problem no longer occurs after the change, retain the original peripheral operating conditions. | Use UART if the required SPI resources cannot be freed. |
| GPIO locations | **Three usable GPIOs and GND must be accessible.**<br>Confirm GPIO numbers, physical locations, and suitability for the required output signals. Do not copy example pins without checking the board. | Fill in the configuration and wiring table. |

> **Resource constraint:** The current implementation uses SPI Controller 2. If the project already uses SPI peripherals, check whether they use the same controller.

If these requirements are met, select SPI output in the existing sdkconfig and determine the MOSI, SCLK, and CS GPIOs. Otherwise, see [UART configuration](#uart).

### 2.2 Configuration and Wiring

| Configuration / connection | Value | Wiring / explanation |
| --- | --- | --- |
| `CONFIG_BLE_LOG_ENABLED` | `y` | Enable BLE Log. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA` | `y` | Select SPI DMA output. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM` | **To be filled in: MOSI GPIO** | Target GPIO → Bridge IO 4. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM` | **To be filled in: CLK GPIO** | Target GPIO → Bridge IO 5. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM` | **To be filled in: CS GPIO** | Target GPIO → Bridge IO 6. |
| GND | No configuration option | Target GND → Bridge GND. |

These Bridge pins apply to the matching ESP32P4 Bridge firmware. Confirm compatible signal levels, keep wires short, and connect a common ground.

### 2.3 Connect the Tool

After building and flashing the firmware, select **SPI Bridge** in the PC tool. For Bridge preparation, see the [Console User Guide](Console-User-Guide-EN.md#3-spi-bridge-mode).

**Next: [Capture verification](#verification).**

<a id="uart"></a>

## 3. UART Log Configuration (Fallback)

Use UART when SPI connection requirements cannot be met. **Prefer the onboard USB-to-UART converter and existing logging UART to reduce extra wiring.** UART bandwidth is more limited; start with the bandwidth optimization setting and make a trial recording.

> **A UART used only for ordinary log output may also be reused.** The current UART0 path sends ordinary serial logs together with BLE Log to BLE Log Console for display and saving. Other UARTs do not automatically forward ordinary UART0 logs.

For log file details, see [Follow Live Logs](Console-User-Guide-EN.md#console-log-files) and [Find and Submit Recording Files](Console-User-Guide-EN.md#recording-files) in the Console User Guide.

### 3.1 Connection Requirements

| Item | Requirement and explanation | Suggested action |
| --- | --- | --- |
| Onboard USB-to-UART converter | Some boards connect a UART to a USB-to-UART chip, allowing connection to the PC by USB. Confirm the actual UART and TX GPIO. A chip's native USB port is not a USB-to-UART connection; for the built-in USB Serial/JTAG port, see [USJ Log](#usj). | Prefer an available onboard connection. |
| UART usage | A UART used only for ordinary logs may be reused. If it also handles command input, peripheral traffic, or fixture communication, check for conflicts. | Use the tool with a logging-only UART; prefer another UART if the existing one carries application communication. |
| Baud rate support | The USB-to-UART device must support the baud rate configured in the firmware. If uncertain, check the chip's documentation or run the script below. | First check support for 3000000, then make a trial recording at the same baud rate on both sides. |
| External connection points (without an onboard connection) | Confirm the available UART's TX GPIO and GND locations. The UART number and GPIO number must be checked separately. | Connect an external USB-to-UART adapter. |
| Resource changes (if already in use) | Disabling existing UART functions must not prevent reproduction of the problem. | If resources cannot be freed, assess another UART or transport. |

After confirming these items, select UART output in the existing sdkconfig and determine the UART number, TX GPIO, and baud rate.

**How to check supported baud rates**

BLE Log recommends starting with `3000000` to accommodate more logs. Check the **USB-to-UART chip or adapter connected to the PC**, whether onboard or external. If its support for this rate is uncertain, use either of the following methods.

| Method | What to do | How to use the result |
| --- | --- | --- |
| Identify the model | Find the exact model in the board schematic, chip marking, or adapter manual, then check its supported baud rates. If identification is difficult, provide the model, relevant documents, or a clear photo to technical support. | Check chip and driver documentation for `3000000` support. If unsupported, determine a lower rate supported by both sides. |
| Run the script | On the PC that will capture logs, connect the actual adapter, close programs using the port, and run the [baud rate probe script](skills/ble-log-intake/scripts/probe_uart_baudrates.py). It tries several baud rates; provide the complete output to technical support for assessment. | `ACCEPTED` means the PC could open the port with the requested setting. `FAIL` means that attempt failed; an occupied port, insufficient permissions, or a device connection error can also cause failure. |

> **A successful probe still requires a trial recording.** Accepting a baud rate setting does not prove stable log reception at that rate or establish the highest usable rate. Use the capture quality report to assess the connection with matching firmware and PC settings. Opening the serial port may reset some boards; confirm that the application can be interrupted before running the script.

### 3.2 Configuration and Wiring

| Configuration / connection | Value | Wiring / explanation |
| --- | --- | --- |
| `CONFIG_BT_LOG_CRITICAL_ONLY` | `y` | Enable bandwidth optimization, which also enables BLE Log. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA` | `y` | Select UART DMA output. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT` | **To be filled in: UART number** | Match the UART actually used for logs. For an onboard converter, verify which UART it connects to. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` | **To be filled in: TX GPIO** | Use the existing TX GPIO for an onboard connection. For an external adapter: target GPIO → adapter RX. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` | Prefer `3000000` | The adapter must support this rate, and the PC setting must match the firmware. Otherwise, select a rate supported by both sides. |
| GND | No configuration option | For an external adapter: target GND → adapter GND. Confirm compatible signal levels. |
| USB | No configuration option | USB port of the onboard converter or external adapter → PC. |

### 3.3 Connect the Tool

After building and flashing the firmware, close serial monitors using the port. In BLE Log Console, select **UART** and the corresponding port, using the same baud rate as the firmware. Repeat the trial recording after changing the rate.

**Next: [Capture verification](#verification).**

<a id="verification"></a>

## 4. Capture Verification

### 4.1 Check the Configuration and Make a Trial Recording

After reconfiguring and building, check the effective sdkconfig: the output mode must match the chosen transport, and GPIOs must match the wiring. For UART, also check the port and baud rate; for USJ, check that USB Serial/JTAG output is selected and that no console uses the port. Flash the firmware from this build before making a trial recording.

Run the BLE application and record briefly. Confirm that **RX and Frames keep increasing and the application operates normally**, then select **Stop & Review** to check the quality report.

> **Check application behavior during the trial as well.** Logging can affect timing. If application behavior or the problem changes, assess the effect of the configuration on reproduction. An intermittent problem not appearing during a short trial does not mean it has disappeared.

### 4.2 Assess the Capture Result

| Result | Suggested action |
| --- | --- |
| RX stays at 0 | Check that the firmware is running with logging enabled, then check the port, wiring, and power. |
| RX increases, but Frames does not | Check the transport mode, UART baud rate, and compatibility between the firmware and tool. |
| Status shows `PLAIN TEXT` (UART or USJ) | The port carries ordinary console text instead of BLE Log. Text before BLE Log starts is expected. If the warning repeats, check that the firmware sends BLE Log to this port. Recording continues. |
| Report says `READY FOR ANALYSIS` | Proceed to reproduce the problem. Still confirm that the recording contains the logs required for this investigation. |
| Report says `SAVED WITH WARNINGS` | Use the report to assess whether the warnings affect the investigation. Keep both the report and logs. |
| Report says `CHECK CONFIGURATION` or `RECORD AGAIN RECOMMENDED` | Follow the report's guidance. If the issue persists, contact technical support with the report and logs. |

### 4.3 Reproduce the Problem

For the full capture, **start recording before triggering the problem**. Note the approximate time of the problem and the actions performed.

<a id="deliverables"></a>

## 5. Deliverables and Files to Submit

### 5.1 Delivery Checklist

A complete delivery includes the recording files, the log database matching the firmware where required, and the [configuration record](#records).

| Deliverable (all modes) | When to include it |
| --- | --- |
| Raw `.bin` and matching `_report.txt` | Submit for every recording. Include every `part` of a split recording. |
| `<recording-name>_database/` | If a database was selected, include the copy alongside the matching recording. |
| `sdkconfig` and [configuration record](#records) | Include the build configuration, wiring, and reproduction details. |
| Generated log files | Include Host text, HCI btsnoop files, or live transcripts relevant to the issue. On UART and USJ, `_console.log` can include boot or panic text. |

### 5.2 Recording File Location

Files are written to **Save to** on the setup screen. It defaults to `logs/` under the working directory on first use, then remembers the selected directory. The report lists the file paths. See the [recording file table](Console-User-Guide-EN.md#recording-files) for suffixes and uses.

### 5.3 Log Database Location and Version

> **The log database must come from the same build as the firmware flashed onto the target.** The firmware build generates the originals. Console saves a copy of the selected database files alongside each recording.

| Build setup | Database location |
| --- | --- |
| Default build directory | `build/ble_log/ble_log_database/` |
| Custom build directory | `<build-directory>/ble_log/ble_log_database/` |
| Customized database path | `log_config.db_path` in `ble_log/module_info.yml` under the build directory, resolved relative to the build directory. |

The database contains files such as each module's `*_logs.json`. Archive and submit the **entire directory** with the logs.

Builds without compressed log modules may not generate a database. If a recording contains compressed logs but the matching database cannot be found, ask technical support to help identify the build artifacts. A database rebuilt after changing source code or configuration cannot be used as a substitute.

<a id="records"></a>

## 6. Configuration Record

Save the verified sdkconfig together with the wiring and receiver settings for subsequent captures. Verify again after changing hardware or configuration.

| Item | Information to record |
| --- | --- |
| Versions | Target chip, SDK, BLE Log Console, and Bridge firmware version (if used). |
| Firmware configuration | sdkconfig from the build that passed capture verification. |
| Hardware connection | USB OTG / USJ / SPI / UART, GPIOs, and physical connection points. |
| Receiver settings | PC-side mode, port, and UART baud rate. |
| Capture result | Log files, quality report, time of the problem, and actions performed. |

<a id="advanced"></a>

## Appendix: Additional Configuration (USB OTG / USJ / SPI / UART)

Buffers hold logs awaiting transmission and absorb short bursts to help reduce log loss. Log levels and source switches control the amount and content of logs.

> **For typical use, retain defaults or previously confirmed settings.** For high throughput, multiple connections, limited memory, or more detailed logging, technical support can assess adjustments using the sdkconfig, application load, and quality report.

### Buffer Configuration

| Buffer configuration option | Current default | Purpose and effect of changes |
| --- | --- | --- |
| `CONFIG_BLE_LOG_POOL_TRANS_CNT` | `8` | Number of transmission buffers. More buffers can accommodate larger bursts but consume more memory. |
| `CONFIG_BLE_LOG_POOL_TRANS_SIZE` | `640` bytes | Size of each transmission buffer. A single log frame must fit entirely in one buffer. Increasing the size consumes more memory; SPI mode requires a multiple of 4. |
| `CONFIG_BLE_LOG_POOL_NON_YIELD_RESERVE_CNT` | `1` | Buffers reserved for contexts that cannot wait, such as interrupts and critical sections. Increasing this reduces buffers available to ordinary tasks. It must be less than the total buffer count. |

Buffers cannot solve sustained log generation exceeding transport capacity and do not guarantee zero loss. The defaults above are not intended to overwrite previously confirmed settings.

### Log Levels and Sources

| Log configuration option | Purpose | Configuration notes |
| --- | --- | --- |
| `CONFIG_BT_LOG_CRITICAL_ONLY` | Enable bandwidth optimization to reduce log volume. | Enable for UART as shown above. If more detailed logs are needed, technical support should assess log coverage and transport capacity. |
| `CONFIG_BT_LE_CONTROLLER_LOG_OUTPUT_LEVEL` / `CONFIG_BT_CTRL_LE_LOG_LEVEL` | Control the Controller log level. | Applicable options and level meanings depend on the chip, Controller, and SDK. Numeric values do not provide a universal indication of log volume. |
| NimBLE log level / Bluedroid module Trace Levels | Control Host log detail. | Examples include `CONFIG_BT_NIMBLE_LOG_LEVEL_INFO` and `CONFIG_BT_LOG_HCI_TRACE_LEVEL_EVENT`. More detailed logs generally require more bandwidth. |
| `CONFIG_BLE_LOG_HOST_LOG`, `CONFIG_BLE_LOG_LL_ENABLED`, `CONFIG_BLE_LOG_HCI_LOG_ENABLED` | Control Host, link-layer, and HCI log sources. | Disabling a source can reduce log volume but may remove information needed for diagnosis. Availability depends on the protocol stack and Controller configuration. |

Switching between USB OTG, USJ, SPI, and UART does not automatically restore existing log levels. Log coverage must include the problem being investigated. Verify transport quality with a trial recording after adjustments.

[ble-log-console]: https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable
[ble-log-config-assistant]: https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_config_assistant_stable
