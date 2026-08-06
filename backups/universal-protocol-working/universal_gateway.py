import logging
import time

from services.config_service import (
    ConfigService,
)
from services.polling_engine import (
    PollingEngine,
)
from services.telemetry_service import (
    TelemetryService,
)


API_BASE_URL = (
    "http://34.131.199.29:8000"
)

CONFIG_REFRESH_SECONDS = 60


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "bbj-sense-gateway"
)


def main() -> None:
    logger.info(
        "BBJ Sense Universal Gateway starting"
    )

    logger.info(
        "Cloud API: %s",
        API_BASE_URL,
    )

    config_service = ConfigService(
        api_base_url=API_BASE_URL,
    )

    telemetry_service = TelemetryService(
        api_base_url=API_BASE_URL,
    )

    polling_engine = PollingEngine(
        telemetry_service=telemetry_service,
    )

    configuration = {}
    last_config_download = 0.0

    while True:
        current_time = time.monotonic()

        try:
            if (
                not configuration
                or current_time
                - last_config_download
                >= CONFIG_REFRESH_SECONDS
            ):
                configuration = (
                    config_service
                    .download_configuration()
                )

                last_config_download = current_time

                logger.info(
                    "Configuration loaded: %s device(s)",
                    configuration.get(
                        "device_count",
                        0,
                    ),
                )

            polling_engine.poll_all(
                configuration
            )

        except Exception as error:
            logger.exception(
                "Gateway loop error: %s",
                error,
            )

        time.sleep(0.25)


if __name__ == "__main__":
    main()