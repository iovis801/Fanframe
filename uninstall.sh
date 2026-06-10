#!/usr/bin/env bash
# Remove FanFrame and restore automatic fan control.
#   sudo ./uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo:  sudo ./uninstall.sh" >&2
  exit 1
fi

# Hand fans back to the EC before tearing anything down.
if [[ -x /usr/local/bin/framework_tool ]]; then
  /usr/local/bin/framework_tool --autofanctrl || true
  echo "==> Automatic fan control restored"
fi

systemctl disable --now fanframed.service 2>/dev/null || true
rm -f /etc/systemd/system/fanframed.service
systemctl daemon-reload

rm -rf /opt/fanframe
rm -f /usr/local/bin/fanframe-gui
rm -f /usr/share/applications/fanframe.desktop
rm -f /run/fanframe.sock

echo "==> FanFrame removed."
echo "    (framework_tool in /usr/local/bin was left in place; remove it manually if you want.)"
