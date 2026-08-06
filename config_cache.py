import json
from pathlib import Path

from logging_config import setup_logger


BASE_DIR = Path(__file__).resolve().parent
CONFIG_CACHE_PATH = BASE_DIR / "config_cache.json"

logger = setup_logger(
    logger_name="bbj-sense-config-cache",
    log_filename="telemetry_poller.log",
)


def write_config_cache(configuration: dict) -> None:
    """Atomically cache the last known-good gateway configuration."""
    temp_path = CONFIG_CACHE_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(configuration))
    temp_path.replace(CONFIG_CACHE_PATH)


def read_config_cache() -> dict | None:
    """Return the last cached configuration, or None if unavailable."""
    if not CONFIG_CACHE_PATH.exists():
        return None

    try:
        return json.loads(CONFIG_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Unable to read cached configuration: %s", error)
        return None
