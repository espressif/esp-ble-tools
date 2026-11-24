# ESP BLE Tools

[English](./README.md) | [中文](./README_CN.md)

ESP BLE Tools 提供在电脑上开发、调试和验证 ESP BLE 应用以及采集日志的工具。每个工具的源码、文档、测试和打包脚本都放在 `components/` 下的独立目录。

## 工具

### BLE Log Console

在终端中发现设备、实时查看和保存 BLE 日志。支持 UART 和 SPI Bridge 等接入方式，可保存原始录制、显示解码结果，并查看丢帧统计。使用和构建方法见 [BLE Log Console 中文说明](./components/ble_log_console/README_CN.md)。

### BLE Log 配置助手

在已有 ESP-IDF 工程中选择 BLE Log 输出接口，预览并应用对应的 `sdkconfig` 修改。使用和构建方法见 [配置助手中文说明](./components/ble_log_config_assistant/README_CN.md)。
