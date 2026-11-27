# language: zh-CN
# Windows API 返回值和串口句柄使用替身；不代表 Windows 真机吞吐或驱动验收。
功能: Windows CDC 串口接收

  场景大纲: 没有产品描述也能识别并打开高编号 COM 端口
    假如 Windows 上有一个 <mode> CDC 端口 COM12
    当 枚举并打开这个 CDC 端口
    那么 仅按设备身份选择 COM12 并独占打开

    例子:
      | mode           |
      | SPI_USB_BRIDGE |
      | USB_OUTPUT     |
      | USJ            |

  场景大纲: Windows 打开失败时不重复打开端口
    假如 Windows 上有一个 <mode> CDC 端口 COM12
    并且 Windows 返回访问被拒绝错误
    当 尝试打开这个 CDC 端口
    那么 只尝试一次并提示检查 Windows COM 端口

    例子:
      | mode           |
      | SPI_USB_BRIDGE |
      | USB_OUTPUT     |
      | USJ            |

  场景: USB OTG 控制线失败时关闭句柄而不是报告已连接
    假如 Windows 上有一个 USB_OUTPUT CDC 端口 COM12
    并且 设置 DTR 时设备返回 I/O 错误
    当 尝试打开这个 CDC 端口
    那么 打开失败且设备句柄已关闭
