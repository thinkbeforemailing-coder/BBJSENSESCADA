import struct

from pymodbus.client import ModbusTcpClient

from drivers.base import BaseProtocolDriver


class ModbusTCPDriver(BaseProtocolDriver):
    """
    Universal Modbus TCP driver for BBJ Sense.

    Supported function codes:
    - 3: Holding Registers
    - 4: Input Registers

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

        self.client: ModbusTcpClient | None = None
        self.connected = False

    def validate_configuration(
        self,
    ) -> None:
        ip_address = self.connection.get(
            "ip_address"
        )

        if not ip_address:
            raise ValueError(
                "IP address is not configured"
            )

        port = self.connection.get(
            "tcp_port"
        )

        if port is None:
            raise ValueError(
                "TCP port is not configured"
            )

    def connect(self) -> bool:
        self.validate_configuration()

        self.client = ModbusTcpClient(
            host=str(
                self.connection.get(
                    "ip_address"
                )
            ),
            port=int(
                self.connection.get(
                    "tcp_port"
                ) or 502
            ),
            timeout=3,
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
        swapped = []

        for register in registers:
            high_byte = (
                register >> 8
            ) & 0xFF

            low_byte = register & 0xFF

            swapped.append(
                (low_byte << 8)
                | high_byte
            )

        return swapped

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
        prepared = cls.prepare_registers(
            registers=registers,
            byte_order=byte_order,
            word_order=word_order,
        )

        raw_bytes = cls.registers_to_bytes(
            prepared
        )

        normalized_type = str(
            data_type
        ).strip().lower()

        formats = {
            "float": (">f", 4),
            "float32": (">f", 4),
            "real": (">f", 4),

            "double": (">d", 8),
            "float64": (">d", 8),

            "int16": (">h", 2),
            "short": (">h", 2),

            "uint16": (">H", 2),
            "unsigned16": (">H", 2),
            "word": (">H", 2),

            "int32": (">i", 4),
            "long": (">i", 4),

            "uint32": (">I", 4),
            "unsigned32": (">I", 4),
            "dword": (">I", 4),
        }

        definition = formats.get(
            normalized_type
        )

        if definition is None:
            raise ValueError(
                f"Unsupported data type: {data_type}"
            )

        format_code, byte_count = definition

        if len(raw_bytes) < byte_count:
            raise ValueError(
                f"{data_type} requires "
                f"{byte_count // 2} register(s)"
            )

        return float(
            struct.unpack(
                format_code,
                raw_bytes[:byte_count],
            )[0]
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
                "Modbus TCP driver is not connected"
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

        unit_id = int(
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
                    device_id=unit_id,
                )
            )

        elif function_code == 4:
            result = (
                self.client
                .read_input_registers(
                    address=address,
                    count=count,
                    device_id=unit_id,
                )
            )

        else:
            raise ValueError(
                "Modbus TCP currently supports "
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
            "protocol": "modbus_tcp",
            "ip_address": self.connection.get(
                "ip_address"
            ),
            "tcp_port": self.connection.get(
                "tcp_port"
            ),
            "unit_id": self.connection.get(
                "slave_id"
            ),
        }