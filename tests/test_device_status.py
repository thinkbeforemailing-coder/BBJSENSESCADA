import device_status


def use_temp_path(monkeypatch, tmp_path):
    monkeypatch.setattr(
        device_status,
        "DEVICE_STATUS_PATH",
        tmp_path / "test_device_status.json",
    )


def test_write_then_read_counts(monkeypatch, tmp_path):
    use_temp_path(monkeypatch, tmp_path)

    device_status.write_device_status({1: "connected", 2: "failed", 3: "connected"})

    connected, failed = device_status.read_device_counts()

    assert connected == 2
    assert failed == 1


def test_read_counts_missing_file_returns_zero(monkeypatch, tmp_path):
    use_temp_path(monkeypatch, tmp_path)

    connected, failed = device_status.read_device_counts()

    assert (connected, failed) == (0, 0)


def test_read_counts_corrupt_file_returns_zero(monkeypatch, tmp_path):
    use_temp_path(monkeypatch, tmp_path)

    device_status.DEVICE_STATUS_PATH.write_text("not valid json{{{")

    connected, failed = device_status.read_device_counts()

    assert (connected, failed) == (0, 0)
