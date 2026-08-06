import logging
import os
from logging_config import setup_logger
import struct
import time
import threading
from typing import Any

import requests
from pymodbus.client import ModbusSerialClient

from offline_buffer import (
    count_pending_messages,
    enqueue_telemetry,
    get_pending_messages,
    initialize_database,
    mark_message_failed,
    mark_message_sent,
)


API_BASE_URL = "http://34.131.199.29:8000"

GATEWAY_KEY = os.environ.get("BBJ_GATEWAY_KEY")

if not GATEWAY_KEY:
    raise RuntimeError(
        "BBJ_GATEWAY_KEY environment variable is not set. "
        "Set it before starting the gateway."
    )

CONFIG_URL = f"{API_BASE_URL}/gateway/config"
TELEMETRY_URL = f"{API_BASE_URL}/gateway/telemetry/"

CONFIG_REFRESH_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
MODBUS_TIMEOUT_SECONDS = 2
DEVICE_LOCKS = {}
MODBUS_SERIAL_LOCK = threading.Lock()
BUFFER_RESEND_INTERVAL_SECONDS = 10
BUFFER_RESEND_BATCH_SIZE = 100

logger = setup_logger(
    logger_name="telemetry-poller",
    log_filename="telemetry_poller.log",
)

def normalize_parity(parity: Any) -> str:
    value = str(parity or "N").strip().upper()

    mapping = {
        "NONE": "N",
        "N": "N",
        "EVEN": "E",
        "E": "E",
        "ODD": "O",
        "O": "O",
    }

    return mapping.get(value, "N")


def normalize_stop_bits(stop_bits: Any) -> int:
    try:
        value = int(float(stop_bits))
    except (TypeError, ValueError):
        return 1

    return 2 if value == 2 else 1


def swap_bytes_in_words(registers: list[int]) -> list[int]:
    result: list[int] = []

    for register in registers:
        high_byte = (register >> 8) & 0xFF
        low_byte = register & 0xFF
        swapped = (low_byte << 8) | high_byte
        result.append(swapped)

    return result


def prepare_registers(
    registers: list[int],
    byte_order: str,
    word_order: str,
) -> list[int]:
    prepared = list(registers)

    if str(word_order).lower() in {"swapped", "little", "reverse"}:
        prepared.reverse()

    if str(byte_order).lower() in {"little", "swapped"}:
        prepared = swap_bytes_in_words(prepared)

    return prepared


def registers_to_bytes(registers: list[int]) -> bytes:
    return b"".join(
        struct.pack(">H", register & 0xFFFF)
        for register in registers
    )


def decode_registers(
    registers: list[int],
    data_type: str,
    byte_order: str,
    word_order: str,
) -> float:
    normalized_type = str(data_type).strip().lower()

    prepared = prepare_registers(
        registers=registers,
        byte_order=byte_order,
        word_order=word_order,
    )

    raw_bytes = registers_to_bytes(prepared)

    if normalized_type in {"float", "float32", "real"}:
        if len(raw_bytes) < 4:
            raise ValueError("float32 requires two registers")
        return float(struct.unpack(">f", raw_bytes[:4])[0])

    if normalized_type in {"double", "float64"}:
        if len(raw_bytes) < 8:
            raise ValueError("float64 requires four registers")
        return float(struct.unpack(">d", raw_bytes[:8])[0])

    if normalized_type in {"int16", "short"}:
        if len(raw_bytes) < 2:
            raise ValueError("int16 requires one register")
        return float(struct.unpack(">h", raw_bytes[:2])[0])

    if normalized_type in {"uint16", "unsigned16", "word"}:
        if len(raw_bytes) < 2:
            raise ValueError("uint16 requires one register")
        return float(struct.unpack(">H", raw_bytes[:2])[0])

    if normalized_type in {"int32", "long"}:
        if len(raw_bytes) < 4:
            raise ValueError("int32 requires two registers")
        return float(struct.unpack(">i", raw_bytes[:4])[0])

    if normalized_type in {"uint32", "unsigned32", "dword"}:
        if len(raw_bytes) < 4:
            raise ValueError("uint32 requires two registers")
        return float(struct.unpack(">I", raw_bytes[:4])[0])

    raise ValueError(f"Unsupported data type: {data_type}")


