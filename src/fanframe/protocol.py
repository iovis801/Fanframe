"""Wire protocol shared between the FanFrame daemon and its GUI client.

Newline-delimited JSON over a Unix domain socket: each request and each response
is a single JSON object on one line. Keeping this tiny and explicit is the whole
point — the daemon's surface is only what is described here.
"""
from __future__ import annotations

import json
from typing import Any

# Socket lives directly in /run (tmpfs, cleared on reboot). The file itself is
# locked down to a trusted group by the daemon; /run stays world-traversable.
DEFAULT_SOCKET_PATH = "/run/fanframe.sock"

DUTY_MIN = 0
DUTY_MAX = 100

CMD_STATUS = "status"
CMD_SET_DUTY = "set_duty"
CMD_AUTO = "auto"

MODE_AUTO = "auto"
MODE_MANUAL = "manual"


def clamp_duty(value: int) -> int:
    """Clamp a duty-cycle percentage into the valid [0, 100] range."""
    return max(DUTY_MIN, min(DUTY_MAX, int(value)))


def encode_message(obj: dict[str, Any]) -> bytes:
    """Serialize a message to one newline-terminated UTF-8 line."""
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(line: bytes | str) -> dict[str, Any]:
    """Parse one protocol line into a dict. Raises ValueError on bad input."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    if not line:
        raise ValueError("empty message")
    obj = json.loads(line)
    if not isinstance(obj, dict):
        raise ValueError("message must be a JSON object")
    return obj


def make_request(cmd: str, **fields: Any) -> dict[str, Any]:
    return {"cmd": cmd, **fields}


def ok_response(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def error_response(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}
