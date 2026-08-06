import struct
from typing import Any

from pymodbus.client import ModbusSerialClient

from drivers.base import BaseProtocolDriver


class ModbusRTUDriver(BaseProtocolDriver):
    """
    Universal Modbus RTU driver for BBJ Sense.

    Supported functions:
    - Function code 3: Holding Registers
    - Function code 4: Input Registers

    Supported data types:
    - float32
    - float64
    - int16
    - uint16
    - int32
    - uint32
    """

    def __init__(
        self,
        device: dict,
    ) -> None:
        super().__init__(device)

        self.client: ModbusSerialClient | None = None
        self.connected = False

    @staticmethod
    def normalize_parity(
        parity: Any,
    ) -> str:
        value = str(
            parity or "N"
        ).strip().upper()

        mapping = {
            "NONE": "N",
            "N": "N",
            "EVEN": "E",
            "E": "E",
            "ODD": "O",
            "O": "O",
        }

        return mapping.get(
            value,
            "N",
        )

    @staticmethod
    def normalize_stop_bits(
        stop_bits: Any,
    ) -> int:
        try:
            value = int(
                float(stop_bits)
            )

        except (
            TypeError,
            ValueError,
        ):
            return 1

        return 2 if value == 2 else 1

    def validate_configuration(
        self,
    ) -> None:
        serial_port = self.connection.get(
            "serial_port"
        )

        if not serial_port:
            raise ValueError(
                "Serial port is not configured"
            )

        slave_id = self.connection.get(
            "slave_id"
        )

        if slave_id is None:
            raise ValueError(
                "Modbus slave ID is not configured"
            )

    def connect(self) -> bool:
        self.validate_configuration()

        self.client = ModbusSerialClient(
            port=str(
                self.connection.get(
                    "serial_port"
                )
            ),
            baudrate=int(
                self.connection.get(
                    "baudrate"
                ) or 9600
            ),
            parity=self.normalize_parity(
                self.connection.get(
                    "parity"
                )
            ),
            stopbits=self.normalize_stop_bits(
                self.connection.get(
                    "stop_bits"
                )
            ),
            bytesize=8,
            timeout=2,
        )

        self.connected = bool(
            self.client.connect()
        )

        return self.connected

    def disconnect(self) -> None:
        if self.client is not None:
            self.client.close()

        self.connected = False

    @staticmethod
    def swap_bytes_in_words(
        registers: list[int],
    ) -> list[int]:
        result = []

        for register in registers:
            high_byte = (
                register >> 8
            ) & 0xFF

            low_byte = (
                register
            ) & 0xFF

            result.append(
                (low_byte << 8)
                | high_byte
            )

        return result

    @classmethod
    def prepare_registers(
        cls,
        registers: list[int],
        byte_order: str,
        word_order: str,
    ) -> list[int]:
        prepared = list(registers)

        normalized_word_order = str(
            word_order or "normal"
        ).strip().lower()

        if normalized_word_order in {
            "swapped",
            "little",
            "reverse",
        }:
            prepared.reverse()

        normalized_byte_order = str(
            byte_order or "big"
        ).strip().lower()

        if normalized_byte_order in {
            "little",
            "swapped",
        }:
            prepared = cls.swap_bytes_in_words(
                prepared
            )

        return prepared

    @staticmethod
    def registers_to_bytes(
        registers: list[int],
    ) -> bytes:
        return b"".join(
            struct.pack(
                ">H",
                register & 0xFFFF,
            )
            for register in registers
        )

    @classmethod
    def decode_registers(
        cls,
        registers: list[int],
        data_type: str,
        byte_order: str,
        word_order: str,
    ) -> float:
        normalized_type = str(
            data_type
        ).strip().lower()

        prepared = cls.prepare_registers(
            registers=registers,
            byte_order=byte_order,
            word_order=word_order,
        )

        raw_bytes = cls.registers_to_bytes(
            prepared
        )

        if normalized_type in {
            "float",
            "float32",
            "real",
        }:
            if len(raw_bytes) < 4:
                raise ValueError(
                    "float32 requires two registers"
                )

            return float(
                struct.unpack(
                    ">f",
                    raw_bytes[:4],
                )[0]
            )

        if normalized_type in {
            "double",
            "float64",
        }:
            if len(raw_bytes) < 8:
                raise ValueError(
                    "float64 requires four registers"
                )

            return float(
                struct.unpack(
                    ">d",
                    raw_bytes[:8],
                )[0]
            )

        if normalized_type in {
            "int16",
            "short",
        }:
            if len(raw_bytes) < 2:
                raise ValueError(
                    "int16 requires one register"
                )

            return float(
                struct.unpack(
                    ">h",
                    raw_bytes[:2],
                )[0]
            )

        if normalized_type in {
            "uint16",
            "unsigned16",
            "word",
        }:
            if len(raw_bytes) < 2:
                raise ValueError(
                    "uint16 requires one register"
                )

            return float(
                struct.unpack(
                    ">H",
                    raw_bytes[:2],
                )[0]
            )

        if normalized_type in {
            "int32",
            "long",
        }:
            if len(raw_bytes) < 4:
                raise ValueError(
                    "int32 requires two registers"
                )

            return float(
                struct.unpack(
                    ">i",
                    raw_bytes[:4],
                )[0]
            )

        if normalized_type in {
            "uint32",
            "unsigned32",
            "dword",
        }:
            if len(raw_bytes) < 4:
                raise ValueError(
                    "uint32 requires two registers"
                )

            return float(
                struct.unpack(
                    ">I",
                    raw_bytes[:4],
                )[0]
            )

        raise ValueError(
            f"Unsupported data type: {data_type}"
        )

    def read_registers(
        self,
        tag: dict,
    ) -> list[int]:
        if (
            self.client is None
            or not self.connected
        ):
            raise ConnectionError(
                "Modbus RTU driver is not connected"
            )

        function_code = int(
            tag.get("function_code") or 3
        )

        address = int(
            tag["register_address"]
        )

        count = int(
            tag.get("register_count") or 1
        )

        slave_id = int(
            self.connection.get(
                "slave_id"
            ) or 1
        )

        if function_code == 3:
            result = (
                self.client
                .read_holding_registers(
                    address=address,
                    count=count,
                    device_id=slave_id,
                )
            )

        elif function_code == 4:
            result = (
                self.client
                .read_input_registers(
                    address=address,
                    count=count,
                    device_id=slave_id,
                )
            )

        else:
            raise ValueError(
                "Modbus RTU currently supports "
                "function codes 3 and 4"
            )

        if result.isError():
            raise RuntimeError(
                f"Modbus error: {result}"
            )

        return list(
            result.registers
        )

    def read_tag(
        self,
        tag: dict,
    ) -> dict:
        registers = self.read_registers(
            tag
        )

        decoded_value = self.decode_registers(
            registers=registers,
            data_type=tag.get(
                "data_type",
                "float32",
            ),
            byte_order=tag.get(
                "byte_order",
                "big",
            ),
            word_order=tag.get(
                "word_order",
                "swapped",
            ),
        )

        scale = float(
            tag.get("scale") or 1.0
        )

        offset = float(
            tag.get("offset_value") or 0.0
        )

        final_value = (
            decoded_value * scale
        ) + offset

        decimal_places = int(
            tag.get("decimal_places") or 0
        )

        final_value = round(
            final_value,
            decimal_places,
        )

        quality = "good"

        minimum_value = tag.get(
            "minimum_value"
        )

        maximum_value = tag.get(
            "maximum_value"
        )

        if (
            minimum_value is not None
            and final_value
            < float(minimum_value)
        ):
            quality = "out_of_range"

        if (
            maximum_value is not None
            and final_value
            > float(maximum_value)
        ):
            quality = "out_of_range"

        return {
            "value": final_value,
            "quality": quality,
            "raw": registers,
        }

    def health_status(self) -> dict:
        return {
            "connected": self.connected,
            "protocol": "modbus_rtu",
            "serial_port": (
                self.connection.get(
                    "serial_port"
                )
            ),
            "slave_id": (
                self.connection.get(
                    "slave_id"
                )
            ),
        }