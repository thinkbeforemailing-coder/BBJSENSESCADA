import struct

import dynamic_modbus_poller
from diagnose_modbus import (
    decode_registers,
    format_tag_field,
    prepare_registers,
)


def float32_to_registers(value: float) -> list[int]:
    raw = struct.pack(">f", value)
    high, low = struct.unpack(">HH", raw)
    return [low, high]


def test_format_tag_field_handles_none():
    assert format_tag_field(None) == "?"


def test_format_tag_field_stringifies_value():
    assert format_tag_field(40157) == "40157"
    assert format_tag_field("Frequency") == "Frequency"


# diagnose_modbus.decode_registers()/prepare_registers() are a deliberate
# independent copy of dynamic_modbus_poller's versions (see that
# function's own docstring), kept in sync by hand rather than by import
# so this diagnostic tool has no dependency on BBJ_GATEWAY_KEY or the
# live poller. These parity tests are what would actually catch the two
# copies drifting.
def test_prepare_registers_matches_poller():
    cases = [
        ([1, 2, 3, 4], "big", "normal"),
        ([1, 2, 3, 4], "big", "swapped"),
        ([0x1234, 0x5678], "little", "normal"),
        ([0x1234, 0x5678], "swapped", "swapped"),
    ]

    for registers, byte_order, word_order in cases:
        assert prepare_registers(
            registers=list(registers),
            byte_order=byte_order,
            word_order=word_order,
        ) == dynamic_modbus_poller.prepare_registers(
            registers=list(registers),
            byte_order=byte_order,
            word_order=word_order,
        )


def test_decode_registers_matches_poller_float32():
    registers = float32_to_registers(49.95)

    assert decode_registers(
        registers=registers,
        data_type="float32",
        byte_order="big",
        word_order="swapped",
    ) == dynamic_modbus_poller.decode_registers(
        registers=registers,
        data_type="float32",
        byte_order="big",
        word_order="swapped",
    )


def test_decode_registers_matches_poller_uint16():
    assert decode_registers(
        registers=[1234],
        data_type="uint16",
        byte_order="big",
        word_order="normal",
    ) == dynamic_modbus_poller.decode_registers(
        registers=[1234],
        data_type="uint16",
        byte_order="big",
        word_order="normal",
    )


def test_decode_registers_matches_poller_int16_negative():
    assert decode_registers(
        registers=[0xFFFF],
        data_type="int16",
        byte_order="big",
        word_order="normal",
    ) == dynamic_modbus_poller.decode_registers(
        registers=[0xFFFF],
        data_type="int16",
        byte_order="big",
        word_order="normal",
    )


def test_decode_registers_matches_poller_int32():
    assert decode_registers(
        registers=[0x0001, 0x0000],
        data_type="int32",
        byte_order="big",
        word_order="normal",
    ) == dynamic_modbus_poller.decode_registers(
        registers=[0x0001, 0x0000],
        data_type="int32",
        byte_order="big",
        word_order="normal",
    )


def test_decode_registers_unsupported_type_raises():
    try:
        decode_registers(
            registers=[1, 2],
            data_type="not_a_real_type",
            byte_order="big",
            word_order="normal",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass
