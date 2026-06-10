import subprocess

import pytest

from fanframe import ec


def _runner(record, returncode=0, stderr=""):
    def run(argv):
        record.append(list(argv))
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr=stderr)
    return run


def test_set_duty_all_fans_argv_and_clamps():
    calls = []
    controller = ec.EcController(tool_path="/x/framework_tool", runner=_runner(calls))
    assert controller.set_duty(150) == 100
    assert calls == [["/x/framework_tool", "--fansetduty", "100"]]


def test_set_duty_single_fan_argv():
    calls = []
    controller = ec.EcController(tool_path="/x/framework_tool", runner=_runner(calls))
    assert controller.set_duty(60, fan=1) == 60
    assert calls == [["/x/framework_tool", "--fansetduty", "1", "60"]]


def test_set_duty_single_fan_clamps():
    calls = []
    controller = ec.EcController(tool_path="/x/framework_tool", runner=_runner(calls))
    assert controller.set_duty(150, fan=2) == 100
    assert calls == [["/x/framework_tool", "--fansetduty", "2", "100"]]


def test_set_auto_all_fans_argv():
    calls = []
    controller = ec.EcController(tool_path="/x/framework_tool", runner=_runner(calls))
    controller.set_auto()
    assert calls == [["/x/framework_tool", "--autofanctrl"]]


def test_set_auto_single_fan_argv():
    calls = []
    controller = ec.EcController(tool_path="/x/framework_tool", runner=_runner(calls))
    controller.set_auto(fan=2)
    assert calls == [["/x/framework_tool", "--autofanctrl", "2"]]


def test_nonzero_exit_raises_ecerror():
    controller = ec.EcController(
        tool_path="/x/framework_tool", runner=_runner([], returncode=1, stderr="boom")
    )
    with pytest.raises(ec.EcError, match="boom"):
        controller.set_duty(50)


def test_missing_binary_raises_ecerror():
    def run(_argv):
        raise FileNotFoundError()

    controller = ec.EcController(tool_path="/nope/framework_tool", runner=run)
    with pytest.raises(ec.EcError, match="not found"):
        controller.set_auto()
