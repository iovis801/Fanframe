"""FanFrame — manual fan control + live readouts for the Framework Desktop.

The package is split into an unprivileged side (sensor reading + GUI) and a
single privileged daemon. Only the daemon ever touches the embedded controller.
"""

__version__ = "0.1.0"
