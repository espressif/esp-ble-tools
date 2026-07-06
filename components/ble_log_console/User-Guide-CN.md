# BLE Log Console 用户指南

## 简介

BLE Log Console 是一个基于终端的实时 BLE 日志捕获与解析工具。它支持 **UART** 和 **SPI Bridge** 两种传输模式，可以实时显示 ESP 设备输出的 BLE Log，并将收到的原始二进制数据保存到文件供离线分析。

- **UART 模式**：通过串口接收日志，适合快速调试、critical log 和日志量较小的场景。
- **SPI Bridge 模式**：通过 BLE Log SPI USB Bridge 设备接收日志，适合日志量较大或需要更稳定采集的场景。

## 准备工作

### 1. UART 模式固件配置

在现有工程中开启 `CONFIG_BT_LOG_CRITICAL_ONLY`，并确认相关配置如下：

```text
CONFIG_BLE_LOG_PRPH_UART_DMA=y
CONFIG_BLE_LOG_PRPH_UART_DMA_PORT=0
CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE=3000000
CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM=0
```

> 注意：
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` 设置 **UART TX 信号对应的 GPIO**，默认值为 `0`。
> - 如果 UART0 已被其他功能占用，请根据实际硬件连接调整 `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT`，避免影响原有功能。
> - `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` 是 UART 输出 BLE Log 使用的波特率，电脑端选择的波特率必须与该值一致。

UART 连接方式：

```text
ESP32 TX GPIO  ->  USB 串口适配器 RX
ESP32 GND      ->  USB 串口适配器 GND
```

当固件配置为 UART PORT 0 时，固件会自动将 `ESP_LOG` 输出包装为 BLE Log 帧（`REDIR` source）。Console 会解码并显示为普通文本日志。

### 2. SPI Bridge 模式固件配置

SPI Bridge 模式需要一个额外的 BLE Log SPI USB Bridge 设备，用于将目标设备产生的 BLE SPI Log 转发到 PC。Bridge 设备目前由 `ESP32P4` 实现支持。

Bridge 设备获取方式：

- 如果你有 `ESP32P4` 开发板，可以在 [Bridge 固件下载](https://espressif.github.io/esp-launchpad/?flashConfigURL=https://dl.espressif.com/ble/ble_log/spi_bridge_bin/launchpad.toml&crossDomain=true) 页面通过 USB 串口连接后自行烧录。
- 如果没有可作为 Bridge 使用的 `ESP32P4` 设备，可以通过官方渠道购买，或向商务/技术支持申请试用。

> 注意：Bridge 设备是额外的转接设备，不能与产生 BLE Log 的目标设备为同一台设备。

在目标设备工程中开启 BLE Log 总开关和 SPI Master DMA 输出：

```text
CONFIG_BLE_LOG_ENABLED=y
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA=y
```

按照实际电路配置以下 GPIO：

```text
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM
CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM
```

默认 Bridge 引脚连接如下：

| 目标设备信号 | Bridge 引脚 |
|--------------|-------------|
| MOSI | IO 4 |
| SCLK | IO 5 |
| CS | IO 6 |
| GND | GND |

> 注意：
> - 上述 GPIO 配置必须与实际接线一致。
> - 两个设备必须共地，否则可能导致数据接收异常。
> - `CONFIG_BLE_LOG_ENABLED` 是 BLE Log 总开关，未开启时电脑端不会收到 BLE Log 数据。

## 启动

### 快速启动（推荐）

使用自带启动脚本。脚本会自动激活 ESP-IDF 环境、安装额外依赖，并将所有参数转发给 `console.py`：

```bash
# Linux / macOS
<esp-idf 根目录>/tools/bt/ble_log_console/run.sh

