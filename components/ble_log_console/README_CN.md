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

日志会保存到选择的目录。接线方式、固件配置、命令行用法和常见问题请查看 [中文用户指南](./docs/User-Guide-CN.md)。
