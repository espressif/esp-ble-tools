# language: zh-CN

# 观察边界：本文件覆盖 USB Serial/JTAG（USJ）的传输层契约（设备身份、打开时的 DTR/RTS 次序、
# 独占打开、复位、速率口径）与命令行、启动界面的模式选择。打开场景使用真实 pyserial 和 POSIX
# 虚拟串口；虚拟串口没有调制解调线路，所以用一个线路模型接管 DTR/RTS 的 ioctl，模型按场景给出
# 设备刚打开时的线路状态（Linux CDC-ACM 在打开时置位 DTR 和 RTS，即 1/1），并记录每次 ioctl 之后
# 的状态。USJ 在 RTS 有效而 DTR 无效时复位芯片（esptool 的 USJ 复位序列）。这证明 Console 发出的
# 线路次序，不证明真实 USB 主机、驱动或芯片的行为，后者只能用实物验证。
# 字节流里的文本与 BLE Log 识别由 console_text.feature 覆盖。

功能: 从 USB Serial/JTAG 口接收 BLE Log

  场景: 枚举时只认 USJ 身份
    假如 系统上有这些串口设备
      | device       | vid_pid   | product                 |
      | /dev/ttyACM0 | 303A:10B1 | BLE-Log-Port (esp32s31) |
      | /dev/ttyACM1 | 303A:1001 | USB JTAG/serial debug   |
      | /dev/ttyACM2 | 303A:4001 | USB-SPI-BRIDGE          |
      | /dev/ttyUSB0 | 10C4:EA60 | CP2102N                 |
    当 列出 USJ 端口
    那么 列出的端口是
      | /dev/ttyACM1 |
    并且 端口标签是 "USJ  /dev/ttyACM1"

  场景大纲: 打开时 RTS 先于 DTR 释放，线路不经过复位组合
    假如 一个 USJ 虚拟串口，设备打开后 DTR/RTS 为 <打开后线路>
    当 打开该 USJ 端口
    那么 DTR/RTS 依次经过 <线路变化>
    并且 线路从未处于 RTS 有效而 DTR 无效
    并且 打开后 DTR 和 RTS 都无效，且没有写入任何数据

    例子:
      | 打开后线路 | 线路变化            |
      | 1/1        | 1/1、1/0、0/0      |
      | 0/0        | 0/0、1/0、1/1、1/0、0/0 |

  场景: 端口已被其他程序独占时拒绝打开，不改动线路也不退回普通打开
    假如 一个 USJ 虚拟串口，设备打开后 DTR/RTS 为 1/1
    并且 该端口已被其他程序独占
    当 尝试打开该 USJ 端口
    那么 打开失败并提示端口无法独占
    并且 只打开过一次设备
    并且 没有改动 DTR 或 RTS

  场景: 平台不支持独占时退回普通打开，同样不经过复位组合
    假如 一个 USJ 虚拟串口，设备打开后 DTR/RTS 为 1/1
    并且 该平台不支持独占打开
    当 打开该 USJ 端口
    那么 设备被打开两次
    并且 线路从未处于 RTS 有效而 DTR 无效
    并且 打开后 DTR 和 RTS 都无效，且没有写入任何数据

  场景: 打开后释放线路失败时关闭设备并报告原因
    假如 一个 USJ 虚拟串口，设备打开后 DTR/RTS 为 1/1
    并且 释放 RTS 时设备返回 I/O 错误
    当 尝试打开该 USJ 端口
    那么 打开失败并说明无法释放 DTR/RTS
    并且 只打开过一次设备
    并且 设备句柄已关闭

  场景: 不支持线路控制的虚拟串口照常打开，复位请求不改动线路
    假如 一个不支持 DTR/RTS 的 USJ 虚拟串口
    当 打开该 USJ 端口
    并且 请求复位 USJ 目标
    那么 该端口已打开
    并且 复位报告为未执行

  场景: USJ 模式不按串口波特率推算线速
    假如 一个 USJ 端口 "/dev/ttyACM1"
    当 读取该 USJ 端口的速率配置
    那么 线速上限为空

  场景: 命令行用 usj 选择该模式，其他模式不变
    当 用 "usj" 选择传输模式
    那么 得到 USJ 模式
    并且 命令行帮助列出模式 "[uart|spi|usb|usj]"
    并且 用 "usb" 选择传输模式仍得到 USB Output 模式

  场景: 启动界面选择 USJ 后隐藏波特率并原样传出端口
    假如 系统上有这些串口设备
      | device       | vid_pid   | product               |
      | /dev/ttyACM1 | 303A:1001 | USB JTAG/serial debug |
    当 在启动界面选择 USJ 模式并连接
    那么 波特率选项被隐藏
    并且 连接配置为 USJ 模式、端口 "/dev/ttyACM1"
