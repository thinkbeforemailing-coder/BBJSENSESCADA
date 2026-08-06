import requests

import drivers
from drivers.registry import get_driver_class


API_URL = (
    "http://34.131.199.29:8000"
    "/gateway/config"
)


configuration = requests.get(
    API_URL,
    timeout=10,
).json()

device = configuration["devices"][0]

driver_class = get_driver_class(
    device.get("communication_type")
)

driver = driver_class(device)

try:
    if not driver.connect():
        raise ConnectionError(
            "Unable to connect to device"
        )

    print(
        "Driver connected:",
        driver.health_status(),
    )

    for tag in device.get(
        "tags",
        [],
    ):
        result = driver.read_tag(tag)

        print(
            "Tag:",
            tag.get("display_name"),
            "| Value:",
            result["value"],
            tag.get("unit") or "",
            "| Quality:",
            result["quality"],
            "| Raw:",
            result["raw"],
        )

finally:
    driver.disconnect()