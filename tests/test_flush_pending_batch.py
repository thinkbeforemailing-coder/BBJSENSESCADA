import requests

import dynamic_modbus_poller
import offline_buffer


def use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(
        offline_buffer,
        "DATABASE_PATH",
        tmp_path / "test_buffer.db",
    )
    offline_buffer.initialize_database()


def test_flush_sends_one_batch_request(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    offline_buffer.enqueue_telemetry(
        device_id=1, tag_id=10, value=1.5, quality="good"
    )
    offline_buffer.enqueue_telemetry(
        device_id=1, tag_id=11, value=2.5, quality="good"
    )

    calls = []

    def fake_post_batch(items):
        calls.append(items)
        return {"success": True, "accepted": len(items), "rejected": []}

    monkeypatch.setattr(
        dynamic_modbus_poller, "post_telemetry_batch", fake_post_batch
    )

    dynamic_modbus_poller.flush_pending_batch()

    assert len(calls) == 1
    assert len(calls[0]) == 2
    assert offline_buffer.count_pending_messages() == 0


def test_flush_marks_rejected_items_failed_not_sent(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    offline_buffer.enqueue_telemetry(
        device_id=1, tag_id=10, value=1.5, quality="good"
    )
    offline_buffer.enqueue_telemetry(
        device_id=99, tag_id=999, value=2.5, quality="good"
    )

    def fake_post_batch(items):
        return {
            "success": True,
            "accepted": 1,
            "rejected": [
                {
                    "device_id": 99,
                    "tag_id": 999,
                    "reason": "Device or tag not found for this tenant",
                }
            ],
        }

    monkeypatch.setattr(
        dynamic_modbus_poller, "post_telemetry_batch", fake_post_batch
    )

    dynamic_modbus_poller.flush_pending_batch()

    # The accepted item is gone from the pending queue; the rejected
    # one stays pending (with an incremented attempt count) rather than
    # being silently dropped or wrongly marked sent.
    pending = offline_buffer.get_pending_messages()

    assert len(pending) == 1
    assert pending[0]["device_id"] == 99
    assert pending[0]["attempts"] == 1


def test_flush_leaves_messages_pending_on_network_failure(
    monkeypatch, tmp_path
):
    use_temp_db(monkeypatch, tmp_path)

    offline_buffer.enqueue_telemetry(
        device_id=1, tag_id=10, value=1.5, quality="good"
    )

    def fake_post_batch(items):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(
        dynamic_modbus_poller, "post_telemetry_batch", fake_post_batch
    )

    dynamic_modbus_poller.flush_pending_batch()

    pending = offline_buffer.get_pending_messages()

    assert len(pending) == 1
    assert pending[0]["attempts"] == 1
    assert "connection refused" in pending[0]["last_error"]


def test_flush_with_no_pending_messages_does_not_call_post(
    monkeypatch, tmp_path
):
    use_temp_db(monkeypatch, tmp_path)

    calls = []

    monkeypatch.setattr(
        dynamic_modbus_poller,
        "post_telemetry_batch",
        lambda items: calls.append(items),
    )

    dynamic_modbus_poller.flush_pending_batch()

    assert calls == []


def test_save_telemetry_enqueues_without_network_call(
    monkeypatch, tmp_path
):
    use_temp_db(monkeypatch, tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "save_telemetry should not attempt a network call"
        )

    monkeypatch.setattr(
        dynamic_modbus_poller, "post_telemetry_batch", fail_if_called
    )

    dynamic_modbus_poller.save_telemetry(
        device_id=1, tag_id=10, value=3.0, quality="good"
    )

    assert offline_buffer.count_pending_messages() == 1
