"""Interactive on-site Modbus console -- no internet and no
config_cache.json needed. Connect once, then read as many
slave-id/register combinations as you want by typing them in, without
retyping connection settings or restarting the script each time.

Usage:

    net stop "BBJ Sense Gateway"      (frees COM6 -- see below)
    python modbus_console.py
    net start "BBJ Sense Gateway"

Like diagnose_modbus.py, this needs the serial port to itself -- the
live gateway service holds it while running, so stop the service
first and restart it when done.

At each prompt, pressing Enter alone accepts the default shown in
brackets, which is always the last value you typed for that field --
so reading several registers off the same slave only means retyping
the address each time, not the whole connection/decode setup.

A register address can also be a range ("300-400") to sweep a block
in one go, the same way the old test_current_scan.py scripts did.

Commands at the register-address prompt: 'q' to quit, 'r' to
reconnect with different port/baud/parity settings.
"""

from pymodbus.client import ModbusSerialClient

from diagnose_modbus import (
    decode_registers,
    normalize_parity,
    normalize_stop_bits,
    read_one_register,
)


def ask(prompt: str, default: str) -> str:
    typed = input(f"{prompt} [{default}]: ").strip()
    return typed if typed else default


def connect() -> ModbusSerialClient | None:
    port = ask("COM port", "COM6")
    baud = int(ask("Baud rate", "4800"))
    parity = ask("Parity (N/E/O)", "O")
    stopbits = int(ask("Stop bits", "2"))

    client = ModbusSerialClient(
        port=port,
        baudrate=baud,
        parity=normalize_parity(parity),
        stopbits=normalize_stop_bits(stopbits),
        bytesize=8,
        timeout=2,
    )

    if not client.connect():
        print(
            f"\nFAILED to open {port}. Either another process has it "
            "open (stop the gateway service: net stop \"BBJ Sense "
            "Gateway\") or it's not a real port right now.\n"
        )

        from serial.tools import list_ports as _list_ports

        ports = list(_list_ports.comports())

        if ports:
            print("COM ports Windows currently sees:")
            for p in ports:
                print(f"  {p.device}  {p.description}")
        else:
            print(
                "Windows sees no COM ports at all -- that's a "
                "driver/USB-adapter problem, not a wiring problem."
            )

        return None

    print(f"Connected to {port}.\n")
    return client


def read_and_print(
    client: ModbusSerialClient,
    slave_id: int,
    address: int,
    count: int,
    function_code: int,
    data_type: str,
    byte_order: str,
    word_order: str,
) -> None:
    try:
        result = read_one_register(
            client, slave_id, address, count, function_code
        )

        if result.isError():
            print(f"  addr={address:<6} FAIL  {result}")
            return

        registers = list(result.registers)

        try:
            value = decode_registers(
                registers, data_type, byte_order, word_order
            )
            print(
                f"  addr={address:<6} OK    raw={registers} "
                f"value={value:.4f}"
            )
        except Exception as decode_error:
            print(
                f"  addr={address:<6} OK    raw={registers} "
                f"(couldn't decode as {data_type}: {decode_error})"
            )

    except Exception as error:
        print(f"  addr={address:<6} ERROR {error}")


def main() -> None:
    print(__doc__)

    client = connect()
    if client is None:
        return

    slave_id = "1"
    count = "2"
    function_code = "3"
    data_type = "float32"
    byte_order = "big"
    word_order = "swapped"

    try:
        while True:
            address_input = ask(
                "\nRegister address (or range like 300-400, "
                "'r' to reconnect, 'q' to quit)",
                "",
            )

            if address_input.lower() == "q":
                break

            if address_input.lower() == "r":
                client.close()
                client = connect()
                if client is None:
                    return
                continue

            if not address_input:
                print("Enter an address, a range, 'r', or 'q'.")
                continue

            slave_id = ask("Slave ID", slave_id)
            count = ask("Register count", count)
            function_code = ask(
                "Function code (3=holding, 4=input)", function_code
            )
            data_type = ask(
                "Data type (float32/float64/int16/uint16/int32/uint32)",
                data_type,
            )
            byte_order = ask("Byte order (big/little)", byte_order)
            word_order = ask("Word order (normal/swapped)", word_order)

            if "-" in address_input:
                start_str, end_str = address_input.split("-", 1)
                start, end = int(start_str), int(end_str)
                step = int(count)

                for address in range(start, end, step):
                    read_and_print(
                        client,
                        int(slave_id),
                        address,
                        int(count),
                        int(function_code),
                        data_type,
                        byte_order,
                        word_order,
                    )
            else:
                read_and_print(
                    client,
                    int(slave_id),
                    int(address_input),
                    int(count),
                    int(function_code),
                    data_type,
                    byte_order,
                    word_order,
                )

    finally:
        client.close()
        print("\nConnection closed.")


if __name__ == "__main__":
    main()
