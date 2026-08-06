import json
import logging
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEVICE_STATUS_PATH = BASE_DIR / "device_status.json"

logger = logging.getLogger("bbj-sense-device-status")


def write_device_status(status_by_device: dict[int, str]) -> None:
    """Atomically write the latest per-device connection status."""
    payload = {
        str(device_id): status
        for device_id, status in status_by_device.items()
    }

    temp_path = DEVICE_STATUS_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload))
    temp_path.replace(DEVICE_STATUS_PATH)


def read_device_counts() -> tuple[int, int]:
    """Return (connected_devices, failed_devices) from the latest snapshot."""
    if not DEVICE_STATUS_PATH.exists():
        return 0, 0

    try:
        payload = json.loads(DEVICE_STATUS_PATH.read_text())
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Unable to read device status: %s", error)
        return 0, 0

    connected = sum(
        1 for status in payload.values() if status == "connected"
    )

    failed = sum(
        1 for status in payload.values() if status == "failed"
    )

    return connected, failed
