"""Unprivileged client the GUI uses to talk to the FanFrame daemon."""
from __future__ import annotations

import socket

from . import protocol


class DaemonUnavailable(RuntimeError):
    """The daemon socket is missing or refused the connection."""


class Client:
    def __init__(self, socket_path: str = protocol.DEFAULT_SOCKET_PATH, timeout: float = 5.0):
        self._path = socket_path
        self._timeout = timeout

    def _request(self, message: dict) -> dict:
        buffer = b""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self._timeout)
                sock.connect(self._path)
                sock.sendall(protocol.encode_message(message))
                while b"\n" not in buffer:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            raise DaemonUnavailable(str(exc)) from exc
        line, _, _ = buffer.partition(b"\n")
        return protocol.decode_message(line)

    def status(self) -> dict:
        return self._request(protocol.make_request(protocol.CMD_STATUS))

    def set_duty(self, value: int, fan: int | None = None) -> dict:
        return self._request(
            protocol.make_request(
                protocol.CMD_SET_DUTY, value=protocol.clamp_duty(value), fan=fan
            )
        )

    def set_auto(self) -> dict:
        return self._request(protocol.make_request(protocol.CMD_AUTO))
