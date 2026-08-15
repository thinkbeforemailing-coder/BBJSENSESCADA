import contextlib
from logging_config import setup_logger
import struct
import time
import threading
from typing import Any

import requests
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

from offline_buffer import (
    count_pending_messages,
    delete_sent_messages,
    enqueue_telemetry,
    get_pending_messages,
    initialize_database,
    mark_message_failed,
    mark_message_sent,
    utc_now_iso,
)
import local_historian
from device_status import write_device_status
from config_cache import read_config_cache, write_config_cache
from gateway_commands import (
    VALID_COMMAND_TYPES,
    ack_command,
    fetch_pending_commands,
    find_writable_tag,
)
from settings import (
    API_BASE_URL,
    CONFIG_REFRESH_SECONDS,
    CONFIG_URL,
    GATEWAY_KEY,
    HTTP_TIMEOUT_SECONDS,
    TELEMETRY_BATCH_URL,
)


if not GATEWAY_KEY:
    raise RuntimeError(
        "BBJ_GATEWAY_KEY environment variable is not set. "
        "Set it before starting the gateway."
    )

MODBUS_TIMEOUT_SECONDS = 2
CLIENT_CLOSE_TIMEOUT_SECONDS = 3
DEVICE_LOCKS = {}
MODBUS_SERIAL_LOCK = threading.Lock()
BATCH_FLUSH_INTERVAL_SECONDS = 5
BATCH_FLUSH_SIZE = 500
BUFFER_CLEANUP_INTERVAL_SECONDS = 3600
BUFFER_CLEANUP_KEEP_LATEST = 1000
DEVICE_STATUS_WRITE_INTERVAL_SECONDS = 5
COMMANDS_POLL_INTERVAL_SECONDS = 60

RTU_COMMUNICATION_TYPES = {"modbus rtu", "serial", "rtu", ""}
TCP_COMMUNICATION_TYPES = {"modbus tcp", "tcp"}

DEVICE_STATUS: dict[int, str] = {}

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
        headers={"X-Gateway-Key": GATEWAY_KEY},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    configuration = response.json()

    if not configuration.get("success"):
        raise RuntimeError("Gateway configuration response failed")

    return configuration


