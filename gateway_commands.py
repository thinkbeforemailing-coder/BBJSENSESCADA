from datetime import datetime, timezone

import requests

from logging_config import setup_logger
from settings import API_BASE_URL, GATEWAY_KEY, HTTP_TIMEOUT_SECONDS


COMMANDS_URL = f"{API_BASE_URL}/gateway/commands/pending"
ACK_URL_TEMPLATE = f"{API_BASE_URL}/gateway/commands/{{command_id}}/ack"

VALID_COMMAND_TYPES = {"write_register", "write_coil"}

logger = setup_logger(
    logger_name="bbj-sense-gateway-commands",
    log_filename="telemetry_poller.log",
)

_endpoint_unsupported_logged = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_pending_commands() -> list[dict]:
    """
    Return pending commands for this gateway.

    Returns an empty list if the backend doesn't expose the commands
    endpoint yet (404) or the request otherwise fails -- callers should
    treat "no commands" and "endpoint unsupported" identically.
    """
    global _endpoint_unsupported_logged

    try:
        response = requests.get(
            COMMANDS_URL,
            headers={"X-Gateway-Key": GATEWAY_KEY},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        logger.warning("Unable to reach commands endpoint: %s", error)
        return []

    if response.status_code == 404:
        if not _endpoint_unsupported_logged:
            logger.info(
                "Backend does not expose a commands endpoint yet; "
                "control support is inactive."
            )
            _endpoint_unsupported_logged = True

        return []

    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        logger.warning(
            "Invalid response from commands endpoint: %s",
            error,
        )
        return []

    if not payload.get("success"):
        return []

    commands = payload.get("commands")

    return commands if isinstance(commands, list) else []


def find_writable_tag(
    configuration: dict,
    device_id: int,
    tag_id: int,
):
    """
    Return (device, tag) for a tag that exists under device_id in the
    current configuration AND is explicitly marked writable.

    Returns (None, None) if the device/tag isn't found or isn't
    writable. This is the gateway-side authorization gate: a command's
    tag_id is never sufficient on its own -- it must match a tag the
    backend already declared writable in the config the gateway
    downloaded independently of the command itself.
    """
    for device in configuration.get("devices", []):
        if int(device.get("id", -1)) != device_id:
            continue

        for tag in device.get("tags", []):
            if int(tag.get("id", -1)) != tag_id:
                continue

            if tag.get("writable") is True:
                return device, tag

            return None, None

    return None, None


def ack_command(
    command_id,
    status: str,
    error: str | None = None,
) -> None:
    try:
        response = requests.post(
            ACK_URL_TEMPLATE.format(command_id=command_id),
            headers={"X-Gateway-Key": GATEWAY_KEY},
            json={
                "status": status,
                "executed_at": utc_now_iso(),
                "error": error,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as ack_error:
        logger.error(
            "Failed to ack command_id=%s | error=%s",
            command_id,
            ack_error,
        )
