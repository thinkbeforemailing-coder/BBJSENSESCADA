"""On-site Modbus diagnostic tool -- for checking serial connectivity
and reading register values by hand, independent of the running
gateway service.

IMPORTANT: a serial port can only be held open by one process at a
time on Windows. The "BBJ Sense Gateway" service already holds COM6
whenever it's running, so this script needs it stopped first:

    net stop "BBJ Sense Gateway"
    python diagnose_modbus.py            (see modes below)
    net start "BBJ Sense Gateway"

Two modes:

1. Default (no extra args): reads every tag of every device listed in
   config_cache.json -- the same connection settings and register map
   the live poller uses -- and prints PASS/FAIL with the raw registers
   and decoded value for each one. Good for "is everything working"
   after a site visit.

2. --address: probes ONE arbitrary register directly, for checking a
   register that isn't in the current tag config yet (e.g. verifying a
   register number from a meter's manual before adding it as a tag).
   Example, reading voltage (register 140, 2 registers, float32) off
   slave 2 on COM6:

       python diagnose_modbus.py --port COM6 --slave-id 2 --address 140

   Full option list: --port --baud --parity --stopbits --slave-id
   --address --count --function-code --data-type --byte-order
   --word-order

Also supports --list-ports, which enumerates what COM ports Windows
currently sees at all -- run this first if a device won't connect. If
the expected port isn't listed, that's a driver/cabling problem, not a
Modbus configuration problem -- no amount of retrying the read will
fix it.
"""

import argparse
import json
import struct
import sys
import time
from pathlib import Path

from pymodbus.client import ModbusSerialClient


# __file__ resolves to a temp extraction folder when this runs inside
# a PyInstaller-frozen .exe, not the folder the .exe actually sits in
# -- config_cache.json needs to be found next to the real .exe (or
# this script) either way, so it's resolved off sys.executable when
# frozen instead.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent

CONFIG_CACHE_PATH = _BASE_DIR / "config_cache.json"


def normalize_parity(parity) -> str:
    value = str(parity or "N").strip().upper()
    mapping = {
        "NONE": "N", "N": "N",
        "EVEN": "E", "E": "E",
        "ODD": "O", "O": "O",
    }
    return mapping.get(value, "N")


def normalize_stop_bits(stop_bits) -> int:
    try:
        value = int(float(stop_bits))
    except (TypeError, ValueError):
        return 1
    return 2 if value == 2 else 1


def swap_bytes_in_words(registers: list[int]) -> list[int]:
    result = []
    for register in registers:
        high_byte = (register >> 8) & 0xFF
        low_byte = register & 0xFF
        result.append((low_byte << 8) | high_byte)
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
    """Mirrors dynamic_modbus_poller.decode_registers() -- kept as an
    independent copy (not an import) so this diagnostic script has no
    dependency on BBJ_GATEWAY_KEY being set or on the live poller's log
    file, and can be run standalone at any time."""

    normalized_type = str(data_type).strip().lower()

    prepared = prepare_registers(registers, byte_order, word_order)
    raw_bytes = registers_to_bytes(prepared)

    if normalized_type in {"float", "float32", "real"}:
        return float(struct.unpack(">f", raw_bytes[:4])[0])
    if normalized_type in {"double", "float64"}:
        return float(struct.unpack(">d", raw_bytes[:8])[0])
    if normalized_type in {"int16", "short"}:
        return float(struct.unpack(">h", raw_bytes[:2])[0])
    if normalized_type in {"uint16", "unsigned16", "word"}:
        return float(struct.unpack(">H", raw_bytes[:2])[0])
    if normalized_type in {"int32", "long"}:
        return float(struct.unpack(">i", raw_bytes[:4])[0])
    if normalized_type in {"uint32", "unsigned32", "dword"}:
        return float(struct.unpack(">I", raw_bytes[:4])[0])

    raise ValueError(f"Unsupported data type: {data_type}")


def list_ports() -> None:
    from serial.tools import list_ports as _list_ports

    ports = list(_list_ports.comports())

    if not ports:
        print("No COM ports detected by Windows at all.")
        print(
            "That points at a driver or USB-adapter problem, not a "
            "Modbus/wiring problem -- check Device Manager."
        )
        return

    print(f"{len(ports)} COM port(s) detected:\n")
    for port in ports:
        print(f"  {port.device}  {port.description}")


