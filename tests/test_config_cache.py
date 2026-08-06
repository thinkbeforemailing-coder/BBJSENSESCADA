import config_cache


def use_temp_path(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_cache,
        "CONFIG_CACHE_PATH",
        tmp_path / "test_config_cache.json",
    )


def test_write_then_read_round_trip(monkeypatch, tmp_path):
    use_temp_path(monkeypatch, tmp_path)

    configuration = {
        "success": True,
        "device_count": 1,
        "devices": [{"id": 1, "device_name": "Test Meter"}],
    }

    config_cache.write_config_cache(configuration)

    assert config_cache.read_config_cache() == configuration


def test_read_missing_file_returns_none(monkeypatch, tmp_path):
    use_temp_path(monkeypatch, tmp_path)

    assert config_cache.read_config_cache() is None


def test_read_corrupt_file_returns_none(monkeypatch, tmp_path):
    use_temp_path(monkeypatch, tmp_path)

    config_cache.CONFIG_CACHE_PATH.write_text("{not valid json")

    assert config_cache.read_config_cache() is None
