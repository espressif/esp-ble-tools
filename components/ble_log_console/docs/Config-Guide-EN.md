# BLE Log Configuration Guide

[中文](Config-Guide-CN.md) | [English](Config-Guide-EN.md)

> **Use SPI first. Use UART when wiring or other SPI requirements cannot be met.**

Download: [BLE Log Console stable release][ble-log-console]. For PC-side operation, see the [Console User Guide](Console-User-Guide-EN.md).

This guide helps determine a usable BLE Log sdkconfig and wiring setup based on the available hardware and peripheral usage. Start with the project's existing sdkconfig, determine the transport, port, GPIOs, and baud rate where applicable, then verify the setup with a trial recording. Available configuration options depend on the target chip and SDK version.

**Reading order: Select SPI or UART → Configure and wire → Verify a recording → Submit the files.**

[SPI configuration](#spi) · [UART configuration](#uart) · [Capture verification](#verification) · [Deliverables](#deliverables) · [Configuration record](#records) · [Buffers and log volume](#advanced)

## Quick Selection

Once a transport is selected, read its SPI or UART section, then continue to capture verification. Buffer and log level adjustments are covered in the appendix.

| Priority | Conditions | Selection and next step |
| --- | --- | --- |
| 1. Prefer SPI | Three signal wires and GND can be connected, SPI resources are available, and a Bridge device is available. | Connect the Bridge and use [SPI Log](#spi). |
| 2. Reuse an existing serial connection | SPI requirements cannot be met; the UART connected to the onboard USB-to-UART converter is available for BLE Log and supports the required baud rate. | Use [UART Log](#uart), usually without extra wiring. A UART used only for ordinary log output may also be reused. |
| 3. Use an external USB-to-UART adapter | The onboard connection cannot be reused, but a UART and accessible TX and GND connections are available. | Connect an external adapter and use [UART Log](#uart). |
| 4. No available transport | None of the above conditions can be met. | Contact technical support to assess a feasible configuration using the sdkconfig and hardware constraints already collected. |

<a id="spi"></a>

## 1. SPI Log Configuration (Recommended)

SPI offers more bandwidth for larger log volumes, helping capture the information needed to locate problems. Connect the target board to a Bridge using three signal wires and GND, then connect the Bridge to the PC.

### 1.1 Connection Requirements

> **Check wiring access first.** An unused SPI controller does not necessarily mean its signals can be brought out. Check SPI resource availability after confirming that wiring is practical.

| Item | Requirement and explanation | Suggested action |
| --- | --- | --- |
| Wiring access | **Three signal wires and GND can be connected.**<br>Prefer existing connectors or test points. If disassembly or soldering is needed, assess whether this is practical at the capture location. | Use UART if the wiring cannot be added. |
| Bridge device | **A dedicated Bridge or an available ESP32P4 development board is required.**<br>The ESP32P4 board must run the matching Bridge firmware. The Bridge and target must be separate devices. | Prepare a Bridge; technical support may help with availability. Use UART if a Bridge cannot be prepared. |
| SPI resources | **Existing peripherals must not conflict, and disabling or changing them must not prevent reproduction of the problem.**<br>If the problem no longer occurs after the change, retain the original peripheral operating conditions. | Use UART if the required SPI resources cannot be freed. |
| GPIO locations | **Three usable GPIOs and GND must be accessible.**<br>Confirm GPIO numbers, physical locations, and suitability for the required output signals. Do not copy example pins without checking the board. | Fill in the configuration and wiring table. |

> **Resource constraint:** The current implementation uses SPI Controller 2. If the project already uses SPI peripherals, check whether they use the same controller.

If these requirements are met, select SPI output in the existing sdkconfig and determine the MOSI, SCLK, and CS GPIOs. Otherwise, see [UART configuration](#uart).

### 1.2 Configuration and Wiring

| Configuration / connection | Value | Wiring / explanation |
| --- | --- | --- |
| `CONFIG_BLE_LOG_ENABLED` | `y` | Enable BLE Log. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA` | `y` | Select SPI DMA output. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM` | **To be filled in: MOSI GPIO** | Target GPIO → Bridge IO 4. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM` | **To be filled in: CLK GPIO** | Target GPIO → Bridge IO 5. |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM` | **To be filled in: CS GPIO** | Target GPIO → Bridge IO 6. |
| GND | No configuration option | Target GND → Bridge GND. |

These Bridge pins apply to the matching ESP32P4 Bridge firmware. Confirm compatible signal levels, keep wires short, and connect a common ground.

### 1.3 Connect the Tool

After building and flashing the firmware, select **SPI Bridge** in the PC tool. For Bridge preparation, see the [Console User Guide](Console-User-Guide-EN.md#3-spi-bridge-mode).

**Next: [Capture verification](#verification).**

<a id="uart"></a>

## 2. UART Log Configuration (Fallback)

Use UART when SPI connection requirements cannot be met. **Prefer the onboard USB-to-UART converter and existing logging UART to reduce extra wiring.** UART bandwidth is more limited; start with the bandwidth optimization setting and make a trial recording.

> **A UART used only for ordinary log output may also be reused.** The current UART0 path sends ordinary serial logs together with BLE Log to BLE Log Console for display and saving. Other UARTs do not automatically forward ordinary UART0 logs.

For log file details, see “View Console Logs” and “Find and Submit Recording Files” in the [Console User Guide](Console-User-Guide-EN.md).

### 2.1 Connection Requirements

| Item | Explanation | Suggested action |
| --- | --- | --- |
| Onboard USB-to-UART converter | Some boards connect a UART to a USB-to-UART chip, allowing connection to the PC by USB. Confirm the actual UART and TX GPIO. A native USB port is not the same as a USB-to-UART connection. | Prefer an available onboard connection. |
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

### 2.2 Configuration and Wiring

| Configuration / connection | Value | Wiring / explanation |
| --- | --- | --- |
| `CONFIG_BT_LOG_CRITICAL_ONLY` | `y` | Enable bandwidth optimization, which also enables BLE Log. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA` | `y` | Select UART DMA output. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT` | **To be filled in: UART number** | Match the UART actually used for logs. For an onboard converter, verify which UART it connects to. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` | **To be filled in: TX GPIO** | Use the existing TX GPIO for an onboard connection. For an external adapter: target GPIO → adapter RX. |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` | Prefer `3000000` | The adapter must support this rate, and the PC setting must match the firmware. Otherwise, select a rate supported by both sides. |
| GND | No configuration option | For an external adapter: target GND → adapter GND. Confirm compatible signal levels. |
| USB | No configuration option | USB port of the onboard converter or external adapter → PC. |

### 2.3 Connect the Tool

After building and flashing the firmware, close serial monitors using the port. In BLE Log Console, select **UART** and the corresponding port, using the same baud rate as the firmware. Repeat the trial recording after changing the rate.

**Next: [Capture verification](#verification).**

<a id="verification"></a>

## 3. Capture Verification

### 3.1 Check the Configuration and Make a Trial Recording

After reconfiguring and building, check the effective sdkconfig: the output mode must match the chosen transport, and GPIOs must match the wiring. For UART, also check the port and baud rate. Flash the firmware from this build before making a trial recording.

Run the BLE application and record briefly. Confirm that **RX and Frames keep increasing and the application operates normally**, then select **Stop & Review** to check the quality report.

> **Check application behavior during the trial as well.** Logging can affect timing. If application behavior or the problem changes, assess the effect of the configuration on reproduction. An intermittent problem not appearing during a short trial does not mean it has disappeared.

### 3.2 Assess the Capture Result

| Result | Suggested action |
| --- | --- |
| RX stays at 0 | Check that the firmware is running with logging enabled, then check the port, wiring, and power. |
| RX increases, but Frames does not | Check the transport mode, UART baud rate, and compatibility between the firmware and tool. |
| Report says `READY FOR ANALYSIS` | Proceed to reproduce the problem. Still confirm that the recording contains the logs required for this investigation. |
| Report says `SAVED WITH WARNINGS` | Use the report to assess whether the warnings affect the investigation. Keep both the report and logs. |
| Report says `CHECK CONFIGURATION` or `RECORD AGAIN RECOMMENDED` | Follow the report's guidance. If the issue persists, contact technical support with the report and logs. |

### 3.3 Reproduce the Problem

For the full capture, **start recording before triggering the problem**. Note the approximate time of the problem and the actions performed.

<a id="deliverables"></a>

## 4. Deliverables and Files to Submit

### 4.1 Delivery Checklist

A complete delivery includes the recording files, the log database matching the firmware where required, and the [configuration record](#records).

| Deliverable | UART | SPI | Purpose |
| --- | --- | --- | --- |
| `ble_log_*.bin` | **Required** | **Required** | Raw BLE Log, including all `part` files. |
| `ble_log_*_report.txt` | **Required** | **Required** | Quality report from the same recording. |
| `ble_log_*_console.log` | Include if generated | Currently not generated | Readable copy of ordinary serial logs; does not replace `.bin`. |
| Entire `ble_log_database/` directory | Required for compressed logs | Required for compressed logs | Database needed to decode compressed logs. |
| `sdkconfig` and configuration record | **Required** | **Required** | Firmware configuration, versions, and reproduction details; see [Configuration record](#records). |

### 4.2 Recording File Location

Recordings are saved in the directory selected when starting a recording. The default is `logs/` under the directory from which the tool was started. The tool prints the actual file paths when it exits.

- `.bin`, `_report.txt`, and any generated `_console.log` are saved in the same directory and must come from **the same recording**.
- For split recordings, include **all `part` files**.
- UART generates `_console.log` only when redirected ordinary logs are received. The file may be absent when using another UART or when no such logs are received.

### 4.3 Log Database Location and Version

> **The log database must come from the same build as the firmware flashed onto the target.** It is generated by the firmware build and is not in the PC tool's recording directory.

| Build setup | Database location |
| --- | --- |
| Default build directory | `build/ble_log/ble_log_database/` |
| Custom build directory | `<build-directory>/ble_log/ble_log_database/` |
| Customized database path | `log_config.db_path` in `ble_log/module_info.yml` under the build directory, resolved relative to the build directory. |

The database contains files such as each module's `*_logs.json`. Archive and submit the **entire directory** with the logs.

Builds without compressed log modules may not generate a database. If a recording contains compressed logs but the matching database cannot be found, ask technical support to help identify the build artifacts. A database rebuilt after changing source code or configuration cannot be used as a substitute.

<a id="records"></a>

## 5. Configuration Record

Save the verified sdkconfig together with the wiring and receiver settings for subsequent captures. Verify again after changing hardware or configuration.

| Item | Information to record |
| --- | --- |
| Versions | Target chip, SDK, BLE Log Console, and Bridge firmware version (if used). |
| Firmware configuration | sdkconfig from the build that passed capture verification. |
| Hardware connection | SPI / UART, GPIOs, and physical connection points. |
| Receiver settings | PC-side mode, port, and UART baud rate. |
| Capture result | Log files, quality report, time of the problem, and actions performed. |

<a id="advanced"></a>

## Appendix: Additional Configuration (SPI / UART)

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

Switching between SPI and UART does not automatically restore existing log levels. Log coverage must include the problem being investigated. Verify transport quality with a trial recording after adjustments.

[ble-log-console]: https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable
