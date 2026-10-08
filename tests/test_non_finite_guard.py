import pytest

import dynamic_modbus_poller
from dynamic_modbus_poller import process_tag

DEVICE = {"id": 9, "device_name": "METER", "connection": {"slave_id": 1}}
TAG = {
    "id": 23,
    "display_name": "POWER",
    "data_type": "float32",
    "byte_order": "big",
    "word_order": "normal",
}


@pytest.fixture
def saved(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dynamic_modbus_poller,
        "save_telemetry",
        lambda **kwargs: calls.append(kwargs),
    )
    return calls


def use_registers(monkeypatch, registers):
    monkeypatch.setattr(
        dynamic_modbus_poller,
        "read_modbus_registers",
        lambda **_kwargs: registers,
    )


@pytest.mark.parametrize(
    "registers",
    [
        [0x7FC0, 0xC4D3],  # NaN
        [0x7F80, 0x0000],  # +inf
        [0xFF80, 0x0000],  # -inf
    ],
)
def test_non_finite_value_is_skipped(monkeypatch, saved, registers):
    use_registers(monkeypatch, registers)

    process_tag(client=None, device=DEVICE, tag=TAG)

    assert saved == []


def test_finite_value_is_saved(monkeypatch, saved):
    use_registers(monkeypatch, [0x4248, 0x0000])  # 50.0

    process_tag(client=None, device=DEVICE, tag=TAG)

    assert len(saved) == 1
    assert saved[0]["value"] == 50.0
