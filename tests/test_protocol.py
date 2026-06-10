import pytest

from fanframe import protocol


def test_clamp_duty_bounds():
    assert protocol.clamp_duty(-5) == 0
    assert protocol.clamp_duty(50) == 50
    assert protocol.clamp_duty(150) == 100


def test_encode_decode_roundtrip():
    message = {"cmd": protocol.CMD_SET_DUTY, "value": 60}
    line = protocol.encode_message(message)
    assert line.endswith(b"\n")
    assert protocol.decode_message(line) == message


def test_decode_rejects_non_object():
    with pytest.raises(ValueError):
        protocol.decode_message("[1, 2, 3]")


def test_decode_rejects_empty():
    with pytest.raises(ValueError):
        protocol.decode_message("   ")


def test_response_helpers():
    assert protocol.ok_response(mode="auto", duty=None) == {"ok": True, "mode": "auto", "duty": None}
    assert protocol.error_response("boom") == {"ok": False, "error": "boom"}
