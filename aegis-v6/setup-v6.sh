#!/bin/bash
# AegisOS v6 guest setup — run ONCE inside a booted v6 image as root
# (guest-apply upgrade path), or on a clean v6 image to re-apply the payload.
# Usage (from the payload dir): sudo bash setup-v6.sh
# Logs to /tmp/v6-setup.log. Idempotent where possible.
# Installs the Hyprland desktop + Quickshell shell + Plymouth theme +
# Chrome + aegis-tools from the payload itself.
set -x
exec > /tmp/v6-setup.log 2>&1
echo "=== AegisOS v6 setup start $(date -u) ==="
export DEBIAN_FRONTEND=noninteractive
# Payload dir (this script lives in the aegis-v6 folder).
P="$(cd "$(dirname "$0")" && pwd)"
SRC="$P/src"
apt-get update || echo "APT_UPDATE_FAILED (continuing; packages may already be present)"
apt-get install -y -t trixie-backports hyprland hyprlock hypridle hyprpaper hyprlauncher hyprcursor-util quickshell xdg-desktop-portal-hyprland \
  || echo "APT_INSTALL_PARTIAL (hyprland/backports packages may be missing; see log)"
# NOTE: no binary packages named `hyprcursor` (CLI is in hyprcursor-util)
# or `aquamarine` (only libaquamarine* libs, pulled in as Hyprland deps)
# exist in trixie-backports — naming them fails the whole apt run.
apt-get install -y --no-install-recommends auditd nftables \
  nmap sqlmap hydra john aircrack-ng nikto \
  foot grim slurp mako-notifier playerctl waybar xwayland \
  libgl1-mesa-dri plymouth plymouth-themes qml6-module-qtmultimedia \
  adwaita-icon-theme libxkbregistry0/trixie-backports \
  || echo "APT_INSTALL_PARTIAL (desktop/lab packages may be missing; see log)"
# NOTE: libxkbregistry0 must come from backports — the image ships
# backports libxkbcommon0 1.13.1, and the trixie libxkbregistry0 demands
# exactly 1.7.0-2. See build-image.sh for the same drift fix.
# Users (LAB ONLY credentials, documented, changeable, disabled by --stop)
id labweb 2>/dev/null || useradd -r -d /srv/labapp -s /usr/sbin/nologin labweb
id labuser 2>/dev/null || useradd -m -s /bin/bash labuser
echo 'labuser:lab123' | chpasswd
# Directories
mkdir -p /srv/labapp/plugins /srv/labapp/public /srv/labapp/flags /var/log/aegis-lab /var/lib/aegis-lab /etc/aegis-lab
cp "$SRC/labapp.py" /srv/labapp/labapp.py
cp "$SRC/server.py" /opt/aegis/server.py
cp "$SRC/v5-console.js" /opt/aegis/v5-console.js
cp "$SRC/aegis-labapp.service" "$SRC/aegis-ssh-lab.service" "$SRC/aegis.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/aegis.service /etc/systemd/system/aegis-labapp.service /etc/systemd/system/aegis-ssh-lab.service
# Lab units must NEVER start at boot: they have no [Install] section, and
# this preset explicitly disables them.
mkdir -p /etc/systemd/system-preset
printf 'disable aegis-labapp.service\ndisable aegis-ssh-lab.service\n' > /etc/systemd/system-preset/00-aegis-lab.preset
systemctl disable aegis-labapp.service aegis-ssh-lab.service 2>/dev/null || true
for h in aegis-gui aegis-autostart aegis-wallpaper aegis-lab aegis-ir aegis-fim aegis-lab-reset-flags aegis-update aegis-tools aegis-status aegis-logs aegis-net aegis-drivers; do
  if [ -f "$SRC/bin/$h" ]; then cp "$SRC/bin/$h" "/usr/local/bin/$h"; chmod 755 "/usr/local/bin/$h";
  elif [ -f "$P/bin/$h" ]; then cp "$P/bin/$h" "/usr/local/bin/$h"; chmod 755 "/usr/local/bin/$h"; fi
