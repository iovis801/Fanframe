from fanframe import daemon, ec


class FakeEc:
    def __init__(self):
        self.duty_calls = []   # list of (value, fan)
        self.auto_calls = []   # list of fan args (None == all)

    def set_duty(self, value, fan=None):
        self.duty_calls.append((value, fan))
        return value

    def set_auto(self, fan=None):
        self.auto_calls.append(fan)


def _make():
    fake = FakeEc()
    return daemon.Daemon(controller=fake), fake


def test_status_defaults_to_empty():
    server, _ = _make()
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {}}


def test_set_duty_per_fan_tracks_state():
    server, fake = _make()
    assert server.handle({"cmd": "set_duty", "value": 70, "fan": 0}) == {
        "ok": True, "fan": 0, "duty": 70
    }
    server.handle({"cmd": "set_duty", "value": 55, "fan": 2})
    assert fake.duty_calls == [(70, 0), (55, 2)]
    # status exposes string-keyed manual duties (JSON-safe)
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {"0": 70, "2": 55}}


def test_set_duty_all_fans_clamps_and_clears_state():
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 30, "fan": 1})
    response = server.handle({"cmd": "set_duty", "value": 150})
    assert response == {"ok": True, "fan": None, "duty": 100}
    assert fake.duty_calls[-1] == (100, None)
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {}}


def test_auto_single_fan_removes_only_that_fan():
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 70, "fan": 0})
    server.handle({"cmd": "set_duty", "value": 50, "fan": 1})
    assert server.handle({"cmd": "auto", "fan": 0}) == {"ok": True, "fan": 0}
    assert fake.auto_calls == [0]
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {"1": 50}}


def test_auto_all_fans_clears_state():
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 50, "fan": 1})
    assert server.handle({"cmd": "auto"}) == {"ok": True, "fan": None}
    assert fake.auto_calls == [None]
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {}}


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

    assert fake.auto_calls == [None]
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {}}


def test_failsafe_noop_when_all_auto(monkeypatch):
    server, fake = _make()

    def must_not_read(*_a, **_k):
        raise AssertionError("sensors read while no fan is manual")

    monkeypatch.setattr(daemon.sensors, "read_snapshot", must_not_read)
    server._failsafe_tick()
    assert fake.auto_calls == []


def test_failsafe_keeps_manual_when_cool(monkeypatch):
    server, fake = _make()
    server.handle({"cmd": "set_duty", "value": 30, "fan": 1})

    class CoolSnapshot:
        max_cpu_celsius = 55.0

    monkeypatch.setattr(daemon.sensors, "read_snapshot", lambda *a, **k: CoolSnapshot())
    server._failsafe_tick()
    assert fake.auto_calls == []
    assert server.handle({"cmd": "status"}) == {"ok": True, "fans": {"1": 30}}