# Windows
<esp-idf 根目录>\tools\bt\ble_log_console\run.bat
```

不带参数启动时，工具会打开 **Launch Screen**。你可以在界面中：

- 选择传输模式：UART 或 SPI Bridge
- 选择当前模式下自动扫描到的端口
- UART 模式下选择波特率
- 设置日志保存目录
- 点击 **Connect** 开始捕获

Launch Screen 支持自适应窗口大小；窗口较小时可以滚动显示。

### 命令行启动

列出可用端口：

```bash
python console.py ports
python console.py ports --mode uart
python console.py ports --mode spi
```

UART 示例：

```bash
python console.py --mode uart --port /dev/ttyUSB0
python console.py --mode uart --port /dev/ttyUSB0 --baudrate 3000000 --log-dir ./logs
```

Windows UART 示例：

```bat
python console.py --mode uart --port COM3
```

SPI Bridge 示例：

```bash
python console.py --mode spi --port <PORT>
```

`spi` 是 `spi_usb_bridge` 的简写，两者等价。Linux 下 SPI Bridge 端口格式通常不同于 UART 串口，这是传输模式本身决定的，不影响使用。请以 `ports --mode spi` 输出为准。

### CLI 选项

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--mode` | `-m` | `uart` | 传输模式：`uart`、`spi` 或 `spi_usb_bridge` |
| `--port` | `-p` | 可选 | 传输端点。省略时打开 Launch Screen |
| `--baudrate` | `-b` | `3000000` | UART 波特率，必须与固件配置一致 |
| `--log-dir` | `-d` | `./logs` | 捕获文件保存目录 |
| `--debug` | 无 | 关闭 | 显示内部同步、流量和固件状态事件 |

子命令：

| 命令 | 说明 |
|------|------|
| `ports` | 列出 UART 和 SPI Bridge 端点，可用 `--mode` 过滤 |
| `ls` | 列出指定目录中的 `ble_log_*.bin` 捕获文件 |

`--output/-o` 仍保留为兼容旧版本的隐藏选项；推荐使用 `--log-dir`。

## 保存文件

捕获文件默认保存到当前工作目录下的 `logs` 目录，文件名按时间戳生成：

```text
ble_log_YYYYMMDD_HHMMSS.bin
```

如果 UART PORT 0 输出了 `REDIR` 文本日志，还会额外保存：

```text
ble_log_YYYYMMDD_HHMMSS_console.log
```

程序退出后会在终端打印实际保存路径。

## 界面说明

启动后，界面主要分为日志区域和状态栏。

### 日志区域

日志区域滚动显示实时日志，包括：

- **`[INFO]`**：连接成功、保存路径、捕获进度等提示
- **`[WARN]`**：丢帧、高流量、长时间无数据或无法解析帧等提示
- **`[SYNC]`**：同步状态变化（仅 `--debug` 下显示）
- 普通文本：UART PORT 0 的 `ESP_LOG` redirect 输出

非 debug 模式会隐藏大部分内部状态，只保留面向用户的提示。

### 状态栏

状态栏固定在底部，实时更新：

```text
Status: RECEIVING | Sync: SYNCED | Checksum: XOR / Header+Payload | Press h for help
RX: 1.2 MB  Frames: 12345  Speed: 2.34 Mbps  Max: 2.80 Mbps  Rate: 3421 fps  Lost: 12 frames, 480 B
```

- **Status**：连接状态（CONNECTED、RECEIVING、IDLE、DISCONNECTED）
- **Sync**：同步状态（SEARCHING、CONFIRMING、SYNCED、CONFIRMING_LOSS）
- **Checksum**：自动检测到的校验模式
- **RX / Frames**：累计接收字节数和解析出的 BLE Log frame 数量
- **Speed / Max**：当前和峰值传输速度
- **Rate**：当前帧率
- **Lost**：固件上报的累计丢帧统计

窗口较窄时，状态栏会自动切换为简短显示。正常工作时，`frames` 会持续增加，传输速度不为 0，并且在接收量达到一定规模时出现捕获大小提示。

## 快捷键

| 按键 | 功能 |
|------|------|
| `q` | 退出 |
| `Ctrl+C` | 退出 |
| `c` | 清空日志区域 |
| `s` | 切换自动滚动 |
| `d` | 查看接收日志统计信息 |
| `m` | 查看缓冲区利用率 |
| `h` | 显示快捷键帮助 |
| `r` | 复位目标设备；SPI Bridge 模式下不支持 |

### 帧统计详情（`d` 键）

按 `d` 会弹出一个覆盖层，包含两个表格，每秒自动刷新。