done
# Version file + updater state dirs
mkdir -p /var/lib/aegis/update /var/lib/aegis/backup
if [ -f "$SRC/VERSION" ]; then cp "$SRC/VERSION" /etc/aegis-version; else printf '6.0.0\n' > /etc/aegis-version; fi
chmod 644 /etc/aegis-version
# Saral 0.3.0
mkdir -p /usr/local/lib/saral/libs
cp "$SRC/saral/saral.py" /usr/local/bin/saral; chmod 755 /usr/local/bin/saral
cp -r "$SRC/saral/libs/." /usr/local/lib/saral/libs/
saral version || echo "SARAL_CHECK_FAILED"
# Hyprland desktop (config, Quickshell shell, wallpapers, swww)
mkdir -p /home/analyst/.config/hypr /home/analyst/.config/quickshell/aegis /etc/aegis/quickshell /usr/share/aegis/wallpapers /home/analyst/.config/aegis
# hyprland.conf + hypridle.conf: regenerate from the build script's copies
# if present in the payload (setup-v6.sh ships beside build-image.sh).
if [ -f "$P/build-image.sh" ]; then
  python3 - "$P/build-image.sh" <<'PY' || echo "HYPR_CONF_EXTRACT_FAILED"
import re, sys
s = open(sys.argv[1]).read()
m = re.search(r"sudo tee \"\$ROOTFS/home/analyst/.config/hypr/hyprland.conf\" >/dev/null <<'HYPR_EOF'\n(.*?)HYPR_EOF", s, re.S)
if m:
    open("/home/analyst/.config/hypr/hyprland.conf", "w").write(m.group(1))
    print("hyprland.conf written")
else:
    print("hyprland.conf block not found in build-image.sh")
PY
fi
cp "$SRC/hypr/hypridle.conf" /home/analyst/.config/hypr/hypridle.conf 2>/dev/null || true
if [ -d "$P/quickshell" ]; then
  cp -r "$P/quickshell/." /etc/aegis/quickshell/
  cp -r "$P/quickshell/." /home/analyst/.config/quickshell/aegis/
fi
if [ -f "$P/wallpaper-draft.png" ]; then
  cp "$P/wallpaper-draft.png" /usr/share/aegis/wallpapers/aegis-v6.png
  cp /usr/share/aegis/wallpapers/aegis-v6.png /home/analyst/.config/aegis/wallpaper.png
fi
if [ -f "$P/wallpaper-animated.gif" ]; then
  cp "$P/wallpaper-animated.gif" /usr/share/aegis/wallpapers/aegis-v6-animated.gif
fi
if [ -f "$P/swww-bin/swww" ]; then
  cp "$P/swww-bin/swww" /usr/local/bin/swww; chmod 755 /usr/local/bin/swww
fi
cp "$SRC/wayland/aegis-colours.py" /usr/local/lib/aegis-colours.py 2>/dev/null || true
chmod 755 /usr/local/lib/aegis-colours.py 2>/dev/null || true
ln -sf /usr/local/lib/aegis-colours.py /usr/local/bin/aegis-colours 2>/dev/null || true
# Plymouth theme (text-only; logo slot documented in README-v6.md)
if [ -d "$P/plymouth/aegis" ]; then
  mkdir -p /usr/share/plymouth/themes/aegis
  cp -r "$P/plymouth/aegis/." /usr/share/plymouth/themes/aegis/
  ln -sf /usr/share/aegis/logo.png /usr/share/plymouth/themes/aegis/logo.png
  plymouth-set-default-theme aegis 2>/dev/null || echo "PLYMOUTH_THEME_FAILED"
  update-initramfs -u 2>/dev/null || echo "INITRAMFS_REBUILD_FAILED"
