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


def normalize_protocol(
    value: str | None,
) -> str:
    """
    Convert protocol names into stable identifiers.

    Examples:
    Modbus RTU -> modbus_rtu
    Modbus-TCP -> modbus_tcp
    OPC UA     -> opc_ua
    """

    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def prepare_device_configuration(
    device: dict,
) -> dict:
    """
    Prepare one device configuration for the driver.

    Priority:
    1. protocol
    2. communication_type fallback

    Connection priority:
    1. connection
    2. connection_config
    3. legacy top-level fields
    """

    prepared_device = dict(device)

    protocol = normalize_protocol(
        device.get("protocol")
        or device.get("communication_type")
    )

    connection = (
        device.get("connection")
        or device.get("connection_config")
        or {}
    )

    if not isinstance(connection, dict):
        connection = {}

    connection = dict(connection)

    # Legacy fallback for older backend responses.
    legacy_fields = {
        "serial_port":
            device.get("serial_port"),

        "baudrate":
            device.get("baudrate"),

        "parity":
            device.get("parity"),

        "stop_bits":
            device.get("stop_bits"),

        "slave_id":
            device.get("slave_id"),

        "ip_address":
            device.get("ip_address"),

        "host":
            device.get("ip_address"),

        "port":
            device.get("port"),

        "tcp_port":
            device.get("port"),
    }

    for key, value in legacy_fields.items():
        if (
            key not in connection
            and value is not None
        ):
            connection[key] = value

    prepared_device["protocol"] = protocol
    prepared_device["connection"] = connection
    prepared_device["connection_config"] = connection

    if not isinstance(
        prepared_device.get("driver_options"),
        dict,
    ):
        prepared_device["driver_options"] = {}

    return prepared_device


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
        prepared_device = (
            prepare_device_configuration(
                device
            )
        )

        protocol = prepared_device.get(
            "protocol"
        )

        if not protocol:
            raise ValueError(
                "Device protocol is missing"
            )

        driver_class = get_driver_class(
            protocol
        )

        driver = driver_class(
            prepared_device
        )

        if not driver.connect():
            raise ConnectionError(
                "Unable to connect using "
                f"{protocol}"
            )

        try:
            current_time = time.monotonic()

            for tag in prepared_device.get(
                "tags",
                [],
            ):
                if not tag.get(
                    "enabled",
                    True,
                ):
                    continue

                device_id = int(
                    prepared_device["id"]
                )

                tag_id = int(
                    tag["id"]
                )

                poll_key = (
                    device_id,
                    tag_id,
                )

                poll_interval = float(
                    tag.get(
                        "poll_interval"
                    )
                    or 2.0
                )

                previous_poll = (
                    self.last_poll_times.get(
                        poll_key,
                        0.0,
                    )
                )

                if (
                    current_time
                    - previous_poll
                    < poll_interval
                ):
                    continue

                try:
                    result = driver.read_tag(
                        tag
                    )

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
                        prepared_device.get(
                            "device_name"
                        ),
                        protocol,
                        tag.get(
                            "display_name"
                        ),
                        result["value"],
                        tag.get("unit") or "",
                        result["quality"],
                        result.get("raw"),
                    )

                except Exception as error:
                    logger.error(
                        "Device=%s | Protocol=%s | "
                        "Tag=%s | Error=%s",
                        prepared_device.get(
                            "device_name"
                        ),
                        protocol,
                        tag.get(
                            "display_name"
                        ),
                        error,
                    )

                finally:
                    self.last_poll_times[
                        poll_key
                    ] = current_time

        finally:
            driver.disconnect()

    def poll_all(
        self,
        configuration: dict,
    ) -> None:
        devices = configuration.get(
            "devices",
            [],
        )

        if not isinstance(
            devices,
            list,
        ):
            raise ValueError(
                "Gateway configuration "
                "'devices' must be a list"
            )

        for device in devices:
            try:
                self.poll_device(
                    device
                )

            except Exception as error:
                logger.error(
                    "Device=%s | Protocol=%s | "
                    "Connection error=%s",
                    device.get(
                        "device_name"
                    ),
                    device.get("protocol")
                    or device.get(
                        "communication_type"
                    ),
                    error,
                )