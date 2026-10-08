import os


API_BASE_URL = os.environ.get(
    "BBJ_API_BASE_URL",
    "https://www.bbjsense.com",
)

GATEWAY_ID = os.environ.get("BBJ_GATEWAY_ID", "BBJ-GW-001-v2")

GATEWAY_NAME = os.environ.get(
    "BBJ_GATEWAY_NAME",
    "BBJ Windows Gateway 01",
)

GATEWAY_KEY = os.environ.get("BBJ_GATEWAY_KEY")

# Workaround: used only when /gateway/config sends a serial device
# with an empty serial_port (backend not saving/returning it).
DEFAULT_SERIAL_PORT = os.environ.get("BBJ_DEFAULT_SERIAL_PORT", "").strip()


def parse_word_order_overrides(raw: str) -> dict[int, str]:
    """
    "23:swapped,24:swapped" -> {23: "swapped", 24: "swapped"}.
    Malformed entries are skipped rather than stopping the gateway.
    """
    overrides = {}

    for entry in (raw or "").split(","):
        tag_id, _, word_order = entry.partition(":")
        try:
            overrides[int(tag_id.strip())] = word_order.strip()
        except ValueError:
            continue

    return {k: v for k, v in overrides.items() if v}


# Workaround: forces word_order for specific tag IDs, ignoring what
# /gateway/config sends (backend not saving word_order edits).
WORD_ORDER_OVERRIDES = parse_word_order_overrides(
    os.environ.get("BBJ_WORD_ORDER_OVERRIDES", "")
)

CONFIG_URL = f"{API_BASE_URL}/gateway/config"
TELEMETRY_URL = f"{API_BASE_URL}/gateway/telemetry/"
TELEMETRY_BATCH_URL = f"{API_BASE_URL}/gateway/telemetry/batch"
HEALTH_URL = f"{API_BASE_URL}/gateway/health"

CONFIG_REFRESH_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
