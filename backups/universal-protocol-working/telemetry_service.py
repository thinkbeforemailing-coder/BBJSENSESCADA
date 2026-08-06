import requests


class TelemetryService:
    def __init__(
        self,
        api_base_url: str,
        timeout_seconds: int = 10,
    ) -> None:
        self.telemetry_url = (
            f"{api_base_url}/gateway/telemetry/"
        )
        self.timeout_seconds = timeout_seconds

    def save(
        self,
        device_id: int,
        tag_id: int,
        value: float,
        quality: str,
    ) -> None:
        payload = {
            "device_id": device_id,
            "tag_id": tag_id,
            "value": value,
            "quality": quality,
        }

        response = requests.post(
            self.telemetry_url,
            json=payload,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()