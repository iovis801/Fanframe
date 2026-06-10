# FanFrame

Manual fan control with live temperature and RPM readouts for the **Framework
Desktop** (AMD Ryzen AI MAX), on Linux. A small GTK4 app with a per-fan slider,
backed by a minimal privileged daemon.

## Why this exists

The Framework Desktop's fans are driven by a Chromium-style embedded controller
(`cros_ec`), not a standard Super I/O chip. The kernel exposes fan **readings**
under `/sys/class/hwmon`, but there are **no writable PWM nodes** — so tools like
CoolerControl or `lm-sensors` can only *read* the fans, never set them. The only
way to control the fans is through the embedded controller via Framework's
official `framework_tool`.

FanFrame wraps that in a desktop GUI with a safe privilege model.

## Features

- **Per-fan sliders** (0–100% duty), each showing that fan's live RPM.
- **Per-fan Auto toggle** — switch any single fan back to EC control. When a fan
  is automatic its slider is disabled (greyed out) and the Auto button is
  pressed, so the current mode is always obvious. A global button puts every fan
  back to automatic at once.
- **Renamable fans** — click a fan's name to rename it (e.g. "CPU", "Intake").
  Names are saved per user under `~/.config/fanframe/labels.json`.
- **Live readouts** of all `cros_ec` temperatures and fan speeds, refreshed once
  a second straight from the kernel.
- **Thermal failsafe**: while any fan is in manual mode, the daemon restores
  automatic control if a CPU sensor crosses a critical threshold (default 92 °C).
- **GUI never runs as root.** The only privileged code is a tiny daemon exposing
  status/set_duty/auto over a group-restricted Unix socket.

## Architecture

```
GUI (GTK4, unprivileged)
  |- reads temps/RPM directly from sysfs (cros_ec hwmon)
  '- sends set_duty / auto  --unix socket-->  fanframed (root)
                                               |- framework_tool --fansetduty / --autofanctrl
                                               '- thermal failsafe (manual + too hot -> auto)
```

The embedded-controller fan index is 0-based, so sysfs `fan1` ("Ventola 1") maps
to `framework_tool --fansetduty 0 <pct>`.

## Requirements

- A Framework Desktop (or another Framework device whose fans are exposed via
  `cros_ec`). Developed and tested on the Ryzen AI MAX Desktop, Fedora 43.
- `systemd`, Python 3.11+, GTK 4 + PyGObject.
- Framework's `framework_tool` binary
  ([FrameworkComputer/framework-system](https://github.com/FrameworkComputer/framework-system/releases)).

```bash
# Fedora: GUI dependencies
sudo dnf install -y python3-gobject gtk4

# Get framework_tool (official release binary) into your PATH
mkdir -p ~/.local/bin
curl -fsSL -o ~/.local/bin/framework_tool \
  https://github.com/FrameworkComputer/framework-system/releases/latest/download/framework_tool
chmod +x ~/.local/bin/framework_tool
```

## Install

```bash
git clone https://github.com/iovis801/Fanframe.git
cd Fanframe
sudo ./install.sh
fanframe-gui          # or launch "FanFrame" from your application menu
```

`install.sh` copies `framework_tool` to `/usr/local/bin` (if not already there),
installs the sources to `/opt/fanframe`, adds the `fanframe-gui` launcher, and
enables the `fanframed` systemd service. The control socket is restricted to your
login group.

## Usage

- Drag a fan's slider to set its duty; it is applied ~350 ms after you stop. The
  RPM next to each slider confirms which physical fan responds.
- Press a fan's **Auto** toggle to hand just that fan back to the EC (its slider
  greys out). Use **All fans: automatic (EC)** to reset every fan at once.
- Click a fan's name to rename it; the name persists across launches.
- The panels keep updating even if the daemon is stopped (reads need no daemon).

## Safety

Manual duty does **not** persist across reboot or suspend — the EC reverts to
automatic. While in manual mode the failsafe forces automatic control if the CPU
gets too hot, but a fan controller is still a foot-gun: don't pin a low duty
under sustained load and walk away. Tune the trip point with `FANFRAME_CRITICAL_C`.

## Configuration

Set in `/etc/systemd/system/fanframed.service` (`Environment=...`):

| Variable | Default | Meaning |
|---|---|---|
| `FANFRAME_SOCKET` | `/run/fanframe.sock` | control socket path |
| `FANFRAME_GROUP` | your login group | group allowed to drive the fans |
| `FANFRAME_TOOL` | `/usr/local/bin/framework_tool` | EC CLI path |
| `FANFRAME_CRITICAL_C` | `92` | failsafe trip temperature (°C) |

After edits: `sudo systemctl daemon-reload && sudo systemctl restart fanframed`.

## Uninstall

```bash
sudo ./uninstall.sh   # restores automatic fan control, then removes everything
```

## Development

```bash
python3 -m pytest                  # unit + socket integration tests
python3 -m pytest --cov=fanframe   # coverage (GUI excluded — verified by running it)
```

The logic modules are unit-tested at ~87%; the GTK UI is validated by running
it. The `--fansetduty <index> <pct>` form is what `framework_tool` exposes for
per-fan control; if a future firmware changes the indexing, adjust
`EcController` in `src/fanframe/ec.py`.

## Contributing

Issues and pull requests are welcome. This is a small, focused tool — keep
changes minimal and the privilege boundary (GUI unprivileged, daemon tiny) intact.

## License

[MIT](LICENSE) — free for anyone to use, modify, and distribute.

## Disclaimer

This is an unofficial community tool, not affiliated with Framework Computer Inc.
It controls cooling hardware; use it at your own risk.
