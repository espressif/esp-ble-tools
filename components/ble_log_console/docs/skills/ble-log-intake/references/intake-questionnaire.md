# BLE Log Intake Questionnaire

Use this questionnaire to determine the log transport, sdkconfig, and wiring, and to record capture results. Fill in known information, mark uncertain facts as “Pending confirmation”, and explain why any section is not applicable.

> **For this round, supply only information marked “Pending confirmation”.** Trial and delivery details can be completed after capture; mark them “After capture” until then.

| Current situation | Details |
| --- | --- |
| Transport | Undecided / SPI / UART |
| Status | Information incomplete / Configured, pending trial / Verified |
| Information still needed this round | To be filled in |

## 1. Existing Project Information

Reuse information available in the project or previous communication.

| Item | Instructions and purpose | Response/material |
| --- | --- | --- |
| Chip and board | Chip model and board/product revision; used to check peripherals and physical wiring. | To be filled in |
| SDK version | Branch, commit, or release, including BLE Log patches; used to check settings and implementation. | To be filled in |
| Current sdkconfig | The file and configuration sources actually used by this build; used to generate the minimum configuration diff. | To be filled in |
| Problem to investigate | Symptoms, reproduction steps, frequency, and relevant startup, restart, or sleep stages; used to determine the capture window. | To be filled in |

## 2. Transport Selection

Prefer SPI. Assess UART when SPI cannot be implemented.

| Item | Instructions and purpose | Response/material |
| --- | --- | --- |
| SPI wiring access | Three signal wires and GND are needed. If impractical, state whether connectors are inaccessible, soldering or disassembly is needed, disassembly is prohibited, or connection points are unknown. | To be filled in |
| Bridge availability | Existing SPI USB Bridge, available separate ESP32P4 development board, equipment that can be prepared, or unavailable; used to assess receiver readiness. | To be filled in |
| Reason for UART (UART only) | For example, extra wiring is impossible, SPI resources conflict, or no Bridge is available; records the selection rationale. | To be filled in |

## 3. SPI Information (SPI Only)

Use one wiring record for all three GPIOs. Mark this section “Not applicable” when SPI is not selected.

| Item | Instructions and purpose | Response/material |
| --- | --- | --- |
| Existing SPI peripherals | Whether SPI is used and which devices it connects to. If unknown, provide the relevant schematic or initialization code for technical support to check conflicts. | To be filled in |
| Peripheral changes (if conflicting) | Whether peripherals can be temporarily disabled or changed while keeping the original problem reproducible; determines whether resources can be freed. | To be filled in |
| MOSI GPIO and location | GPIO number and connector/test point; maps to MOSI configuration and matching Bridge IO 4. | To be filled in |
| CLK GPIO and location | GPIO number and connector/test point; maps to SCLK configuration and matching Bridge IO 5. | To be filled in |
| CS GPIO and location | GPIO number and connector/test point; maps to CS configuration and matching Bridge IO 6. | To be filled in |
| GND location | Common-ground connection points on the target and Bridge; completes the wiring table. | To be filled in |
| GPIO availability evidence | Schematic, hardware confirmation, or wiring documentation showing both availability and physical access. sdkconfig values alone do not confirm wiring. | To be filled in |
| Bridge status | Board model, matching firmware version, and whether it has been flashed; confirms pin definitions and receiver readiness. | To be filled in |

## 4. UART Information (UART Only)

Prefer an onboard USB-to-UART converter. Either model documentation or probe results can support baud rate selection. Mark this section “Not applicable” when UART is not selected.

| Item | Instructions and purpose | Response/material |
| --- | --- | --- |
| UART usage | Logging only, unused, or also used for AT commands, command input, peripheral/fixture communication; determines whether it can be reused. | To be filled in |
| UART number | UART actually used for log output; maps to the port setting and is distinct from the GPIO number. | To be filled in |
| TX GPIO and wiring | Actual TX GPIO and whether it connects to the RX of the converter used for this capture; maps to TX configuration. Include a relevant schematic or hardware confirmation if available. | To be filled in |
| GND connection | Common-ground location for an external adapter, or confirmation of the onboard connection. | To be filled in |
| Receiver and PC port | Onboard/external converter, actual USB connector, and PC port name such as COM3; avoids selecting the wrong device. Native USB is not a USB-to-UART converter. | To be filled in |
| Baud rate evidence (either source) | Exact chip/tool model and documentation, or complete probe output including errors from the actual capture PC. A photo may help identify an unknown model. | To be filled in |
| Capture PC operating system | Windows/Linux and version; used to provide suitable commands and investigate driver issues. | To be filled in |
| UART changes (if conflicting) | Whether its existing role can be paused without affecting reproduction. A conflicting UART that cannot be freed cannot simply be switched to logging. | To be filled in |

