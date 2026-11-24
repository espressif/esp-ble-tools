# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import locale
import os
import sys
from pathlib import Path
from typing import ClassVar

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, ContentSwitcher, Input, Label, LoadingIndicator, Select, Static, TextArea
from textual_fspicker import SelectDirectory

from . import __version__
from .config import (
    ConfigError,
    ConfigPlan,
    PreparedChange,
    apply_prepared,
    build_settings,
    configured_mode,
    prepare_change,
)

TEXT = {
    "zh": {
        "title": "BLE Log 配置助手",
        "language_help": "请选择配置助手使用的语言。",
        "project": "选择 ESP-IDF 工程",
        "project_help": "选择包含 CMakeLists.txt 的工程根目录。",
        "browse": "浏览…",
        "transport": "选择传输方式",
        "transport_help": "选择目标板用于输出 BLE 日志的接口。",
        "configured_mode": "工程当前配置：{mode}",
        "usj": "USB Serial/JTAG (USJ)",
        "otg": "USB OTG",
        "spi": "SPI 桥接器（SPI Bridge）",
        "uart": "串口（UART）",
        "parameters": "配置参数",
        "uart_port": "UART 端口号",
        "baudrate": "波特率",
        "tx_gpio": "UART TX GPIO",
        "uart_port_help": "默认值 0。这里填写 DUT 内部的 UART 控制器编号，不是电脑上的 COM 口。如果 UART0 已被系统控制台或其他功能占用，请改成实际可用的 UART 编号。",
        "baudrate_help": "助手推荐值 3000000；当前 SDK 原始默认值通常为 921600。固件波特率必须与 BLE Log Console 选择的波特率完全一致；如果串口转换器或连线在 3 Mbps 下不稳定，请同时降低两端的波特率。",
        "tx_gpio_help": "默认值 0。填写 DUT 实际输出 BLE Log 的 TX GPIO，并将它连接到电脑串口的 RX；如果 GPIO0 未接出、被占用或与板卡接线不符，必须修改。",
        "spi_pin_help": "SPI 引脚没有跨芯片通用默认值，以下三项都必须按 DUT 原理图填写。Bridge 端固定使用 IO4、IO5、IO6，并且 DUT 与 Bridge 必须共地。",
        "mosi_gpio": "目标板 MOSI 引脚",
        "sclk_gpio": "目标板 SCLK 引脚",
        "cs_gpio": "目标板 CS 引脚",
        "review": "检查并应用",
        "mosi_gpio_help": "目标板 MOSI → Bridge IO4",
        "sclk_gpio_help": "目标板 SCLK → Bridge IO5",
        "cs_gpio_help": "目标板 CS → Bridge IO6",
        "scroll_hint": "内容超过窗口高度时，可用鼠标滚轮或 ↑/↓、PageUp/PageDown 滚动。",
        "review_help": "检查下面列出的改动，点击“应用配置”保存。",
        "no_changes": "当前 sdkconfig 已符合所选配置，无需修改。",
        "back": "上一步",
        "next": "下一步",
        "apply": "应用配置",
        "close": "关闭",
        "error": "配置失败",
        "summary_usj": "USJ 使用芯片内置 USB 口。应用后将关闭第二控制台，原先从该口输出的控制台日志会停止。",
        "summary_uart": "UART 会开启“仅关键日志”以降低串口流量。普通蓝牙日志可能减少。",
        "summary_spi": "按目标板接线填写 MOSI、SCLK 和 CS。",
        "select_dir": "选择目录",
        "cancel": "取消",
        "summary_otg": "USB OTG 通过 TinyUSB CDC 输出日志。",
        "add_tinyusb": '应用时将运行 idf.py add-dependency "espressif/esp_tinyusb^2.0.0"，更新 main/idf_component.yml。',
        "capture": "编译烧录后，打开 BLE Log Console，选择 {port} 开始录制。",
        "bad_number": "所选模式的参数必须是非负整数，波特率必须大于 0。",
        "success": "配置已保存。",
        "backup": "原配置备份：",
        "no_backup": "本次无需备份。",
        "pick_project": "选择 ESP-IDF 工程",
    },
    "en": {
        "title": "BLE Log Configuration Assistant",
        "language_help": "Choose the language used by the assistant.",
        "project": "Choose an ESP-IDF project",
        "project_help": "Choose the project root containing CMakeLists.txt.",
        "browse": "Browse…",
        "transport": "Choose transport",
        "transport_help": "Select the interface your board will use for BLE logs.",
        "configured_mode": "Currently configured in this project: {mode}",
        "usj": "USB Serial/JTAG (USJ)",
        "otg": "USB OTG",
        "spi": "SPI Bridge",
        "uart": "UART",
        "parameters": "Parameters",
        "uart_port": "UART port number",
        "baudrate": "Baud rate",
        "tx_gpio": "UART TX GPIO",
        "uart_port_help": "Default: 0. This is the UART controller number inside the DUT, not a PC COM port. If UART0 is already used by the system console or another feature, select the UART controller actually available on the DUT.",
        "baudrate_help": "Assistant recommendation: 3000000; the current SDK default is usually 921600. The firmware baud rate must exactly match BLE Log Console. If the adapter or wiring is unstable at 3 Mbps, lower the value on both sides.",
        "tx_gpio_help": "Default: 0. Enter the DUT GPIO that actually outputs BLE Log and connect it to the PC adapter RX. Change it if GPIO0 is unavailable, occupied, or does not match the board wiring.",
        "spi_pin_help": "SPI pins have no universal default across chips. Enter all three from the DUT schematic. The Bridge side is fixed to IO4, IO5, and IO6, and the DUT and Bridge must share ground.",
        "mosi_gpio": "DUT MOSI GPIO (connect to Bridge IO4)",
        "sclk_gpio": "DUT SCLK GPIO (connect to Bridge IO5)",
        "cs_gpio": "DUT CS GPIO (connect to Bridge IO6)",
        "review": "Review and apply",
        "mosi_gpio_help": "Enter the DUT SPI MOSI GPIO used for log output and connect it to Bridge IO4. Do not simply enter 4 unless DUT MOSI really is GPIO4.",
        "sclk_gpio_help": "Enter the DUT SPI clock GPIO and connect it to Bridge IO5. Do not simply enter 5 unless the DUT clock really is GPIO5.",
        "cs_gpio_help": "Enter the DUT SPI chip-select GPIO and connect it to Bridge IO6. Do not simply enter 6 unless DUT chip select really is GPIO6.",
        "scroll_hint": "If the content exceeds the window height, scroll with the mouse wheel or ↑/↓ and PageUp/PageDown.",
        "review_help": "Review the changes below, then select Apply configuration to save them.",
        "no_changes": "The current sdkconfig already matches these choices.",
        "back": "Back",
        "next": "Next",
        "apply": "Apply configuration",
        "close": "Close",
        "error": "Configuration failed",
        "summary_usj": "USJ uses the built-in USB port. Applying this mode disables the secondary console and its output on this port.",
        "summary_uart": "UART enables critical-only logging to reduce traffic. Fewer ordinary Bluetooth logs may appear.",
        "summary_spi": "Enter MOSI, SCLK and CS for the target board wiring.",
        "select_dir": "Select directory",
        "cancel": "Cancel",
        "summary_otg": "USB OTG · Enable BLE Log output over TinyUSB CDC.",
        "add_tinyusb": 'Apply will run idf.py add-dependency "espressif/esp_tinyusb^2.0.0" and update main/idf_component.yml.',
        "capture": "Build and flash, then open BLE Log Console and select {port} to record.",
        "bad_number": "Parameters for the selected mode must be non-negative integers, and baud rate must be positive.",
        "success": "Configuration saved.",
        "backup": "Original configuration backup:",
        "no_backup": "No backup was needed.",
        "pick_project": "Choose an ESP-IDF project",
    },
}

