import struct

from pymodbus.client import ModbusSerialClient


PORT = "COM6"
SLAVE_ID = 2
REGISTER_ADDRESS = 140
REGISTER_COUNT = 2


client = ModbusSerialClient(
    port=PORT,
    baudrate=4800,
    parity="O",
    stopbits=2,
    bytesize=8,
    timeout=2,
)


def decode_float32_word_swapped(
    registers: list[int],
) -> float:
    if len(registers) != 2:
        raise ValueError(
            "Two registers are required"
        )

    raw = struct.pack(
        ">HH",
        registers[1],
        registers[0],
    )

    return struct.unpack(
        ">f",
        raw,
    )[0]


try:
    if not client.connect():
        raise ConnectionError(
            f"Could not open {PORT}"
        )

    result = client.read_holding_registers(
        address=REGISTER_ADDRESS,
        count=REGISTER_COUNT,
        device_id=SLAVE_ID,
    )

    if result.isError():
        raise RuntimeError(
            f"Modbus error: {result}"
        )

    registers = list(result.registers)

    value = decode_float32_word_swapped(
        registers
    )

    print(
        "Raw registers:",
        registers,
    )

    print(
        "Decoded voltage:",
        round(value, 2),
        "V",
    )

finally:
    client.close()