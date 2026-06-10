"""Privileged fan control via the official Framework `framework_tool` CLI.

Only the daemon imports this module — it needs access to /dev/cros_ec (root).
Everything is a thin, validated wrapper around two operations so the privileged
surface stays minimal: set a duty cycle, or hand control back to the EC.

The duty argument form (`--fansetduty <pct>` for all fans) is verified on the
first real run; `set_duty` clamps to [0, 100] before the value ever reaches the
firmware.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

from . import protocol

DEFAULT_TOOL_PATH = "/usr/local/bin/framework_tool"
RUN_TIMEOUT_S = 10

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess"]


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )


class EcError(RuntimeError):
    """Raised when framework_tool is missing, times out, or returns non-zero."""


class EcController:
    def __init__(self, tool_path: str = DEFAULT_TOOL_PATH, runner: Runner | None = None):
        self._tool = tool_path
        self._run = runner or _default_runner

    def duty_argv(self, value: int, fan: int | None = None) -> list[str]:
        duty = str(protocol.clamp_duty(value))
        # framework_tool: one value sets all fans, `<index> <value>` sets one
        # (the EC fan index is 0-based: sysfs fan1 -> index 0).
        if fan is None:
            return [self._tool, "--fansetduty", duty]
        return [self._tool, "--fansetduty", str(int(fan)), duty]

    def auto_argv(self) -> list[str]:
        return [self._tool, "--autofanctrl"]

    def _execute(self, argv: Sequence[str]) -> str:
        try:
            result = self._run(argv)
        except FileNotFoundError as exc:
            raise EcError(f"framework_tool not found at {self._tool}") from exc
        except subprocess.TimeoutExpired as exc:
            raise EcError("framework_tool timed out") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise EcError(f"framework_tool failed: {detail or 'exit ' + str(result.returncode)}")
        return (result.stdout or "").strip()

    def set_duty(self, value: int, fan: int | None = None) -> int:
        duty = protocol.clamp_duty(value)
        self._execute(self.duty_argv(duty, fan))
        return duty

    def set_auto(self) -> None:
        self._execute(self.auto_argv())
