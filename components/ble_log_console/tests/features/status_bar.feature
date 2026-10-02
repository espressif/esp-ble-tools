# language: zh-CN

# 观察边界：帧以真实字节进入 Console 的解析链路（parser → aggregator → presenter → App handler），
# 被替换的是 transport、worker 进程与队列轮询；不覆盖串口 / USB 侧的收包。
# chip 身份在 Console 侧的载体是 SNAPSHOT。独立 VERSION_INFO 帧（早期固件会发）由 _chip_label 兼容，
# 但其版本内容面向日志解析器，不作为 Console 的行为承诺，因此不写进场景。

功能: 状态栏显示设备 chip 身份

  背景:
    假如 一个已挂载并连接的 BLE Log Console

  场景大纲: SNAPSHOT 携带 chip 身份时状态栏显示它
    当 控制台从设备收到一帧 SNAPSHOT，其中 chip 为 "<chip>"、revision 为 "<revision>"
    那么 状态栏显示 "<label>"

    例子:
      | chip    | revision | label         |
      | ESP32C6 | v3.02    | ESP32C6 v3.02 |
      | ESP32S3 | v1.00    | ESP32S3 v1.00 |

  场景: 尚未收到 SNAPSHOT 时状态栏不显示 chip
    那么 状态栏不显示 chip

  场景: 无法解读的 SNAPSHOT 不会清掉已显示的 chip
    假如 控制台已从一帧 SNAPSHOT 显示 chip "ESP32C6"、revision "v3.02"
    当 控制台从设备收到一帧版本信息块无法解读的 SNAPSHOT
    那么 状态栏显示 "ESP32C6 v3.02"

  场景: 重新录制时不保留上一台的 chip
    假如 控制台已从一帧 SNAPSHOT 显示 chip "ESP32C6"、revision "v3.02"
    当 控制台开始新的录制
    那么 状态栏不显示 chip
