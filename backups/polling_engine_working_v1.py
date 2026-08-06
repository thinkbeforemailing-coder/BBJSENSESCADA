import logging
import time

import drivers
from drivers.registry import get_driver_class
from services.telemetry_service import (
    TelemetryService,
)


logger = logging.getLogger(
    "bbj-sense-gateway"
)


class PollingEngine:
    def __init__(
        self,
        telemetry_service: TelemetryService,
    ) -> None:
        self.telemetry_service = telemetry_service
        self.last_poll_times: dict[
            tuple[int, int],
            float,
        ] = {}

    def poll_device(
        self,
        device: dict,
    ) -> None:
        driver_class = get_driver_class(
            device.get("communication_type")
        )

        driver = driver_class(device)

        if not driver.connect():
            raise ConnectionError(
                "Unable to connect using "
                f"{device.get('communication_type')}"
            )

        try:
            current_time = time.monotonic()

            for tag in device.get("tags", []):
                if not tag.get("enabled", True):
                    continue

                device_id = int(device["id"])
                tag_id = int(tag["id"])

                poll_key = (
                    device_id,
                    tag_id,
                )

                poll_interval = float(
                    tag.get("poll_interval") or 2.0
                )

                previous_poll = (
                    self.last_poll_times.get(
                        poll_key,
                        0.0,
                    )
                )

                if (
                    current_time - previous_poll
                    < poll_interval
                ):
                    continue

                try:
                    result = driver.read_tag(tag)

                    self.telemetry_service.save(
                        device_id=device_id,
                        tag_id=tag_id,
                        value=result["value"],
                        quality=result["quality"],
                    )

                    logger.info(
                        "Device=%s | Protocol=%s | "
                        "Tag=%s | Value=%s %s | "
                        "Quality=%s | Raw=%s",
                        device.get("device_name"),
                        device.get(
                            "communication_type"
                        ),
                        tag.get("display_name"),
                        result["value"],
                        tag.get("unit") or "",
                        result["quality"],
                        result.get("raw"),
                    )

                except Exception as error:
                    logger.error(
                        "Device=%s | Tag=%s | Error=%s",
                        device.get("device_name"),
                        tag.get("display_name"),
                        error,
                    )

                finally:
                    self.last_poll_times[poll_key] = (
                        current_time
                    )

        finally:
            driver.disconnect()

    def poll_all(
        self,
        configuration: dict,
    ) -> None:
        for device in configuration.get(
            "devices",
            [],
        ):
            try:
                self.poll_device(device)

            except Exception as error:
                logger.error(
                    "Device=%s | Connection error=%s",
                    device.get("device_name"),
                    error,
                )