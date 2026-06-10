#!/usr/bin/env bash
# Remove FanFrame and restore automatic fan control.
#   sudo ./uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Esegui con sudo:  sudo ./uninstall.sh" >&2
  exit 1
fi

# Hand fans back to the EC before tearing anything down.
if [[ -x /usr/local/bin/framework_tool ]]; then
  /usr/local/bin/framework_tool --autofanctrl || true
  echo "==> Controllo automatico ripristinato"
fi

systemctl disable --now fanframed.service 2>/dev/null || true
rm -f /etc/systemd/system/fanframed.service
systemctl daemon-reload

rm -rf /opt/fanframe
rm -f /usr/local/bin/fanframe-gui
rm -f /usr/share/applications/fanframe.desktop
rm -f /run/fanframe.sock

echo "==> FanFrame rimosso."
echo "    (framework_tool in /usr/local/bin e' stato lasciato: rimuovilo a mano se vuoi.)"
