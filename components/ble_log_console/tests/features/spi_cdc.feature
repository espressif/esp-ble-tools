# language: zh-CN
功能: SPI Bridge 在各平台仅使用 CDC 接收

  场景大纲: 有 CDC 端口时不依赖直接 USB 接收
    假如 在 <platform> 上系统已枚举 Bridge CDC 端口
    当 查找并选择 SPI Bridge 接收端口
    那么 使用共用串口接收器且不访问 USB Bulk

    例子:
      | platform |
      | linux    |
      | darwin   |
      | win32    |

  场景大纲: 没有 CDC 端口时不回退到直接 USB 接收
    假如 在 <platform> 上系统没有 Bridge CDC 端口
    当 查找 SPI Bridge 接收端口
    那么 没有可选端口且不访问 USB Bulk

    例子:
      | platform |
      | linux    |
      | darwin   |
      | win32    |

  场景: 拒绝旧的 Bulk 地址并提示选择 CDC 串口
    假如 在 linux 上系统已枚举 Bridge CDC 端口
    当 使用旧的 Bulk 地址创建 SPI Bridge 接收器
    那么 提示改用 CDC 串口且不访问 USB Bulk

  场景: 发布程序无需 PyUSB 即可接收所有 CDC 模式
    当 在禁用 PyUSB 的新进程启动 Console 并接收各模式数据
    那么 SPI、USB OTG 和 USJ 均可通过串口接收且不加载 Bulk 工具
