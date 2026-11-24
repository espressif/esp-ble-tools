# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest
from ble_log_config_assistant.app import load_language, save_language
from ble_log_config_assistant.config import ConfigPlan, apply_prepared, build_settings, prepare_change


class FakeConfServer:
    def __init__(self, project: Path, accepted: dict[str, object] | None = None):
        self.project = project
        self.accepted = accepted

    def validate(self, settings):
        return settings if self.accepted is None else self.accepted


def test_profiles_only_change_required_ble_log_settings():
    uart = build_settings(ConfigPlan(mode="uart", uart_port=1, baudrate=3_000_000, tx_gpio=7))
    assert uart == {
        "BT_LOG_CRITICAL_ONLY": True,
        "BLE_LOG_ENABLED": True,
        "BLE_LOG_PRPH_UART_DMA": True,
        "BLE_LOG_PRPH_UART_DMA_PORT": 1,
        "BLE_LOG_PRPH_UART_DMA_BAUD_RATE": 3_000_000,
        "BLE_LOG_PRPH_UART_DMA_TX_IO_NUM": 7,
    }

    spi = build_settings(ConfigPlan(mode="spi", mosi_gpio=4, sclk_gpio=5, cs_gpio=6))
    assert spi == {
        "BLE_LOG_ENABLED": True,
        "BLE_LOG_PRPH_SPI_MASTER_DMA": True,
        "BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM": 4,
        "BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM": 5,
        "BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM": 6,
    }


@pytest.mark.parametrize(
    ("pins", "signals"),
    [((25, 25, 27), "MOSI and SCLK"), ((25, 26, 25), "MOSI and CS"), ((26, 25, 25), "SCLK and CS")],
)
def test_duplicate_spi_pins_are_rejected(pins, signals):
    with pytest.raises(ValueError, match=f"{signals} both use GPIO25"):
        build_settings(ConfigPlan("spi", mosi_gpio=pins[0], sclk_gpio=pins[1], cs_gpio=pins[2]))


def test_apply_writes_only_reviewed_settings_and_preserves_case(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(test)\n", encoding="utf-8")
    sdkconfig = tmp_path / "sdkconfig"
    sdkconfig.write_text("CONFIG_KEEP_ME=y\n", encoding="utf-8")
    prepared = prepare_change(
        tmp_path,
        ConfigPlan(mode="uart", uart_port=0, baudrate=3_000_000, tx_gpio=0),
        server_factory=FakeConfServer,
    )

    assert sdkconfig.read_text(encoding="utf-8") == "CONFIG_KEEP_ME=y\n"
    assert "CONFIG_KEEP_ME" not in prepared.diff
    commands: list[list[str]] = []
    backup = apply_prepared(prepared, runner=lambda command, **_: commands.append(command))

    assert backup is not None and backup.read_text(encoding="utf-8") == "CONFIG_KEEP_ME=y\n"
    assert "CONFIG_BLE_LOG_PRPH_UART_DMA=y" in sdkconfig.read_text(encoding="utf-8")
    assert sdkconfig.read_bytes().startswith(backup.read_bytes())
    assert commands == []


def test_rejected_kconfig_value_does_not_touch_sdkconfig(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(test)\n", encoding="utf-8")
    sdkconfig = tmp_path / "sdkconfig"
    sdkconfig.write_text("CONFIG_KEEP_ME=y\n", encoding="utf-8")

    with pytest.raises(ValueError, match="BLE_LOG_ENABLED"):
        prepare_change(
            tmp_path,
            ConfigPlan(mode="spi", mosi_gpio=4, sclk_gpio=5, cs_gpio=6),
            server_factory=lambda project: FakeConfServer(project, accepted={}),
        )

    assert sdkconfig.read_text(encoding="utf-8") == "CONFIG_KEEP_ME=y\n"


def test_usj_switch_preserves_case_bytes_and_repeat_is_a_noop(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").touch()
    sdkconfig = tmp_path / "sdkconfig"
    case = b'# case-specific setting\r\nCONFIG_CASE="A B"\r\n# default:\r\nCONFIG_BT_LOG_CRITICAL_ONLY=y\r\n'
    original = case + b"CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA=y\r\nCONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG=y\r\n"
    sdkconfig.write_bytes(original)
    plan = ConfigPlan(mode="usj")
    backup = apply_prepared(prepare_change(tmp_path, plan, server_factory=FakeConfServer))
    changed = sdkconfig.read_bytes()
    assert backup.read_bytes() == original
    assert changed.startswith(case)
    assert b"# CONFIG_BLE_LOG_PRPH_SPI_MASTER_DMA is not set\r\n" in changed
    assert b"# CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG is not set\r\n" in changed
    assert b"CONFIG_ESP_CONSOLE_SECONDARY_NONE=y\r\n" in changed
    assert b"CONFIG_BT_ENABLED" not in changed
    assert apply_prepared(prepare_change(tmp_path, plan, server_factory=FakeConfServer)) is None
    assert list(tmp_path.glob("sdkconfig.bak.*")) == [backup]


def test_apply_refuses_to_overwrite_a_change_made_after_preview(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(test)\n", encoding="utf-8")
    sdkconfig = tmp_path / "sdkconfig"
    sdkconfig.write_text("CONFIG_ORIGINAL=y\n", encoding="utf-8")
    prepared = prepare_change(
        tmp_path,
        ConfigPlan(mode="spi", mosi_gpio=4, sclk_gpio=5, cs_gpio=6),
        server_factory=FakeConfServer,
    )
    sdkconfig.write_text("CONFIG_CHANGED_BY_SOMEONE_ELSE=y\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after preview"):
        apply_prepared(prepared)

    assert sdkconfig.read_text(encoding="utf-8") == "CONFIG_CHANGED_BY_SOMEONE_ELSE=y\n"


def test_language_choice_is_remembered(tmp_path: Path):
    path = tmp_path / "settings.json"
    save_language("zh", path)
    assert load_language(path) == "zh"


def test_usb_previews_and_rolls_back_manifest_on_apply_failure(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("project(test)")
    main = tmp_path / "main"
    main.mkdir()
    manifest = main / "idf_component.yml"
    manifest.write_text("dependencies: {}\n")
    (tmp_path / "sdkconfig").write_text("CONFIG_BT_ENABLED=y\n")
    prepared = prepare_change(tmp_path, ConfigPlan("otg"), server_factory=FakeConfServer)
    assert prepared.add_tinyusb
    assert manifest.read_text() == "dependencies: {}\n"

    def fail(command, **_):
        if command[1] == "add-dependency":
            manifest.write_text("changed")
        (tmp_path / "dependencies.lock").write_text("changed")
        raise RuntimeError("Could not fetch component")

    with pytest.raises(RuntimeError, match="Could not fetch component"):
        apply_prepared(prepared, runner=fail)
    assert not (tmp_path / "dependencies.lock").exists()
    assert manifest.read_text() == "dependencies: {}\n"
    assert (tmp_path / "sdkconfig").read_text() == "CONFIG_BT_ENABLED=y\n"


def test_existing_tinyusb_is_reused(tmp_path):
    (tmp_path / "CMakeLists.txt").touch()
    plan = ConfigPlan("otg")
    effective = dict(build_settings(plan), TINYUSB_CDC_ENABLED=True)
    prepared = prepare_change(tmp_path, plan, server_factory=lambda p: FakeConfServer(p, effective))
    assert not prepared.add_tinyusb
    assert build_settings(ConfigPlan("usj"))["ESP_CONSOLE_SECONDARY_NONE"]
