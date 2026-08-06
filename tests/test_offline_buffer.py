import offline_buffer


def use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(
        offline_buffer,
        "DATABASE_PATH",
        tmp_path / "test_buffer.db",
    )
    offline_buffer.initialize_database()


def test_enqueue_and_get_pending(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    message_id = offline_buffer.enqueue_telemetry(
        device_id=1,
        tag_id=2,
        value=3.14,
        quality="good",
    )

    pending = offline_buffer.get_pending_messages()

    assert len(pending) == 1
    assert pending[0]["message_id"] == message_id
    assert pending[0]["payload"]["device_id"] == 1
    assert pending[0]["payload"]["tag_id"] == 2
    assert pending[0]["payload"]["value"] == 3.14


def test_mark_message_sent_removes_from_pending(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    message_id = offline_buffer.enqueue_telemetry(
        device_id=1,
        tag_id=2,
        value=1.0,
        quality="good",
    )

    offline_buffer.mark_message_sent(message_id)

    assert offline_buffer.get_pending_messages() == []
    assert offline_buffer.count_pending_messages() == 0
    assert offline_buffer.count_all_messages() == 1


def test_mark_message_failed_increments_attempts(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    message_id = offline_buffer.enqueue_telemetry(
        device_id=1,
        tag_id=2,
        value=1.0,
        quality="good",
    )

    offline_buffer.mark_message_failed(message_id, "connection refused")

    pending = offline_buffer.get_pending_messages()

    assert len(pending) == 1
    assert pending[0]["attempts"] == 1
    assert pending[0]["last_error"] == "connection refused"


def test_count_pending_messages(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    for i in range(3):
        offline_buffer.enqueue_telemetry(
            device_id=1,
            tag_id=i,
            value=float(i),
            quality="good",
        )

    assert offline_buffer.count_pending_messages() == 3


def test_delete_sent_messages_keeps_latest(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    message_ids = [
        offline_buffer.enqueue_telemetry(
            device_id=1,
            tag_id=i,
            value=float(i),
            quality="good",
        )
        for i in range(5)
    ]

    for message_id in message_ids:
        offline_buffer.mark_message_sent(message_id)

    deleted = offline_buffer.delete_sent_messages(keep_latest=2)

    assert deleted == 3
    assert offline_buffer.count_all_messages() == 2
