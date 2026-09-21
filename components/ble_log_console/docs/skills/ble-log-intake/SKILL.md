---
name: ble-log-intake
description: Prepare BLE Log intake questionnaires, identify missing hardware and project information, and map confirmed answers to SPI or UART sdkconfig, wiring, and capture verification. Use for setup consultations, UART baud rate assessment, and delivery checks, not log root-cause analysis.
---

# BLE Log Intake Assistant

Turn available information into a questionnaire that can be filled in and handed over, then map confirmed answers to a configuration for trial recording. Use English by default, or the user's requested language. Keep questions short and explain what each answer is used for.

## Read the Basis First

Before assessing a setup, read the [BLE Log Configuration Guide](../../Config-Guide-EN.md). The guide owns configuration tables, wiring, and delivery requirements; this skill owns information collection and mapping.

If the skill was copied separately, look for `components/ble_log_console/docs/Config-Guide-EN.md` in the current project. If unavailable, ask for the guide or its repository location. You may list missing information, but cannot claim the configuration has been checked without its supporting material. Scripts are in this skill's `scripts/` directory.

Collect existing sdkconfig, chip and SDK versions, board wiring, peripheral usage, receiver tools, and reproduction details. Reuse supplied information. Check chip support and configuration dependencies against the project's Kconfig and implementation instead of asking customers questions that can be answered internally. If the customer's branch differs from the guide, explain the differences and verify settings against that branch.

## Follow the Feasible Transport

Prefer SPI, then reuse an existing logging UART, then consider an external USB-to-UART adapter. Advance only the currently feasible branch. If SPI cannot be wired, proceed directly to UART; if SPI is feasible, do not add a UART questionnaire.

| Decision | Information needed now | Result |
| --- | --- | --- |
| Can SPI be implemented? | Whether three signal wires and GND can be connected and a Bridge can be prepared. | Whether SPI assessment can continue; an unused SPI controller does not establish wiring access. |
| SPI resources and GPIOs | Existing SPI peripherals, three available GPIOs, and physical connection points. | Output mode, MOSI/CLK/CS settings, and Bridge wiring. Request only the relevant schematic or initialization code if unclear. |
| Can UART be reused? | UART usage, UART number, TX wiring, and onboard or external converter. | Port and TX settings; ordinary logging alone is not an application conflict. |
| UART baud rate candidates | Converter/tool model, or complete output from the probe script below. | Candidate rates and strength of evidence; a trial recording is still required. |

Absence of a resource conflict in inspected code does not prove availability. Port and GPIO values in sdkconfig do not confirm physical wiring. An available UART and GPIO do not prove that TX connects to the receiver being probed. If extra wiring is impossible, confirm that the existing connection can be reused. Native USB is not a USB-to-UART converter. Changing existing peripherals is feasible only if the problem remains reproducible.

For each gap, name the specific material and its purpose, such as confirming the TX GPIO to fill in the UART TX setting. Collect each item once even if it supports several settings. Keep unknowns pending confirmation. If a confirmed conflict cannot be resolved, summarize the constraints for technical support instead of asking the customer to try parameter combinations.

## Prepare the Complete Questionnaire

When creating or updating a questionnaire, read the [intake questionnaire template](references/intake-questionnaire.md). It is the source of questionnaire fields for project information, transport selection, SPI, UART, trial recording, and delivery.

- Produce a complete questionnaire for the current scenario, rather than isolated follow-up questions. Fill the response column with known information and its filename or confirmation source; mark unconfirmed facts as “Pending confirmation”.
- Blank fields mean unanswered, not “unused”, “supported”, or “passed”. Extract project information from sdkconfig and the conversation without requesting it again.
- Expand only the needed SPI or UART branch. Retain other branch headings with “Not applicable” and a reason. If the transport is undecided, resolve feasibility before requesting every field for both interfaces. Include all branches when the user explicitly requests a generic blank form.
- Retain trial recording and delivery sections at the end, marked “After capture” until that stage. Expand special scenarios only when their conditions apply; otherwise mark them “Not applicable”.
- Precede the questionnaire with a short list of information still needed this round. Preserve known context for handover and explain each question's purpose alongside it without creating a duplicate questionnaire.
- Verify chip capabilities, Kconfig dependencies, and field mapping yourself, then state conclusions after the questionnaire. Customers supply physical hardware and operating conditions; they need not select technical parameters.

## UART Baud Rates: Either Evidence Source Is Enough

