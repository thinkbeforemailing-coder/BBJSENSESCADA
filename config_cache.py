import json
import logging
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_CACHE_PATH = BASE_DIR / "config_cache.json"

# Deliberately NOT setup_logger() -- see offline_buffer.py for why.
logger = logging.getLogger("telemetry-poller.config_cache")


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
