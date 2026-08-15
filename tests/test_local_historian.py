from datetime import datetime, timedelta, timezone

import local_historian


def use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(
        local_historian,
        "DATABASE_PATH",
        tmp_path / "test_historian.db",
    )
    local_historian.initialize_database()


def test_record_and_get_recent_readings(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    local_historian.record_reading(
        device_id=1,
        tag_id=2,
        value=3.14,
        quality="good",
        source_timestamp="2026-08-15T10:00:00+00:00",
    )

    local_historian.record_reading(
        device_id=1,
        tag_id=2,
        value=3.20,
        quality="good",
        source_timestamp="2026-08-15T10:00:05+00:00",
    )

    readings = local_historian.get_recent_readings(
        device_id=1,
        tag_id=2,
        since_iso="2026-08-15T00:00:00+00:00",
    )

    assert len(readings) == 2
    assert readings[0]["value"] == 3.14
    assert readings[1]["value"] == 3.20


def test_get_recent_readings_filters_by_since(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    local_historian.record_reading(
        device_id=1,
        tag_id=2,
        value=1.0,
        quality="good",
        source_timestamp="2026-08-14T10:00:00+00:00",
    )

    local_historian.record_reading(
        device_id=1,
        tag_id=2,
        value=2.0,
        quality="good",
        source_timestamp="2026-08-15T10:00:00+00:00",
    )

    readings = local_historian.get_recent_readings(
        device_id=1,
        tag_id=2,
        since_iso="2026-08-15T00:00:00+00:00",
    )

    assert len(readings) == 1
    assert readings[0]["value"] == 2.0


def test_get_recent_readings_filters_by_device_and_tag(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    local_historian.record_reading(
        device_id=1,
        tag_id=2,
        value=1.0,
        quality="good",
        source_timestamp="2026-08-15T10:00:00+00:00",
    )

    local_historian.record_reading(
        device_id=1,
        tag_id=99,
        value=2.0,
        quality="good",
        source_timestamp="2026-08-15T10:00:00+00:00",
    )

    local_historian.record_reading(
        device_id=99,
        tag_id=2,
        value=3.0,
        quality="good",
        source_timestamp="2026-08-15T10:00:00+00:00",
    )

    readings = local_historian.get_recent_readings(
        device_id=1,
        tag_id=2,
        since_iso="2026-08-15T00:00:00+00:00",
    )

    assert len(readings) == 1
    assert readings[0]["value"] == 1.0


def test_prune_old_history_removes_only_old_rows(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)

    now = datetime.now(timezone.utc)
    old_cutoff = now - timedelta(
        days=local_historian.HISTORY_RETENTION_DAYS + 1
    )

    with local_historian.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO telemetry_history
                (device_id, tag_id, value, quality,
                 source_timestamp, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, 2, 1.0, "good", old_cutoff.isoformat(), old_cutoff.isoformat()),
        )
        connection.commit()

    local_historian.record_reading(
        device_id=1,
        tag_id=2,
        value=2.0,
        quality="good",
        source_timestamp=now.isoformat(),
    )

    deleted_count = local_historian.prune_old_history()

    assert deleted_count == 1

    with local_historian.get_connection() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) AS count FROM telemetry_history"
        ).fetchone()

    assert remaining["count"] == 1
