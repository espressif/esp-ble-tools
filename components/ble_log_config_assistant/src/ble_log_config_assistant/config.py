# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class ConfigPlan:
    mode: str
    uart_port: int = 0
    baudrate: int = 3_000_000
    tx_gpio: int = 0
    mosi_gpio: int = -1
    sclk_gpio: int = -1
    cs_gpio: int = -1


@dataclass(frozen=True)
class PreparedChange:
    project: Path
    sdkconfig: Path
    preview: Path
    diff: str
    original: bytes | None
    mode: str
    add_tinyusb: bool
    manifest_before: bytes | None


TINYUSB = "espressif/esp_tinyusb^2.0.0"


class ConfigError(ValueError):
    def __init__(self, en: str, zh: str):
        super().__init__(en)
        self.zh = zh


MODE_SYMBOLS = {
    "usj": "BLE_LOG_PRPH_USB_SERIAL_JTAG",
    "otg": "BLE_LOG_PRPH_USB",
    "spi": "BLE_LOG_PRPH_SPI_MASTER_DMA",
    "uart": "BLE_LOG_PRPH_UART_DMA",
}
# A Kconfig choice switches off the previously selected member.
TRANSPORT_CHOICES = {*MODE_SYMBOLS.values(), "BLE_LOG_PRPH_DUMMY", "BLE_LOG_PRPH_TEST", "BLE_LOG_PRPH_SPI_MASTER_HD"}


def configured_mode(project: Path) -> str | None:
    try:
        lines = set((project / "sdkconfig").read_bytes().splitlines())
    except OSError:
        return None
    if b"CONFIG_BLE_LOG_ENABLED=y" not in lines:
        return None
    selected = [symbol for symbol in TRANSPORT_CHOICES if f"CONFIG_{symbol}=y".encode() in lines]
    return next((mode for mode, symbol in MODE_SYMBOLS.items() if selected == [symbol]), None)


def _edit_settings(original: bytes, settings: dict[str, object]) -> bytes:
    """Edit only requested symbols, retaining comments, unknown symbols and line endings."""
    updates = dict(settings)
    updates.update({name: False for name in TRANSPORT_CHOICES if name not in settings})
    if "ESP_CONSOLE_SECONDARY_NONE" in settings:
        updates["ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG"] = False
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    out = []
    present = set()
    for line in original.splitlines(keepends=True):
        match = re.fullmatch(rb"(?:CONFIG_(\w+)=(.*)|# CONFIG_(\w+) is not set)", line.rstrip(b"\r\n"))
        key = (match[1] or match[3]).decode() if match else None
        if key in updates:
            present.add(key)
            value = updates[key]
            name = b"CONFIG_" + key.encode()
            new = (
                b"# " + name + b" is not set"
                if value is False
                else name + b"=" + (b"y" if value is True else str(value).encode())
            )
            if line.rstrip(b"\r\n") != new:
                if out and out[-1].rstrip(b"\r\n") == b"# default:":
                    out.pop()
                line = new + line[len(line.rstrip(b"\r\n")) :]
        out.append(line)
    for key, value in settings.items():
        if key not in present:
            if out and not out[-1].endswith(b"\n"):
                out.append(newline)
            out.append(f"CONFIG_{key}={('y' if value is True else value)}".encode() + newline)
    return b"".join(out)