PAGE_IDS = ("language-page", "project-page", "transport-page", "parameters-page", "review-page")


def settings_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "ble-log-config-assistant" / "settings.json"


def load_language(path: Path | None = None) -> str:
    path = path or settings_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("language")
        if value in TEXT:
            return value
    except (OSError, ValueError, AttributeError):
        pass
    language = locale.getlocale()[0] or ""
    return "zh" if language.lower().startswith("zh") else "en"


def save_language(language: str, path: Path | None = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"language": language}), encoding="utf-8")
    except OSError:
        pass


class ConfigurationAssistant(App[None]):
    TITLE = "BLE Log Configuration Assistant"
    BINDINGS: ClassVar = [Binding("q", "quit", "Quit", show=False), Binding("ctrl+c", "quit", show=False)]
    CSS = """
    Screen { align: center middle; }
    #wizard { width: 90%; max-width: 100; height: 90%; padding: 1 2; border: round $accent; background: $surface; }
    #language-select { width: 18; align-horizontal: right; }
    #pages { height: 1fr; }
    .page { height: 100%; }
    .page-title { text-style: bold; text-align: center; margin-bottom: 1; }
    .page-help { margin-bottom: 2; }
    .field-label { margin-top: 1; }
    .field-help { color: $text-muted; margin-bottom: 1; }
    #uart-fields, #spi-fields { height: auto; }
    #scroll-hint { color: $text-muted; margin-top: 1; }
    .field-row { height: auto; }
    .field-row Input { width: 1fr; }
    #browse-btn { width: 16; margin-left: 1; }
    #review-diff { height: 1fr; border: round $primary; }
    #busy { height: 1; display: none; }
    #navigation { height: 3; align: right middle; }
    #navigation Button { margin-left: 1; }
    """

    def __init__(self, project: Path | str = ".", language_path: Path | None = None) -> None:
        super().__init__()
        self.project = Path(project).expanduser().resolve()
        self.language_path = language_path
        self.language = load_language(language_path)
        self.configured_mode: str | None = None
        self.page = 0
        self.prepared: PreparedChange | None = None
        self.applied = False

    def text(self, key: str) -> str:
        return TEXT[self.language][key]

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard"):
            yield Select(
                [("中文", "zh"), ("English", "en")], value=self.language, allow_blank=False, id="language-select"
            )
            with ContentSwitcher(initial=PAGE_IDS[0], id="pages"):
                with VerticalScroll(id=PAGE_IDS[0], classes="page"):
                    yield Label("BLE Log 配置助手 / Configuration Assistant", classes="page-title")
                    yield Static(self.text("language_help"), id="language-help", classes="page-help")
                with VerticalScroll(id=PAGE_IDS[1], classes="page"):
                    yield Label(self.text("project"), id="project-title", classes="page-title")
                    yield Static(self.text("project_help"), id="project-help", classes="page-help")
                    with Horizontal(classes="field-row"):
                        yield Input(str(self.project), id="project-input")
                        yield Button(self.text("browse"), id="browse-btn")
                with VerticalScroll(id=PAGE_IDS[2], classes="page"):
                    yield Label(self.text("transport"), id="transport-title", classes="page-title")
                    yield Static(self.text("transport_help"), id="transport-help", classes="page-help")
                    yield Select(self._transport_options(), value="usj", allow_blank=False, id="transport-select")
                    yield Static("", id="mode-hint", classes="field-help")
                with VerticalScroll(id=PAGE_IDS[3], classes="page"):
                    yield Label(self.text("parameters"), id="parameters-title", classes="page-title")
                    with Vertical(id="uart-fields"):
                        yield Label(self.text("uart_port"), id="uart-port-label", classes="field-label")
                        yield Input("0", type="integer", id="uart-port-input")
                        yield Static(self.text("uart_port_help"), id="uart-port-help", classes="field-help")
                        yield Label(self.text("baudrate"), id="baudrate-label", classes="field-label")
                        yield Input("3000000", type="integer", id="baudrate-input")
                        yield Static(self.text("baudrate_help"), id="baudrate-help", classes="field-help")
                        yield Label(self.text("tx_gpio"), id="tx-gpio-label", classes="field-label")
                        yield Input("0", type="integer", id="tx-gpio-input")
                        yield Static(self.text("tx_gpio_help"), id="tx-gpio-help", classes="field-help")
                    with Vertical(id="spi-fields"):
                        yield Static(self.text("spi_pin_help"), id="spi-pin-help", classes="field-help")
                        yield Label(self.text("mosi_gpio"), id="mosi-gpio-label", classes="field-label")
                        yield Input("", type="integer", id="mosi-gpio-input")
                        yield Static(self.text("mosi_gpio_help"), id="mosi-gpio-help", classes="field-help")
                        yield Label(self.text("sclk_gpio"), id="sclk-gpio-label", classes="field-label")
                        yield Input("", type="integer", id="sclk-gpio-input")
                        yield Static(self.text("sclk_gpio_help"), id="sclk-gpio-help", classes="field-help")
                        yield Label(self.text("cs_gpio"), id="cs-gpio-label", classes="field-label")
                        yield Input("", type="integer", id="cs-gpio-input")
                        yield Static(self.text("cs_gpio_help"), id="cs-gpio-help", classes="field-help")
                    yield Static(self.text("scroll_hint"), id="scroll-hint")
                with Vertical(id=PAGE_IDS[4], classes="page"):
                    yield Label(self.text("review"), id="review-title", classes="page-title")
                    yield Static(self.text("review_help"), id="review-help", classes="page-help")
                    yield TextArea(read_only=True, show_line_numbers=False, id="review-diff")
            yield LoadingIndicator(id="busy")
            with Horizontal(id="navigation"):
                yield Button(self.text("back"), id="back-btn")
                yield Button(self.text("next"), variant="primary", id="next-btn")
                yield Button(self.text("apply"), variant="success", id="apply-btn")
                yield Button(self.text("close"), id="close-btn")

    def on_mount(self) -> None:
        self._sync_language()
        self._sync_parameters()
        if (self.project / "CMakeLists.txt").is_file():
            self._show_page(2)
        else:
            self._sync_navigation()

    def _transport_options(self) -> list[tuple[str, str]]:
        return [(self.text(mode), mode) for mode in ("usj", "otg", "spi", "uart")]

    @on(Select.Changed, "#language-select")
    def language_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self.language = str(event.value)
        save_language(self.language, self.language_path)
        self._sync_language()

    @on(Select.Changed, "#transport-select")
    def transport_changed(self) -> None:
        self._sync_parameters()

    def _sync_language(self) -> None:
        self.title = self.text("title")
        labels = {
            "#language-help": "language_help",
            "#project-title": "project",
            "#project-help": "project_help",
            "#transport-title": "transport",
            "#parameters-title": "parameters",
            "#uart-port-label": "uart_port",
            "#baudrate-label": "baudrate",
            "#tx-gpio-label": "tx_gpio",
            "#uart-port-help": "uart_port_help",
            "#baudrate-help": "baudrate_help",
            "#tx-gpio-help": "tx_gpio_help",
            "#mosi-gpio-label": "mosi_gpio",
            "#sclk-gpio-label": "sclk_gpio",
            "#cs-gpio-label": "cs_gpio",
            "#spi-pin-help": "spi_pin_help",
            "#mosi-gpio-help": "mosi_gpio_help",
            "#sclk-gpio-help": "sclk_gpio_help",
            "#cs-gpio-help": "cs_gpio_help",
            "#scroll-hint": "scroll_hint",
            "#review-title": "review",
            "#review-help": "review_help",
        }
        for selector, key in labels.items():
            self.query_one(selector, Static).update(self.text(key))
        self.query_one("#browse-btn", Button).label = self.text("browse")
        transport = self.query_one("#transport-select", Select)
        value = transport.value
        transport.set_options(self._transport_options())
        transport.value = value
        self._sync_parameters()
        if self.page == 4 and self.prepared and not self.applied:
            self._review_ready(self.prepared)
        self._sync_navigation()

    def _sync_parameters(self) -> None:
        mode = self.query_one("#transport-select", Select).value
        help_text = self.text("transport_help")
        if self.configured_mode:
            help_text = self.text("configured_mode").format(mode=self.text(self.configured_mode))
        self.query_one("#transport-help", Static).update(help_text)
        self.query_one("#mode-hint", Static).update(self.text("summary_" + str(mode)))
        self.query_one("#uart-fields").display = mode == "uart"
        self.query_one("#spi-fields").display = mode == "spi"

    def _sync_navigation(self) -> None:
        self.query_one("#back-btn", Button).display = self.page > 0 and not self.applied
        self.query_one("#next-btn", Button).display = self.page < len(PAGE_IDS) - 1
        self.query_one("#apply-btn", Button).display = self.page == len(PAGE_IDS) - 1 and not self.applied
        self.query_one("#close-btn", Button).display = self.applied
        for selector, key in (
            ("#back-btn", "back"),
            ("#next-btn", "next"),
            ("#apply-btn", "apply"),
            ("#close-btn", "close"),
        ):
            self.query_one(selector, Button).label = self.text(key)

    def _show_page(self, page: int) -> None:
        if page == 2 and self.page < 2:
            project = Path(self.query_one("#project-input", Input).value).expanduser()
            self.configured_mode = configured_mode(project)
            self.query_one("#transport-select", Select).value = self.configured_mode or "usj"
            self._sync_parameters()
        self.page = page
        self.query_one(ContentSwitcher).current = PAGE_IDS[page]
        self._sync_navigation()

    def _plan(self) -> ConfigPlan:
        try:
            mode = str(self.query_one("#transport-select", Select).value)
            if mode == "uart":
                plan = ConfigPlan(
                    mode=mode,
                    uart_port=int(self.query_one("#uart-port-input", Input).value),
                    baudrate=int(self.query_one("#baudrate-input", Input).value),
                    tx_gpio=int(self.query_one("#tx-gpio-input", Input).value),
                )
            elif mode == "spi":
                plan = ConfigPlan(
                    mode=mode,
                    mosi_gpio=int(self.query_one("#mosi-gpio-input", Input).value),
                    sclk_gpio=int(self.query_one("#sclk-gpio-input", Input).value),
                    cs_gpio=int(self.query_one("#cs-gpio-input", Input).value),
                )
            else:
                plan = ConfigPlan(mode=mode)
            build_settings(plan)
            return plan
        except ConfigError as error:
            raise ValueError(error.zh if self.language == "zh" else str(error)) from error
        except ValueError as error:
            raise ValueError(self.text("bad_number")) from error

    @on(Button.Pressed, "#next-btn")
    def next_page(self) -> None:
        usb = self.query_one("#transport-select", Select).value in ("usj", "otg")
        if self.page == 3 or (self.page == 2 and usb):
            try:
                plan = self._plan()
            except ValueError as error:
                self.notify(str(error), severity="error")
                return
            self._set_busy(True)
            self.prepare_review(Path(self.query_one("#project-input", Input).value), plan)
            return
        self._show_page(self.page + 1)

    @work(thread=True, exclusive=True, group="prepare")
    def prepare_review(self, project: Path, plan: ConfigPlan) -> None:
        try:
            prepared = prepare_change(project, plan)
        except Exception as error:
            self.call_from_thread(self._operation_failed, error)
            return
        self.call_from_thread(self._review_ready, prepared)

    def _review_ready(self, prepared: PreparedChange) -> None:
        self.prepared = prepared
        summary = self.text("summary_" + prepared.mode) + "\n\n"
        if prepared.add_tinyusb:
            summary += self.text("add_tinyusb") + "\n\n"
        self.query_one("#review-diff", TextArea).load_text(summary + (prepared.diff or self.text("no_changes")))
        self._set_busy(False)
        self._show_page(4)

    def _operation_failed(self, error: Exception) -> None:
        message = error.zh if self.language == "zh" and isinstance(error, ConfigError) else str(error)
        self._set_busy(False)
        self.notify(message, title=self.text("error"), severity="error", timeout=10)

    @on(Button.Pressed, "#back-btn")
    def back_page(self) -> None:
        if self.page == 4 and self.prepared:
            self.prepared.preview.unlink(missing_ok=True)
            self.prepared = None
        usb_review = self.page == 4 and self.query_one("#transport-select", Select).value in ("usj", "otg")
        self._show_page(2 if usb_review else self.page - 1)

    @on(Button.Pressed, "#apply-btn")
    def apply_change(self) -> None:
        if self.prepared:
            self._set_busy(True)
            self.apply_review(self.prepared)

    @work(thread=True, exclusive=True, group="apply")
    def apply_review(self, prepared: PreparedChange) -> None:
        try:
            backup = apply_prepared(prepared)
        except Exception as error:
            self.call_from_thread(self._operation_failed, error)
            return
        self.call_from_thread(self._apply_done, backup)

    def _apply_done(self, backup: Path | None) -> None:
        detail = f"{self.text('backup')} {backup}" if backup else self.text("no_backup")
        ports = {
            "otg": "USB → USB OTG (303A:10B1)",
            "usj": "USB → USJ (303A:1001)",
            "spi": "SPI Bridge",
            "uart": "UART",
        }
        port = ports[str(self.query_one("#transport-select", Select).value)]
        follow_up = self.text("capture").format(port=port)
        self.query_one("#review-diff", TextArea).load_text(f"{self.text('success')}\n\n{follow_up}\n\n{detail}")
        self.applied = True
        self._set_busy(False)
        self._sync_navigation()

    def _set_busy(self, busy: bool) -> None:
        self.query_one("#busy", LoadingIndicator).display = busy
        self.query_one("#language-select").disabled = busy or self.applied
        for selector in ("#back-btn", "#next-btn", "#apply-btn"):
            self.query_one(selector, Button).disabled = busy

    @on(Button.Pressed, "#browse-btn")
    @work
    async def browse_directory(self) -> None:
        current = Path(self.query_one("#project-input", Input).value)
        start = current if current.is_dir() else Path.cwd()
        chosen = await self.push_screen_wait(
            SelectDirectory(
                location=start,
                title=self.text("pick_project"),
                select_button=self.text("select_dir"),
                cancel_button=self.text("cancel"),
            )
        )
        if chosen is not None:
            self.query_one("#project-input", Input).value = str(chosen)

    @on(Button.Pressed, "#close-btn")
    def close(self) -> None:
        self.exit()

    def action_quit(self) -> None:
        if self.prepared:
            self.prepared.preview.unlink(missing_ok=True)
        self.exit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BLE Log Configuration Assistant")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("project", nargs="?", default=".", help="ESP-IDF project directory")
    args = parser.parse_args(argv)
    ConfigurationAssistant(args.project).run()
    return 0
