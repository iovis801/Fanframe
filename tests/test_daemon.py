from fanframe import daemon, ec


class FakeEc:
    def __init__(self):
        self.duty_calls = []   # list of (value, fan)
        self.auto_calls = 0

    def set_duty(self, value, fan=None):
        self.duty_calls.append((value, fan))
        return value

    def set_auto(self):
        self.auto_calls += 1


def _make():
    fake = FakeEc()
    return daemon.Daemon(controller=fake), fake


def test_status_defaults_to_auto():
    server, _ = _make()
    assert server.handle({"cmd": "status"}) == {"ok": True, "mode": "auto", "duties": {}}


def test_set_duty_all_fans_clamps_and_clears_per_fan_state():
    server, fake = _make()
    response = server.handle({"cmd": "set_duty", "value": 150})
    assert response == {"ok": True, "mode": "manual", "fan": None, "duty": 100}
    assert fake.duty_calls == [(100, None)]
    assert server.handle({"cmd": "status"}) == {"ok": True, "mode": "manual", "duties": {}}


def test_set_duty_per_fan_tracks_state():
    server, fake = _make()
    assert server.handle({"cmd": "set_duty", "value": 70, "fan": 0}) == {
        "ok": True, "mode": "manual", "fan": 0, "duty": 70
    }
    server.handle({"cmd": "set_duty", "value": 55, "fan": 2})
    assert fake.duty_calls == [(70, 0), (55, 2)]
    # status exposes string-keyed duties (JSON-safe)
    assert server.handle({"cmd": "status"}) == {
        "ok": True, "mode": "manual", "duties": {"0": 70, "2": 55}
    }


def test_auto_resets_state():
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 50, "fan": 1})
    assert server.handle({"cmd": "auto"}) == {"ok": True, "mode": "auto", "duties": {}}
    assert fake.auto_calls == 1


def test_unknown_command_is_error():
    server, _ = _make()
    assert server.handle({"cmd": "nope"})["ok"] is False


def test_ec_error_is_reported_not_raised():
    class Boom(FakeEc):
        def set_duty(self, value, fan=None):
            raise ec.EcError("device busy")

    server = daemon.Daemon(controller=Boom())
    response = server.handle({"cmd": "set_duty", "value": 50, "fan": 0})
    assert response["ok"] is False and "device busy" in response["error"]


def test_failsafe_restores_auto_when_too_hot(monkeypatch):
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 20, "fan": 0})

    class HotSnapshot:
        max_cpu_celsius = 99.0

    monkeypatch.setattr(daemon.sensors, "read_snapshot", lambda *a, **k: HotSnapshot())
    server._failsafe_tick()

    assert fake.auto_calls == 1
    assert server.handle({"cmd": "status"})["mode"] == "auto"


def test_failsafe_noop_when_already_auto(monkeypatch):
    server, fake = _make()

    def must_not_read(*_a, **_k):
        raise AssertionError("sensors read while in auto mode")

    monkeypatch.setattr(daemon.sensors, "read_snapshot", must_not_read)
    server._failsafe_tick()
    assert fake.auto_calls == 0


def test_failsafe_keeps_manual_when_cool(monkeypatch):
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 30, "fan": 1})

    class CoolSnapshot:
        max_cpu_celsius = 55.0

    monkeypatch.setattr(daemon.sensors, "read_snapshot", lambda *a, **k: CoolSnapshot())
    server._failsafe_tick()
    assert fake.auto_calls == 0
    assert server.handle({"cmd": "status"})["mode"] == "manual"
