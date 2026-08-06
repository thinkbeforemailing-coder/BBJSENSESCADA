from typing import Type

from drivers.base import BaseProtocolDriver


_DRIVER_REGISTRY: dict[
    str,
    Type[BaseProtocolDriver],
] = {}


def normalize_protocol(
    protocol: str | None,
) -> str:
    if protocol is None:
        return ""

    return (
        str(protocol)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def register_driver(
    protocol_names: list[str],
    driver_class: Type[BaseProtocolDriver],
) -> None:
    for protocol_name in protocol_names:
        normalized = normalize_protocol(
            protocol_name
        )

        _DRIVER_REGISTRY[normalized] = (
            driver_class
        )


def get_driver_class(
    protocol: str | None,
) -> Type[BaseProtocolDriver]:
    normalized = normalize_protocol(
        protocol
    )

    driver_class = _DRIVER_REGISTRY.get(
        normalized
    )

    if driver_class is None:
        supported = ", ".join(
            sorted(_DRIVER_REGISTRY.keys())
        )

        raise ValueError(
            f"Unsupported protocol: {protocol}. "
            f"Available drivers: {supported}"
        )

    return driver_class


def list_supported_protocols() -> list[str]:
    return sorted(
        _DRIVER_REGISTRY.keys()
    )