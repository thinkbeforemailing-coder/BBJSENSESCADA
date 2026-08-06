from pymodbus.client import ModbusSerialClient
import struct


client = ModbusSerialClient(
    port="COM6",
    baudrate=4800,
    parity="O",
    stopbits=2,
    bytesize=8,
    timeout=2
)


if not client.connect():
    print("Failed to connect COM6")
    exit()


for address in range(300, 400, 2):

    try:

        result = client.read_holding_registers(
            address=address,
            count=2,
            device_id=2
        )


        if not result.isError():

            raw = result.registers


            data = struct.pack(
                ">HH",
                raw[1],
                raw[0]
            )


            value = struct.unpack(
                ">f",
                data
            )[0]


            print(
                f"Address {address} | Raw {raw} | Float {value}"
            )


    except Exception as e:

        print(
            f"Address {address} Error: {e}"
        )


client.close()