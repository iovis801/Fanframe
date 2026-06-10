"""GTK4 desktop window for FanFrame.

Sensor values are read directly from sysfs (no privileges); control commands go
to the privileged daemon over its Unix socket. The window itself never runs as
root. Run with: `fanframe-gui` or `python -m fanframe.gui.window`.

Each fan has an editable name, its live RPM, an Auto toggle, and a duty slider.
When a fan is in automatic mode its slider is disabled (greyed out) and the Auto
toggle is pressed, so the current mode is always visible at a glance. The EC fan
index is 0-based, so sysfs `fan1` maps to `--fansetduty 0 <pct>`.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import client as client_mod  # noqa: E402
from .. import config, sensors  # noqa: E402

POLL_INTERVAL_MS = 1000
DUTY_DEBOUNCE_MS = 350
DUTY_MARKS = (0, 25, 50, 75, 100)
DAEMON_DOWN = "fanframed daemon is not running — control unavailable."


def ec_index(fan_name: str) -> int:
    """Map a sysfs fan name ('fan1') to its 0-based EC index (0)."""
    digits = "".join(ch for ch in fan_name if ch.isdigit())
    return int(digits) - 1 if digits else 0


def default_name(fan_name: str) -> str:
    digits = "".join(ch for ch in fan_name if ch.isdigit())
    return f"Fan {digits}" if digits else fan_name


class FanFrameWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, client: client_mod.Client):
        super().__init__(application=app, title="FanFrame — Framework Desktop")
        self._client = client
        self._labels = config.load_labels()
        self._temp_rows: dict[str, Gtk.Label] = {}
        self._rpm_labels: dict[str, Gtk.Label] = {}
        self._name_widgets: dict[str, Gtk.EditableLabel] = {}
        self._toggles: dict[str, Gtk.ToggleButton] = {}
        self._sliders: dict[str, Gtk.Scale] = {}
        self._suppress: set[str] = set()
        self._duty_timeouts: dict[str, int] = {}
        self._status_fans: dict[int, int] = {}
        self.set_default_size(500, 560)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for setter in (root.set_margin_top, root.set_margin_bottom,
                       root.set_margin_start, root.set_margin_end):
            setter(20)
        self.set_child(root)

        self._temp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._fan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.append(_titled_frame("Temperatures", self._temp_box))
        root.append(_titled_frame("Fans", self._fan_box))

        all_auto = Gtk.Button(label="All fans: automatic (EC)")
        all_auto.add_css_class("suggested-action")
        all_auto.set_halign(Gtk.Align.START)
        all_auto.connect("clicked", self._on_all_auto)
        root.append(all_auto)

        self._status_label = Gtk.Label(xalign=0)
        self._status_label.add_css_class("dim-label")
        self._status_label.set_wrap(True)
        root.append(self._status_label)

        self._load_status()
        self._tick()
        GLib.timeout_add(POLL_INTERVAL_MS, self._tick)

    # ---- live polling -----------------------------------------------------
    def _tick(self) -> bool:
        try:
            snapshot = sensors.read_snapshot()
        except OSError:
            self._set_status("cros_ec sensors not found.")
            return True
        self._update_temps(snapshot)
        self._update_fans(snapshot)
        return True

    def _update_temps(self, snapshot: sensors.SensorSnapshot) -> None:
        for temp in snapshot.temps:
            label = self._temp_rows.get(temp.name)
            if label is None:
                row, label = _kv_row(temp.label)
                self._temp_rows[temp.name] = label
                self._temp_box.append(row)
            label.set_text(f"{temp.celsius:.1f} °C")

    def _update_fans(self, snapshot: sensors.SensorSnapshot) -> None:
        for fan in snapshot.fans:
            self._ensure_fan_controls(fan.name)
            self._rpm_labels[fan.name].set_text("stopped" if fan.rpm == 0 else f"{fan.rpm} RPM")

    def _ensure_fan_controls(self, fan_name: str) -> None:
        if fan_name in self._sliders:
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_widget = Gtk.EditableLabel(text=self._labels.get(fan_name) or default_name(fan_name))
        name_widget.set_hexpand(True)
        name_widget.add_css_class("heading")
        name_widget.set_tooltip_text("Click to rename this fan")
        name_widget.connect("notify::editing", self._on_name_editing, fan_name)
        rpm_label = Gtk.Label(xalign=1)
        rpm_label.add_css_class("dim-label")
        toggle = Gtk.ToggleButton(label="Auto")
        toggle.set_tooltip_text("Automatic control for this fan")
        toggle.connect("toggled", self._on_toggle, fan_name)
        header.append(name_widget)
        header.append(rpm_label)
        header.append(toggle)
        box.append(header)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_hexpand(True)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        for mark in DUTY_MARKS:
            scale.add_mark(mark, Gtk.PositionType.BOTTOM, f"{mark}%")
        scale.connect("value-changed", self._on_slider_changed, fan_name)
        box.append(scale)

        self._name_widgets[fan_name] = name_widget
        self._rpm_labels[fan_name] = rpm_label
        self._toggles[fan_name] = toggle
        self._sliders[fan_name] = scale
        self._fan_box.append(box)

        manual_duty = self._status_fans.get(ec_index(fan_name))
        if manual_duty is None:
            self._apply_mode(fan_name, auto=True)
        else:
            self._apply_mode(fan_name, auto=False, duty=manual_duty)

    # ---- mode helpers -----------------------------------------------------
    def _apply_mode(self, fan_name: str, auto: bool, duty: int | None = None) -> None:
        self._suppress.add(fan_name)
        self._toggles[fan_name].set_active(auto)
        self._sliders[fan_name].set_sensitive(not auto)
        if duty is not None:
            self._sliders[fan_name].set_value(duty)
        self._suppress.discard(fan_name)

    def _display(self, fan_name: str) -> str:
        return self._labels.get(fan_name) or default_name(fan_name)

    # ---- control callbacks ------------------------------------------------
    def _on_toggle(self, toggle: Gtk.ToggleButton, fan_name: str) -> None:
        if fan_name in self._suppress:
            return
        if toggle.get_active():
            self._command_auto(fan_name)
        else:
            self._command_manual(fan_name, int(self._sliders[fan_name].get_value()))

    def _on_slider_changed(self, _scale: Gtk.Scale, fan_name: str) -> None:
        if fan_name in self._suppress:
            return
        existing = self._duty_timeouts.pop(fan_name, None)
        if existing is not None:
            GLib.source_remove(existing)
        self._duty_timeouts[fan_name] = GLib.timeout_add(
            DUTY_DEBOUNCE_MS, self._commit_duty, fan_name
        )

    def _commit_duty(self, fan_name: str) -> bool:
        self._duty_timeouts.pop(fan_name, None)
        self._command_manual(fan_name, int(self._sliders[fan_name].get_value()))
        return False

    def _command_manual(self, fan_name: str, value: int) -> None:
        try:
            self._client.set_duty(value, fan=ec_index(fan_name))
        except client_mod.DaemonUnavailable:
            self._set_status(DAEMON_DOWN)
            return
        self._apply_mode(fan_name, auto=False)
        self._set_status(f"{self._display(fan_name)}: {value}% (manual) — failsafe active.")

    def _command_auto(self, fan_name: str) -> None:
        try:
            self._client.set_auto(fan=ec_index(fan_name))
        except client_mod.DaemonUnavailable:
            self._set_status(DAEMON_DOWN)
            return
        self._apply_mode(fan_name, auto=True)
        self._set_status(f"{self._display(fan_name)}: automatic (EC).")

    def _on_all_auto(self, _button: Gtk.Button) -> None:
        try:
            self._client.set_auto(None)
        except client_mod.DaemonUnavailable:
            self._set_status(DAEMON_DOWN)
            return
        for fan_name in self._sliders:
            self._apply_mode(fan_name, auto=True)
        self._set_status("All fans: automatic (EC).")

    # ---- rename -----------------------------------------------------------
    def _on_name_editing(self, widget: Gtk.EditableLabel, _pspec, fan_name: str) -> None:
        if widget.get_property("editing"):
            return  # editing just started
        text = widget.get_text().strip()
        if not text:
            text = default_name(fan_name)
            self._suppress.add(fan_name)
            widget.set_text(text)
            self._suppress.discard(fan_name)
        self._labels[fan_name] = text
        try:
            config.save_labels(self._labels)
        except OSError:
            self._set_status("Could not save fan name.")

    # ---- status -----------------------------------------------------------
    def _load_status(self) -> None:
        try:
            status = self._client.status()
        except client_mod.DaemonUnavailable:
            self._set_status(DAEMON_DOWN + " (sensors still update)")
            return
        fans = status.get("fans") or {}
        self._status_fans = {int(index): duty for index, duty in fans.items()}

    def _set_status(self, text: str) -> None:
        self._status_label.set_text(text)


def _titled_frame(title: str, child: Gtk.Widget) -> Gtk.Frame:
    frame = Gtk.Frame(label=title)
    child.set_margin_top(6)
    child.set_margin_bottom(6)
    frame.set_child(child)
    return frame


def _kv_row(caption: str) -> tuple[Gtk.Box, Gtk.Label]:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.set_margin_start(8)
    row.set_margin_end(8)
    key = Gtk.Label(label=caption, xalign=0)
    key.set_hexpand(True)
    value = Gtk.Label(xalign=1)
    row.append(key)
    row.append(value)
    return row, value


class FanFrameApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="dev.fanframe.Gui")
        self._client = client_mod.Client()

    def do_activate(self) -> None:
        window = self.get_active_window() or FanFrameWindow(self, self._client)
        window.present()


def main() -> int:
    return FanFrameApp().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
