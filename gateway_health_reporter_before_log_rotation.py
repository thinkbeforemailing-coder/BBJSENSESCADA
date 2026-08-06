import platform
import socket
import time
from datetime import datetime, timezone

import psutil
import requests


CLOUD_API_URL = "http://34.131.199.29:8000/gateway/health"

GATEWAY_ID = "BBJ-GW-001"
GATEWAY_NAME = "BBJ Windows Gateway 01"
APP_VERSION = "1.0.0"

REPORT_INTERVAL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10


def get_ip_address() -> str:
    """Return the primary local IP address."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()


def get_uptime_seconds() -> int:
    """Return Windows system uptime in seconds."""
    boot_time = psutil.boot_time()
    return int(time.time() - boot_time)


def build_health_payload() -> dict:
    """Collect current gateway health information."""
    return {
        "gateway_id": GATEWAY_ID,
        "gateway_name": GATEWAY_NAME,
        "status": "online",
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("C:\\").percent,
        "uptime_seconds": get_uptime_seconds(),
        "connected_devices": 1,
        "failed_devices": 0,
        "ip_address": get_ip_address(),
        "hostname": socket.gethostname(),
        "operating_system": (
            f"{platform.system()} "
            f"{platform.release()} "
            f"{platform.version()}"
        ),
        "app_version": APP_VERSION,
    }


def send_health_report() -> None:
    """Send one gateway health report to the cloud."""
    payload = build_health_payload()

    response = requests.post(
        CLOUD_API_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    result = response.json()

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"Health sent successfully | "
        f"record_id={result.get('id')} | "
        f"cpu={payload['cpu_percent']}% | "
        f"memory={payload['memory_percent']}% | "
        f"disk={payload['disk_percent']}%"
    )


def main() -> None:
    print("BBJ Sense Gateway Health Reporter starting...")
    print(f"Cloud API: {CLOUD_API_URL}")
    print(f"Gateway ID: {GATEWAY_ID}")
    print(f"Interval: {REPORT_INTERVAL_SECONDS} seconds")

    while True:
        try:
            send_health_report()
        except requests.RequestException as exc:
            print(f"Health upload failed: {exc}")
        except Exception as exc:
            print(f"Unexpected health reporter error: {exc}")

        time.sleep(REPORT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()