# language: zh-CN
功能: SPI Bridge 在各平台优先复用 CDC 接收

  场景大纲: 有 CDC 端口时不依赖直接 USB 接收
    假如 在 <platform> 上系统已枚举 Bridge CDC 端口
    当 查找并选择 SPI Bridge 接收端口
    那么 使用共用串口接收器且不访问 USB Bulk

    例子:
      | platform |
      | linux    |
      | darwin   |
      | win32    |
