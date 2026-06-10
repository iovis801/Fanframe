"""GTK4 desktop window for FanFrame.

Sensor values are read directly from sysfs (no privileges); control commands go
to the privileged daemon over its Unix socket. The window itself never runs as
root. Run with: `fanframe-gui` or `python -m fanframe.gui.window`.

Each fan gets its own slider (EC index is 0-based: sysfs fan1 -> index 0) with
its live RPM shown next to it, plus one global button to hand control back to
the EC.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import client as client_mod  # noqa: E402
from .. import protocol, sensors  # noqa: E402

POLL_INTERVAL_MS = 1000
DUTY_DEBOUNCE_MS = 350
DUTY_MARKS = (0, 25, 50, 75, 100)


def ec_index(fan_name: str) -> int:
    """Map a sysfs fan name ('fan1') to its 0-based EC index (0)."""
    digits = "".join(ch for ch in fan_name if ch.isdigit())
    return int(digits) - 1 if digits else 0


class FanFrameWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, client: client_mod.Client):
        super().__init__(application=app, title="FanFrame — Framework Desktop")
        self._client = client
        self._temp_rows: dict[str, Gtk.Label] = {}
        self._rpm_labels: dict[str, Gtk.Label] = {}
        self._sliders: dict[str, Gtk.Scale] = {}
        self._suppress: set[str] = set()
        self._duty_timeouts: dict[str, int] = {}
        self._pending_duties: dict[int, int] = {}
        self.set_default_size(480, 520)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for setter in (root.set_margin_top, root.set_margin_bottom,
                       root.set_margin_start, root.set_margin_end):
            setter(20)
        self.set_child(root)

        self._temp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._fan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.append(_titled_frame("Temperature", self._temp_box))
        root.append(_titled_frame("Ventole (controllo manuale)", self._fan_box))

        auto_btn = Gtk.Button(label="Automatico (EC) — tutte le ventole")
        auto_btn.add_css_class("suggested-action")
        auto_btn.set_halign(Gtk.Align.START)
        auto_btn.connect("clicked", self._on_auto_clicked)
        root.append(auto_btn)

        self._status_label = Gtk.Label(xalign=0)
        self._status_label.add_css_class("dim-label")
        self._status_label.set_wrap(True)
        root.append(self._status_label)

        self._refresh_status()
        self._tick()
        GLib.timeout_add(POLL_INTERVAL_MS, self._tick)

    # ---- live polling -----------------------------------------------------
    def _tick(self) -> bool:
        try:
            snapshot = sensors.read_snapshot()
        except OSError:
            self._set_status("Sensori cros_ec non trovati.")
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
            self._rpm_labels[fan.name].set_text("ferma" if fan.rpm == 0 else f"{fan.rpm} RPM")

    def _ensure_fan_controls(self, fan_name: str) -> None:
        if fan_name in self._sliders:
            return
        caption = fan_name.replace("fan", "Ventola ")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(8)
        box.set_margin_end(8)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_label = Gtk.Label(label=caption, xalign=0)
        name_label.set_hexpand(True)
        name_label.add_css_class("heading")
        rpm_label = Gtk.Label(xalign=1)
        rpm_label.add_css_class("dim-label")
        header.append(name_label)
        header.append(rpm_label)
        box.append(header)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_hexpand(True)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        for mark in DUTY_MARKS:
            scale.add_mark(mark, Gtk.PositionType.BOTTOM, f"{mark}%")
        scale.connect("value-changed", self._on_slider_changed, fan_name)
        box.append(scale)

        self._rpm_labels[fan_name] = rpm_label
        self._sliders[fan_name] = scale
        self._fan_box.append(box)

        pending = self._pending_duties.get(ec_index(fan_name))
        if pending is not None:
            self._set_slider_silently(fan_name, pending)

    # ---- control callbacks ------------------------------------------------
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
        value = int(self._sliders[fan_name].get_value())
        caption = fan_name.replace("fan", "Ventola ")
        try:
            self._client.set_duty(value, fan=ec_index(fan_name))
            self._set_status(f"{caption}: {value}% — failsafe termico attivo.")
        except client_mod.DaemonUnavailable:
            self._set_status("Demone fanframed non attivo: impossibile impostare il duty.")
        return False

    def _on_auto_clicked(self, _button: Gtk.Button) -> None:
        try:
            self._client.set_auto()
            self._set_status("Controllo automatico dell'EC ripristinato (tutte le ventole).")
        except client_mod.DaemonUnavailable:
            self._set_status("Demone fanframed non attivo: impossibile cambiare modalità.")

    def _refresh_status(self) -> None:
        try:
            status = self._client.status()
        except client_mod.DaemonUnavailable:
            self._set_status("Demone fanframed non attivo — sola lettura.")
            return
        duties = status.get("duties") or {}
        self._pending_duties = {int(index): duty for index, duty in duties.items()}
        for fan_name in self._sliders:
            value = self._pending_duties.get(ec_index(fan_name))
            if value is not None:
                self._set_slider_silently(fan_name, value)
        if status.get("mode") == protocol.MODE_MANUAL and self._pending_duties:
            self._set_status("Modalità manuale attiva.")
        else:
            self._set_status("Automatico (EC).")

    def _set_slider_silently(self, fan_name: str, value: int) -> None:
        self._suppress.add(fan_name)
        self._sliders[fan_name].set_value(value)
        self._suppress.discard(fan_name)

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
