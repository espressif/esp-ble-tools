# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from threading import Event
from types import SimpleNamespace

from pytest_bdd import given, parsers, scenarios, then, when
from src.backend.io import WriterConfig
from src.backend.models import LogLine
from src.backend.pipeline import controller
from src.frontend.capture_events import CaptureEventPresenter

from tests.helpers import BytesReader, snapshot_payload, version_info_payload
from tests.test_hci_logs import hci_stream
from tests.test_host_logs import frame

scenarios("features/hci_logs.feature")


@given(parsers.parse("固件输出 {mode} 数据"), target_fixture="world")
def world(mode, tmp_path):
    c2 = mode == "C2_LL_HCI"
    initial = version_info_payload(0, version=6, chip_model=12) if c2 else snapshot_payload()
    return SimpleNamespace(
        mode=mode,
        raw=frame(0, 0, initial) + hci_stream(6 if mode == "HCI" else 3, c2=c2),
        output=tmp_path / "recording.bin",
    )


@when("Console 完成 HCI 录制")
def record(world, monkeypatch):
    events = []
    original = controller._result_from_events

    def collect(items):
        events.extend(items)
        return original(items)

    monkeypatch.setattr(controller, "_result_from_events", collect)
    stop = Event()
    world.result = controller.run_capture_pipeline_inprocess(
        BytesReader(world.raw, stop), WriterConfig(world.output), stop_requested=stop
    )
    presenter = CaptureEventPresenter(world.output)
    world.messages = presenter.handle_events(events) + presenter.finish()
    world.state = presenter.state


@then("实时显示 HCI 时间方向类型和内容且不区分来源")
def display(world):
    text = "\n".join(m.text for m in world.messages if isinstance(m, LogLine))
    assert "1000000 us TX HCI type=1 03 0c 00" in text
    assert "LL_HCI" not in text


@then("统一保存 HCI 文本和 BTSnoop 且原始 BIN 不变")
def files(world):
    assert world.result.completed and world.output.read_bytes() == world.raw
    (text,) = world.state.hci_paths
    assert world.result.products.error is None
    (binary,) = world.result.products.paths
    assert text.name == "recording_hci.log" and "TX HCI type=1 03 0c 00" in text.read_text()
    assert binary.name == (
        "recording_hci_btsnoop.log" if world.mode == "HCI" else "recording_ll_hci_btsnoop.log"
    ) and binary.read_bytes().endswith(b"\x01\x03\x0c\x00")
    assert not world.state.hci_error
