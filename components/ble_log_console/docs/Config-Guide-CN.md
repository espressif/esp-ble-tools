# BLE Log 配置指南

[中文](Config-Guide-CN.md) | [English](Config-Guide-EN.md)

> **优先 SPI，接线等条件不具备时再用 UART。**

工具下载：[BLE Log Console 稳定版发布页][ble-log-console]。电脑端操作参照 [Console 使用指南](Console-User-Guide-CN.md)。

本文用于根据实际硬件和资源占用，确定一套可用的 BLE Log sdkconfig 及配套接线。以现有工程的 sdkconfig 为基础，逐项确定传输方式、端口、GPIO 和速率，再通过试录验证。配置项是否可用取决于目标芯片和 SDK 版本。

**阅读顺序：选择 SPI 或 UART → 配置与接线 → 试录验证 → 提交产物。**

[SPI 配置](#spi) · [UART 配置](#uart) · [采集验证](#verification) · [最终产物](#deliverables) · [配置记录](#records) · [缓冲与日志量](#advanced)

## 快速选择

确定接入方式后，只需阅读对应的 SPI 或 UART 章节，再进入采集验证。缓冲和日志级别的调整说明位于文末附录。

| 顺序 | 使用条件 | 选择与操作 |
| --- | --- | --- |
| 1. 优先 SPI | 能接出三根信号线和 GND，SPI 资源空闲以及有 Bridge 设备。 | 外接使用 SPI Log，见 [SPI Log](#spi)。 |
| 2. 复用现有串口 | SPI 条件不具备；板载 USB 转串口连接的 UART 可用于BLE Log，且支持所需波特率。 | 使用 UART，通常无需额外接线，见 [UART Log](#uart)。仅用于普通日志打印的串口也可考虑复用。 |
| 3. 外接转串口工具 | 无法复用板载连接，但有可用 UART 和可接出的 TX、GND。 | 外接 USB 转串口工具，见 [UART Log](#uart)。 |
| 4. 暂无可用方式 | 上述条件均不满足。 | 基于前面已核对的 sdkconfig 和硬件限制，联系技术支持继续评估可行配置。 |

<a id="spi"></a>

## 1. SPI Log 配置（推荐）

SPI 带宽更充足，适合采集较大量的日志，便于快速定位问题。目标板通过三根信号线和 GND 连接 Bridge，再由 Bridge 连接电脑。

### 1.1 接入条件

> **先确认能否接线。** SPI 空闲并不代表引脚能够接出；接线条件确认后再检查 SPI 资源。

| 确认项 | 条件与说明 | 处理建议 |
| --- | --- | --- |
| 接线条件 | **能接出三根信号线和 GND。**<br>优先使用现成接口或测试点；需要拆机、焊线时，评估现场是否方便实施。 | 无法接线时选择 UART。 |
| Bridge 设备 | **有独立 Bridge 或可用的 ESP32P4 开发板。**<br>ESP32P4 开发板需烧录配套 Bridge 固件；Bridge 与目标设备必须是不同设备。 | 准备 Bridge，可向技术寻求资源支持，无法准备时选择 UART。 |
| SPI 资源 | **是否与现有外设冲突，停用或调整外设不影响问题复现。**<br>若调整后原问题不再出现，应保留原有外设工作条件。 | 无法释放资源时选择 UART。 |
| GPIO 位置 | **三个可用 GPIO 和 GND 均可连接。**<br>核对 GPIO 编号与板上位置，并确认适用于所需输出信号；不要直接套用示例引脚。 | 填写配置和接线表。 |

> **资源限制：** 当前实现使用 SPI Controller 2；若已有 SPI 外设，请检查是否占用同一控制器。

满足上述条件后，在现有 sdkconfig 中选择 SPI 输出，并确定 MOSI、SCLK、CS 的 GPIO；否则参见 [UART 配置](#uart)。

### 1.2 配置和接线

| 配置项／连接 | 设置值 | 对应接线／说明 |
| --- | --- | --- |
| `CONFIG_BLE_LOG_ENABLED` | `y` | 启用 BLE Log。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA` | `y` | 选择 SPI DMA 输出。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM` | **待填写：MOSI GPIO** | 目标板该 GPIO → Bridge IO 4。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM` | **待填写：CLK GPIO** | 目标板该 GPIO → Bridge IO 5。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM` | **待填写：CS GPIO** | 目标板该 GPIO → Bridge IO 6。 |
| GND | 无配置项 | 目标板 GND → Bridge GND。 |

这里的 Bridge 引脚对应配套 ESP32P4 Bridge 固件。确认两端电平兼容，接线尽量短，并正确共地。

### 1.3 连接工具

编译、烧录后，电脑端选择 **SPI Bridge**。Bridge 准备步骤参照 [Console 使用指南](Console-User-Guide-CN.md#3-spi-bridge-模式)。

**下一步：[采集验证](#verification)。**

<a id="uart"></a>

## 2. UART Log 配置（备选）

不具备 SPI 接入条件时，可使用 UART。**优先复用板载 USB 转串口和现有日志串口，减少额外接线。** UART 带宽较有限，建议先使用带宽优化配置试录。

> **仅用于普通日志打印的串口也可复用。** 当前 UART0 路径会将普通串口日志与 BLE Log 一起发送到 BLE Log Console，支持显示和保存。其他 UART 不会自动转发 UART0 的普通日志。

日志文件说明见 [Console 使用指南](Console-User-Guide-CN.md)中的“查看 Console Log”和“找到并提交录制文件”。

### 2.1 接入条件

| 确认项 | 说明 | 处理建议 |
| --- | --- | --- |
| 板载 USB 转串口 | 部分板卡已将 UART 接到 USB 转串口芯片，插 USB 即可连接电脑；核对实际连接的 UART 和 TX GPIO。原生 USB 接口不等同于 USB 转串口。 | 有可用板载连接时优先复用。 |
| 串口用途 | 仅打印普通日志时可考虑复用；同时用于命令输入、外设或工装通信时，需确认是否冲突。 | 日志专用串口可使用本工具；有业务通信时优先选其他串口。 |
| 波特率支持 | USB 转串口设备需要支持固件设置的波特率。不确定时，可查询芯片型号对应的资料，或运行下方脚本检查。 | 建议先确认是否支持 3000000，再以相同波特率进行试录。 |
| 外接位置（无板载连接时） | 核对可用 UART 的 TX GPIO 和 GND 位置；UART 编号与 GPIO 编号需分别确认。 | 接入外部 USB 转串口工具。 |
| 资源调整（有占用时） | 暂停原有串口功能不能影响问题复现。 | 无法释放时评估其他串口或接入方式。 |

确认后，在现有 sdkconfig 中选择 UART 输出，并确定 UART 编号、TX GPIO 和波特率。

**如何确认串口支持的波特率**

BLE Log 建议优先使用 `3000000` 波特率，以便传输更多日志。这里需要确认的是电脑连接的 **USB 转串口芯片或工具**，包括板载 USB 转串口和外接转串口工具。如果不确定它是否支持该速率，可以选择以下一种方式了解。

| 方式 | 具体做法 | 如何使用结果 |
| --- | --- | --- |
| 查询型号 | 从板卡原理图、芯片表面标识或转串口工具说明书中找到具体型号，查询它支持的波特率。不方便确认时，可将型号、相关资料或清晰照片提供给技术支持。 | 根据芯片和驱动资料确认是否支持 `3000000`；不支持时，再确定双方支持的较低速率。 |
| 运行脚本 | 在准备采集日志的电脑上，连接实际使用的转串口设备，关闭占用该端口的程序，再运行 [波特率探测脚本](skills/ble-log-intake/scripts/probe_uart_baudrates.py)。脚本会逐项尝试不同波特率，完整输出可提供给技术支持判断。 | `ACCEPTED` 表示电脑端可以按该设置打开串口；`FAIL` 表示本次尝试失败，也可能是端口被占用、权限不足或设备连接异常。 |

> **脚本通过后仍需试录。** 能设置某个波特率，不代表设备能以该速率稳定接收日志，也不能据此认定它是实际可用的最高波特率。最终以固件和电脑端设置一致后的采集质量报告为准。脚本打开串口时可能使部分板卡复位，运行前需确认业务可以暂停。

### 2.2 配置和接线

| 配置项／连接 | 设置值 | 对应接线／说明 |
| --- | --- | --- |
| `CONFIG_BT_LOG_CRITICAL_ONLY` | `y` | 启用带宽优化模式，同时开启 BLE Log。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA` | `y` | 选择 UART DMA 输出。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT` | **待填写：UART 编号** | 与实际用于日志的串口一致；板载转串口需核对其连接的 UART。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` | **待填写：TX GPIO** | 板载连接使用原有 TX GPIO；外接时，目标板该 GPIO → 转串口 RX。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` | 优先 `3000000` | 接收工具需支持该速率，电脑端设置与固件一致；不支持时选择双方支持的速率。 |
| GND | 无配置项 | 外接时，目标板 GND → 转串口 GND，并确认两端电平兼容。 |
| USB | 无配置项 | 板载或外接转串口工具的对应 USB 接口 → 电脑。 |

### 2.3 连接工具

编译、烧录后，关闭占用该端口的串口监视器，在 BLE Log Console 中选择 **UART** 和对应端口，波特率与固件一致。调整速率后重新试录。

**下一步：[采集验证](#verification)。**

<a id="verification"></a>

## 3. 采集验证

### 3.1 核对配置并试录

重新配置并编译后，核对实际生效的 sdkconfig：输出方式与所选方案一致，GPIO 与接线一致；UART 还需核对端口和波特率。烧录本次构建的固件后再试录。

先运行 BLE 业务并短时录制，确认 **RX 和 Frames 持续增加、原有业务正常**，再点击 **Stop & Review** 检查质量报告。

> **试录也要检查业务表现。** 日志可能影响运行时序。若业务或问题表现改变，先评估配置对复现的影响；偶发问题短时间未出现，不代表已消失。

### 3.2 判断采集结果

| 结果 | 处理建议 |
| --- | --- |
| RX 一直是 0 | 检查固件是否运行并启用日志、端口、接线和供电。 |
| RX 增加，但 Frames 不增加 | 检查传输模式、UART 波特率，以及固件与工具是否匹配。 |
| 报告为“可用于分析” | 进入正式复现；仍需确认采集包含本次问题需要的日志。 |
| 报告为“已保存，但存在警告” | 根据报告判断是否影响本次定位，保留报告和日志。 |
| 报告为“检查配置”或“建议重新录制” | 按报告处理；反复出现时联系技术支持，提供对应报告和日志。 |

### 3.3 正式复现

正式采集时，**先开始录制，再触发问题**。记下问题发生的大致时间和当时操作。

<a id="deliverables"></a>

## 4. 最终产物与提交文件

### 4.1 交付清单

一次完整交付包括本次录制文件、与固件匹配的 log database，以及[配置记录](#records)。

| 产物 | UART | SPI | 用途 |
| --- | --- | --- | --- |
| `ble_log_*.bin` | **必需** | **必需** | 原始 BLE Log，包含全部 `part` 分片。 |
| `ble_log_*_report.txt` | **必需** | **必需** | 同次录制的质量报告。 |
| `ble_log_*_console.log` | 生成时提供 | 当前不生成 | 普通串口日志的可读副本，不能替代 `.bin`。 |
| `ble_log_database/` 整个目录 | 有压缩日志时必需 | 有压缩日志时必需 | 压缩日志解析所需的数据库。 |
| `sdkconfig` 与配置记录 | **必需** | **必需** | 本次固件配置、版本及复现信息，见[配置记录](#records)。 |

### 4.2 录制文件位置

录制文件位于启动录制时选择的保存目录，默认是启动工具时所在目录下的 `logs/`。工具退出时会打印实际文件路径。

- `.bin`、`_report.txt` 和已生成的 `_console.log` 保存在同一目录，应来自**同次录制**。
- 拆分录制需包含**全部 `part` 文件**。
- UART 只有收到重定向的普通日志时才生成 `_console.log`；使用其他 UART 或没有此类日志时，可能没有该文件。

### 4.3 Log database 位置与版本

> **Log database 必须来自实际烧录固件的同一次构建。** 它由固件构建生成，不在电脑端工具的录制目录中。

| 构建方式 | 数据库位置 |
| --- | --- |
| 默认构建目录 | `build/ble_log/ble_log_database/` |
| 自定义构建目录 | `<构建目录>/ble_log/ble_log_database/` |
| 数据库路径另有定制 | 构建目录中 `ble_log/module_info.yml` 的 `log_config.db_path`，相对于构建目录。 |

数据库包含各模块的 `*_logs.json` 等文件，**整个目录**可压缩后随日志提交。

没有启用压缩日志模块的构建可能不生成 database；如果采集包含压缩日志但找不到匹配的数据库，可由技术支持协助确认构建产物，不能用修改源码或配置后重新构建的数据库代替。

<a id="records"></a>

## 5. 配置记录

将验证通过的 sdkconfig 与接线、接收设置一并保存，作为后续采集配置。调整硬件或配置后应重新验证。

| 项目 | 记录内容 |
| --- | --- |
| 版本 | 目标芯片、SDK、BLE Log Console 和 Bridge 固件版本（使用 Bridge 时）。 |
| 固件配置 | 本次构建并通过采集验证的 sdkconfig。 |
| 硬件连接 | SPI / UART、GPIO 与接线位置。 |
| 接收设置 | 电脑端模式、端口及 UART 波特率。 |
| 采集结果 | 日志文件、质量报告、问题发生时间及操作。 |

<a id="advanced"></a>

## 附录：其他配置（SPI / UART 通用）

Buffer 配置用于缓冲待发送的日志、应对短时突发，帮助减少日志丢失；log level 和日志来源开关用于控制日志数量与内容。

> **一般场景沿用默认值或已有确认过的配置。** 高吞吐、多连接、内存紧张或需要更详细日志等特殊场景，可由技术支持结合 sdkconfig、业务负载和质量报告评估是否调整。

### 缓冲配置

| Buffer 配置项 | 当前默认值 | 作用与调整影响 |
| --- | --- | --- |
| `CONFIG_BLE_LOG_POOL_TRANS_CNT` | `8` | 传输缓冲数量。增加数量可容纳更多突发日志，同时增加内存占用。 |
| `CONFIG_BLE_LOG_POOL_TRANS_SIZE` | `640` 字节 | 单个传输缓冲大小，单帧日志必须能完整放入。增大会增加内存占用；SPI 模式要求为 4 的倍数。 |
| `CONFIG_BLE_LOG_POOL_NON_YIELD_RESERVE_CNT` | `1` | 为中断、临界区等不能等待的上下文保留的缓冲数量。增大会减少普通任务可用的缓冲，且必须小于总缓冲数量。 |

缓冲无法解决日志持续产生速度超过传输速度的问题，也不保证完全无丢失。上表默认值不用于覆盖已有确认过的配置。

### 日志级别与来源

| 日志配置项 | 作用 | 配置说明 |
| --- | --- | --- |
| `CONFIG_BT_LOG_CRITICAL_ONLY` | 启用带宽优化模式，减少日志量。 | UART 按前表启用；需要更详细日志时，由技术支持评估日志范围和传输能力。 |
| `CONFIG_BT_LE_CONTROLLER_LOG_OUTPUT_LEVEL` / `CONFIG_BT_CTRL_LE_LOG_LEVEL` | 控制 Controller 日志级别。 | 适用项及级别含义取决于芯片、Controller 和 SDK，不能统一按数值大小判断日志量。 |
| NimBLE 日志级别 / Bluedroid 各模块 Trace Level | 控制 Host 日志的详细程度。 | 例如 `CONFIG_BT_NIMBLE_LOG_LEVEL_INFO`、`CONFIG_BT_LOG_HCI_TRACE_LEVEL_EVENT`。更详细的日志通常占用更多带宽。 |
| `CONFIG_BLE_LOG_HOST_LOG`、`CONFIG_BLE_LOG_LL_ENABLED`、`CONFIG_BLE_LOG_HCI_LOG_ENABLED` | 控制 Host、链路层和 HCI 日志来源。 | 关闭来源可能减少日志量，也可能丢失定位信息；适用条件取决于协议栈和 Controller 配置。 |

切换 SPI / UART 不会自动恢复已有日志级别。日志范围应覆盖待定位的问题，调整后的传输质量通过试录确认。

[ble-log-console]: https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable
