# BLE Log Console 快速使用指南
版本：v1.0.5

## 简介
BLE Log Console 是一个用于实时接收、显示和保存 ESP BLE 日志的终端工具。它支持 UART 和 SPI Bridge 两种传输模式。

 **首次使用前，请先下载最新稳定版 BLE Log Console 工具包：**
>[BLE Log Console 工具下载](https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable)

## 1. 准备工作

启动前只需确认以下三件事：固件已启用 BLE Log，硬件接线正确，电脑端工具可正常运行。

快速跳转到要使用的传输模式：

* [查看 UART 模式](#2-uart-模式)
* [查看 SPI Bridge 模式](#3-spi-bridge-模式)

## 2. UART 模式

设备连接示意图：

<p align="center">
  <img src="./figure/uart-connection.png" alt="BLE UART设备连接" style="width: 70%; max-width: 900px;">
</p>

### 2.1 固件配置

- 在现有工程中开启 `CONFIG_BT_LOG_CRITICAL_ONLY`，并将相关配置项设置如下：
  - `CONFIG_BLE_LOG_PRPH_UART_DMA=y`
  - `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT=0`
  - `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE=3000000`
  - `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM=0`
- 确认 UART TX 已连接到电脑端串口 RX。
- 编译并烧录固件。

> 注意：
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` 设置 **UART TX 信号对应的 GPIO**，默认值为 `0`。
> - 如果 UART0 已被其他功能占用，请根据实际硬件连接调整 `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT`，避免影响原有功能。
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` 是 UART 输出 BLE Log 使用的波特率，电脑端 `ble_log_console` 选择的波特率必须与该值一致。

### 2.2 在 PC 端启动应用

- Windows 使用说明见 [Windows 系统](#411-windows-系统)。
- Linux 使用说明见 [Linux 系统](#412-linux-系统)。

## 3. SPI Bridge 模式

设备连接示意图：

```text
ESP 设备  ->  BLE Log SPI USB Bridge  ->  电脑
```

<p align="center">
  <img src="./figure/spi-bridge-connection.png" alt="BLE SPI Log 设备连接" style="width: 70%; max-width: 900px;">
</p>

**如何获取 Bridge 设备？**

Bridge 设备用于将**你的设备产生的 BLE SPI Log** 转发到 PC，目前由我们的产品 `ESP32P4` 实现支持。你可以通过以下两种方式获取 Bridge 设备：

* 自行烧录：如果你有一块 `ESP32P4` 开发板，可通过 USB 串口连接开发板，并在 [Bridge 固件烧录](https://espressif.github.io/esp-launchpad/?flashConfigURL=https://dl.espressif.com/ble/ble_log/spi_bridge_bin/launchpad.toml&crossDomain=true) 页面自行烧录固件，即可作为 Bridge 设备使用。

* 官方申请/采购：如果你没有可作为 Bridge 使用的 `ESP32P4` 设备，但确实需要使用 SPI Bridge 模式，可通过官方渠道购买，或向技术支持申请试用。

> 注意：
> * Bridge 设备是额外的转接设备，不能与产生 BLE Log 的设备为同一台设备。
> * 如果上述烧录方法不顺利，可前往 [Bridge 固件手动下载](https://github.com/espressif/esp-ble-tools/releases/download/ble_log_bridge_stable/ble_log_bridge_esp32p4.bin)自行下载固件进行烧录。

### 3.1 固件配置

- 在产生 BLE Log 的目标设备工程中开启 `CONFIG_BLE_LOG_ENABLED`，并同时开启以下相关配置：
  - `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA=y`
- 按照实际电路配置以下 GPIO 端口号：
  - `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM`
  - `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM`
  - `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM`
- 将对应 GPIO 连接到 SPI Bridge：
  - `MOSI_IO_NUM` 连接 `Bridge IO 4`
  - `SCLK_IO_NUM` 连接 `Bridge IO 5`
  - `DMA_CS_IO_NUM` 连接 `Bridge IO 6`
  - 连接两个设备的 GND
- 编译并烧录固件。

> 注意：
> - **上述 GPIO 配置必须与实际接线一致**。
> - 如果两个设备的 GND 未正确连接，可能导致数据接收异常。
> - `CONFIG_BLE_LOG_ENABLED` 是 BLE Log 总开关，未开启时电脑端不会收到 BLE Log 数据。

### 3.2 在 PC 端启动应用

- Windows 使用说明见 [Windows 系统](#411-windows-系统)。
- Linux 使用说明见 [Linux 系统](#412-linux-系统)。

## 4. 首次运行与启动

### 4.1 获取工具

工具包提供了适用于不同操作系统的应用程序。请从 [BLE Log Console 稳定版下载](https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable) 页面获取最新工具包。

#### 4.1.1 Windows 系统

Windows 下使用 `ble_log_console_windows_v1.0.5.exe`。推荐直接双击图标启动。

> 注意：本工具包现支持 `Windows 10` 及以上版本。

#### 4.1.2 Linux 系统

Linux 下使用 `ble_log_console_ubuntu_v1.0.5`。如果文件没有执行权限，请先进入对应目录，并在命令行执行：

```bash
chmod +x ./ble_log_console_ubuntu_v1.0.5
```

如果计划在 Linux 下使用 SPI Bridge，首次使用时请先运行：

```bash
sudo ./ble_log_console_ubuntu_v1.0.5
```

该命令会安装 SPI Bridge 所需的 USB 访问权限规则。命令执行完成后，请重新拔插一次 SPI Bridge 设备。之后正常使用时无需再加 `sudo`。

随后执行以下命令即可启动本程序：

```bash
./ble_log_console_ubuntu_v1.0.5
```

> 注意：本工具包现支持 `Ubuntu 22.04` 及以上版本。

### 4.2 应用指南

启动应用后会显示如下界面：

<p align="center">
  <img src="./figure/interactive-screen.png" alt="BLE Log Console 交互界面" style="width: 60%; max-width: 900px;">
</p>

&emsp;首先选择长文本使用的语言，再选择传输模式：通过串口接收时选择 UART，通过 SPI Bridge 接收时选择 SPI Bridge。选择模式后，应用会自动扫描可用端口。

&emsp;随后选择端口。UART 模式下还需要选择波特率，且必须与固件配置保持一致。然后指定日志保存路径，默认保存到当前目录下的 `logs` 目录；若该目录不存在，程序会自动创建。最后点击「连接」即可开始接收日志。

&emsp;需要结束采集时，点击 **Stop & Review**，或按 `q` / `Ctrl+C`。工具会先停止接收并保存剩余数据，再等待质量检查完成，最长等待 20 秒，然后显示本次录制质量报告；此时不会立即退出。报告页可选择按原配置再次录制或退出程序。较大的采集文件可能会被拆分为多个 `part` 文件。

> 注意：结束采集时请使用 **Stop & Review**、`q` 或 `Ctrl+C`。界面显示 `FINALIZING`（正在保存）时请耐心等待。若直接关闭终端窗口，最后的数据和质量报告可能无法保存完整。

&emsp;Linux 下 UART 和 SPI Bridge 显示的端口名称可能不同，按当前模式选择设备即可。

## 5. 使用界面与日志文件

### 5.1 界面说明

启动后，界面主要包含日志区域和状态栏，如下图所示。

<p align="center">
  <img src="./figure/log-screen.png" alt="BLE Log Console 日志界面" style="width: 70%; max-width: 900px;">
</p>

日志区域会实时显示设备转发的串口日志、运行提示和警告。

&emsp;状态栏会显示当前连接状态、电脑已收到的数据量、当前速度、峰值速度和帧率。是否存在数据异常，以结束录制后的质量报告为准。

&emsp;工具支持自适应窗口大小。窗口较小时，部分状态信息可能显示不全，可放大窗口或通过滚动查看其余信息。

### 5.2 正常状态说明

&emsp;如上图所示，`Frames` 表示工具已识别出的有效日志帧数，`RX` 表示电脑已收到并保存的数据量。

&emsp;**正常状态：** `RX` 和 `Frames` 持续增加，说明工具正在正常接收和识别日志。如果 `RX` 增加但 `Frames` 长时间不增加，请优先检查传输模式、UART 波特率、固件配置和接线。

> 如果连接正常，但上述指标存在异常，请检查 `BLE Log` 模块是否正常开启，或者连线是否完全正确。

> 注意：出现高流量提示时，界面更新可能暂时变慢，但工具仍会优先保存数据。如果数据保存失败，界面会直接提示错误。

### 5.3 日志文件保存规则

录制文件默认保存到启动时指定的日志目录；如果未修改保存路径，则默认保存到当前目录下的 `logs` 目录。文件名按时间生成：

```text
ble_log_YYYYMMDD_HHMMSS.bin
```

如果固件启用了串口日志转发，原本输出到 UART0（串口监视器）的普通 console log 还会额外保存为：

```text
ble_log_YYYYMMDD_HHMMSS_console.log
```

安全结束录制后还会生成对应的质量报告：

```text
ble_log_YYYYMMDD_HHMMSS_report.txt
```

程序退出后会在终端打印实际保存路径。较大的录制会自动分成多个文件。同一秒内再次录制时，文件名会自动增加序号，不会覆盖已有文件。

### 5.4 录制质量报告

结束录制后，工具会给出以下三种结论：

- 可用于分析：数据已正常保存并且能够解析，可以直接提交分析。

- 已保存，但存在警告：数据已经保存，但录制过程中可能存在中断、丢失或无法确认的情况。文件仍可提交技术支持用于分析。

- 建议重新录制：本次有效数据不足、数据未能正常保存，或检测到的丢失比例较高。请检查连接、模式、端口、波特率和固件配置后重新录制。如果反复出现，可以联系技术支持进行评估。

报告页面会显示本次录制的帧数、数据量和文件位置。需要进一步排查时，可将生成的 `report.txt` 和 `.bin` 文件一起提供给技术支持。

## 6. 更多说明

更多快捷键可按 `h` 查看。源码使用方法、工具命令行参数见[仓库 README](https://github.com/espressif/esp-ble-tools/blob/main/components/ble_log_console/README.md)。

## 附录：故障排查与注意事项

快速查找：

* [端口列表里看不到设备](#faq-no-port)
* [程序启动但没有日志](#faq-no-logs)
* [串口监视器日志的显示与保存](#faq-console-log)
* [源码环境安装失败](#faq-source-setup)
* [ESP32P4 Bridge 固件版本确认](#faq-esp32p4-version)
* [质量报告显示“无法确认”或检查未完成](#faq-quality-check)

<a id="faq-no-port"></a>

### 我插上设备后，端口列表里还是看不到。

请检查：

- 设备是否正确连线，SPI 模式下 GND 是否已正确共地。
- 设备是否已经上电。
- 设备中是否运行了正确的固件。
- 端口是否已经被其他程序占用。
- Linux 下是否已经执行过一次 `sudo ./ble_log_console_ubuntu_v1.0.5`，并在执行后拔插过设备。

<a id="faq-no-logs"></a>

### 程序启动了，但一直没有日志。

请检查：

- 选择的连接方式是否正确。
- 选择的端口是否正确。
- ESP 设备固件是否已经启用 BLE Log。
- UART 模式下，工具中选择的波特率是否与固件配置一致。
- ESP 设备和串口工具或 SPI Bridge 之间的接线是否正确。
- SPI Bridge 模式下，ESP 设备固件中的 MOSI、SCLK、CS 对应 GPIO 是否与实际接线一致。

<a id="faq-console-log"></a>

### 串口监视器日志为什么会出现在工具里，并保存在哪里？

固件启用串口日志转发后，原本输出到 UART0（串口监视器）的普通 console log 会随 BLE Log 数据一起转发到 BLE Log Console。工具会在日志区域实时显示这些内容，并自动保存到所选日志目录下的 `ble_log_YYYYMMDD_HHMMSS_console.log` 文件。

每组 console log 的第一行会显示电脑收到该组日志的时间，例如 `[15:14:54.367]`；后续没有时间戳的行仍属于同一组日志。这个时间不是设备的运行时间。

`_console.log` 会自动清理颜色等显示控制字符并统一换行，不会改变原始 `.bin` 文件。

<a id="faq-source-setup"></a>

### 源码环境安装失败。

源码启动依赖本机 Python 环境、依赖源访问和系统 PATH 配置。安装脚本会尽量自动准备这些内容，但不同电脑环境可能需要手动处理。必要项包括：

- Python 3.11 或更高版本。
- `uv`，并且可以在 `PATH` 中被找到。
- 可以访问 `pyproject.toml` 中声明的 Python 依赖包。

如果脚本无法完成环境准备，请手动安装上述必要项，然后在源码目录下执行 `uv sync --all-extras`，再运行启动脚本。

<a id="faq-esp32p4-version"></a>

### ESP32P4 烧录的固件如何确定版本？

当前 ESP32P4 Bridge 固件版本为 `1.0`。固件启动时会在串口日志中打印版本信息。确认版本时，请将 ESP32P4 通过 USB 串口连接到电脑，然后打开串口监视器查看启动日志。

```bash
idf.py -p <PORT> monitor
```

如果已错过启动日志，可按下开发板复位键，版本信息会在 ESP32P4 重新启动后再次打印。

> 注意：查看版本时，ESP32P4 的串口不能同时被 `ble_log_console` 的 UART 模式或其他串口工具占用。

<a id="faq-quality-check"></a>

### 质量报告显示“无法确认”，或检查未完成，文件还能用吗？

报告会分别说明原始数据是否完整保存，以及自动质量检查覆盖了多少数据。如果检查未能在 20 秒内完成，原始数据仍会保留；帧数和丢失检查只代表已经解析的部分，整份录制的连续性会显示为“无法确认”。

详细报告会逐段列出接收帧数、固件写入失败帧数和序列号检查结果，并标明开头或结尾不完整的段。收到固件分段统计时，总体质量统计只使用完整段；无法确定连续性时显示“无法确认”。

请保留原始 `.bin` 文件及对应的 `_report.txt`；有分片时请一并提供全部分片，由技术支持结合报告评估是否需要重新录制。