def post_telemetry_batch(items: list[dict]) -> dict:
    response = requests.post(
        TELEMETRY_BATCH_URL,
        json={"items": items},
        headers={
            "X-Gateway-Key": GATEWAY_KEY
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()


def save_telemetry(
    device_id: int,
    tag_id: int,
    value: float,
    quality: str = "good",
) -> None:
    """
    Queue one reading locally; flush_pending_batch() uploads it.

    Deliberately does not attempt a synchronous cloud POST here -- that
    used to block the single-threaded poll loop on network I/O for up
    to HTTP_TIMEOUT_SECONDS per tag whenever the connection was slow or
    down, which could cascade into every other device/tag falling
    behind its own poll schedule. Enqueuing is a local SQLite write;
    the periodic batch flush does the actual upload, off the poll hot
    path, batching everything accumulated since the last flush into
    one HTTP request instead of one request per reading.
    """
    source_timestamp = utc_now_iso()

    enqueue_telemetry(
        device_id=device_id,
        tag_id=tag_id,
        value=value,
        quality=quality,
        source_timestamp=source_timestamp,
    )

    # Best-effort, separate from the send-queue above -- a historian
    # write failing must never block or fail the actual telemetry
    # upload path.
    try:
        local_historian.record_reading(
            device_id=device_id,
            tag_id=tag_id,
            value=value,
            quality=quality,
            source_timestamp=source_timestamp,
        )
    except Exception:
        logger.exception(
            "Local historian write failed | device_id=%s tag_id=%s",
            device_id,
            tag_id,
        )


def flush_pending_batch() -> None:
    """Upload everything currently queued locally in one HTTP request."""
    pending_messages = get_pending_messages(
        limit=BATCH_FLUSH_SIZE,
    )

    if not pending_messages:
        return

    items = []
    valid_messages = []

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
            item = {
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

        items.append(item)
        valid_messages.append((message_id, item))

    if not items:
        return

    try:
        result = post_telemetry_batch(items)

    except requests.RequestException as error:
        logger.warning(
            "Batch telemetry upload failed | count=%s | error=%s",
            len(items),
            error,
        )

        for message_id, _item in valid_messages:
            mark_message_failed(message_id, str(error))

        return

    rejected = result.get("rejected") or []

    rejected_pairs = {
        (int(entry["device_id"]), int(entry["tag_id"]))
        for entry in rejected
        if "device_id" in entry and "tag_id" in entry
    }

    for message_id, item in valid_messages:
        pair = (item["device_id"], item["tag_id"])

        if pair in rejected_pairs:
            mark_message_failed(
                message_id,
                "Rejected by cloud: device or tag not found",
            )
        else:
            mark_message_sent(message_id)

    logger.info(
        "Batch telemetry uploaded | accepted=%s | rejected=%s",
        result.get("accepted"),
        len(rejected),
    )


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


def create_tcp_client(connection: dict) -> ModbusTcpClient:
    ip_address = connection.get("ip_address")

    if not ip_address:
        raise ValueError("IP address is not configured")

    return ModbusTcpClient(
        host=str(ip_address),
        port=int(connection.get("tcp_port") or 502),
        timeout=MODBUS_TIMEOUT_SECONDS,
    )


def create_modbus_client(
    communication_type: str,
    connection: dict,
) -> ModbusSerialClient | ModbusTcpClient:
    if communication_type in RTU_COMMUNICATION_TYPES:
        return create_serial_client(connection)

    if communication_type in TCP_COMMUNICATION_TYPES:
        return create_tcp_client(connection)

    raise ValueError(
        f"Unsupported communication type: {communication_type}"
    )


def close_client_with_timeout(
    client: ModbusSerialClient | ModbusTcpClient,
) -> None:
    """
    Close a Modbus client without letting a stuck driver freeze the poller.

    client.close() is a blocking OS-level call with no timeout of its own.
    If the underlying serial handle is wedged (see the 2026-08-07 COM-port
    zombie incident), close() can block indefinitely and, since polling is
    single-threaded, take the whole gateway down with it. Running it on a
    daemon thread and waiting only up to CLIENT_CLOSE_TIMEOUT_SECONDS lets
    the poll loop move on regardless; the abandoned thread finishes (or
    doesn't) on its own.
    """
    close_thread = threading.Thread(target=client.close, daemon=True)
    close_thread.start()
    close_thread.join(timeout=CLIENT_CLOSE_TIMEOUT_SECONDS)

    if close_thread.is_alive():
        logger.warning(
            "client.close() did not return within %ss -- abandoning it "
            "so the poll loop is not blocked; the underlying handle may "
            "still be held by the OS",
            CLIENT_CLOSE_TIMEOUT_SECONDS,
        )


def read_modbus_registers(
    client: ModbusSerialClient | ModbusTcpClient,
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
    client: ModbusSerialClient | ModbusTcpClient,
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

        if (
            communication_type not in RTU_COMMUNICATION_TYPES
            and communication_type not in TCP_COMMUNICATION_TYPES
        ):
            logger.warning(
                "Skipping unsupported communication type for device %s: %s",
                device.get("device_name"),
                communication_type,
            )
            DEVICE_STATUS[device_id] = "failed"
            return

        is_serial = communication_type in RTU_COMMUNICATION_TYPES

        bus_lock = (
            MODBUS_SERIAL_LOCK
            if is_serial
            else contextlib.nullcontext()
        )

        with bus_lock:

            client = create_modbus_client(
                communication_type=communication_type,
                connection=connection,
            )

            if not client.connect():
                raise ConnectionError(
                    "Unable to connect to device "
                    f"{device.get('device_name')}"
                )

            DEVICE_STATUS[device_id] = "connected"


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

                close_client_with_timeout(client)


    except Exception:
        DEVICE_STATUS[device_id] = "failed"
        raise

    finally:

        lock.release()

def write_command_value(
    client: ModbusSerialClient | ModbusTcpClient,
    tag: dict,
    command_type: str,
    value: Any,
    slave_id: int,
) -> None:
    register_address = int(tag["register_address"])

    if command_type == "write_register":

        if int(tag.get("function_code") or 3) == 4:
            raise ValueError(
                "Tag is an input register (function_code=4); "
                "input registers are read-only in Modbus and "
                "cannot be written"
            )

        result = client.write_register(
            address=register_address,
            value=int(value),
            device_id=slave_id,
        )

    elif command_type == "write_coil":
        result = client.write_coil(
            address=register_address,
            value=bool(value),
            device_id=slave_id,
        )

    else:
        raise ValueError(f"Unsupported command type: {command_type}")

    if result.isError():
        raise RuntimeError(f"Modbus write error: {result}")


def execute_command(
    command: dict,
    configuration: dict,
) -> None:
    command_id = command.get("command_id")
    command_type = str(command.get("command_type") or "")
    value = command.get("value")

    try:
        device_id = int(command["device_id"])
        tag_id = int(command["tag_id"])
    except (KeyError, TypeError, ValueError) as error:
        logger.error(
            "Command=%s | Rejected: malformed device_id/tag_id | error=%s",
            command_id,
            error,
        )
        ack_command(command_id, "failed", f"Malformed command: {error}")
        return

    if command_type not in VALID_COMMAND_TYPES:
        logger.error(
            "Command=%s | Rejected: unsupported command_type=%s",
            command_id,
            command_type,
        )
        ack_command(
            command_id,
            "failed",
            f"Unsupported command_type: {command_type}",
        )
        return

    device, tag = find_writable_tag(configuration, device_id, tag_id)

    if device is None or tag is None:
        logger.error(
            "Command=%s | Rejected: device=%s tag=%s not found "
            "or not marked writable",
            command_id,
            device_id,
            tag_id,
        )
        ack_command(
            command_id,
            "failed",
            "Tag not found or not marked writable",
        )
        return

    device_id_int = int(device["id"])

    lock = DEVICE_LOCKS.setdefault(device_id_int, threading.Lock())

    client = None

    with lock:
        try:
            connection = device.get("connection") or {}

            communication_type = (
                str(device.get("communication_type") or "")
                .strip()
                .lower()
                .replace("_", " ")
                .replace("-", " ")
            )

            is_serial = communication_type in RTU_COMMUNICATION_TYPES

            bus_lock = (
                MODBUS_SERIAL_LOCK
                if is_serial
                else contextlib.nullcontext()
            )

            with bus_lock:

                client = create_modbus_client(
                    communication_type=communication_type,
                    connection=connection,
                )

                if not client.connect():
                    raise ConnectionError(
                        "Unable to connect to device "
                        f"{device.get('device_name')}"
                    )

                slave_id = int(connection.get("slave_id") or 1)

                write_command_value(
                    client=client,
                    tag=tag,
                    command_type=command_type,
                    value=value,
                    slave_id=slave_id,
                )

        except Exception as error:
            logger.error(
                "Command=%s | Device=%s | Tag=%s | Execution failed: %s",
                command_id,
                device.get("device_name"),
                tag.get("display_name"),
                error,
            )
            ack_command(command_id, "failed", str(error))
            return

        finally:
            if client is not None:
                close_client_with_timeout(client)

    logger.info(
        "Command=%s | Device=%s | Tag=%s | Executed successfully | "
        "command_type=%s | value=%s",
        command_id,
        device.get("device_name"),
        tag.get("display_name"),
        command_type,
        value,
    )
    ack_command(command_id, "success")


def run_buffer_cleanup_loop() -> None:
    """
    Periodically delete old sent telemetry records.

    Runs on its own thread, deliberately decoupled from the main
    polling loop: a bulk DELETE across a large "sent" backlog can take
    much longer than expected on Windows (Defender real-time scanning
    interacting with SQLite's synchronous=FULL fsync behavior is a
    known cause), and the main loop must never be blocked by
    housekeeping -- devices still need to be polled on schedule while
    this runs. Sleeps first so cleanup never competes with startup.
    """
    while True:
        time.sleep(BUFFER_CLEANUP_INTERVAL_SECONDS)

        try:
            deleted_count = delete_sent_messages(
                keep_latest=BUFFER_CLEANUP_KEEP_LATEST,
            )

            if deleted_count:
                logger.info(
                    "Offline buffer cleanup removed %s old "
                    "sent record(s)",
                    deleted_count,
                )
        except Exception as error:
            logger.exception(
                "Offline buffer cleanup error: %s",
                error,
            )


def run_history_cleanup_loop() -> None:
    """
    Periodically prune local_historian rows older than its retention
    window. Same decoupled-thread rationale as run_buffer_cleanup_loop
    above -- housekeeping must never compete with the poll schedule.
    """
    while True:
        time.sleep(BUFFER_CLEANUP_INTERVAL_SECONDS)

        try:
            deleted_count = local_historian.prune_old_history()

            if deleted_count:
                logger.info(
                    "Local historian cleanup removed %s old record(s)",
                    deleted_count,
                )
        except Exception:
            logger.exception("Local historian cleanup error")


def main() -> None:
    initialize_database()
    local_historian.initialize_database()

    logger.info("BBJ Sense Dynamic Gateway starting")
    logger.info("Cloud API: %s", API_BASE_URL)

    threading.Thread(
        target=run_buffer_cleanup_loop,
        daemon=True,
    ).start()

    threading.Thread(
        target=run_history_cleanup_loop,
        daemon=True,
    ).start()

    configuration: dict = read_config_cache() or {}

    if configuration:
        logger.info(
            "Loaded cached configuration: %s device(s)",
            configuration.get("device_count", 0),
        )

    last_config_download = 0.0
    last_batch_flush = 0.0
    last_device_status_write = 0.0
    last_commands_poll = 0.0
    last_poll_times: dict = {}

    while True:
        current_time = time.monotonic()

        if (
            current_time - last_batch_flush
            >= BATCH_FLUSH_INTERVAL_SECONDS
        ):
            try:
                flush_pending_batch()

                # Every reading passes through this queue now, so a
                # small pending count between flushes is normal, not a
                # problem -- only warn once the queue is growing faster
                # than a full batch flush can drain it (a real backlog,
                # e.g. the cloud or connection actually being down).
                pending_count = count_pending_messages()

                if pending_count > BATCH_FLUSH_SIZE:
                    logger.warning(
                        "Offline buffer backlog growing | pending=%s",
                        pending_count,
                    )
            except Exception as error:
                logger.exception(
                    "Batch flush error: %s",
                    error,
                )

            last_batch_flush = current_time

        try:
            if (
                not configuration
                or current_time - last_config_download
                >= CONFIG_REFRESH_SECONDS
            ):
                configuration = download_configuration()
                last_config_download = current_time

                write_config_cache(configuration)

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

            if (
                current_time - last_device_status_write
                >= DEVICE_STATUS_WRITE_INTERVAL_SECONDS
            ):
                try:
                    write_device_status(DEVICE_STATUS)
                except Exception as error:
                    logger.error(
                        "Failed to write device status: %s",
                        error,
                    )

                last_device_status_write = current_time

            if (
                current_time - last_commands_poll
                >= COMMANDS_POLL_INTERVAL_SECONDS
            ):
                try:
                    pending_commands = fetch_pending_commands()

                    for command in pending_commands:
                        execute_command(
                            command=command,
                            configuration=configuration,
                        )
                except Exception as error:
                    logger.exception(
                        "Command processing error: %s",
                        error,
                    )

                last_commands_poll = current_time

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