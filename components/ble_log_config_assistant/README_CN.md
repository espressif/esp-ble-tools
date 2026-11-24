# BLE Log 配置助手

这是一个独立的中英文终端向导，用于在已有 ESP-IDF 工程中安全开启 BLE Log，
支持 USB Serial/JTAG、USB OTG、SPI Bridge 和 UART。

## 使用方法

1. 打开能直接运行 `idf.py` 的 ESP-IDF 终端。
2. 在工程目录运行 `ble_log_config_assistant`，也可以把工程目录作为唯一参数传入。
3. 在窗口顶部选择中文或 English。已配置过的工程会直接进入外设选择；首次配置的工程请先运行 `idf.py reconfigure`。
4. 选择目标板使用的接口，查看配置预览，再点击 **应用配置**。UART 会启用“仅关键日志”以降低串口流量。USJ 会关闭第二控制台，将该端口留给 BLE Log。SPI 按板上接线填写引脚。USB OTG 使用 TinyUSB CDC，缺少组件时预览会列出要添加的依赖。
5. 按工程原有流程编译、烧录，然后在 BLE Log Console 中选择对应端口录制。

助手用 ESP-IDF 的 `confserver` 校验所选配置。保存时先备份原文件为 `sdkconfig.bak.*`，再将预览中的配置项写入现有 `sdkconfig`。其余配置和注释保留原样。工程的重新配置由后续构建完成。

## 开发与构建

要求 Python 3.10+。界面与 BLE Log Console 一样使用 Textual，并复用相同的目录选择器。

```bash
python -m pip install -e '.[test]'
pytest
python -m ble_log_config_assistant
```

构建当前平台的单文件程序：

```bash
python -m pip install -e '.[build]'
python build.py
```

在 Windows x64 构建时，安装带有 `py` 启动器的 Python 3.11 x64，在助手目录运行 `.\build.bat`。脚本创建本地虚拟环境、运行测试并验证成品版本。输出为 `dist\ble_log_config_assistant_windows_v0.1.0.exe`。使用者可在 ESP-IDF 终端里直接运行该文件，打开界面后选择工程目录。
