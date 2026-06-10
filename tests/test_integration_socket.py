"""End-to-end test of the real Unix-socket path: Client <-> Daemon <-> (fake EC).

No hardware and no root required — the EC is stubbed, the socket lives in a temp
dir, and the daemon runs in a background thread.
"""
import os
import threading
import time

import pytest

from fanframe import client as client_mod
from fanframe import daemon


class FakeEc:
    def __init__(self):
        self.duty_calls = []   # list of (value, fan)
        self.auto_calls = 0

    def set_duty(self, value, fan=None):
        self.duty_calls.append((value, fan))
        return value

    def set_auto(self):
        self.auto_calls += 1


def _wait_for_socket(path, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def running_daemon(tmp_path):
    socket_path = str(tmp_path / "fanframe.sock")
    fake = FakeEc()
    server = daemon.Daemon(socket_path=socket_path, controller=fake, socket_group=None)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    assert _wait_for_socket(socket_path), "daemon socket never appeared"
    try:
        yield socket_path, fake
    finally:
        server._stop.set()


def test_status_roundtrip(running_daemon):
    socket_path, _ = running_daemon
    client = client_mod.Client(socket_path=socket_path)
    assert client.status() == {"ok": True, "mode": "auto", "duties": {}}


def test_set_duty_per_fan_roundtrip(running_daemon):
    socket_path, fake = running_daemon
    client = client_mod.Client(socket_path=socket_path)
    assert client.set_duty(70, fan=0) == {"ok": True, "mode": "manual", "fan": 0, "duty": 70}
    assert fake.duty_calls == [(70, 0)]
    # duties come back string-keyed over the wire
    assert client.status() == {"ok": True, "mode": "manual", "duties": {"0": 70}}


def test_set_duty_all_fans_roundtrip(running_daemon):
    socket_path, fake = running_daemon
    client = client_mod.Client(socket_path=socket_path)
    assert client.set_duty(45) == {"ok": True, "mode": "manual", "fan": None, "duty": 45}
    assert fake.duty_calls == [(45, None)]


def test_auto_roundtrip(running_daemon):
    socket_path, fake = running_daemon
    client = client_mod.Client(socket_path=socket_path)
    client.set_duty(40, fan=1)
    assert client.set_auto() == {"ok": True, "mode": "auto", "duties": {}}
    assert fake.auto_calls == 1


def test_client_raises_when_daemon_absent(tmp_path):
    client = client_mod.Client(socket_path=str(tmp_path / "missing.sock"))
    with pytest.raises(client_mod.DaemonUnavailable):
        client.status()
