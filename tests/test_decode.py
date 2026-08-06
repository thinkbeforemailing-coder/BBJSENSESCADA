import struct

from dynamic_modbus_poller import (
    decode_registers,
    normalize_parity,
    normalize_stop_bits,
    prepare_registers,
    swap_bytes_in_words,
)


def float32_to_registers(value: float) -> list[int]:
    raw = struct.pack(">f", value)
    high, low = struct.unpack(">HH", raw)
    return [low, high]


def test_decode_float32_word_swapped():
    registers = float32_to_registers(49.95)

    value = decode_registers(
        registers=registers,
        data_type="float32",
        byte_order="big",
        word_order="swapped",
    )

    assert round(value, 2) == 49.95


def test_decode_uint16():
    value = decode_registers(
        registers=[1234],
        data_type="uint16",
        byte_order="big",
        word_order="normal",
    )

    assert value == 1234.0


def test_decode_int16_negative():
    value = decode_registers(
        registers=[0xFFFF],
        data_type="int16",
        byte_order="big",
        word_order="normal",
    )

    assert value == -1.0


def test_decode_unsupported_data_type_raises():
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


def test_decode_float32_requires_two_registers():
    try:
        decode_registers(
            registers=[1],
            data_type="float32",
            byte_order="big",
            word_order="normal",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_swap_bytes_in_words():
    assert swap_bytes_in_words([0x1234]) == [0x3412]


def test_prepare_registers_swapped_word_order_reverses():
    assert prepare_registers(
        registers=[1, 2],
        byte_order="big",
        word_order="swapped",
    ) == [2, 1]


def test_prepare_registers_normal_word_order_keeps_order():
    assert prepare_registers(
        registers=[1, 2],
        byte_order="big",
        word_order="normal",
    ) == [1, 2]


def test_normalize_parity_variants():
    assert normalize_parity("even") == "E"
    assert normalize_parity("Odd") == "O"
    assert normalize_parity(None) == "N"
    assert normalize_parity("garbage") == "N"


def test_normalize_stop_bits_variants():
    assert normalize_stop_bits(2) == 2
    assert normalize_stop_bits("2") == 2
    assert normalize_stop_bits(1) == 1
    assert normalize_stop_bits(None) == 1
    assert normalize_stop_bits("not a number") == 1
