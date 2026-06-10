"""Read Framework Desktop temperatures and fan speeds from the cros_ec hwmon.

Reading is unprivileged: the kernel exposes everything we need under
/sys/class/hwmon. Writing fan duty is NOT possible here (the cros_ec hwmon has
no pwm nodes), which is exactly why control goes through the daemon instead.

hwmon indices are not stable across boots, so we always locate the device by
its `name` ("cros_ec") rather than a fixed hwmonN path.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

HWMON_ROOT = "/sys/class/hwmon"
CROS_EC_NAME = "cros_ec"


@dataclass(frozen=True)
class TempReading:
    name: str        # raw sysfs base, e.g. "temp4"
    label: str       # human label, e.g. "cpu@4c"
    celsius: float


@dataclass(frozen=True)
class FanReading:
    name: str        # e.g. "fan1"
    rpm: int


@dataclass(frozen=True)
class SensorSnapshot:
    temps: tuple[TempReading, ...]
    fans: tuple[FanReading, ...]

    @property
    def max_cpu_celsius(self) -> float | None:
        """Hottest CPU-labelled sensor, used by the daemon's thermal failsafe."""
        cpu = [t.celsius for t in self.temps if "cpu" in t.label.lower()]
        return max(cpu) if cpu else None


def _read_first_line(path: str) -> str | None:
    try:
        with open(path, "r") as handle:
            return handle.readline().strip()
    except OSError:
        return None


def find_cros_ec_hwmon(root: str = HWMON_ROOT) -> str | None:
    """Return the hwmon directory whose name is 'cros_ec', or None if absent."""
    for hwmon in sorted(glob.glob(os.path.join(root, "hwmon*"))):
        if _read_first_line(os.path.join(hwmon, "name")) == CROS_EC_NAME:
            return hwmon
    return None


def _read_int(path: str) -> int | None:
    raw = _read_first_line(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_temps(hwmon: str) -> tuple[TempReading, ...]:
    out: list[TempReading] = []
    for inp in sorted(glob.glob(os.path.join(hwmon, "temp*_input"))):
        base = inp[: -len("_input")]
        milli = _read_int(inp)
        if milli is None:
            continue
        label = _read_first_line(base + "_label") or os.path.basename(base)
        out.append(TempReading(os.path.basename(base), label, milli / 1000.0))
    return tuple(out)


def _read_fans(hwmon: str) -> tuple[FanReading, ...]:
    out: list[FanReading] = []
    for inp in sorted(glob.glob(os.path.join(hwmon, "fan*_input"))):
        base = inp[: -len("_input")]
        rpm = _read_int(inp)
        if rpm is None:
            continue
        out.append(FanReading(os.path.basename(base), rpm))
    return tuple(out)


def read_snapshot(root: str = HWMON_ROOT) -> SensorSnapshot:
    """Read all temps and fans. Raises FileNotFoundError if cros_ec is absent."""
    hwmon = find_cros_ec_hwmon(root)
    if hwmon is None:
        raise FileNotFoundError(f"cros_ec hwmon not found under {root}")
    return SensorSnapshot(_read_temps(hwmon), _read_fans(hwmon))