**Firmware Counters**：固件上报的每个 Source 的写入和 buffer loss 统计。

| Source | Written Frames | Written Bytes | Buffer Loss Frames | Buffer Loss Bytes |
|--------|----------------|---------------|--------------------|-------------------|
| LL_TASK | 12345 | 56.7 KB | 5 | 200 B |
| HOST | 456 | 12.1 KB | - | - |

**Console Measurements**：Console 端接收和峰值突发统计。

| Source | Received Frames | Received Bytes | Average Frames/s | Average Bits/s | Peak Frames/10ms | Peak Bits/s |
|--------|-----------------|----------------|------------------|----------------|------------------|-------------|
| LL_TASK | 12340 | 56.5 KB | 412 | 1.54 Mbps | 8 | 1.92 Mbps |

### 缓冲区利用率（`m` 键）

按 `m` 会显示固件上报的每个 LBM（Log Buffer Manager）缓冲区利用率：

| Pool | Idx | Name | Peak | Total | Util% |
|------|-----|------|------|-------|-------|
| COMMON_TASK | 0 | spin | 3 | 4 | 75% |
| COMMON_TASK | 1 | atomic[0] | 4 | 4 | 100% |

`Util%` 为 `Peak / Total`。100% 会高亮显示，表示该缓冲池曾被占满，可能导致丢帧。

## 打包为独立可执行文件

使用自带构建脚本可将 BLE Log Console 打包为单文件可执行程序：

```bash
# Linux / macOS
<esp-idf 根目录>/tools/bt/ble_log_console/build.sh

# Windows
<esp-idf 根目录>\tools\bt\ble_log_console\build.bat
```

脚本会自动激活 ESP-IDF 环境、安装 PyInstaller、构建可执行文件、将其放置在当前工作目录下，并清理中间产物。

构建脚本会使用当前 `VERSION` 生成文件名，不会自动递增版本号。输出文件名会包含平台和版本号，例如：

```text
ble_log_console_ubuntu_v1.0.1
ble_log_console_macos_v1.0.1
ble_log_console_windows_v1.0.1.exe
```

如果需要在打包时调整版本，可以先手动修改 `VERSION`，也可以直接运行 `build_exe.py`：

```bash
python build_exe.py                 # 使用当前 VERSION，不递增
python build_exe.py --bump-patch    # 成功后递增 patch
python build_exe.py --version 1.2.3 # 指定版本，不修改 VERSION
```

## 常见问题

### 端口列表里看不到设备

- 检查设备是否已经上电。
- 检查端口是否已被其他程序占用。
- UART 模式下确认串口连接正确。
- SPI Bridge 模式下确认 SPI 接线和共地正确。
- Linux 下如使用 SPI Bridge，请确认已执行过一次 `sudo ./ble_log_console_ubuntu` 或等效的权限规则安装步骤，并在执行后重新拔插 Bridge 设备。

### 程序启动了，但一直没有日志

- 确认选择的传输模式正确。
- 确认选择的端口正确。
- 确认 ESP 设备固件已经启用 BLE Log。
- UART 模式下，确认工具中选择的波特率与固件配置一致。
- SPI Bridge 模式下，确认目标设备固件中的 MOSI、SCLK、CS GPIO 与实际接线一致。

### 出现 Buffer overflow warning

表示工具已经收到数据，但在内部缓冲区中没有解析出有效 BLE Log 帧。请优先检查传输模式、波特率、固件配置和硬件连接是否匹配。

### 丢帧严重或出现 High log traffic

- 按 `d` 查看各 Source 的丢帧详情。
- 按 `m` 查看缓冲区利用率。
- UART 模式下确认波特率和串口适配器能力。
- SPI Bridge 模式下确认 Bridge 设备、SPI 接线和固件 GPIO 配置。
- 根据统计结果增大固件 BLE Log buffer 或 LBM 数量。

### 看不到 ESP_LOG 输出

- 仅 UART PORT 0 会显示 `ESP_LOG` redirect 文本。
- 确认固件配置了 `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT=0`。
- 日志由 1 秒周期定时器刷新，可能有短暂延迟。
