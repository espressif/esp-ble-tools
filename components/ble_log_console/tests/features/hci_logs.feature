# language: zh-CN
功能: HCI 和 LL_HCI 统一显示并保存

  场景大纲: 不同芯片使用同一 HCI 展示和文件格式
    假如 固件输出 <mode> 数据
    当 Console 完成 HCI 录制
    那么 实时显示 HCI 时间方向类型和内容且不区分来源
    并且 统一保存 HCI 文本和 BTSnoop 且原始 BIN 不变

    例子:
      | mode |
      | HCI |
      | LL_HCI |
      | C2_LL_HCI |
