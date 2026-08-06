from abc import ABC, abstractmethod
from typing import Any


class BaseProtocolDriver(ABC):
    """
    Base interface for every BBJ Sense protocol driver.

    Future drivers:
    - Modbus RTU
    - Modbus TCP
    - OPC UA
    - MQTT
    - BACnet
    - SNMP
    - REST API
    """

    def __init__(
        self,
        device: dict,
    ) -> None:
        self.device = device
        self.connection = (
            device.get("connection") or {}
        )

    @abstractmethod
    def connect(self) -> bool:
        """Open the device connection."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the device connection."""

    @abstractmethod
    def read_tag(
        self,
        tag: dict,
    ) -> dict:
        """
        Read one configured tag.

        Expected response:
        {
            "value": 49.95,
            "quality": "good",
            "raw": [1234, 5678]
        }
        """

    def validate_configuration(
        self,
    ) -> None:
        """
        Validate the device connection configuration.

        Drivers can override this method when they need
        protocol-specific validation.
        """

    def health_status(self) -> dict[str, Any]:
        return {
            "connected": False,
            "protocol": self.device.get(
                "communication_type"
            ),
        }