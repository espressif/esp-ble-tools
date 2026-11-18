# language: zh-CN

# 观察边界：本文件只看命令行 `ports --mode spi` 的用户可见输出（公开路径），
# 用假的 USB 设备替换 pyusb 枚举，不碰真实设备；TUI 启动界面的同一段说明
# 由 tests/test_launch_screen.py 覆盖。

功能: SPI Bridge 插着却打不开时说明原因

  场景: 缺少 USB 权限规则时给出装规则的办法
    假如 系统上有一个 bus 为 1、addr 为 8 的 SPI Bridge
    并且 这个 SPI Bridge 因为缺少权限而打不开
    当 列出 SPI 模式的端口
    那么 输出显示 "  (none)"
    并且 输出说明没有 USB 访问权限，并给出用 sudo 运行一次工具的办法

  场景: 缺少 libusb 后端时说明要装什么
    假如 枚举 USB 设备时没有可用的 libusb 后端
    当 列出 SPI 模式的端口
    那么 输出显示 "  (none)"
    并且 输出说明缺少 libusb-1.0

  场景: 读端点时设备报错也给出原始错误
    假如 系统上有一个 bus 为 1、addr 为 8 的 SPI Bridge
    并且 这个 SPI Bridge 读配置里的接口时报 I/O 错误
    当 列出 SPI 模式的端口
    那么 输出显示 "  (none)"
    并且 输出原样给出设备报告的 "Input/output error"

  场景: 能正常打开的 SPI Bridge 照常列出端点
    假如 系统上有一个 bus 为 1、addr 为 8 的 SPI Bridge
    当 列出 SPI 模式的端口
    那么 输出列出端点 "--port 1:8:0:129"

  场景: 完全没有设备时不给出误导性的原因
    假如 系统上没有挂 SPI Bridge
    当 列出 SPI 模式的端口
    那么 输出显示 "  (none)"
    并且 输出只字不提 USB 权限或 libusb