When the model is known, check manufacturer documentation and current driver conditions to identify candidate rates. If the model is unknown or running a script is easier, provide [probe_uart_baudrates.py](scripts/probe_uart_baudrates.py) for the actual capture PC and adapter. Do not additionally require the model when usable probe results already exist; request more information only for errors or insufficient evidence.

Customer instructions must include:

- Close serial monitors and BLE Log Console using the port, and confirm the actual port name.
- The script does not transmit or receive application data, but opening the port may change DTR/RTS and reset some boards. Run it when the application can be interrupted. A setup consultation does not authorize the AI to operate connected hardware.
- Python and `pyserial` are required, and the port must be specified explicitly. Run these commands from the script directory; skip installation if the dependency is already available.

Windows:

```powershell
py -m pip install pyserial
py probe_uart_baudrates.py COM3 > uart_baudrates.txt 2>&1
```

Linux:

```bash
python3 -m pip install pyserial
python3 probe_uart_baudrates.py /dev/ttyUSB0 > uart_baudrates.txt 2>&1
```

If the system requires a virtual environment, install into an existing Python environment or a virtual environment instead of bypassing package management restrictions. Request the complete `uart_baudrates.txt`, including errors. COM3 and `/dev/ttyUSB0` are example ports.

Interpret results within these limits:

| Result | Supported conclusion | Next step |
| --- | --- | --- |
| `ACCEPTED` | The driver accepted the open/configuration request. `Property` is a pySerial setting, not a measurement of the physical baud rate. | First assess the guide's recommended 3000000. An accepted rate remains a trial candidate; do not automatically choose the highest rate. |
| `FAIL` | Opening or configuring failed; possible causes include baud rate, port contention, permissions, or device state. | Inspect the complete error. Failure at every rate does not establish that the chip supports none of them. |
| Lower rates accepted, 3000000 failed | Lower-rate candidates exist, but stable application log capture is unproven. | Select a candidate using the error and log volume, match firmware and PC settings, then make a trial recording. |

The script performs no transfer test and cannot establish throughput, error rate, log completeness, or correct GPIO and firmware port selection. See the [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html); final confirmation comes from the guide's capture verification.

## Map Information to Configuration

Once information is sufficient, use the guide's fixed settings for the chosen transport and map confirmed board details to GPIOs, UART port, and baud rate. Produce the minimum sdkconfig changes against the existing project, preserving application settings and selecting exactly one transport. Cite the source of each value. Keep missing values in a pending table rather than filling copyable configuration blocks with default GPIOs, UART0, or guesses.

Distinguish “Information incomplete”, “Configured, pending trial”, and “Verified”. Use “Verified” only after checking the effective build configuration against wiring, trial recording quality, and application behavior. Follow the guide and implementation for ordinary serial log forwarding and file generation conditions.

Follow the guide for buffers, log levels, and source switches. For unusual load, memory limits, loss, or missing diagnostic logs, collect only relevant load and report details for technical support. Do not automatically enlarge buffers or disable logs needed for diagnosis.

## Output

When information is incomplete:

1. **Current conclusion:** Candidate transport, status, and information needed this round.
2. **Intake questionnaire:** Fill the template with known information and mark pending, after-capture, and inapplicable fields. Make it ready to copy or save as Markdown for handover. Draft only; do not send it on the user's behalf.
3. **Configuration impact:** Explain which missing facts block which settings. Include OS-specific script instructions only when the script is needed.

When information is sufficient:

1. Transport and status, plus the completed questionnaire.
2. Configuration mapping: `Setting | Value | Evidence/source | Confirmation status`, covering fixed settings and board variables, followed by the minimum configuration diff.
3. Wiring table: `Target signal | GPIO/port | Receiver pin/interface | Confirmation status`, including GND and, for UART, the PC port and baud rate.
4. Trial steps and delivery table: `File/directory | Required when | Likely location | Actual path/filename | Status`. Use the guide's delivery requirements and the template's location hints. Distinguish suggested locations from verified paths: recordings default to `<tool-start-directory>/logs/` unless another save directory was selected; the database usually lives under the firmware build directory; sdkconfig usually lives at the firmware project root. Resolve custom locations from the actual capture/build settings. Confirm that the database and flashed firmware come from the same build; directory names alone do not prove a match.

For questions about a tool's meaning, explain only the relevant part. Continue filling an existing questionnaire, retaining evidence sources and avoiding repeated requests.
