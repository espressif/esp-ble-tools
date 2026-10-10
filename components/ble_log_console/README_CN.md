# BLE Log Console

[English](./README.md) | [中文](./README_CN.md)

BLE Log Console 是一个用于实时接收、显示和保存 ESP BLE 日志的电脑端工具。

它支持：

- **UART**：通过串口接收 BLE 日志。
- **SPI Bridge**：通过 BLE Log SPI USB Bridge 设备接收 BLE 日志。

## 工具下载

请从 GitHub Release 下载最新稳定版工具包：

[BLE Log Console 工具下载](https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable)

## 使用文档

| 文档 | 主要内容 | 语言 |
| --- | --- | --- |
| BLE Log 配置指南 | 传输方式选择、sdkconfig、接线、采集验证和交付清单。 | [中文](./docs/Config-Guide-CN.md) / [English](./docs/Config-Guide-EN.md) |
| Console 使用指南 | 工具准备、连接、录制、质量报告和故障排查。 | [中文](./docs/Console-User-Guide-CN.md) / [English](./docs/Console-User-Guide-EN.md) |

尚未确定硬件和固件配置时，先阅读配置指南；阅读后仍有疑问，可联系技术支持。配置已就绪时，可直接阅读 Console 使用指南。

### 使用 AI 辅助整理接入信息

[BLE Log 接入 skill](./docs/skills/ble-log-intake/SKILL.md) 提供问卷和配置映射流程。使用能读取本地文件的 AI 工具时，可以提供该文件路径和已有材料，例如：

> 请读取 `components/ble_log_console/docs/skills/ble-log-intake/SKILL.md`，根据我提供的 sdkconfig 和板卡信息回填接入问卷，列出还需要确认的内容。

## 快速使用

1. 从稳定版 Release 页面下载对应操作系统的工具包。
2. 启动工具：

```bash
# Windows
ble_log_console_windows_v1.1.0.exe

# Linux
chmod +x ./ble_log_console_ubuntu_v1.1.0
./ble_log_console_ubuntu_v1.1.0
```

3. 在界面中选择语言、传输模式、端口、UART 波特率和日志保存目录，然后点击 **Connect** 开始接收日志。
4. 录制完成后点击 **Stop & Review**，工具会保存数据并显示质量结论。

Linux 下首次使用 SPI Bridge 时，请先用 `sudo` 运行一次工具，然后重新拔插 Bridge 设备：

```bash
sudo ./ble_log_console_ubuntu_v1.1.0
```

日志会保存到选择的目录。接线方式、固件配置和基本操作请查看 [中文用户指南](./docs/Console-User-Guide-CN.md)。

## 源码启动

本工具也提供源码，有本地调试、临时修改或功能验证需求的用户，可参考本章说明从源码运行。

### 源码获取

源码位于 BLE Log Console 源码目录下。使用前请先进入该目录。

```bash
cd <ble_log_console 源码目录>
```

源码目录中主要包含以下文件：

| 文件或目录 | 说明 |
| --- | --- |
| `console.py` | 应用入口 |
| `install.sh` | Linux 源码环境安装脚本 |
| `run.sh` | Linux 源码启动脚本 |
| `install.bat` | Windows 源码环境安装脚本 |
| `run.bat` | Windows 源码启动脚本 |
| `src/` | 工具源码 |
| `tests/` | 单元测试 |
| `logs/` | 默认日志保存目录，运行后自动创建 |

> 注意：
> - 普通用户推荐优先使用打包好的可执行程序。
> - 源码启动主要用于本地调试、临时修改工具逻辑或验证新功能。


### 源码使用

源码启动方式与打包程序基本一致。本工具基于 Python，并使用 `uv` 管理依赖。首次使用时请先运行安装脚本准备本地环境，之后通过启动脚本运行 `console.py`。

#### Windows 系统

在 Windows 下进入源码目录，首次使用时先准备环境：

```bat
.\install.bat
```

随后执行：

```bat
.\run.bat
```

不带参数运行时会打开交互界面，可在界面中选择传输模式、端口、波特率和日志保存目录。

也可以直接通过命令行参数启动指定模式：

```bat
.\run.bat --mode uart --port COM3 --baudrate 3000000
.\run.bat --mode spi --port <PORT>
```


#### Linux 系统

在 Linux 下进入源码目录，首次使用时先准备环境：

```bash
./install.sh
```

随后执行：

```bash
./run.sh
```

如果脚本没有执行权限，请先执行：

```bash
chmod +x ./install.sh ./run.sh
```

命令行启动示例如下：

```bash
./run.sh --mode uart --port /dev/ttyUSB0 --baudrate 3000000
./run.sh --mode spi --port <PORT>
```


#### 直接运行 console.py

若已手动准备好所需的 Python 环境，可以直接运行 `console.py`：

```bash
cd <ble_log_console 源码目录>
python console.py
```

也可以在普通 Python 环境中安装依赖后运行：

```bash
python -m pip install .
python console.py
```

常用命令如下：

```bash
python console.py --mode uart --port /dev/ttyUSB0 --baudrate 3000000
python console.py --mode spi --port <PORT>
```

> 注意：
> - 直接运行 `console.py` 需要确保所有 Python 依赖已经安装。
> - 如果只是正常使用工具，推荐先运行一次 `install.sh` 或 `install.bat`，之后使用 `run.sh` 或 `run.bat`。

## 命令行参考

&emsp;本节补充说明工具包的命令行用法。常用命令如下：

