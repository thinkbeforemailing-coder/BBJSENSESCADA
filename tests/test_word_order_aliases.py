import struct

import pytest

from dynamic_modbus_poller import decode_registers, is_word_swapped


@pytest.mark.parametrize(
    "word_order",
    [
        "swapped", "Swapped", "swap", "SWAP", "little", "reverse",
        "CDAB", "cdab", "little_word", "little-word", "Little Word",
        "Swap / Little Word", "swap/little word", "word_swap",
        "Word Swapped", "  swapped  ",
    ],
)
def test_swapped_aliases(word_order):
    assert is_word_swapped(word_order)


@pytest.mark.parametrize(
    "word_order",
    ["normal", "big", "ABCD", "", None, "badc", "dcba"],
)
def test_not_swapped(word_order):
    assert not is_word_swapped(word_order)


def test_cdab_decodes_float32():
    # Kartar ENERGY METER reading: float32, big-endian bytes, CDAB.
    registers = [13488, 19028]
    expected = struct.unpack(">f", struct.pack(">HH", 19028, 13488))[0]

    for word_order in ("swapped", "CDAB", "Swap / Little Word"):
        assert decode_registers(
            registers=registers,
            data_type="float32",
            byte_order="big",
            word_order=word_order,
        ) == expected
