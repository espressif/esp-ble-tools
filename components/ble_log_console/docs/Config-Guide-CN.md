# BLE Log 配置指南

[中文](Config-Guide-CN.md) | [English](Config-Guide-EN.md)

> **优先 USB 直连。** 确认目标板有对应的 USB 插座，或能通过引出的 D+、D− 和 GND 接入 USB，且固件支持所选的 USB OTG 或 USJ 输出。直连条件不具备时，再选择 SPI Bridge 或 UART。

工具下载：[BLE Log Console 稳定版发布页][ble-log-console] · [BLE Log 配置助手稳定版发布页][ble-log-config-assistant]。电脑端录制操作参照 [Console 使用指南](Console-User-Guide-CN.md)。

本文用于根据实际硬件和资源占用，确定一套可用的 BLE Log sdkconfig 及配套接线。以现有工程的 sdkconfig 为基础，逐项确定传输方式、端口、GPIO 和速率，再通过试录验证。配置项是否可用取决于目标芯片和 SDK 版本。

**阅读顺序：选择 USB 直连、SPI Bridge 或 UART → 配置与接线 → 试录验证 → 提交产物。**

[USJ 配置](#usj) · [USB OTG 配置](#usb) · [SPI 配置](#spi) · [UART 配置](#uart) · [采集验证](#verification) · [最终产物](#deliverables) · [配置记录](#records) · [缓冲与日志量](#advanced)

## 快速选择

| 顺序 | 使用条件 | 选择与操作 |
| --- | --- | --- |
| 1. USB 直连（推荐） | 板卡引出了芯片原生 USB，所用固件支持通过该外设输出 BLE Log。 | 板上引出内置 [USJ](#usj) 时优先选用；使用 TinyUSB CDC 时选 [USB OTG](#usb)。两者在 Console 中都选 **USB**。 |
| 2. SPI Bridge | 目标板有空闲 SPI，可接出 MOSI、SCLK、CS 和 GND，手边有独立 Bridge。 | 按 [SPI 配置](#spi) 连接两块板。 |
| 3. UART | 有可用的板载 USB 转串口，或能引出 UART TX 和 GND 接外置适配器。 | 按 [UART 配置](#uart) 核对 TX 和双方波特率。 |

### 简化配置：使用 BLE Log 配置助手（推荐）

选定外设后，可在工程的 **ESP-IDF 终端**中运行交互式向导，代替手动逐项修改 Kconfig：

1. 在 Windows x64 或 Ubuntu x86-64 的 ESP-IDF 终端中，进入已启用蓝牙的工程根目录。首次配置工程时，先运行 `idf.py reconfigure` 生成 `sdkconfig`。
2. 运行 `idf.py ble-log-config-assistant`，助手会打开当前工程。如果 ESP-IDF 没有这条命令，可从[稳定版发布页][ble-log-config-assistant]下载助手，在同一终端启动并选择工程目录（Linux 首次运行需先执行 `chmod +x`）。
3. 在向导中选择所用的外设接口（USB OTG / USJ / SPI Bridge / UART），核对变更预览后点击 **应用配置（Apply configuration）**：
   - 工具会自动处理联动配置（如 UART 启用精简日志、USJ 关闭第二控制台、SPI 检查重复引脚、USB OTG 提示添加 TinyUSB 依赖）。
   - 保存前自动将原配置备份为 `sdkconfig.bak.*`，并保留工程其余配置与注释。
4. 按原有流程编译并烧录固件，接好设备后运行 `idf.py ble-log-console` 或打开已下载的 Console，进入 [采集验证](#verification)。

> 若不便运行该工具，或需确认硬件接线要求与具体配置宏说明，请继续阅读下方对应章节。

## 1. USB 直连配置（推荐）

目标芯片原生支持 USB 直连且板卡引出了对应接口时，一根 USB 数据线即可高速输出完整 BLE Log，无需外接 Bridge，也不受串口波特率限制。板上同时引出两种接口时，优先选择 **USJ**。芯片支持表与接线示意参见 [Console 使用指南](Console-User-Guide-CN.md#usb-direct)。

### 1.1 接入条件

| 确认项 | 条件与说明 | 处理建议 |
| --- | --- | --- |
| 原生 USB 接口 | **板卡引出了所选外设的原生 USB 插座，或可接出 D+、D− 和 GND。**<br>接在板载 USB 转串口芯片上的插座属于 UART，不能用于 USB 直连。 | 板上引出 USJ 时优先选 USJ；均未引出时改用 [SPI](#spi) 或 [UART](#uart)。 |
| 芯片与 SDK 支持 | **目标芯片具备对应外设，且当前 ESP-IDF 支持对应输出项。**<br>USJ 对应 `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG`，USB OTG 对应 `CONFIG_BLE_LOG_PRPH_USB`。 | 当前 SDK 不支持时改用 [SPI](#spi) 或 [UART](#uart)。 |
| 端口独占（选 USJ 时） | **USJ 端口未被主/次控制台、`esp_trace` 或 OpenThread RCP 占用，且保持 `CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=y`。**<br>被占用时 `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG` 不会显示。 | 在不影响问题复现的前提下释放 USJ 端口；否则改用其他方式。 |
| 组件与外设（选 USB OTG 时） | **工程可引入 `espressif/esp_tinyusb` 组件，且未与其他自定义 USB OTG 业务冲突。**<br>仅烧录固件但业务未初始化 BLE Log 时，电脑不会枚举出该 CDC 端口。 | 执行 `idf.py add-dependency` 添加依赖；若冲突则改用其他方式。 |

满足上述条件后，按所选外设在现有 `sdkconfig` 中完成配置。

### 1.2 配置和接线

<a id="usj"></a>

#### USB Serial/JTAG（USJ）

| 配置项／连接 | 设置值 | 对应接线／说明 |
| --- | --- | --- |
| `CONFIG_BLE_LOG_ENABLED` | `y` | 启用 BLE Log。 |
| `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG` | 不启用 | 主控制台保留在默认 UART0 等其他通道。 |
| `CONFIG_ESP_CONSOLE_SECONDARY_NONE` | `y` | 关闭第二控制台以释放 USJ 端口。 |
| `CONFIG_BLE_LOG_PRPH_USB_SERIAL_JTAG` | `y` | 选择 USJ 输出（端口空闲且 SDK 支持时可选）。 |
| USB | 无配置项 | 芯片原生 USJ 口 → 电脑（USB 数据线，USB ID `303A:1001`）。 |

<a id="usb"></a>

#### USB OTG

| 配置项／连接 | 设置值 | 对应接线／说明 |
| --- | --- | --- |
| TinyUSB 组件依赖 | `espressif/esp_tinyusb^2.0.0` | 未引入时在工程根目录执行 `idf.py add-dependency "espressif/esp_tinyusb^2.0.0"`。 |
| `CONFIG_BLE_LOG_ENABLED` | `y` | 启用 BLE Log。 |
| `CONFIG_BLE_LOG_PRPH_USB` | `y` | 选择 USB OTG 输出（自动启用 TinyUSB CDC 并使用默认缓冲区）。 |
| USB | 无配置项 | 芯片原生 USB OTG 口 → 电脑（USB 数据线，USB ID `303A:10B1`）。 |

若所用旧版 ESP-IDF 未自动启用 CDC 或单独列出了 BLE Log CDC 缓冲配置，请同时开启 `CONFIG_TINYUSB_CDC_ENABLED=y` 并按编译提示调整缓冲区大小。

### 1.3 连接工具

编译、烧录后，用数据线连接对应原生 USB 口，在 BLE Log Console 中选择 **USB**，再选标有 **USJ** 或 **USB OTG** 的端口。

**下一步：[采集验证](#verification)。**

<a id="spi"></a>

## 2. SPI Log 配置

SPI 带宽更充足，适合采集较大量的日志，便于快速定位问题。目标板通过三根信号线和 GND 连接 Bridge，再由 Bridge 连接电脑。

### 2.1 接入条件

> **先确认能否接线。** SPI 空闲并不代表引脚能够接出；接线条件确认后再检查 SPI 资源。

| 确认项 | 条件与说明 | 处理建议 |
| --- | --- | --- |
| 接线条件 | **能接出三根信号线和 GND。**<br>优先使用现成接口或测试点；需要拆机、焊线时，评估现场是否方便实施。 | 无法接线时选择 UART。 |
| Bridge 设备 | **有独立 Bridge 或可用的 ESP32P4 开发板。**<br>ESP32P4 开发板需烧录配套 Bridge 固件；Bridge 与目标设备必须是不同设备。 | 准备 Bridge，可向技术寻求资源支持，无法准备时选择 UART。 |
| SPI 资源 | **是否与现有外设冲突，停用或调整外设不影响问题复现。**<br>若调整后原问题不再出现，应保留原有外设工作条件。 | 无法释放资源时选择 UART。 |
| GPIO 位置 | **三个可用 GPIO 和 GND 均可连接。**<br>核对 GPIO 编号与板上位置，并确认适用于所需输出信号；不要直接套用示例引脚。 | 填写配置和接线表。 |

> **资源限制：** 当前实现使用 SPI Controller 2；若已有 SPI 外设，请检查是否占用同一控制器。

满足上述条件后，在现有 sdkconfig 中选择 SPI 输出，并确定 MOSI、SCLK、CS 的 GPIO；否则参见 [UART 配置](#uart)。

### 2.2 配置和接线

| 配置项／连接 | 设置值 | 对应接线／说明 |
| --- | --- | --- |
| `CONFIG_BLE_LOG_ENABLED` | `y` | 启用 BLE Log。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA` | `y` | 选择 SPI DMA 输出。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM` | **待填写：MOSI GPIO** | 目标板该 GPIO → Bridge IO 4。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM` | **待填写：CLK GPIO** | 目标板该 GPIO → Bridge IO 5。 |
| `CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM` | **待填写：CS GPIO** | 目标板该 GPIO → Bridge IO 6。 |
| GND | 无配置项 | 目标板 GND → Bridge GND。 |

这里的 Bridge 引脚对应配套 ESP32P4 Bridge 固件。确认两端电平兼容，接线尽量短，并正确共地。

### 2.3 连接工具

编译、烧录后，电脑端选择 **SPI Bridge**。Bridge 准备步骤参照 [Console 使用指南](Console-User-Guide-CN.md#3-spi-bridge-模式)。

**下一步：[采集验证](#verification)。**

<a id="uart"></a>

## 3. UART Log 配置（备选）

不具备 SPI 接入条件时，可使用 UART。**优先复用板载 USB 转串口和现有日志串口，减少额外接线。** UART 带宽较有限，建议先使用带宽优化配置试录。

> **仅用于普通日志打印的串口也可复用。** 当前 UART0 路径会将普通串口日志与 BLE Log 一起发送到 BLE Log Console，支持显示和保存。其他 UART 不会自动转发 UART0 的普通日志。

日志文件说明见 Console 使用指南中的[查看实时日志](Console-User-Guide-CN.md#console-log-files)和[找到并提交录制文件](Console-User-Guide-CN.md#recording-files)。

### 3.1 接入条件

| 确认项 | 条件与说明 | 处理建议 |
| --- | --- | --- |
| 板载 USB 转串口 | 部分板卡已将 UART 接到 USB 转串口芯片，插 USB 即可连接电脑；核对实际连接的 UART 和 TX GPIO。芯片原生 USB 接口不等同于 USB 转串口；芯片内置 USB Serial/JTAG 端口见 [USJ Log](#usj)。 | 有可用板载连接时优先复用。 |
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

### 3.2 配置和接线

| 配置项／连接 | 设置值 | 对应接线／说明 |
| --- | --- | --- |
| `CONFIG_BT_LOG_CRITICAL_ONLY` | `y` | 启用带宽优化模式，同时开启 BLE Log。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA` | `y` | 选择 UART DMA 输出。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_PORT` | **待填写：UART 编号** | 与实际用于日志的串口一致；板载转串口需核对其连接的 UART。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_TX_IO_NUM` | **待填写：TX GPIO** | 板载连接使用原有 TX GPIO；外接时，目标板该 GPIO → 转串口 RX。 |
| `CONFIG_BLE_LOG_PRPH_UART_DMA_BAUD_RATE` | 优先 `3000000` | 接收工具需支持该速率，电脑端设置与固件一致；不支持时选择双方支持的速率。 |
| GND | 无配置项 | 外接时，目标板 GND → 转串口 GND，并确认两端电平兼容。 |
| USB | 无配置项 | 板载或外接转串口工具的对应 USB 接口 → 电脑。 |

### 3.3 连接工具

编译、烧录后，关闭占用该端口的串口监视器，在 BLE Log Console 中选择 **UART** 和对应端口，波特率与固件一致。调整速率后重新试录。

**下一步：[采集验证](#verification)。**

<a id="verification"></a>

## 4. 采集验证

### 4.1 核对配置并试录

重新配置并编译后，核对实际生效的 sdkconfig：输出方式与所选方案一致，GPIO 与接线一致；UART 还需核对端口和波特率；USJ 还需确认已选择 USB Serial/JTAG 输出，且没有控制台占用该端口。烧录本次构建的固件后再试录。

先运行 BLE 业务并短时录制，确认 **RX 和 Frames 持续增加、原有业务正常**，再点击 **Stop & Review** 检查质量报告。

> **试录也要检查业务表现。** 日志可能影响运行时序。若业务或问题表现改变，先评估配置对复现的影响；偶发问题短时间未出现，不代表已消失。

### 4.2 判断采集结果

| 结果 | 处理建议 |
| --- | --- |
| RX 一直是 0 | 检查固件是否运行并启用日志、端口、接线和供电。 |
| RX 增加，但 Frames 不增加 | 检查传输模式、UART 波特率，以及固件与工具是否匹配。 |
| 状态栏显示“纯文本”（UART 或 USJ） | 端口上收到的是普通控制台文本，而不是 BLE Log。BLE Log 启动前出现文本属于正常现象；警告反复出现时，检查固件是否把 BLE Log 输出到这个端口。录制会继续。 |
| 报告为“可用于分析” | 进入正式复现；仍需确认采集包含本次问题需要的日志。 |
| 报告为“已保存，但存在警告” | 根据报告判断是否影响本次定位，保留报告和日志。 |
| 报告为“检查配置”或“建议重新录制” | 按报告处理；反复出现时联系技术支持，提供对应报告和日志。 |

### 4.3 正式复现

正式采集时，**先开始录制，再触发问题**。记下问题发生的大致时间和当时操作。

<a id="deliverables"></a>

## 5. 最终产物与提交文件

### 5.1 交付清单

一次完整交付包括本次录制文件、与固件匹配的 log database，以及[配置记录](#records)。

| 产物（所有模式） | 何时提供 |
| --- | --- |
| 原始 `.bin` 和同次录制的 `_report.txt` | 每次提交；较大录制需附全部 `part` 分片。 |
| `<录制名>_database/` | 录制时选择了 Database，就将该副本与同名录制一起打包。 |
| `sdkconfig` 与[配置记录](#records) | 提供本次构建配置、接线和复现信息。 |
| 已生成的日志文件 | 按问题附 Host 文本、HCI btsnoop 或实时转录。UART 和 USJ 的启动或崩溃文本可在 `_console.log` 中查看。 |

### 5.2 录制文件位置

文件保存在启动页的 **保存目录**。首次使用默认为当前工作目录下的 `logs/`，此后沿用上次选择。报告列出同次录制的文件路径；文件后缀和用途见[使用指南的录制产物表](Console-User-Guide-CN.md#recording-files)。

### 5.3 Log database 位置与版本

> **Database 必须来自实际烧录固件的同一次构建。** Console 会将所选目录下的模块文件（`*_logs.json`）随当次录制保存一份。

| 构建方式 | 数据库位置 |
| --- | --- |
| 默认构建目录 | `build/ble_log/ble_log_database/` |
| 自定义构建目录 | `<构建目录>/ble_log/ble_log_database/` |
| 数据库路径另有定制 | 构建目录中 `ble_log/module_info.yml` 的 `log_config.db_path`，相对于构建目录。 |

数据库包含各模块的 `*_logs.json` 等文件，**整个目录**可压缩后随日志提交。

没有启用压缩日志模块的构建可能不生成 database；如果采集包含压缩日志但找不到匹配的数据库，可由技术支持协助确认构建产物，不能用修改源码或配置后重新构建的数据库代替。

<a id="records"></a>

## 6. 配置记录

将验证通过的 sdkconfig 与接线、接收设置一并保存，作为后续采集配置。调整硬件或配置后应重新验证。

| 项目 | 记录内容 |
| --- | --- |
| 版本 | 目标芯片、SDK、BLE Log Console 和 Bridge 固件版本（使用 Bridge 时）。 |
| 固件配置 | 本次构建并通过采集验证的 sdkconfig。 |
| 硬件连接 | USB OTG / USJ / SPI / UART、GPIO 与接线位置。 |
| 接收设置 | 电脑端模式、端口及 UART 波特率。 |
| 采集结果 | 日志文件、质量报告、问题发生时间及操作。 |

<a id="advanced"></a>

## 附录：其他配置（USB OTG / USJ / SPI / UART 通用）

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

切换 USB OTG / USJ / SPI / UART 不会自动恢复已有日志级别。日志范围应覆盖待定位的问题，调整后的传输质量通过试录确认。

[ble-log-console]: https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable
[ble-log-config-assistant]: https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_config_assistant_stable
