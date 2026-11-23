# BLE Log Console

[English](./README.md) | [中文](./README_CN.md)

BLE Log Console 是一个用于实时接收、显示和保存 ESP BLE 日志的电脑端工具。

**推荐 USB 直连。** 若目标板引出了原生 USB 口，且固件支持 USB Output 或 USJ，用一根数据线即可录制。

| 连接方式 | 工具中如何选择 |
| --- | --- |
| USB 直连 | 选 **USB**，再选 **USB OTG**（固件 TinyUSB CDC）或 **USJ**（内置 USB Serial/JTAG）。无需设置波特率。 |
| SPI Bridge | 目标板 SPI 接独立 Bridge，选 **SPI Bridge** 和 Bridge 端口。 |
| UART | 选 **UART**、转串口端口和固件使用的波特率。 |

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

3. USB 直连时，在 **接收方式** 选 **USB**，再选与固件一致的 **USB OTG** 或 **USJ** 端口。界面默认英文，可在右上角切换中文。
4. 选择 **保存目录**。需要压缩 Host 文本时，在 **Host 字典** 选择本次固件构建中包含 `BLE_HOST_logs.json` 的目录。想看实时消息时勾选 **Host** 或 **HCI**，也可以全部留空直接 **连接**。显示选择只影响屏幕。
5. 确认 **RX** 和 **Frames** 持续增加后再触发问题。点击 **Stop & Review** 查看报告。需要 Host 文本时，查看「压缩 Host 文本」一项。选了字典时，工具会在录制结束后复制字典。报告列出 `<录制名>_database/` 后，就可以把它和日志一起打包。

SPI Bridge、USB OTG、USJ 在各平台统一使用 CDC 串口接收。没有 Bridge CDC 端口时，请重新连接设备并刷新端口列表；工具不再切换到直接 USB Bulk。

发布二进制不包含 Bulk 对照实现和 PyUSB。开发对照代码位于 `tools/spi_bulk_transport.py`，所需依赖仅包含在 `test` 扩展中。

Linux 下 CDC 使用串口访问权限（通常由 `dialout` 组提供）。当前用户有端口读写权限时，直接正常启动即可。先关闭其他占用 Bridge 的程序；如果之前的 Bulk 接收器解绑了串口驱动，关闭该程序后重新插拔 Bridge。

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

Windows 源码安装需要 Visual Studio Build Tools 的 **使用 C++ 的桌面开发** 工作负载
（MSVC 和 Windows SDK）。安装后，从 Developer Command Prompt 进入源码目录。
随附的 BLFD 源码包会在本机编译，参考构建环境为 Python 3.11 x64；运行已打包的 exe 不需要编译工具。
首次使用时先准备环境：

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
.\run.bat --mode usb --port COM5
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
./run.sh --mode usb --port /dev/ttyACM0
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
python console.py --mode usb --port /dev/ttyACM0
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
| 启动 USB OTG 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode usb --port /dev/ttyACM0` | `ble_log_console_windows_v1.1.0.exe --mode usb --port COM5` |
| 启动 USJ 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode usj --port /dev/ttyACM0` | `ble_log_console_windows_v1.1.0.exe --mode usj --port COM5` |
| 启动 UART 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode uart --port /dev/ttyUSB0` | `ble_log_console_windows_v1.1.0.exe --mode uart --port COM3` |
| 启动 SPI Bridge 模式 | `./ble_log_console_ubuntu_v1.1.0 --mode spi --port <PORT>` | `ble_log_console_windows_v1.1.0.exe --mode spi --port <PORT>` |
| 查看已保存日志 | `./ble_log_console_ubuntu_v1.1.0 ls` | `ble_log_console_windows_v1.1.0.exe ls` |

### 命令行参数

| 参数 | 缩写 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--mode` | `-m` | `uart` | 传输模式：`uart`、`spi`、`usb`（USB Output）或 `usj`（USB Serial/JTAG） |
| `--port` | `-p` | 可选 | 串口、SPI Bridge、USB Output 或 USJ 端口。省略时打开交互界面 |
| `--baudrate` | `-b` | `3000000` | UART 波特率，必须与固件配置一致 |
| `--log-dir` | `-d` | 上次使用的目录，无记录时为 `./logs` | 录制文件保存目录；显式指定时优先于记住的目录 |
| `--log-database` | 无 | 记忆值或自动查找 | 包含 `BLE_HOST_logs.json` 的固件字典目录 |
| `--debug` | 无 | 关闭 | 显示额外的调试信息 |
| `--show-log` | 无 | 全部关闭 | 显示 `host`、`hci` 或 `console`；可重复指定，如 `--show-log host --show-log hci`，不影响日志文件保存 |

子命令：

| 命令 | 说明 |
| --- | --- |
| `ports` | 列出 UART、SPI Bridge、USB Output 和 USJ 端口，并显示 CDC 端口的权限问题；可用 `--mode` 过滤 |
| `ls` | 列出指定目录中的 `ble_log_*.bin` 录制文件 |

`--output/-o` 仍保留为兼容旧版本的隐藏选项；推荐使用 `--log-dir`。

### USJ 模式

USJ 模式通过芯片内置的 USB Serial/JTAG 口（USB ID `303A:1001`）接收 BLE Log。`ports --mode usj` 只列出这个 USB ID 的端口；交互界面的 **USB** 列表同时显示 USJ 和 USB OTG 端口。波特率设置不适用。固件需要把 BLE Log 输出到 USB Serial/JTAG，这要求所用 ESP-IDF 提供 `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG`，见 [USJ 配置](./docs/Config-Guide-CN.md#usj)。

在这个端口上，DTR 和 RTS 线控制芯片的复位和启动模式。BLE Log Console 打开端口时先释放 RTS、再释放 DTR（与 ESP-IDF Monitor 避免复位的次序相同），之后两条线保持释放状态、不再改动，因此 `r` 快捷键不会复位目标设备。操作系统或其 USB 驱动在打开设备时仍可能改变这两条线，请在自己的电脑上确认打开端口是否会复位开发板。

**Host 字典**在录制文件创建成功后会记住所选目录，包括主动清空。即使随后端口连接失败，选择仍会保留；显式 `--log-database` 优先。目录失效时回退到自动发现，源码与二进制版本共用当前用户的应用设置。

### 开录积压与分析文件

所有传输模式都会在正常解析过程中观察开录快照；实时转录和原始文件保留完整数据。仅在接收开始后的前 5 秒、最多 2 MiB 内，v8 快照显示设备时间大幅前跳、快照计数前进，且随后恢复两个稳定间隔，才会确认旧积压边界。当 ESP 微秒时钟回绕或间隔较长时，Console 使用同一对快照中的 OS 毫秒时钟核对经过时间。两条快照必须各自对应一段连续帧序号，两段在接收顺序上的交界就是新数据起点；即使 24 位序号已经绕回，也能按这个位置分开。证据不明确、元数据不支持或设备复位时，报告评估完整录制；后续缺口不会重新归为开录积压。

收到的全部字节始终保留在原始 `.bin` 中。Console 在实时解析时将同一份已解码帧交给整份录制和候选新区间的检查器；确认边界并安全保存后，结论和丢失指标使用新区间结果；总字节数、总帧数和解析覆盖仍描述完整录制。报告显示区间偏移、时间证据及原始流缺失序号数。边界之后的真实丢包仍影响结论。新数据区间未能完整检查时，保守回退到原始流结论并提示原因。

Host 任务映射不再阻止积压识别，完整原始文件始终保留为后续分析输入。报告记录新区间起点，不再自动生成额外的 `_analysis.bin`。停止时仅收尾检查状态，不重读或复制整份录制；任务映射和日志上下文始终保留。新区间只有快照时，报告如实显示该区间普通日志为零，不因这一点强制重录。

识别依赖时间和序号证据，并非设备提供的精确队列边界。异常设备时钟前跳可能产生相似证据；积压不足阈值、缺少快照或观察时间不足时可能无法识别。完整原始数据和原始断档统计始终保留供核对。

### UART 与 USJ 上的文本数据

UART 和 USJ 端口上还可能出现普通控制台文本，例如 ROM 启动信息或崩溃转储。在这两种模式下，无法解析为 BLE Log 帧的字节会显示在日志区域，并保存到 `_console.log`，前后带有“未解码成功数据”标记。工具只保留可打印 ASCII，保存到文件时去掉颜色，并统一换行符。一行文本在换行、后面出现 BLE Log 数据或长度达到 16 KiB 时才显示在日志区域，因此不会被界面刷新拆开。可能还会补全的半个帧不会提前显示；录制结束时，剩余的未解码尾部只显示一次。这些文本不计入 BLE Log 帧。原始 `.bin` 文件保存工具收到的全部字节；报告了传输或保存失败时，该文件可能不完整。在任何模式下，如果 `_console.log` 无法写入或同步到存储，工具只提示一次并停止写入该文件。已开启的日志类别继续显示文本。此错误本身不会停止原始录制。质量报告会说明串口转发日志未能完整保存，并单独报告原始录制的保存失败。

工具还会识别端口上的数据内容：

- **纯文本：** 状态栏显示 `PLAIN TEXT`，并立即出现警告，文本持续时每 10 秒再提示一次。录制不会中断。出现纯文本通常说明固件没有把 BLE Log 输出到这个端口。
- **BLE Log：** 收到一条固件身份记录，或三个来自已知 BLE Log 来源的有效帧后，状态栏显示 `BLE LOG`。在此之前出现启动信息等文本属于正常情况。端口变安静或之后再输出文本，识别结果都不会改回去。

质量报告会写明识别出的内容，以及有多少数据不属于 BLE Log 帧。录制停止时被截断的最后一帧属于正常情况：这些字节记入“结尾未完成数据字节数”，不会附加该警告。不属于 BLE Log 帧的字节写入 `.bin` 文件而不是 `_console.log`，后者最多只包含其中可打印的文本；写入失败时这些字节可能不在文件中，质量报告会说明原始录制是否已确认完整。仅仅识别出 BLE Log 并不代表录制可用于分析：只有身份记录的录制仍会提示检查配置。SPI Bridge 和 USB Output 模式不显示未解码数据，也不做内容识别。

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

### Parser Core 接入版本

此分支使用统一的 BLFD 1.0.0.dev5 包进行流式完整性检查和固件统计。

有序 Host/HCI 产物从确认的新序号段第一帧开始。报告记录该帧在原始录制中的字节偏移。证据不足时偏移为零。普通 Host 文本保存为 `_host.log`，匹配字典的压缩 Host 日志保存为 `_DECOMPRESSED_BLE_HOST.log`。主机侧 HCI 和控制器 HCI 分别保存为 `_hci_btsnoop.log` 和 `_ll_hci_btsnoop.log`，使用设备时间。v8 录制跨越多次初始化时可按 epoch 分文件。实时转录 `_console.log` 和 `_hci.log` 带电脑接收时间。启动页的显示选项只影响屏幕。
Linux x86_64 / CPython 3.11 使用随附 wheel；Windows 等平台使用同一版本的源码包在本机编译，编译工具要求见 [vendor/README.md](vendor/README.md)。Windows 构建和真机验证尚待完成。