fi
# Chrome (download at setup time; needs network)
if ! command -v google-chrome >/dev/null 2>&1; then
  curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/google-chrome.deb \
    && apt-get install -y /tmp/google-chrome.deb \
    && rm -f /tmp/google-chrome.deb \
    || echo "CHROME_INSTALL_FAILED (needs network; install later with apt)"
fi
if [ -f /usr/share/applications/google-chrome.desktop ]; then
  sed -i 's|^Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable --ozone-platform-hint=auto|' /usr/share/applications/google-chrome.desktop
fi
# Console wiring: add v5-console.js after app.js if not present
python3 - <<'PY'
p="/opt/aegis/index.html"
try:
    s=open(p).read()
    if "v5-console.js" not in s:
        s=s.replace("</body>", '<script src="v5-console.js"></script>\n</body>')
        open(p,"w").write(s)
        print("v5-console.js injected into index.html")
except Exception as e:
    print("index.html inject failed:", e)
PY
# Frontend files (only if the payload carries them)
if [ -f "$SRC/frontend/index.html" ]; then
  cp "$SRC/frontend/index.html" "$SRC/frontend/app.js" "$SRC/frontend/style.css" /opt/aegis/ 2>/dev/null || true
  cp -r "$SRC/frontend/apps" "$SRC/frontend/aegis" /opt/aegis/ 2>/dev/null || true
  cp "$SRC/v5-console.js" /opt/aegis/v5-console.js
fi
# Ownership / permissions
chown -R labweb:labweb /srv/labapp
chmod 755 /srv/labapp
chmod 700 /srv/labapp/flags 2>/dev/null || true
chown -R analyst:analyst /home/analyst 2>/dev/null || true
chmod 755 /usr/share/aegis /usr/share/aegis/wallpapers /usr/local/lib/saral /usr/local/lib/saral/libs /etc/aegis/quickshell 2>/dev/null || true
# SSH host keys
ssh-keygen -A 2>/dev/null || true
mkdir -p /var/log/aegis-lab
chown labweb:labweb /var/log/aegis-lab 2>/dev/null || true
chmod 755 /var/log/aegis-lab 2>/dev/null || true
# Auditd rules
cat > /etc/audit/rules.d/aegis-lab.rules <<'EOF'
-w /srv/labapp -p wa -k aegis_lab
-w /home/labuser -p wa -k aegis_labuser
-w /etc/aegis-lab -p wa -k aegis_labstate
EOF
systemctl restart auditd 2>/dev/null || systemctl start auditd 2>/dev/null || echo "AUDITD_START_FAILED"
augenrules --load 2>/dev/null || auditctl -R /etc/audit/rules.d/aegis-lab.rules 2>/dev/null || echo "AUDIT_RULES_LOAD_FAILED"
# Default state: LAB OFF
printf 'disabled\n' > /etc/aegis-lab/state
rm -f /etc/aegis-lab/env
systemctl daemon-reload
systemctl enable aegis.service 2>/dev/null || true
systemctl restart aegis.service
# Flag 2 + FIM manifest (labapp creates DB/flag3 on first start)
aegis-lab-reset-flags || echo "FLAG2_FAILED"
printf 'SECUREOS_BIND_IP=127.0.0.1\n' > /etc/aegis-lab/env
systemctl restart aegis-labapp.service || echo "LABAPP_FIRST_START_FAILED"
sleep 3
curl -s http://127.0.0.1:8080/ | head -c 300; echo
systemctl stop aegis-labapp.service
rm -f /etc/aegis-lab/env
chown labweb:labweb /srv/labapp/lab.db /srv/labapp/flags/flag3.txt 2>/dev/null || true
chmod 600 /srv/labapp/lab.db /srv/labapp/flags/flag3.txt 2>/dev/null || true
aegis-fim --init || echo "FIM_INIT_FAILED"
curl -s http://127.0.0.1:8000/api/health | head -c 500; echo
echo "=== AegisOS v6 setup done $(date -u) ==="
ls -l /srv/labapp/ /usr/local/bin/aegis-* /etc/systemd/system/aegis-*.service