| 操作 | Linux | Windows |
| --- | --- | --- |
| 查看帮助 | `./ble_log_console_ubuntu_v1.1.0 --help` | `ble_log_console_windows_v1.1.0.exe --help` |
| 列出端口 | `./ble_log_console_ubuntu_v1.1.0 ports` | `ble_log_console_windows_v1.1.0.exe ports` |
| 启动交互模式 | `./ble_log_console_ubuntu_v1.1.0` | `ble_log_console_windows_v1.1.0.exe` |
| 启动 UART 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode uart --port /dev/ttyUSB0` | `ble_log_console_windows_v1.1.0.exe --mode uart --port COM3` |
| 启动 SPI Bridge 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode spi --port <PORT>` | `ble_log_console_windows_v1.1.0.exe --mode spi --port <PORT>` |
| 启动 USJ 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode usj --port /dev/ttyACM0` | `ble_log_console_windows_v1.1.0.exe --mode usj --port COM5` |
| 查看已保存日志 | `./ble_log_console_ubuntu_v1.1.0 ls` | `ble_log_console_windows_v1.1.0.exe ls` |

### 命令行参数

| 参数 | 缩写 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--mode` | `-m` | `uart` | 传输模式：`uart`、`spi`、`usb`（USB Output）或 `usj`（USB Serial/JTAG） |
| `--port` | `-p` | 可选 | 串口、SPI Bridge、USB Output 或 USJ 端口。省略时打开交互界面 |
| `--baudrate` | `-b` | `3000000` | UART 波特率，必须与固件配置一致 |
| `--log-dir` | `-d` | `./logs` | 录制文件保存目录 |
| `--debug` | 无 | 关闭 | 显示额外的调试信息 |

子命令：

| 命令 | 说明 |
| --- | --- |
| `ports` | 列出 UART、SPI Bridge、USB Output 和 USJ 端口，可用 `--mode` 过滤 |
| `ls` | 列出指定目录中的 `ble_log_*.bin` 录制文件 |

`--output/-o` 仍保留为兼容旧版本的隐藏选项；推荐使用 `--log-dir`。

### USJ 模式

USJ 模式通过芯片内置的 USB Serial/JTAG 口（USB ID `303A:1001`）接收 BLE Log。`ports` 子命令和交互界面只列出这个 USB ID 的端口。波特率设置不适用。固件需要把 BLE Log 输出到 USB Serial/JTAG，这要求所用 ESP-IDF 提供 `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG`，见 [USJ 配置](./docs/Config-Guide-CN.md#usj)。

在这个端口上，DTR 和 RTS 线控制芯片的复位和启动模式。BLE Log Console 打开端口时先释放 RTS、再释放 DTR（与 ESP-IDF Monitor 避免复位的次序相同），之后两条线保持释放状态、不再改动，因此 `r` 快捷键不会复位目标设备。操作系统或其 USB 驱动在打开设备时仍可能改变这两条线，请在自己的电脑上确认打开端口是否会复位开发板。

### UART 与 USJ 上的文本数据

UART 和 USJ 端口上还可能出现普通控制台文本，例如 ROM 启动信息或崩溃转储。在这两种模式下，无法解析为 BLE Log 帧的字节会显示在日志区域，并保存到 `_console.log`，前后带有“未解码成功数据”标记。工具只保留可打印 ASCII，保存到文件时去掉颜色，并统一换行符。一行文本在换行、后面出现 BLE Log 数据或长度达到 16 KiB 时才显示在日志区域，因此不会被界面刷新拆开。可能还会补全的半个帧不会提前显示；录制结束时，剩余的未解码尾部只显示一次。这些文本不计入 BLE Log 帧。原始 `.bin` 文件始终保存收到的全部字节。在任何模式下，如果 `_console.log` 无法写入或同步到存储，工具只提示一次并停止写入该文件。日志区域继续显示文本。此错误本身不会停止原始录制。质量报告会说明串口转发日志未能完整保存，并单独报告原始录制的保存失败。

工具还会识别端口上的数据内容：

- **纯文本：** 状态栏显示 `PLAIN TEXT`，并立即出现警告，文本持续时每 10 秒再提示一次。录制和原始数据保存不会中断。出现纯文本通常说明固件没有把 BLE Log 输出到这个端口。
- **BLE Log：** 收到一条固件身份记录，或三个来自已知 BLE Log 来源的有效帧后，状态栏显示 `BLE LOG`。在此之前出现启动信息等文本属于正常情况。端口变安静或之后再输出文本，识别结果都不会改回去。

质量报告会写明识别出的内容，以及有多少数据不属于 BLE Log 帧。录制停止时被截断的最后一帧属于正常情况：这些字节记入“结尾未完成数据字节数”，不会附加该警告。全部原始字节都保存在 `.bin` 文件中，`_console.log` 最多只包含其中可打印的文本。仅仅识别出 BLE Log 并不代表录制可用于分析：只有身份记录的录制仍会提示检查配置。SPI Bridge 和 USB Output 模式不显示未解码数据，也不做内容识别。

## 快捷键

以下是在应用运行中常用的一些快捷键，可用于查看统计信息、复位设备、退出应用等。

| 按键 | 功能 |
| --- | --- |
| `q` | 录制中停止并查看报告；报告页退出 |
| `Ctrl+C` | 录制中停止并查看报告；报告页退出 |
| `c` | 清空日志区域 |
| `s` | 切换自动滚动 |
| `d` | 查看接收日志统计信息 |
| `m` | 查看缓冲区利用率 |
| `h` | 显示快捷键帮助 |
| `r` | 复位目标设备；SPI Bridge、USB Output 和 USJ 模式下不支持 |

## 故障排查

连接异常、日志显示、质量检查限制、源码环境安装和 Bridge 版本确认见[用户指南末尾的故障排查](./docs/Console-User-Guide-CN.md#faq-no-port)。
