# language: zh-CN
功能: 一个 USB 入口选择 OTG 或 USJ

  场景大纲: 混合设备列表无需打开串口即可选择正确接收方式
    假如 系统同时枚举 USB OTG、USJ 和 SPI Bridge
    当 在统一 USB 列表刷新并选择 <port>
    那么 连接使用 <mode> 且枚举没有打开串口

    例子:
      | port         | mode       |
      | /dev/ttyACM0 | usb_output |
      | /dev/ttyACM1 | usj        |

  场景: USJ 录制失败返回设置页时保留接收方式
    假如 默认录制配置是暂时未枚举到的 USJ 端口
    当 在统一 USB 设置页重试连接
    那么 连接使用 usj 且枚举没有打开串口