def read_one_register(
    client: ModbusSerialClient,
    slave_id: int,
    address: int,
    count: int,
    function_code: int,
):
    if function_code == 4:
        return client.read_input_registers(
            address=address, count=count, device_id=slave_id
        )
    return client.read_holding_registers(
        address=address, count=count, device_id=slave_id
    )


def run_config_scan() -> None:
    if not CONFIG_CACHE_PATH.exists():
        print(f"No config_cache.json found at {CONFIG_CACHE_PATH}")
        print("Run with --port/--address instead for a raw probe.")
        return

    config = json.loads(CONFIG_CACHE_PATH.read_text())

    devices = config.get("devices", [])

    if not devices:
        print("config_cache.json has no devices listed.")
        return

    for device in devices:
        conn = device.get("connection") or {}
        port = conn.get("serial_port")

        print(f"\n=== {device.get('device_name')} ({port}) ===")

        if not port:
            print("  No serial_port configured -- skipping (TCP device?)")
            continue

        client = ModbusSerialClient(
            port=port,
            baudrate=int(conn.get("baudrate") or 9600),
            parity=normalize_parity(conn.get("parity")),
            stopbits=normalize_stop_bits(conn.get("stop_bits")),
            bytesize=int(conn.get("data_bits") or 8),
            timeout=2,
        )

        if not client.connect():
            print(
                f"  FAILED to open {port} -- either another process "
                "has it open (stop the gateway service first) or it's "
                "not a real port right now (check --list-ports)."
            )
            continue

        slave_id = conn.get("slave_id")

        for tag in device.get("tags", []):
            address = tag.get("register_address")
            count = tag.get("register_count") or 2
            function_code = int(tag.get("function_code") or 3)

            started = time.monotonic()

            try:
                result = read_one_register(
                    client, slave_id, address, count, function_code
                )
                elapsed_ms = (time.monotonic() - started) * 1000

                if result.isError():
                    print(
                        f"  FAIL  {tag.get('display_name'):<20} "
                        f"addr={address:<6} -- {result}"
                    )
                    continue

                registers = list(result.registers)
                value = decode_registers(
                    registers,
                    tag.get("data_type", "float32"),
                    tag.get("byte_order", "big"),
                    tag.get("word_order", "swapped"),
                )
                scaled = (
                    value * float(tag.get("scale", 1.0))
                    + float(tag.get("offset_value", 0.0))
                )

                print(
                    f"  OK    {tag.get('display_name'):<20} "
                    f"addr={address:<6} raw={registers} "
                    f"value={scaled:.3f} {tag.get('unit') or ''} "
                    f"({elapsed_ms:.0f} ms)"
                )

            except Exception as error:
                print(
                    f"  ERROR {tag.get('display_name'):<20} "
                    f"addr={address:<6} -- {error}"
                )

        client.close()


def run_raw_probe(args) -> None:
    client = ModbusSerialClient(
        port=args.port,
        baudrate=args.baud,
        parity=normalize_parity(args.parity),
        stopbits=normalize_stop_bits(args.stopbits),
        bytesize=8,
        timeout=2,
    )

    if not client.connect():
        print(
            f"FAILED to open {args.port} -- either another process has "
            "it open (stop the gateway service first) or it's not a "
            "real port right now (check --list-ports)."
        )
        return

    try:
        result = read_one_register(
            client,
            args.slave_id,
            args.address,
            args.count,
            args.function_code,
        )

        if result.isError():
            print(f"Modbus error: {result}")
            return

        registers = list(result.registers)
        print("Raw registers:", registers)

        value = decode_registers(
            registers, args.data_type, args.byte_order, args.word_order
        )
        print(f"Decoded value ({args.data_type}):", round(value, 4))

    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--list-ports", action="store_true")

    parser.add_argument("--port")
    parser.add_argument("--baud", type=int, default=4800)
    parser.add_argument("--parity", default="O")
    parser.add_argument("--stopbits", type=int, default=2)
    parser.add_argument("--slave-id", type=int, default=1)
    parser.add_argument("--address", type=int)
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--function-code", type=int, default=3)
    parser.add_argument("--data-type", default="float32")
    parser.add_argument("--byte-order", default="big")
    parser.add_argument("--word-order", default="swapped")

    args = parser.parse_args()

    if args.list_ports:
        list_ports()
        return

    if args.address is not None:
        if not args.port:
            parser.error("--port is required with --address")
        run_raw_probe(args)
        return

    run_config_scan()


if __name__ == "__main__":
    main()