> `ACCEPTED` from the probe only means the driver accepted the request. It proves neither stable transfer nor that the highest rate should be chosen. Verify the final rate with a trial recording.

## 5. Special Scenarios (As Needed)

Use this section when technical support needs to assess buffers, log levels, or resource changes; customers need not choose parameters themselves. Mark it “Not applicable” for ordinary cases. Complete it for log loss, insufficient memory, changed application behavior, or specific additional diagnostic needs.

| Item | Instructions and purpose | Response/material |
| --- | --- | --- |
| Load when the problem occurs | Connection count, throughput, concurrent activity, and ordinary log volume; provide only relevant details. | To be filled in |
| Existing custom settings | Changed buffers, log levels, or sources, with reasons; extract values already present in sdkconfig. | To be filled in |
| Resource or capture problems | Memory status, initialization errors, loss reports, or missing diagnostic logs; used to determine whether and how settings should change. | To be filled in |

## 6. Trial Recording Results (After Capture)

| Item | Instructions and purpose | Response/material |
| --- | --- | --- |
| Effective configuration | sdkconfig and firmware version used for this build; confirms that the intended configuration was applied and flashed. | After capture |
| Tool settings | BLE Log Console version, SPI/UART mode, receiver port, and UART baud rate where applicable; checks that both ends agree. | After capture |
| Reception | Whether RX and Frames keep increasing; distinguishes no input from parsing failure. | After capture |
| Application and reproduction | Whether normal operation continues, whether the problem occurred, its time, and actions taken; assesses whether logging changed the conditions. | After capture |
| Quality report | Complete `_report.txt` and matching recording files; assesses capture quality beyond visible incoming data. | After capture |

## 7. Final Delivery (After Capture)

Locations below are search hints, not confirmation that files exist. Record the actual paths used for this capture and build. Relative build paths are relative to the firmware project; the tool's startup directory may be elsewhere.

| File/information | Required when | Likely location / how to find it | Actual path/filename and status |
| --- | --- | --- | --- |
| Raw `ble_log_*.bin` | UART and SPI; include every part of the same recording. | Save directory selected at recording start; defaults to `<tool-start-directory>/logs/`. The tool prints actual paths on exit. | After capture |
| `ble_log_*_report.txt` | UART and SPI; must match the `.bin`. | Same recording directory as the `.bin`. | After capture |
| `ble_log_*_console.log` | Include if generated; currently absent for SPI and generated for UART only when redirected ordinary logs are received. | Same recording directory as the `.bin`; it may legitimately be absent. | After capture |
| Entire `ble_log_database/` directory | Required for compressed logs. | Usually `<firmware-project>/build/ble_log/ble_log_database/`; for a custom build directory, `<build-directory>/ble_log/ble_log_database/`. If customized, read `log_config.db_path` in `<build-directory>/ble_log/module_info.yml` and resolve it relative to the build directory. This is a firmware build artifact, not a recording-directory output. | After capture |
| Database/firmware match | Database must come from the same build as the flashed firmware. | Record the original build or archived artifact location and firmware identity. A directory name alone cannot establish a match; a rebuild after source/configuration changes is not a substitute. | After capture |
| sdkconfig | Actual configuration of the captured firmware. | Usually `<firmware-project>/sdkconfig`; if the build overrides `SDKCONFIG`, use that path from the build invocation or `<build-directory>/CMakeCache.txt`. Defaults files alone do not establish the effective configuration. | After capture |
| Wiring and version record | Actual target wiring and SDK/tool/Bridge versions where applicable. | Reuse this questionnaire and existing project/support records. No automatically generated directory is assumed; state where the completed record is saved. | After capture |
| Problem time and actions | Needed to locate the problem in the logs. | Trial/full-capture notes or this questionnaire; record the saved note's path or include the details here. | After capture |
