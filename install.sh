#!/usr/bin/env bash
# FanFrame installer — Framework Desktop fan control (manual + live readouts).
#
#   sudo ./install.sh
#
# Installs: framework_tool -> /usr/local/bin, sources -> /opt/fanframe,
# GUI launcher -> /usr/local/bin/fanframe-gui, root daemon -> systemd.
set -euo pipefail

SRC_DST=/opt/fanframe/src
SERVICE_DST=/etc/systemd/system/fanframed.service
TOOL_DST=/usr/local/bin/framework_tool
GUI_BIN=/usr/local/bin/fanframe-gui
DESKTOP_DST=/usr/share/applications/fanframe.desktop

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo:  sudo ./install.sh" >&2
  exit 1
fi

REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
  echo "Could not determine the non-root user. Run: sudo ./install.sh" >&2
  exit 1
fi
REAL_GROUP="$(id -gn "$REAL_USER")"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Target user: $REAL_USER (socket group: $REAL_GROUP)"

# 1) framework_tool ---------------------------------------------------------
if [[ ! -x "$TOOL_DST" ]]; then
  if [[ -x "$REAL_HOME/.local/bin/framework_tool" ]]; then
    install -m 0755 "$REAL_HOME/.local/bin/framework_tool" "$TOOL_DST"
    echo "==> framework_tool installed to $TOOL_DST"
  else
    echo "framework_tool not found. Put it in $TOOL_DST and re-run." >&2
    exit 1
  fi
else
  echo "==> framework_tool already present at $TOOL_DST"
fi

# 2) sources ----------------------------------------------------------------
rm -rf "$SRC_DST"
install -d -m 0755 "$SRC_DST/fanframe/gui"
install -m 0644 "$SCRIPT_DIR"/src/fanframe/*.py        "$SRC_DST/fanframe/"
install -m 0644 "$SCRIPT_DIR"/src/fanframe/gui/*.py    "$SRC_DST/fanframe/gui/"
echo "==> Sources installed to $SRC_DST"

# 3) GUI launcher (runs unprivileged) ---------------------------------------
cat > "$GUI_BIN" <<EOF
#!/usr/bin/env bash
exec env PYTHONPATH=$SRC_DST /usr/bin/python3 -m fanframe.gui.window "\$@"
EOF
chmod 0755 "$GUI_BIN"
echo "==> Launcher: $GUI_BIN"

# 4) application menu entry -------------------------------------------------
if [[ -f "$SCRIPT_DIR/desktop/fanframe.desktop" ]]; then
  install -m 0644 "$SCRIPT_DIR/desktop/fanframe.desktop" "$DESKTOP_DST"
  echo "==> Menu entry installed"
fi

# 5) systemd service --------------------------------------------------------
sed "s/__GROUP__/$REAL_GROUP/g" "$SCRIPT_DIR/systemd/fanframed.service" > "$SERVICE_DST"
chmod 0644 "$SERVICE_DST"
systemctl daemon-reload
systemctl enable fanframed.service
systemctl restart fanframed.service   # restart so code changes are picked up on re-install
echo "==> fanframed service started/restarted"

# 6) GUI dependencies -------------------------------------------------------
if ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk","4.0")' 2>/dev/null; then
  echo
  echo "WARNING: PyGObject/GTK4 are missing. Install them with:"
  echo "  sudo dnf install -y python3-gobject gtk4"
fi

echo
echo "Done. Launch the GUI with:  fanframe-gui   (or from your application menu)"
systemctl --no-pager --lines=0 status fanframed.service | sed -n '1,4p' || true
