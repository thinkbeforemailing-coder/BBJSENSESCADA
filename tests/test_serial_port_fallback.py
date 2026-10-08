import pytest

import dynamic_modbus_poller
from dynamic_modbus_poller import resolve_serial_port


@pytest.fixture(autouse=True)
def reset_warned():
    dynamic_modbus_poller._DEFAULT_PORT_WARNED.clear()
    yield
    dynamic_modbus_poller._DEFAULT_PORT_WARNED.clear()


def test_configured_port_wins_over_default(monkeypatch):
    monkeypatch.setattr(dynamic_modbus_poller, "DEFAULT_SERIAL_PORT", "COM6")

    assert resolve_serial_port({"serial_port": "COM3"}, "METER") == "COM3"


def test_empty_port_uses_default(monkeypatch):
    monkeypatch.setattr(dynamic_modbus_poller, "DEFAULT_SERIAL_PORT", "COM6")

    assert resolve_serial_port({"serial_port": ""}, "METER") == "COM6"
    assert resolve_serial_port({}, "METER") == "COM6"


def test_empty_port_without_default_raises(monkeypatch):
    monkeypatch.setattr(dynamic_modbus_poller, "DEFAULT_SERIAL_PORT", "")

    with pytest.raises(ValueError, match="Serial port is not configured"):
        resolve_serial_port({"serial_port": ""}, "METER")


def test_fallback_warns_once_per_device(monkeypatch, caplog):
    monkeypatch.setattr(dynamic_modbus_poller, "DEFAULT_SERIAL_PORT", "COM6")
    caplog.set_level("WARNING")
    dynamic_modbus_poller.logger.addHandler(caplog.handler)

    try:
        for _ in range(3):
            resolve_serial_port({"serial_port": ""}, "METER")
    finally:
        dynamic_modbus_poller.logger.removeHandler(caplog.handler)

    warnings = [
        r for r in caplog.records if "BBJ_DEFAULT_SERIAL_PORT" in r.getMessage()
    ]
    assert len(warnings) == 1
