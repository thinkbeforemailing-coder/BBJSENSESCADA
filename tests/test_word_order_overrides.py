import pytest

import dynamic_modbus_poller
from dynamic_modbus_poller import resolve_word_order
from settings import parse_word_order_overrides


@pytest.fixture(autouse=True)
def reset_warned():
    dynamic_modbus_poller._WORD_ORDER_OVERRIDE_WARNED.clear()
    yield
    dynamic_modbus_poller._WORD_ORDER_OVERRIDE_WARNED.clear()


def test_parse_overrides():
    assert parse_word_order_overrides("23:swapped, 24:CDAB") == {
        23: "swapped",
        24: "CDAB",
    }


@pytest.mark.parametrize("raw", ["", None, "abc", "23", "23:", "x:swapped"])
def test_parse_overrides_skips_malformed(raw):
    assert parse_word_order_overrides(raw) == {}


def test_override_applies_only_to_named_tags(monkeypatch):
    monkeypatch.setattr(
        dynamic_modbus_poller, "WORD_ORDER_OVERRIDES", {23: "swapped"}
    )

    assert resolve_word_order({"id": 23, "word_order": "normal"}) == "swapped"
    assert resolve_word_order({"id": 99, "word_order": "normal"}) == "normal"


def test_override_warns_once_per_tag(monkeypatch, caplog):
    monkeypatch.setattr(
        dynamic_modbus_poller, "WORD_ORDER_OVERRIDES", {23: "swapped"}
    )
    caplog.set_level("WARNING")
    dynamic_modbus_poller.logger.addHandler(caplog.handler)

    try:
        for _ in range(3):
            resolve_word_order({"id": 23, "word_order": "normal"})
    finally:
        dynamic_modbus_poller.logger.removeHandler(caplog.handler)

    warnings = [
        r for r in caplog.records
        if "BBJ_WORD_ORDER_OVERRIDES" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "can be removed" not in warnings[0].getMessage()


def test_override_notes_when_cloud_agrees(monkeypatch, caplog):
    monkeypatch.setattr(
        dynamic_modbus_poller, "WORD_ORDER_OVERRIDES", {23: "swapped"}
    )
    caplog.set_level("WARNING")
    dynamic_modbus_poller.logger.addHandler(caplog.handler)

    try:
        resolve_word_order({"id": 23, "word_order": "Swap / Little Word"})
    finally:
        dynamic_modbus_poller.logger.removeHandler(caplog.handler)

    assert any("can be removed" in r.getMessage() for r in caplog.records)
