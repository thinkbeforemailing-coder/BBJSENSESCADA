from drivers.modbus_rtu import ModbusRTUDriver
from drivers.modbus_tcp import ModbusTCPDriver
from drivers.registry import register_driver


register_driver(
    protocol_names=[
        "modbus_rtu",
        "modbus rtu",
        "modbus-rtu",
        "rtu",
        "serial",
    ],
    driver_class=ModbusRTUDriver,
)


register_driver(
    protocol_names=[
        "modbus_tcp",
        "modbus tcp",
        "modbus-tcp",
        "tcp",
    ],
    driver_class=ModbusTCPDriver,
)


__all__ = [
    "ModbusRTUDriver",
    "ModbusTCPDriver",
]