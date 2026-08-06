import struct

from pymodbus.client import ModbusSerialClient


PORT = "COM6"
SLAVE_ID = 2

# Keep the same address that returned [64575, 17048].
REGISTER_ADDRESS = 140

client = ModbusSerialClient(
    port=PORT,
    baudrate=4800,
    parity="O",
    stopbits=2,
    bytesize=8,
    timeout=2,
)


def decode_variations(registers):
    first, second = registers

    variations = {
        "Big byte + normal word": struct.pack(
            ">HH",
            first,
            second,
        ),

        "Big byte + swapped word": struct.pack(
            ">HH",
            second,
            first,
        ),

        "Little byte + normal word": struct.pack(
            "<HH",
            first,
            second,
        ),

        "Little byte + swapped word": struct.pack(
            "<HH",
            second,
            first,
        ),
    }

    for name, raw_bytes in variations.items():
        try:
            value = struct.unpack(
                ">f",
                raw_bytes,
            )[0]

            print(
                f"{name}: {value}"
            )

        except Exception as error:
            print(
                f"{name}: ERROR {error}"
            )


try:
    if not client.connect():
        raise ConnectionError(
            f"Unable to open {PORT}"
        )

    result = client.read_holding_registers(
        address=REGISTER_ADDRESS,
        count=2,
        device_id=SLAVE_ID,
    )

    if result.isError():
        raise RuntimeError(
            f"Modbus error: {result}"
        )

    registers = list(result.registers)

    print(
        "Raw registers:",
        registers,
    )

    decode_variations(registers)

finally:
    client.close()