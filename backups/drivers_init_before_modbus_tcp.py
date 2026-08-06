from drivers.modbus_rtu import ModbusRTUDriver
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


__all__ = [
    "ModbusRTUDriver",
]