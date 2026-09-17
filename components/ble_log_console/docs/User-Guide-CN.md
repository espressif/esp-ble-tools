# BLE Log Console 快速使用指南
版本：v1.0.5

## 简介
BLE Log Console 是一个用于实时接收、显示和保存 ESP BLE 日志的终端工具。它支持 UART 和 SPI Bridge 两种传输模式。

**首次使用前，请先下载最新稳定版 BLE Log Console 工具包：**

> [BLE Log Console 工具下载](https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable)

## 1. 准备工作

启动前只需确认以下三件事：固件已启用 BLE Log，硬件接线正确，电脑端工具可正常运行。

快速跳转到要使用的传输模式：

* [查看 UART 模式](#2-uart-模式)
* [查看 SPI Bridge 模式](#3-spi-bridge-模式)

## 2. UART 模式

设备连接示意图：

<p align="center">
  <img src="./figure/uart-connection.png" alt="BLE UART 设备连接" style="width: 70%; max-width: 900px;">
</p>

### 2.1 固件配置

- 在现有工程中开启 `CONFIG_BT_LOG_CRITICAL_ONLY`，并将相关配置项设置如下：
  - `CONFIG_BLE_LOG_PRPH_UART_DMA=y`
  - `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT=0`
  - `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE=3000000`
  - `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM=0`
- 确认 UART TX 已连接到电脑端串口 RX。
- 编译并烧录固件。

> 配置说明：
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` 设置 **UART TX 信号对应的 GPIO**，默认值为 `0`。
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT` 指定 BLE Log 的输出串口。固件启用串口日志转发后，普通 console log 也会由工具接收，具体说明见 [Console Log 的显示与保存](#console-log-files)。
> - 如果 UART0 已被其他功能占用（如指令下发），请根据实际硬件连接调整 UART 端口 `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT`，避免影响原有功能。
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` 是 UART 输出 BLE Log 使用的波特率，推荐使用较高波特率。配置前请确认电脑端串口支持该波特率，并确保 `ble_log_console` 选择的波特率与该值一致。

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

Bridge 设备用于将**目标设备产生的 BLE SPI Log** 转发到 PC，目前可使用 `ESP32P4` 开发板实现。你可以通过以下两种方式获取 Bridge 设备：

* 自行烧录：如果你有一块 `ESP32P4` 开发板，可通过 USB 串口连接开发板，并在 [Bridge 固件烧录](https://espressif.github.io/esp-launchpad/?flashConfigURL=https://dl.espressif.com/ble/ble_log/spi_bridge_bin/launchpad.toml&crossDomain=true) 页面自行烧录固件，即可作为 Bridge 设备使用。

* 官方申请/采购：如果你没有可作为 Bridge 使用的 `ESP32P4` 设备，但确实需要使用 SPI Bridge 模式，可通过官方渠道购买，或向技术支持申请试用。

> 注意：
> * Bridge 设备是额外的转接设备，不能与产生 BLE Log 的设备为同一台设备。
> * 如果无法通过上述页面完成烧录，可前往 [Bridge 固件手动下载](https://github.com/espressif/esp-ble-tools/releases/download/ble_log_bridge_stable/ble_log_bridge_esp32p4.bin) 自行下载并烧录固件。

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

## 4. 首次运行与录制

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

### 4.2 开始录制

#### 4.2.1 选择模式和端口

启动应用后会显示如下界面：

<p align="center">
  <img src="./figure/interactive-screen.png" alt="BLE Log Console 交互界面" style="width: 60%; max-width: 900px;">
</p>

&emsp;首先选择警告和质量报告等长文本的显示语言，再选择传输模式：通过串口接收时选择 UART，通过 SPI Bridge 接收时选择 SPI Bridge。选择模式后，应用会自动扫描可用端口。

&emsp;随后选择端口。UART 模式下还需要选择波特率，且必须与固件配置保持一致。然后指定日志保存路径，默认保存到当前目录下的 `logs` 目录；若该目录不存在，程序会自动创建。最后点击「连接」即可开始接收日志。

#### 4.2.2 确认日志正在正常接收

录制界面如下图所示：

<p align="center">
  <img src="./figure/log-screen.png" alt="BLE Log Console 日志界面" style="width: 70%; max-width: 900px;">
</p>

录制过程中先看界面底部的 `RX` 和 `Frames`：`RX` 表示电脑已收到并保存的数据量，`Frames` 表示工具已识别出的有效日志帧数。

- **正常：** `RX` 和 `Frames` 持续增加，说明工具正在正常接收和识别日志。

- **没有收到数据：** `RX` 为 0。工具会每 10 秒警告一次，请检查端口、线缆和固件日志配置。

- **收到的数据无法解析：** `RX` 增加，但 `Frames` 持续为 0 或连续 10 秒不再增加。工具会每 10 秒警告一次。此时请停止录制，并检查传输模式、UART 波特率、固件配置和接线，不要继续无效录制。

> 高流量下界面更新可能暂时变慢，但工具仍会优先保存数据；如果保存失败，界面会直接提示错误。

<a id="console-log-files"></a>

#### 4.2.3 查看 Console Log

固件启用串口日志转发后，原本输出到 UART0（串口监视器）的普通 console log 会随 BLE Log 一起发送到 BLE Log Console。工具会在日志区域实时显示这些内容，并自动保存到所选日志目录；只有实际收到普通串口日志时才会生成 `_console.log` 文件。

每组 console log 的第一行会附带电脑接收时间，例如 `[15:14:54.367]`。保存时会清理颜色等终端控制字符并统一换行，但不会修改原始 `.bin` 文件。

### 4.3 结束录制并检查结果

#### 4.3.1 Stop & Review

需要结束录制时，点击 **Stop & Review**，或按 `q` / `Ctrl+C`。工具会先停止接收并保存剩余数据，再等待质量检查完成，最长等待 20 秒，然后显示本次录制质量报告；此时不会立即退出。报告页可选择按原配置再次录制或退出程序。

> 注意：界面显示 `FINALIZING`（正在保存）时请耐心等待。若直接关闭终端窗口，最后的数据和质量报告可能无法保存完整。

#### 4.3.2 查看质量报告

**提交日志前必须查看录制质量报告。** 工具会给出以下四种结论：

- 可用于分析：数据已正常保存并且能够解析，可以直接提交分析。

- 已保存，但存在警告：数据已经保存，但录制过程中可能存在中断、丢失或无法确认的情况。文件仍可提交技术支持用于分析。

- 检查配置：本次没有录到任何有效日志帧。**请勿提交本次文件**；检查传输模式、端口、UART 波特率、接线和固件日志配置，确认无误后重新录制。

- 建议重新录制：本次录到了有效日志帧，但数据未能正常保存，或检测到的丢失比例较高。**请勿直接提交本次文件**；排除保存或传输问题后重新录制。如果反复出现，可以联系技术支持进行评估。

只有“可用于分析”或“已保存，但存在警告”的文件可以直接提交。若另外两种结论反复出现，请先联系技术支持，并按要求提供对应的 `report.txt` 和 `.bin` 文件用于排查。

#### 4.3.3 找到并提交录制文件

录制文件默认保存到启动时指定的日志目录；如果未修改保存路径，则默认保存到当前目录下的 `logs` 目录。文件名按时间生成：

```text
ble_log_YYYYMMDD_HHMMSS.bin
ble_log_YYYYMMDD_HHMMSS_console.log
ble_log_YYYYMMDD_HHMMSS_report.txt
```

- `.bin` 是收到的原始 BLE Log 数据，也是后续问题分析的主要文件。
- `_report.txt` 用于说明本次录制是否有效。
- `_console.log` 是可直接查看的普通串口日志，只有实际收到此类日志时才会生成，不能替代 `.bin` 文件。

提交问题时，请提供同名的 `.bin` 和 `_report.txt`；如果生成了 `_console.log`，也请一并提供。程序退出后会在终端打印实际保存路径。较大的录制会自动拆分为多个 `part` 文件，同一秒内再次录制时会自动增加序号，不会覆盖已有文件。

## 5. 源码启动

需要本地调试、临时修改或验证新功能时，可以从源码运行 BLE Log Console。普通使用仍推荐下载打包好的可执行程序。

### 5.1 准备源码

进入 BLE Log Console 源码目录：

```bash
cd <ble_log_console 源码目录>
```

源码运行需要 Python 3.11 或更高版本，并使用 `uv` 管理环境和依赖。安装脚本会自动准备 `uv` 和项目虚拟环境。

### 5.2 Windows

首次使用时运行：

```bat
.\install.bat
```

安装完成后启动工具：

```bat
.\run.bat
```

也可以通过参数直接选择录制方式：

```bat
.\run.bat --mode uart --port COM3 --baudrate 3000000
.\run.bat --mode spi --port <PORT>
```

### 5.3 Linux

首次使用时运行：

```bash
chmod +x ./install.sh ./run.sh
./install.sh
```

安装完成后启动工具：

```bash
./run.sh
```

也可以通过参数直接选择录制方式：

```bash
./run.sh --mode uart --port /dev/ttyUSB0 --baudrate 3000000
./run.sh --mode spi --port <PORT>
```

### 5.4 直接运行 console.py

如果已经手动准备好 Python 3.11 及全部依赖，可以直接运行：

```bash
python console.py
```

常用命令如下：

```bash
python console.py --mode uart --port /dev/ttyUSB0 --baudrate 3000000
python console.py --mode spi --port <PORT>
```

如果安装或启动失败，请参见[源码环境安装失败](#faq-source-setup)。

## 6. 更多说明

更多快捷键可按 `h` 查看。完整的工具命令行参数见[仓库 README](https://github.com/espressif/esp-ble-tools/blob/main/components/ble_log_console/README.md)。

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

请参见 [Console Log 的显示与保存](#console-log-files)。

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
