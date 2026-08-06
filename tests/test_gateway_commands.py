from gateway_commands import find_writable_tag


SAMPLE_CONFIG = {
    "devices": [
        {
            "id": 1,
            "device_name": "Main Incomer Meter",
            "tags": [
                {"id": 10, "display_name": "Frequency", "writable": False},
                {"id": 11, "display_name": "Setpoint", "writable": True},
                {"id": 12, "display_name": "No Flag Set"},
            ],
        },
        {
            "id": 2,
            "device_name": "Second Device",
            "tags": [
                {"id": 20, "display_name": "Breaker", "writable": True},
            ],
        },
    ],
}


def test_find_writable_tag_returns_device_and_tag_when_writable():
    device, tag = find_writable_tag(SAMPLE_CONFIG, device_id=1, tag_id=11)

    assert device["id"] == 1
    assert tag["id"] == 11


def test_find_writable_tag_rejects_non_writable_tag():
    device, tag = find_writable_tag(SAMPLE_CONFIG, device_id=1, tag_id=10)

    assert (device, tag) == (None, None)


def test_find_writable_tag_rejects_tag_missing_writable_flag():
    # A tag with no "writable" key at all must NOT be treated as
    # writable by default -- absence of the flag is not consent.
    device, tag = find_writable_tag(SAMPLE_CONFIG, device_id=1, tag_id=12)

    assert (device, tag) == (None, None)


def test_find_writable_tag_rejects_unknown_device():
    device, tag = find_writable_tag(SAMPLE_CONFIG, device_id=999, tag_id=11)

    assert (device, tag) == (None, None)


def test_find_writable_tag_rejects_unknown_tag_on_known_device():
    device, tag = find_writable_tag(SAMPLE_CONFIG, device_id=1, tag_id=999)

    assert (device, tag) == (None, None)


def test_find_writable_tag_rejects_tag_id_that_belongs_to_a_different_device():
    # tag_id=20 exists, but only under device_id=2, not device_id=1 --
    # a command must not be able to cross-wire a valid tag_id from one
    # device onto a different device_id in the payload.
    device, tag = find_writable_tag(SAMPLE_CONFIG, device_id=1, tag_id=20)

    assert (device, tag) == (None, None)
