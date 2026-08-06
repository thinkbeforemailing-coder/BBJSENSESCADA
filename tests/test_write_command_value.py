from unittest.mock import MagicMock

import pytest

from dynamic_modbus_poller import write_command_value


def make_client(is_error=False):
    client = MagicMock()
    result = MagicMock()
    result.isError.return_value = is_error
    client.write_register.return_value = result
    client.write_coil.return_value = result
    return client


def test_write_register_calls_client_with_correct_args():
    client = make_client()
    tag = {"register_address": 100, "function_code": 3}

    write_command_value(
        client=client,
        tag=tag,
        command_type="write_register",
        value=42,
        slave_id=2,
    )

    client.write_register.assert_called_once_with(
        address=100,
        value=42,
        device_id=2,
    )


def test_write_register_rejects_input_register_function_code_4():
    # function_code=4 means the tag is an input register, which is
    # read-only in the Modbus spec regardless of what a config claims
    # -- this must be rejected before any write attempt reaches the
    # wire, not just logged after the fact.
    client = make_client()
    tag = {"register_address": 100, "function_code": 4}

    with pytest.raises(ValueError, match="read-only"):
        write_command_value(
            client=client,
            tag=tag,
            command_type="write_register",
            value=42,
            slave_id=2,
        )

    client.write_register.assert_not_called()


def test_write_coil_calls_client_with_correct_args():
    client = make_client()
    tag = {"register_address": 5}

    write_command_value(
        client=client,
        tag=tag,
        command_type="write_coil",
        value=1,
        slave_id=3,
    )

    client.write_coil.assert_called_once_with(
        address=5,
        value=True,
        device_id=3,
    )


def test_unsupported_command_type_raises_and_writes_nothing():
    client = make_client()
    tag = {"register_address": 5, "function_code": 3}

    with pytest.raises(ValueError, match="Unsupported command type"):
        write_command_value(
            client=client,
            tag=tag,
            command_type="write_multiple_registers",
            value=1,
            slave_id=1,
        )

    client.write_register.assert_not_called()
    client.write_coil.assert_not_called()


def test_modbus_error_result_raises_runtime_error():
    client = make_client(is_error=True)
    tag = {"register_address": 5, "function_code": 3}

    with pytest.raises(RuntimeError, match="Modbus write error"):
        write_command_value(
            client=client,
            tag=tag,
            command_type="write_register",
            value=1,
            slave_id=1,
        )