def _contents(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _restore(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(previous)


def build_settings(plan: ConfigPlan) -> dict[str, object]:
    if plan.mode == "usj":
        return {"BLE_LOG_ENABLED": True, "ESP_CONSOLE_SECONDARY_NONE": True, "BLE_LOG_PRPH_USB_SERIAL_JTAG": True}
    if plan.mode == "otg":
        return {"BLE_LOG_ENABLED": True, "BLE_LOG_PRPH_USB": True}
    if plan.mode == "uart":
        _require_non_negative("UART port", plan.uart_port)
        _require_positive("baud rate", plan.baudrate)
        _require_non_negative("TX GPIO", plan.tx_gpio)
        return {
            "BT_LOG_CRITICAL_ONLY": True,
            "BLE_LOG_ENABLED": True,
            "BLE_LOG_PRPH_UART_DMA": True,
            "BLE_LOG_PRPH_UART_DMA_PORT": plan.uart_port,
            "BLE_LOG_PRPH_UART_DMA_BAUD_RATE": plan.baudrate,
            "BLE_LOG_PRPH_UART_DMA_TX_IO_NUM": plan.tx_gpio,
        }
    if plan.mode == "spi":
        assigned = {}
        for signal, gpio in (("MOSI", plan.mosi_gpio), ("SCLK", plan.sclk_gpio), ("CS", plan.cs_gpio)):
            _require_non_negative(signal, gpio)
            if gpio in assigned:
                raise ConfigError(
                    f"{assigned[gpio]} and {signal} both use GPIO{gpio}. Choose a different pin for one of them.",
                    f"{assigned[gpio]} 和 {signal} 都使用了 GPIO{gpio}，请修改其中一个引脚。",
                )
            assigned[gpio] = signal
        return {
            "BLE_LOG_ENABLED": True,
            "BLE_LOG_PRPH_SPI_MASTER_DMA": True,
            "BLE_LOG_PRPH_SPI_MASTER_DMA_MOSI_IO_NUM": plan.mosi_gpio,
            "BLE_LOG_PRPH_SPI_MASTER_DMA_SCLK_IO_NUM": plan.sclk_gpio,
            "BLE_LOG_PRPH_SPI_MASTER_DMA_CS_IO_NUM": plan.cs_gpio,
        }
    raise ValueError(f"Unsupported transport mode: {plan.mode}")


def prepare_change(
    project: Path | str,
    plan: ConfigPlan,
    *,
    server_factory: Callable[[Path], object] | None = None,
) -> PreparedChange:
    project = Path(project).expanduser().resolve()
    if not (project / "CMakeLists.txt").is_file():
        raise ConfigError(f"No CMakeLists.txt in {project}", f"所选目录缺少 CMakeLists.txt：{project}")

    settings = build_settings(plan)
    fd, preview_name = tempfile.mkstemp(prefix=".sdkconfig.ble-log-", dir=project)
    os.close(fd)
    preview = Path(preview_name)
    sdkconfig = project / "sdkconfig"
    original = _contents(sdkconfig)
    manifest = _contents(project / "main" / "idf_component.yml")
    try:
        server = (server_factory or ConfServer)(project)
        effective = server.validate(settings)
        rejected = [name for name, value in settings.items() if effective.get(name) != value]
        if rejected:
            names = ", ".join(rejected)
            raise ConfigError(f"ESP-IDF rejected these settings: {names}", f"当前工程无法启用以下配置：{names}")
        add_tinyusb = plan.mode == "otg" and "TINYUSB_CDC_ENABLED" not in effective
        if plan.mode == "otg" and not add_tinyusb and not effective["TINYUSB_CDC_ENABLED"]:
            raise ConfigError("TinyUSB CDC is unavailable", "此工程无法启用 TinyUSB CDC。")
        if plan.mode == "otg":
            settings["TINYUSB_CDC_ENABLED"] = True
        preview.write_bytes(_edit_settings(original or b"", settings))
        before = original.decode("utf-8", errors="replace").splitlines(keepends=True) if original is not None else []
        after = preview.read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(before, after, fromfile="sdkconfig", tofile="sdkconfig", n=0))
        return PreparedChange(project, sdkconfig, preview, diff, original, plan.mode, add_tinyusb, manifest)
    except Exception:
        preview.unlink(missing_ok=True)
        raise


def apply_prepared(
    prepared: PreparedChange,
    *,
    runner: Callable[..., object] | None = None,
) -> Path | None:
    if not prepared.preview.is_file():
        raise ConfigError("Configuration preview has expired", "预览已失效，请返回后重新预览。")
    current = _contents(prepared.sdkconfig)
    if current != prepared.original:
        raise ConfigError(
            "sdkconfig changed after preview; review it again", "预览后 sdkconfig 已发生变化，请返回后重新预览。"
        )

    if not prepared.diff and not prepared.add_tinyusb:
        prepared.preview.unlink()
        return None
    run = runner or _run_idf
    manifest = prepared.project / "main" / "idf_component.yml"
    lock = prepared.project / "dependencies.lock"
    if prepared.add_tinyusb and _contents(manifest) != prepared.manifest_before:
        raise ConfigError("The dependency manifest changed after preview", "预览后组件清单已发生变化，请重新预览。")
    original_lock = _contents(lock) if prepared.add_tinyusb else None
    backup = None
    if current is not None:
        stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S-%f")
        backup = prepared.sdkconfig.with_name(f"sdkconfig.bak.{stamp}")
        shutil.copy2(prepared.sdkconfig, backup)
    try:
        if prepared.add_tinyusb:
            run(["idf.py", "add-dependency", TINYUSB], cwd=prepared.project, check=True)
        if current is not None:
            shutil.copymode(prepared.sdkconfig, prepared.preview)
        os.replace(prepared.preview, prepared.sdkconfig)
    except Exception as error:
        if prepared.add_tinyusb:
            _restore(manifest, prepared.manifest_before)
            _restore(lock, original_lock)
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise ConfigError(f"Could not add TinyUSB.\n{detail}", f"添加 TinyUSB 依赖失败。\n{detail}") from error
        raise
    return backup


def _idf_python() -> str:
    env_root = os.environ.get("IDF_PYTHON_ENV_PATH")
    if env_root:
        return str(Path(env_root) / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    python = shutil.which("python")
    if not python:
        raise ConfigError(
            "Open an ESP-IDF terminal before starting the assistant", "请从已加载工程环境的 ESP-IDF 终端启动助手。"
        )
    return python


def _idf_env() -> dict[str, str]:
    env = os.environ.copy()
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def _run_idf(command: list[str], *, cwd: Path, check: bool = True):
    args = [_idf_python(), str(Path(os.environ["IDF_PATH"]) / "tools/idf.py"), *command[1:]]
    # Build tools can leave background processes holding inherited pipe handles.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as output:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=_idf_env(),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode:
            output.seek(0)
            result.stdout = output.read()
            if check:
                result.check_returncode()
        return result


class ConfServer:
    def __init__(self, project: Path):
        self.project = project

    def validate(self, settings: dict[str, object]) -> dict[str, object]:
        if not os.environ.get("IDF_PATH"):
            raise ConfigError(
                "Open an ESP-IDF terminal before starting the assistant", "请从已加载工程环境的 ESP-IDF 终端启动助手。"
            )
        build = self.project / "build"
        config = self.project / "sdkconfig"
        with tempfile.TemporaryDirectory(prefix="ble-log-config-") as temporary:
            desc = build / "project_description.json"
            if desc.exists():
                meta = json.loads(desc.read_text(encoding="utf-8"))
                if Path(meta["config_file"]).resolve() != config:
                    raise ConfigError(
                        "Custom sdkconfig: " + meta["config_file"],
                        "此工程使用自定义 sdkconfig 路径：" + meta["config_file"],
                    )
                if Path(meta["idf_path"]).resolve() != Path(os.environ["IDF_PATH"]).resolve():
                    raise ConfigError(
                        "Open the ESP-IDF environment used to configure this project",
                        "请切换到此工程配置时使用的 ESP-IDF 环境。",
                    )
            if not desc.exists() or not (build / "config.env").exists() or not config.exists():
                raise ConfigError(
                    "Run idf.py reconfigure in the project, then retry.",
                    "请先在工程目录运行 idf.py reconfigure，再回来选择外设。",
                )
            trial = Path(temporary) / "sdkconfig"
            shutil.copyfile(config, trial)
            return self._validate(build, trial, settings)

    def _validate(self, build, config, settings):
        idf = Path(os.environ["IDF_PATH"])
        command = [
            _idf_python(),
            "-m",
            "kconfserver",
            "--env-file",
            str(build / "config.env"),
            "--kconfig",
            str(idf / "Kconfig"),
            "--sdkconfig-rename",
            str(idf / "sdkconfig.rename"),
            "--config",
            str(config),
        ]
        with (
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors,
            subprocess.Popen(
                command,
                cwd=build,
                env=_idf_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                text=True,
                encoding="utf-8",
            ) as process,
        ):
            try:
                assert process.stdout and process.stdin
                line = process.stdout.readline()
                if not line:
                    errors.seek(0)
                    raise RuntimeError(errors.read() or "ESP-IDF confserver could not start")
                initial = json.loads(line)
                current = initial["values"]
                if not current.get("BT_ENABLED"):
                    raise ConfigError(
                        "Bluetooth is disabled in this project", "此工程尚未启用蓝牙，请先确认用例需要蓝牙。"
                    )
                if "BLE_LOG_PRPH_USB_SERIAL_JTAG" in settings:
                    owners = (
                        "ESP_CONSOLE_USB_SERIAL_JTAG",
                        "ESP_TRACE_TRANSPORT_USB_SERIAL_JTAG",
                        "OPENTHREAD_RCP_USB_SERIAL_JTAG",
                    )
                    for owner in owners:
                        if current.get(owner):
                            raise ConfigError(
                                f"USJ is in use by CONFIG_{owner}",
                                f"CONFIG_{owner} 正在使用 USJ，请选择其他外设或先在工程中释放端口。",
                            )
                if "BLE_LOG_PRPH_USB" in settings and current.get("ESP_CONSOLE_USB_CDC"):
                    raise ConfigError(
                        "The primary console uses USB OTG", "主控制台正在使用 USB OTG，请选择其他外设或先释放端口。"
                    )
                if (
                    "BLE_LOG_PRPH_USB" in settings
                    and "TINYUSB_CDC_ENABLED" in current
                    and not current.get("TINYUSB_CDC_ENABLED")
                ):
                    # Some SDKs select CDC automatically, others expose it as a separate option.
                    settings = dict(settings, TINYUSB_CDC_ENABLED=True)
                request = {"version": initial["version"], "set": settings}
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                reply = json.loads(process.stdout.readline())
                if reply.get("error"):
                    detail = "\n".join(reply["error"])
                    raise ConfigError(
                        f"ESP-IDF rejected the configuration.\n{detail}",
                        f"当前芯片或工程不支持所选配置。ESP-IDF 返回：\n{detail}",
                    )
                current.update(reply["values"])
                return current
            finally:
                process.stdin.close()


def _require_non_negative(label: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{label} must be zero or greater")


def _require_positive(label: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{label} must be greater than zero")
