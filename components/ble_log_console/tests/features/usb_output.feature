# language: zh-CN

# 观察边界：本文件只覆盖 USB Output 的传输层契约（设备身份、DTR、复位、速率口径、错误提示）
# 与模式选择；字节流解码与状态栏展示由 status_bar.feature 覆盖。

功能: 从 USB Output 口接收 BLE Log

  场景: 枚举时只认 USB Output 身份
    假如 系统上有这些串口设备
      | device       | vid_pid   | product                 |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port (esp32s31) |
      | /dev/ttyACM1 | 303A:1001 | USB-Serial-JTAG         |
      | /dev/ttyACM2 | 303A:4001 | USB-SPI-BRIDGE          |
    当 列出 USB Output 端口
    那么 列出的端口是
      | /dev/ttyACM0 |

  场景: product 串读不到或不是本固件也照样列出（身份只看 VID:PID）
    假如 系统上有这些串口设备
      | device       | vid_pid   | product            |
      | /dev/ttyACM0 | 303A:10B1 |                    |
      | /dev/ttyACM1 | 303A:10B1 | Some Other CDC App |
    当 列出 USB Output 端口
    那么 列出的端口是
      | /dev/ttyACM0 |
      | /dev/ttyACM1 |

  场景: product 串里的 chip 目标直接标在端口上
    假如 系统上有这些串口设备
      | device       | vid_pid   | product                |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port (esp32s3) |
    当 列出 USB Output 端口
    那么 端口标签是 "USB  /dev/ttyACM0 (esp32s3)"

  场景: product 串只有基名时不编造目标
    假如 系统上有这些串口设备
      | device       | vid_pid   | product      |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port |
    当 列出 USB Output 端口
    那么 端口标签是 "USB  /dev/ttyACM0"

  场景: product 里的 chip 目标不同不影响识别
    假如 系统上有这些串口设备
      | device       | vid_pid   | product                 |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port (esp32s3)  |
      | /dev/ttyACM1 | 303A:10B1 | BLE-Log-Port (esp32s31) |
    当 列出 USB Output 端口
    那么 列出的端口是
      | /dev/ttyACM0 |
      | /dev/ttyACM1 |

  场景大纲: 端口标签带上 USB 速度档
    假如 系统上有这些串口设备
      | device       | vid_pid   | product        |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port   |
    并且 设备 "/dev/ttyACM0" 的 USB 设备目录里 speed 为 "<speed>"
    当 列出 USB Output 端口
    那么 端口标签是 "USB <tier>  /dev/ttyACM0"

    例子:
      | speed | tier |
      | 480   | HS   |
      | 12    | FS   |

  场景大纲: 速度档读不到时不猜
    假如 系统上有这些串口设备
      | device       | vid_pid   | product        |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port   |
    并且 设备 "/dev/ttyACM0" 的 speed 信息为 "<state>"
    当 列出 USB Output 端口
    那么 端口标签是 "USB  /dev/ttyACM0"

    例子:
      | state  |
      | 不存在 |
      | 读不出 |

  场景: 打开端口后保持 DTR 有效
    假如 一个 USB Output 端口 "/dev/ttyACM0"
    当 打开该端口
    那么 该端口保持了 DTR 有效

  场景: 复位目标时不发 RTS 下载脉冲
    假如 一个 USB Output 端口 "/dev/ttyACM0"
    当 打开该端口
    并且 请求复位目标
    那么 未发送 RTS 脉冲
    并且 复位报告为未执行

  场景: USB 模式不设线速上限
    假如 一个 USB Output 端口 "/dev/ttyACM0"
    当 读取该端口的速率配置
    那么 线速上限为空

  场景大纲: 打开失败时给出可执行提示
    假如 一个 USB Output 端口 "/dev/ttyACM0"
    并且 打开端口会因「<failure>」失败
    当 尝试打开该端口
    那么 错误提示建议 "<hint>"

    例子:
      | failure      | hint         |
      | 权限不足     | dialout      |
      | 端口被占用   | ModemManager |
      | 设备已移除   | Re-plug      |

  场景: 命令行与界面都用 usb 指代该模式
    当 用 "usb" 选择传输模式
    那么 得到 USB Output 模式