def download_configuration() -> dict:
    response = requests.get(
        CONFIG_URL,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    configuration = response.json()

    if not configuration.get("success"):
        raise RuntimeError("Gateway configuration response failed")

    return configuration


def post_telemetry_payload(payload: dict) -> None:
    response = requests.post(
    TELEMETRY_URL,
    json=payload,
    headers={
        "X-Gateway-Key": GATEWAY_KEY
    },
    timeout=HTTP_TIMEOUT_SECONDS,
)
    response.raise_for_status()

    logger.info(
    "Telemetry uploaded successfully | status=%s | payload=%s",
    response.status_code,
    payload
)

def save_telemetry(
    device_id: int,
    tag_id: int,
    value: float,
    quality: str = "good",
) -> None:
    payload = {
        "device_id": int(device_id),
        "tag_id": int(tag_id),
        "value": float(value),
        "quality": str(quality),
    }

    try:
        post_telemetry_payload(payload)
    except requests.RequestException as error:
        message_id = enqueue_telemetry(
            device_id=device_id,
            tag_id=tag_id,
            value=value,
            quality=quality,
        )

        logger.warning(
            "Cloud upload failed; telemetry buffered | "
            "message_id=%s | device_id=%s | tag_id=%s | error=%s",
            message_id,
            device_id,
            tag_id,
            error,
        )


def resend_pending_telemetry() -> None:
    pending_messages = get_pending_messages(
        limit=BUFFER_RESEND_BATCH_SIZE,
    )

    if not pending_messages:
        return

    logger.info(
        "Attempting to resend %s buffered message(s)",
        len(pending_messages),
    )

    for message in pending_messages:
        message_id = str(message["message_id"])
        payload = message.get("payload")

        if not isinstance(payload, dict):
            mark_message_failed(
                message_id,
                "Invalid or missing payload JSON",
            )
            logger.error(
                "Buffered telemetry has invalid payload | message_id=%s",
                message_id,
            )
            continue

        try:
            cloud_payload = {
                "device_id": int(payload["device_id"]),
                "tag_id": int(payload["tag_id"]),
                "value": float(payload["value"]),
                "quality": str(payload.get("quality") or "good"),
            }
        except (KeyError, TypeError, ValueError) as error:
            mark_message_failed(
                message_id,
                f"Invalid buffered telemetry fields: {error}",
            )
            logger.error(
                "Buffered telemetry fields are invalid | "
                "message_id=%s | error=%s",
                message_id,
                error,
            )
            continue

        try:
            post_telemetry_payload(cloud_payload)
            mark_message_sent(message_id)

            logger.info(
                "Buffered telemetry sent | "
                "message_id=%s | device_id=%s | tag_id=%s",
                message_id,
                cloud_payload["device_id"],
                cloud_payload["tag_id"],
            )
        except requests.RequestException as error:
            mark_message_failed(message_id, str(error))

            logger.warning(
                "Buffered telemetry resend failed | "
                "message_id=%s | error=%s",
                message_id,
                error,
            )

            break


def create_serial_client(connection: dict) -> ModbusSerialClient:
    serial_port = connection.get("serial_port")

    if not serial_port:
        raise ValueError("Serial port is not configured")

    return ModbusSerialClient(
        port=str(serial_port),
        baudrate=int(connection.get("baudrate") or 9600),
        parity=normalize_parity(connection.get("parity")),
        stopbits=normalize_stop_bits(connection.get("stop_bits")),
        bytesize=8,
        timeout=MODBUS_TIMEOUT_SECONDS,
    )


def read_modbus_registers(
    client: ModbusSerialClient,
    tag: dict,
    slave_id: int,
) -> list[int]:
    function_code = int(tag.get("function_code") or 3)
    register_address = int(tag["register_address"])
    register_count = int(tag.get("register_count") or 1)

    if function_code == 3:
        result = client.read_holding_registers(
            address=register_address,
            count=register_count,
            device_id=slave_id,
        )
    elif function_code == 4:
        result = client.read_input_registers(
            address=register_address,
            count=register_count,
            device_id=slave_id,
        )
    else:
        raise ValueError(
            "Only Modbus function codes 3 and 4 are currently supported"
        )

    if result.isError():
        raise RuntimeError(f"Modbus error: {result}")

    return list(result.registers)


def process_tag(
    client: ModbusSerialClient,
    device: dict,
    tag: dict,
) -> None:
    device_id = int(device["id"])
    tag_id = int(tag["id"])

    connection = device.get("connection") or {}
    slave_id = int(connection.get("slave_id") or 1)

    registers = read_modbus_registers(
        client=client,
        tag=tag,
        slave_id=slave_id,
    )

    decoded_value = decode_registers(
        registers=registers,
        data_type=tag.get("data_type", "float32"),
        byte_order=tag.get("byte_order", "big"),
        word_order=tag.get("word_order", "swapped"),
    )

    scale = float(tag.get("scale") or 1.0)
    offset = float(tag.get("offset_value") or 0.0)
    final_value = (decoded_value * scale) + offset

    decimal_places = int(tag.get("decimal_places") or 0)
    final_value = round(final_value, decimal_places)

    minimum_value = tag.get("minimum_value")
    maximum_value = tag.get("maximum_value")

    quality = "good"

    if (
        minimum_value is not None
        and final_value < float(minimum_value)
    ):
        quality = "out_of_range"

    if (
        maximum_value is not None
        and final_value > float(maximum_value)
    ):
        quality = "out_of_range"

    save_telemetry(
        device_id=device_id,
        tag_id=tag_id,
        value=final_value,
        quality=quality,
    )

    logger.info(
        "Device=%s | Tag=%s | Value=%s %s | Quality=%s | Raw=%s",
        device.get("device_name"),
        tag.get("display_name"),
        final_value,
        tag.get("unit") or "",
        quality,
        registers,
    )

def run_device(
    device: dict,
    last_poll_times: dict,
) -> None:

    device_id = int(device["id"])

    lock = DEVICE_LOCKS.setdefault(
        device_id,
        threading.Lock()
    )

    if not lock.acquire(blocking=False):
        logger.warning(
            "Device=%s already polling, skipping duplicate cycle",
            device.get("device_name"),
        )
        return

    client = None

    try:

        connection = device.get("connection") or {}

        communication_type = (
            str(device.get("communication_type") or "")
            .strip()
            .lower()
            .replace("_", " ")
            .replace("-", " ")
        )

        if communication_type not in {
            "modbus rtu",
            "serial",
            "rtu",
            "",
        }:
            logger.warning(
                "Skipping unsupported communication type for device %s: %s",
                device.get("device_name"),
                communication_type,
            )
            return


        with MODBUS_SERIAL_LOCK:

            client = create_serial_client(connection)

            if not client.connect():
                raise ConnectionError(
                    "Unable to connect to serial port "
                    f"{connection.get('serial_port')}"
                )


            try:

                current_time = time.monotonic()


                for tag in device.get("tags", []):

                    if not tag.get("enabled", True):
                        continue


                    poll_key = (
                        int(device["id"]),
                        int(tag["id"]),
                    )


                    poll_interval = float(
                        tag.get("poll_interval") or 2.0
                    )


                    previous_poll = last_poll_times.get(
                        poll_key,
                        0.0,
                    )


                    if current_time - previous_poll < poll_interval:
                        continue


                    try:

                        process_tag(
                            client=client,
                            device=device,
                            tag=tag,
                        )

                    except Exception as error:

                        logger.error(
                            "Device=%s | Tag=%s | Error=%s",
                            device.get("device_name"),
                            tag.get("display_name"),
                            error,
                        )

                    finally:

                        last_poll_times[poll_key] = current_time


            finally:

                client.close()


    finally:

        lock.release()

def main() -> None:
    initialize_database()

    logger.info("BBJ Sense Dynamic Gateway starting")
    logger.info("Cloud API: %s", API_BASE_URL)

    configuration: dict = {}
    last_config_download = 0.0
    last_buffer_resend = 0.0
    last_poll_times: dict = {}

    while True:
        current_time = time.monotonic()

        if (
            current_time - last_buffer_resend
            >= BUFFER_RESEND_INTERVAL_SECONDS
        ):
            try:
                resend_pending_telemetry()

                pending_count = count_pending_messages()

                if pending_count:
                    logger.warning(
                        "Offline buffer pending=%s",
                        pending_count,
                    )
            except Exception as error:
                logger.exception(
                    "Offline buffer resend error: %s",
                    error,
                )

            last_buffer_resend = current_time

        try:
            if (
                not configuration
                or current_time - last_config_download
                >= CONFIG_REFRESH_SECONDS
            ):
                configuration = download_configuration()
                last_config_download = current_time

                logger.info(
                    "Configuration loaded: %s device(s)",
                    configuration.get("device_count", 0),
                )

            for device in configuration.get("devices", []):
                try:
                    run_device(
                        device=device,
                        last_poll_times=last_poll_times,
                    )
                except Exception as error:
                    logger.error(
                        "Device=%s | Connection error=%s",
                        device.get("device_name"),
                        error,
                    )

        except requests.RequestException as error:
            logger.error(
                "Cloud API connection error: %s",
                error,
            )

        except Exception as error:
            logger.exception(
                "Unexpected gateway error: %s",
                error,
            )

        time.sleep(0.25)


if __name__ == "__main__":
    main()