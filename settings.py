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

CONFIG_URL = f"{API_BASE_URL}/gateway/config"
TELEMETRY_URL = f"{API_BASE_URL}/gateway/telemetry/"
TELEMETRY_BATCH_URL = f"{API_BASE_URL}/gateway/telemetry/batch"
HEALTH_URL = f"{API_BASE_URL}/gateway/health"

CONFIG_REFRESH_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
