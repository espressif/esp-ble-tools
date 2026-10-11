# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Small gettext-compatible catalog for customer-facing text."""

from __future__ import annotations

import gettext
import locale

ENGLISH = "en"
CHINESE = "zh_CN"

_ZH_CN = {
    "--- Undecoded data ---": "--- 未解码成功数据 ---",
    "--- End of undecoded data ---": "--- 未解码成功数据结束 ---",
    "PLAIN TEXT": "纯文本",
    "Stream content": "数据内容",
    "Identified as": "识别结果",
    "Evidence scope": "识别依据范围",
    "No data": "无数据",
    "Unrecognized data": "无法识别的数据",
    "Plain console text": "普通控制台文本",
    "Parsed bytes outside BLE Log frames": "已解析数据中不属于 BLE Log 帧的字节数",
    "Of which after BLE Log was identified": "其中识别出 BLE Log 之后的字节数",
    "Frames from known BLE Log sources": "来自已知 BLE Log 来源的帧数",
    "Firmware identity records": "固件身份记录数",
    "Received data looks like plain console text, not BLE Log frames; check that the firmware sends BLE Log to this port.": "收到的数据像是普通控制台文本，而不是 BLE Log 帧；请确认固件把 BLE Log 输出到这个端口。",
    "BLE Log was identified, but no regular log frames were decoded; check the firmware log configuration.": "已识别到 BLE Log，但没有解析到普通日志帧；请检查固件日志配置。",
    "Data outside BLE Log frames arrived after BLE Log was identified; those bytes are written to the raw file, and the console log holds at most their displayable text.": "识别出 BLE Log 之后仍收到不属于 BLE Log 帧的数据；这些字节都会写入原始数据文件，串口转发日志最多只包含其中可显示的文本。",
    "Data outside BLE Log frames arrived after BLE Log was identified; the raw recording could not be confirmed complete, so those bytes may not all be in the raw file, and the console log holds at most their displayable text.": "识别出 BLE Log 之后仍收到不属于 BLE Log 帧的数据；原始录制未能确认完整，这些字节可能未全部写入原始数据文件，串口转发日志最多只包含其中可显示的文本。",
    "The console log could not be saved completely; this error does not itself stop raw recording.": "串口转发日志未能完整保存；此错误本身不会停止原始录制。",
    "Console log error": "串口转发日志错误",
    "Console log could not be saved: {message}. The text is still shown here; this error does not itself stop raw recording.": "无法保存串口转发日志：{message}。文本仍在此处显示；此错误本身不会停止原始录制。",
    "BLE LOG": "BLE Log",
    "Received data looks like plain console text, not BLE Log frames. Recording continues; check that the firmware sends BLE Log to this port.": "收到的数据像是普通控制台文本，而不是 BLE Log 帧。录制仍在继续；请确认固件把 BLE Log 输出到这个端口。",
    "BLE Log frames identified; earlier text is shown as undecoded data.": "已识别到 BLE Log 帧；之前的文本作为未解码数据显示。",
    "BLE Log was identified on this port, but no regular log frames were decoded for 10s. Check the firmware log configuration.": "已在此端口识别到 BLE Log，但连续 10 秒未解析到普通日志帧，请检查固件日志配置。",
    "BLE Log Recording Report": "BLE Log 录制质量报告",
    "READY FOR ANALYSIS": "可用于分析",
    "SAVED WITH WARNINGS": "已保存，但存在警告",
    "CHECK CONFIGURATION": "检查配置",
    "RECORD AGAIN RECOMMENDED": "建议重新录制",
    "Verdict": "结论",
    "Reasons": "判断依据",
    "Recording": "录制信息",
    "Mode": "模式",
    "Port": "端口",
    "Firmware protocol": "固件协议",
    "one shared counter": "共用一套序号",
    "per-source counters": "按来源各自编号",
    "not identified": "未识别",
    "Baud rate": "波特率",
    "Started": "开始时间",
    "Ended": "结束时间",
    "Duration": "持续时间",
    "Raw bytes": "原始数据量",
    "Decoded frames": "解析帧数",
    "Regular frames": "普通日志帧数",
    "Average receive rate": "平均接收速率",
    "Peak receive rate": "峰值接收速率",
    "Parser coverage": "解析覆盖情况",
    "Complete": "完整覆盖",
    "Parsed raw bytes": "已解析原始字节数",
    "Dropped chunks/bytes": "预览丢弃的数据块/字节数",
    "Parser lag bytes": "解析器滞后字节数",
    "Trailing carried bytes": "结尾未完成数据字节数",
    "Experimental quality metrics": "实验性质量统计",
    "Firmware write failure rate": "固件写入失败率",
    "Sequence discontinuity rate": "传输序列不连续率",
    "Record-again threshold": "建议重录阈值",
    "Recording segments": "分段统计",
    "No FINAL_STAT segments were decoded.": "没有解析到 FINAL_STAT 分段。",
    "Not enough data": "数据不足",
    "Sequence continuity": "序列号连续性",
    "All frames": "全部帧",
    "All sources": "全部来源",
    "counter contract unproven": "序号契约未证明",
    "Counter contract unproven: continuity is accounted with one shared counter.": (
        "序号契约未证明：连续性按「共用一套序号」记账。"
    ),
    "Frames by source": "各来源观测帧数",
    "Source": "来源",
    "Observed": "观察帧数",
    "SN range": "SN 范围",
    "Missing": "缺失",
    "Segments": "分段数",
    "Status": "状态",
    "GAPS DETECTED": "发现不连续",
    "CONTINUOUS": "连续",
    "UNCERTAIN": "无法确认",
    "Late": "迟到帧",
    "Duplicates": "重复帧",
    "Wraps": "回绕次数",
    "Unable to verify": "无法确认",
    "No regular source frames were available for sequence verification.": "没有可用于校验序列号的普通日志帧。",
    "Firmware buffer loss observed during this recording": "本次录制期间观察到的固件缓冲区丢失",
    "None observed after baseline.": "建立基线后未观察到丢失。",
    "{source}: {frames} frame(s), {bytes}": "{source}：{frames} 帧，{bytes}",
    "complete": "完整",
    "partial start": "开头不完整",
    "partial end": "结尾不完整",
    "no data": "无数据",
    "uncertain": "无法确认",
    "{frames} missing": "缺失 {frames} 帧",
    "continuous": "连续",
    "firmware failed {frames} frame(s)": "固件写入失败 {frames} 帧",
    "firmware buffer loss (ENH_STAT) {frames} frame(s)": "固件缓冲丢帧（ENH_STAT）{frames} 帧",
    "no firmware counters": "无固件统计",
    "Segment {index} ({status}): received {frames} frame(s); {firmware}; SN {sequence}": "第 {index} 段（{status}）：接收 {frames} 帧；{firmware}；SN {sequence}",
    "Files": "文件",
    "Raw": "原始数据",
    "Console log": "串口转发日志",
    "Report": "质量报告",
    "NOT SAVED": "未保存",
    "Errors": "错误",
    "YES": "是",
    "NO": "否",
    "N/A": "不适用",
    "Reader": "读取器",
    "Writer": "写入器",
    "Parser": "解析器",
    "Aggregator": "统计器",
    "No raw recording data was saved.": "没有保存到原始录制数据。",
    "Raw recording could not be finalized safely.": "原始录制数据未能安全完成封存。",
    "No regular BLE Log frames were decoded; check mode, wiring, and firmware configuration.": "没有解析到普通 BLE Log 帧，请检查模式、接线和固件配置。",
    "Live parsing did not cover all saved raw data; sequence integrity is not fully verified.": "实时解析未覆盖全部原始数据，因此无法完整验证序列号连续性。",
    "The transport ended unexpectedly; the files saved before disconnection are retained.": "传输意外中断；断开前已经写入的文件仍然保留。",
    "The raw recording was saved, but live verification failed; retain the raw files for support.": "原始数据已经保存，但实时校验失败；请保留原始文件以便进一步分析。",
    "Raw data was finalized, BLE Log frames were decoded, and no continuity loss was observed.": "原始数据已完成封存，能够解析 BLE Log 帧，且未观察到序列号不连续。",
    "Observed sequence discontinuity: {count} missing frame number(s).": "观察到序列号不连续：缺少 {count} 个帧序号。",
    "Sequence continuity could not be verified within the bounded tracker.": "序列号变化超出有界跟踪器的可信范围，无法确认连续性。",
    "Firmware write failure rate exceeded the 5% record-again threshold.": "固件日志写入失败率超过 5% 建议重录阈值。",
    "Sequence discontinuity rate exceeded the 5% record-again threshold.": "序列号不连续率超过 5% 建议重录阈值。",
    "Observed firmware buffer loss during recording: {frames} frame(s), {bytes}.": "本次录制期间观察到固件缓冲区丢失：{frames} 帧，{bytes}。",
    "Regular BLE Log frames": "有效日志帧",
    "Recommendation": "建议",
    "This recording is ready to submit for analysis.": "本次录制可直接提交分析。",
    "The data can be submitted for analysis, but recording quality warnings were detected.": "数据可以提交分析，但录制质量存在警告。",
    "Check the connection and configuration, then record again.": "请检查连接和配置后重新录制。",
    "No valid BLE Log frames were recorded. Check the transport mode, port, baud rate, wiring, and firmware log configuration, then record again.": "没有录到有效 BLE Log 帧。请检查传输模式、端口、波特率、接线和固件日志配置后重新录制。",
    "No valid BLE Log frames were recorded. Check the transport mode, port, wiring, and firmware log configuration, then record again.": "没有录到有效 BLE Log 帧。请检查传输模式、端口、接线和固件日志配置后重新录制。",
    "Saved data (confirmed)": "已保存数据（已确认）",
    "Saved data (not confirmed)": "已保存数据（未确认）",
    "{size}, {count} file(s)": "{size}，共 {count} 个文件",
    "Quality checks": "质量检查",
    "Automated quality check": "自动质量检查",
    "all saved data": "覆盖全部已保存数据",
    "parsed portion only": "仅覆盖已解析部分",
    "Frames found in parsed portion": "已解析部分识别到的有效日志帧",
    "Full-recording sequence continuity": "整份录制的序列号连续性",
    "Firmware loss found in parsed portion": "已解析部分观察到的固件丢失",
    "Reliability": "可信范围",
    "Saved raw data": "已保存原始数据",
    "Confirmed": "已确认",
    "Not confirmed": "未确认",
    "Parser coverage summary": "解析覆盖",
    "Complete result": "完整",
    "Incomplete result": "不完整",
    "Possible sequence loss": "序列号疑似缺失",
    "Firmware-reported loss": "固件报告丢失",
    "Detailed report": "详细报告",
    "Raw data file": "原始数据文件",
    "frames": "帧",
    "Recording report could not be saved: {message}": "无法保存录制质量报告：{message}",
    "Failed to start recording: {message}": "无法开始录制：{message}",
    "Failed to list ports: {message}": "无法列出端口：{message}",
    "Please select a port": "请选择端口",
    "Please select a baud rate": "请选择波特率",
    "Unsupported transport mode: {mode}\nPlease select the right mode.": "不支持的传输模式：{mode}\n请选择正确的模式。",
    "Recording could not start in {path}: {message}. Choose another log directory or fix the storage error, then select Connect.": "无法在 {path} 开始录制：{message}。请选择其他日志目录或排除存储错误，然后点击 Connect。",
    "Reader error: {message}": "读取器错误：{message}",
    "Writer error: {message}": "写入器错误：{message}",
    "Parser error: {message}": "解析器错误：{message}",
    "Aggregator error: {message}": "统计器错误：{message}",
    "Reset failed: {message}": "复位失败：{message}",
    "No data received for 10s. Check transport mode, port, cable, and firmware logging.": "连续 10 秒未收到数据，请检查传输模式、端口、线缆和固件日志配置。",
    "No valid BLE Log frames were decoded for 10s. Check transport mode, wiring, and firmware log configuration.": "连续 10 秒未解析到有效 BLE Log 帧，请检查传输模式、接线和固件日志配置。",
    "Realtime parser fell behind; raw recording continues, live stats may be incomplete.": "实时解析器处理不及，原始数据仍在继续保存，但实时统计可能不完整。",
    "Realtime parser queue stayed full during shutdown; the raw recording is unaffected, final live stats may be incomplete.": "结束录制时实时解析队列仍然已满；原始录制不受影响，但最终实时统计可能不完整。",
    "Realtime parser skipped {chunks} chunks ({bytes}); live stats are incomplete. The quality report states whether the raw recording was finalized completely.": "实时解析跳过了 {chunks} 个数据块（{bytes}）；实时统计不完整。质量报告会说明原始录制是否完整封存。",
    "Backend stopped: {message}": "后端已停止：{message}",
    "Reset is not available because recording is not running": "当前没有正在进行的录制，无法复位设备",
    "USB Output cannot reset the target; use the reset button on the board": "USB Output 无法复位目标设备，请按开发板上的复位键",
    "Finalizing recording: saving data, then allowing up to 20 seconds for the quality check.": "正在结束录制：保存数据后，质量检查最多等待 20 秒。",
    "Live quality check did not finish within 20 seconds.": "实时质量检查未能在 20 秒内完成。",
}


class _CatalogTranslations(gettext.NullTranslations):
    def __init__(self, catalog: dict[str, str]) -> None:
        super().__init__()
        self._catalog = catalog

    def gettext(self, message: str) -> str:
        return self._catalog.get(message, message)


def _system_language() -> str:
    language = locale.getlocale()[0] or ""
    return CHINESE if language.lower().startswith("zh") else ENGLISH


_language = _system_language()
_translations = {
    ENGLISH: gettext.NullTranslations(),
    CHINESE: _CatalogTranslations(_ZH_CN),
}


def get_language() -> str:
    return _language


def set_language(language: str) -> None:
    global _language
    if language not in (ENGLISH, CHINESE):
        raise ValueError(f"Unsupported language: {language}")
    _language = language


def tr(msgid: str, *, language: str | None = None, **values: object) -> str:
    selected = language or _language
    translated = _translations[selected].gettext(msgid)
    return translated.format(**values) if values else translated
