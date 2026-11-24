# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import asyncio
from pathlib import Path

from ble_log_config_assistant.app import ConfigurationAssistant
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, Select, Static


def test_language_is_the_first_tui_step(tmp_path: Path):
    async def check() -> None:
        language_path = tmp_path / "settings.json"
        language_path.write_text('{"language": "en"}', encoding="utf-8")
        app = ConfigurationAssistant(project=tmp_path, language_path=language_path)
        async with app.run_test() as pilot:
            assert app.query_one(ContentSwitcher).current == "language-page"
            app.query_one("#language-select", Select).value = "zh"
            await pilot.pause()
            assert str(app.query_one("#next-btn").label) == "下一步"
            assert language_path.read_text(encoding="utf-8") == '{"language": "zh"}'
            await pilot.click("#next-btn")
            assert app.query_one(ContentSwitcher).current == "project-page"
            assert app.query_one("#project-input").value == str(tmp_path)

    asyncio.run(check())


def test_peripheral_fields_explain_defaults_and_when_to_change_them(tmp_path: Path):
    async def check() -> None:
        language_path = tmp_path / "settings.json"
        language_path.write_text('{"language": "zh"}', encoding="utf-8")
        app = ConfigurationAssistant(project=tmp_path, language_path=language_path)
        async with app.run_test(size=(70, 20)):
            assert isinstance(app.query_one("#parameters-page"), VerticalScroll)
            assert "默认值 0" in str(app.query_one("#uart-port-help", Static).content)
            assert "必须与 BLE Log Console" in str(app.query_one("#baudrate-help", Static).content)
            assert "Bridge IO4" in str(app.query_one("#mosi-gpio-help", Static).content)
            assert "滚动" in str(app.query_one("#scroll-hint", Static).content)

    asyncio.run(check())


def test_project_starts_on_transport_and_usb_skips_parameters(tmp_path, monkeypatch):
    from ble_log_config_assistant.config import PreparedChange

    (tmp_path / "CMakeLists.txt").touch()
    preview = tmp_path / "preview"
    preview.touch()

    def prepare(project, plan):
        assert plan.mode == "otg"
        return PreparedChange(project, project / "sdkconfig", preview, "USB OTG diff", None, plan.mode, True, None)

    monkeypatch.setattr("ble_log_config_assistant.app.prepare_change", prepare)

    async def check():
        app = ConfigurationAssistant(tmp_path, tmp_path / "settings.json")
        async with app.run_test(size=(100, 35)) as pilot:
            initial = app.query_one(ContentSwitcher).current
            app.query_one("#transport-select", Select).value = "otg"
            await pilot.click("#next-btn")
            await pilot.pause()
            review = app.query_one(ContentSwitcher).current
            diff = app.query_one("#review-diff").text
            await pilot.click("#back-btn")
            previous = app.query_one(ContentSwitcher).current
        assert (initial, review, previous) == ("transport-page", "review-page", "transport-page")
        assert "add-dependency" in diff
        assert not preview.exists()

    asyncio.run(check())


def test_switch_language_from_project_and_explain_uart_and_usj(tmp_path):
    (tmp_path / "CMakeLists.txt").touch()
    language = tmp_path / "settings.json"
    language.write_text('{"language": "en"}')

    async def check():
        app = ConfigurationAssistant(tmp_path, language)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.click("#language-select")
            await pilot.press("home", "enter")
            await pilot.pause()
            assert "第二控制台" in str(app.query_one("#mode-hint", Static).content)
            app.query_one("#transport-select", Select).value = "uart"
            await pilot.pause()
            assert "仅关键日志" in str(app.query_one("#mode-hint", Static).content)
            assert app.query_one("#next-btn").label.plain == "下一步"

    asyncio.run(check())
