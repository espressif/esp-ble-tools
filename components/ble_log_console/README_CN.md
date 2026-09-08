# BLE Log Console

[English](./README.md) | [中文](./README_CN.md)

BLE Log Console 是一个用于实时接收、显示和保存 ESP BLE 日志的电脑端工具。

它支持：

- **UART**：通过串口接收 BLE 日志。
- **SPI Bridge**：通过 BLE Log SPI USB Bridge 设备接收 BLE 日志。

## 工具下载

请从 GitHub Release 下载最新稳定版工具包：

[BLE Log Console 工具下载](https://github.com/espressif/esp-ble-tools/releases/tag/ble_log_console_stable)

## 用户手册

推荐首次使用前先阅读用户手册。

[中文用户指南](./docs/User-Guide-CN.md) | [User Guide](./docs/User-Guide-EN.md)

## 快速使用

1. 从稳定版 Release 页面下载对应操作系统的工具包。
2. 启动工具：

```bash
# Windows
ble_log_console_windows_v1.0.5.exe

# Linux
chmod +x ./ble_log_console_ubuntu_v1.0.5
./ble_log_console_ubuntu_v1.0.5
```

3. 在界面中选择语言、传输模式、端口、UART 波特率和日志保存目录，然后点击 **Connect** 开始接收日志。
4. 录制完成后点击 **Stop & Review**，工具会保存数据并显示质量结论。

Linux 下首次使用 SPI Bridge 时，请先用 `sudo` 运行一次工具，然后重新拔插 Bridge 设备：

```bash
sudo ./ble_log_console_ubuntu_v1.0.5
```

日志会保存到选择的目录。接线方式、固件配置和基本操作请查看 [中文用户指南](./docs/User-Guide-CN.md)。

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
| 查看帮助 | `./ble_log_console_ubuntu_v1.0.5 --help` | `ble_log_console_windows_v1.0.5.exe --help` |
| 列出端口 | `./ble_log_console_ubuntu_v1.0.5 ports` | `ble_log_console_windows_v1.0.5.exe ports` |
| 启动交互模式 | `./ble_log_console_ubuntu_v1.0.5` | `ble_log_console_windows_v1.0.5.exe` |
| 启动 UART 模式 | `./ble_log_console_ubuntu_v1.0.5 --mode uart --port /dev/ttyUSB0` | `ble_log_console_windows_v1.0.5.exe --mode uart --port COM3` |
| 启动 SPI Bridge 模式 | `./ble_log_console_ubuntu_v1.0.5 --mode spi --port <PORT>` | `ble_log_console_windows_v1.0.5.exe --mode spi --port <PORT>` |
| 查看已保存日志 | `./ble_log_console_ubuntu_v1.0.5 ls` | `ble_log_console_windows_v1.0.5.exe ls` |

### 命令行参数

| 参数 | 缩写 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--mode` | `-m` | `uart` | 传输模式：`uart` 或 `spi` |
| `--port` | `-p` | 可选 | 串口或 SPI Bridge 端口。省略时打开交互界面 |
| `--baudrate` | `-b` | `3000000` | UART 波特率，必须与固件配置一致 |
| `--log-dir` | `-d` | `./logs` | 录制文件保存目录 |
| `--debug` | 无 | 关闭 | 显示额外的调试信息 |

子命令：

| 命令 | 说明 |
| --- | --- |
| `ports` | 列出 UART 串口和 SPI Bridge 端口，可用 `--mode` 过滤 |
| `ls` | 列出指定目录中的 `ble_log_*.bin` 录制文件 |

`--output/-o` 仍保留为兼容旧版本的隐藏选项；推荐使用 `--log-dir`。

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
| `r` | 复位目标设备；SPI Bridge 模式下不支持 |

## 故障排查

连接异常、日志显示、质量检查限制、源码环境安装和 Bridge 版本确认见[用户指南末尾的故障排查](./docs/User-Guide-CN.md#faq-no-port)。
