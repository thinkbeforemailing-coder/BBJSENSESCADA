import requests


class ConfigService:
    def __init__(
        self,
        api_base_url: str,
        timeout_seconds: int = 10,
    ) -> None:
        self.config_url = (
            f"{api_base_url}/gateway/config"
        )
        self.timeout_seconds = timeout_seconds

    def download_configuration(self) -> dict:
        response = requests.get(
            self.config_url,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        configuration = response.json()

        if not configuration.get("success"):
            raise RuntimeError(
                "Gateway configuration response failed"
            )

        return configuration