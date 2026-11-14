#!/bin/bash
# AegisOS v5 guest setup — run ONCE inside a booted v4 image as root
# (guest-apply upgrade path), or on a clean v5 image to re-apply the payload.
# Usage (from the payload dir): sudo bash setup-v5.sh
# Logs to /tmp/v5-setup.log. Idempotent where possible.
# Unlike setup-v4.sh, this script does NOT assume v3 helpers are already
# present: it installs all aegis-* helpers, the Wayland desktop and Saral
# from the payload itself.
set -x
exec > /tmp/v5-setup.log 2>&1
echo "=== AegisOS v5 setup start $(date -u) ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update || echo "APT_UPDATE_FAILED (continuing; packages may already be present)"
apt-get install -y --no-install-recommends auditd nftables \
  sway swaybg swayidle swaylock xwayland \
  libgtk-layer-shell0 gir1.2-gtklayershell-0.1 python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-pil libjpeg62-turbo \
  foot grim slurp mako-notifier playerctl libgl1-mesa-dri \
  || echo "APT_INSTALL_PARTIAL (wayland/lab packages may be missing; see log)"
# Users (LAB ONLY credentials, documented, changeable, disabled by --stop)
id labweb 2>/dev/null || useradd -r -d /srv/labapp -s /usr/sbin/nologin labweb
id labuser 2>/dev/null || useradd -m -s /bin/bash labuser
echo 'labuser:lab123' | chpasswd
# Directories
mkdir -p /srv/labapp/plugins /srv/labapp/public /srv/labapp/flags /var/log/aegis-lab /var/lib/aegis-lab /etc/aegis-lab
# Payload files (this script lives in the payload dir)
P="$(cd "$(dirname "$0")" && pwd)"
cp "$P/labapp.py" /srv/labapp/labapp.py
cp "$P/server.py" /opt/aegis/server.py
cp "$P/v5-console.js" /opt/aegis/v5-console.js
cp "$P/aegis-labapp.service" "$P/aegis-ssh-lab.service" "$P/aegis.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/aegis.service /etc/systemd/system/aegis-labapp.service /etc/systemd/system/aegis-ssh-lab.service  # units were 660 (systemd "world-inaccessible" warning)
# Lab units must NEVER start at boot: they have no [Install] section, and
# this preset explicitly disables them (first-boot preset population
# enabled them in v5 repack #3 — see README-v5.md).
mkdir -p /etc/systemd/system-preset
printf 'disable aegis-labapp.service\ndisable aegis-ssh-lab.service\n' > /etc/systemd/system-preset/00-aegis-lab.preset
systemctl disable aegis-labapp.service aegis-ssh-lab.service 2>/dev/null || true
for h in aegis-lab aegis-ir aegis-fim aegis-lab-reset-flags aegis-gui aegis-status aegis-logs aegis-net aegis-drivers; do
  cp "$P/bin/$h" "/usr/local/bin/$h"; chmod 755 "/usr/local/bin/$h"
done
# Saral 0.3.0 (NEW in v5 — was never in the v4 image)
mkdir -p /usr/local/lib/saral/libs
cp "$P/saral/saral.py" /usr/local/bin/saral; chmod 755 /usr/local/bin/saral
cp -r "$P/saral/libs/." /usr/local/lib/saral/libs/
saral version || echo "SARAL_CHECK_FAILED"
# Wayland desktop (sway + original GTK layer-shell shell + wallpapers)
bash "$P/wayland/install-wayland.sh" || echo "WAYLAND_INSTALL_FAILED"
# Permission normalization (same umask bug as the clean build): shared
# wallpapers, shell lib and Saral libs must be world-readable.
chmod 755 /usr/share/aegis /usr/share/aegis/wallpapers /usr/local/lib/aegis-shell /usr/local/lib/saral /usr/local/lib/saral/libs 2>/dev/null || true
chmod 644 /usr/share/aegis/wallpapers/*.png /usr/local/lib/saral/libs/*.py 2>/dev/null || true
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
# Frontend files (only if the payload carries them — the clean build already has them)
if [ -f "$P/frontend/index.html" ]; then
  cp "$P/frontend/index.html" "$P/frontend/app.js" "$P/frontend/style.css" /opt/aegis/ 2>/dev/null || true
  cp -r "$P/frontend/apps" "$P/frontend/aegis" /opt/aegis/ 2>/dev/null || true
  cp "$P/v5-console.js" /opt/aegis/v5-console.js
  python3 - <<'PY'
p="/opt/aegis/index.html"
try:
    s=open(p).read()
    if "v5-console.js" not in s:
        s=s.replace("</body>", '<script src="v5-console.js"></script>\n</body>')
        open(p,"w").write(s)
except Exception as e:
    print("index.html inject failed:", e)
PY
fi
# Ownership / permissions (flags separated by user, see labapp.py)
chown -R labweb:labweb /srv/labapp
chmod 755 /srv/labapp
chmod 700 /srv/labapp/flags 2>/dev/null || true
chown -R analyst:analyst /home/analyst 2>/dev/null || true
# SSH host keys (openssh-server is already in the image, masked by default)
ssh-keygen -A 2>/dev/null || true
mkdir -p /var/log/aegis-lab
chown labweb:labweb /var/log/aegis-lab 2>/dev/null || true
chmod 755 /var/log/aegis-lab 2>/dev/null || true
# Auditd rules (real detection; if auditd fails in QEMU, journal/auth/app logs still work)
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
# Lab units are NOT enabled on boot (default OFF). They are started only by aegis-lab --enable.
systemctl daemon-reload
systemctl enable aegis.service 2>/dev/null || true
systemctl restart aegis.service
# Flag 2 + FIM manifest (labapp creates DB/flag3 on first start)
aegis-lab-reset-flags || echo "FLAG2_FAILED"
# Start labapp briefly as labweb to create DB/flag3, then stop (lab stays OFF by default)
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
echo "=== AegisOS v5 setup done $(date -u) ==="
ls -l /srv/labapp/ /usr/local/bin/aegis-* /etc/systemd/system/aegis-*.service
