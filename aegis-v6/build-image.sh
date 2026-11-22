#!/usr/bin/env bash
# AegisOS v6 — build a REAL bootable Debian 13 trixie disk image.
# v6 = v5 lab + console + Saral (carried over) + REAL Hyprland 0.55.2 +
# Quickshell 0.3.0 desktop (trixie-backports) + Plymouth boot splash +
# Google Chrome + aegis-tools installer + swww animated wallpaper.
# Default boot is still CLI + web console on http://127.0.0.1:8000;
# lab is OFF until aegis-lab --enable; GUI starts only via `aegis-gui`.
#
# BUILD METHOD (changed from v5): fakechroot debootstrap DIES on trixie
# (glibc 2.41 > host 2.39, second stage aborts with stack smashing).
# This script uses plain ROOT debootstrap (sudo) + sudo chroot instead.
# Requires: sudo -n works, debootstrap, grub-mkimage, mkfs.ext4, python3.
#
# Logo: SKIPPED by the user (2026-11-22) — he designs it himself later.
# No logo image is baked in anywhere. The slot is documented:
#   /usr/share/aegis/logo.png  (boot splash, lock screen, bar, launcher)
# See README-v6.md and /usr/share/aegis/LOGO-SLOT-README.md.
#
# Usage:  ./build-image.sh [output-dir]
# Default output dir: the directory containing this script.
# Produces: aegis-v6.img (raw, MBR + GRUB BIOS, single ext4 partition)
#           aegis-v6.img.sha256
# Image size default 7168 MiB (v5 was 5120; Chrome + Qt6 + Quickshell grow it).
#
# Why no loop devices? Same as v5: rootfs built with debootstrap +
# chroot, packed with `mkfs.ext4 -d <rootfs>`, GRUB BIOS installed
# manually. Boots in QEMU and can be dd'd to a USB stick.
set -euo pipefail

OUT="${1:-$(cd "$(dirname "$0")" && pwd)}"
OUT="$(cd "$OUT" && pwd)"
SRC="$(cd "$(dirname "$0")" && pwd)"
WORK="$OUT/.build"
ROOTFS="$WORK/rootfs"
IMG="$OUT/aegis-v6.img"
IMG_SIZE_MB="${IMG_SIZE_MB:-7168}"
PART_OFFSET_MB=1

log() { echo "[build] $*"; }
die() { echo "[build] ERROR: $*" >&2; exit 1; }

command -v debootstrap >/dev/null || die "debootstrap not found"
command -v grub-mkimage >/dev/null || die "grub-mkimage not found (install grub-pc-bin)"
command -v mkfs.ext4 >/dev/null || die "mkfs.ext4 not found"
command -v debugfs >/dev/null || die "debugfs not found (install e2fsprogs)"
command -v python3 >/dev/null || die "python3 not found"
sudo -n true 2>/dev/null || die "passwordless sudo is required for the v6 root-debootstrap build (sudo -n true failed)"
[ -f "$SRC/src/server.py" ] || die "v6 source tree missing: $SRC/src/server.py (run from the aegis-v6 folder)"
[ -f "$SRC/src/VERSION" ] || die "VERSION file missing in src/"
[ -d "$SRC/quickshell" ] || die "Quickshell shell missing: $SRC/quickshell/"
[ -f "$SRC/swww-bin/swww" ] || die "swww binary missing: $SRC/swww-bin/swww (build it first, see swww-BUILD.md)"
[ -f "$SRC/swww-bin/swww-daemon" ] || die "swww-daemon binary missing: $SRC/swww-bin/swww-daemon (build it first, see swww-BUILD.md — both binaries are required)"
[ -f "$SRC/bin/aegis-tools" ] || die "aegis-tools missing: $SRC/bin/aegis-tools"
[ -d "$SRC/plymouth/aegis" ] || die "Plymouth theme missing: $SRC/plymouth/aegis/"

log "output dir: $OUT"
# AEGIS_REUSE_ROOTFS=1 skips debootstrap+setup when a complete rootfs
# already exists in $WORK/rootfs (faster rebuilds; default is a clean build).
REUSE=0
if [ "${AEGIS_REUSE_ROOTFS:-0}" = "1" ] && ls "$ROOTFS"/boot/vmlinuz-* >/dev/null 2>&1; then
  REUSE=1
  log "reusing existing rootfs in $ROOTFS (AEGIS_REUSE_ROOTFS=1)"
fi
if [ "$REUSE" = 0 ]; then
  rm -rf "$WORK"
  mkdir -p "$WORK" "$ROOTFS"
  # Ownership fix (v6 build, found 2026-11-22): the workspace tree is
  # setgid group "nogroup" (gid 65534, unmapped in this cell), so a fresh
  # $WORK/$ROOTFS inherits group nogroup + setgid — and chown then fails
  # with EPERM on any file created under them (base-files postinst died
  # on `chown root:mail /var/mail`). Normalise to root:root, no setgid,
  # so everything debootstrap/dpkg creates inside inherits root:root.
  sudo chgrp root "$WORK" "$ROOTFS"
  sudo chmod g-s "$WORK" "$ROOTFS"

# --- 1. debootstrap: real Debian trixie, minimal (ROOT, not fakechroot) ---
log "debootstrap trixie (root, this downloads ~300MB)..."
sudo debootstrap --variant=minbase trixie "$ROOTFS" http://deb.debian.org/debian
fi
mkdir -p "$WORK" "$ROOTFS"

# --- 2. inside the chroot: real kernel, systemd, Hyprland stack -----------
if [ "$REUSE" = 0 ]; then
log "configuring rootfs..."
sudo tee "$ROOTFS/etc/apt/sources.list" >/dev/null <<'EOF'
deb http://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb http://deb.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
deb http://deb.debian.org/debian trixie-updates main contrib non-free non-free-firmware
EOF
sudo tee "$ROOTFS/etc/apt/sources.list.d/trixie-backports.list" >/dev/null <<'EOF'
deb http://deb.debian.org/debian trixie-backports main contrib non-free non-free-firmware
EOF
# Backports pinned to 100: it only fills gaps (Hyprland/Quickshell),
# never upgrades stable packages.
sudo mkdir -p "$ROOTFS/etc/apt/preferences.d"
sudo tee "$ROOTFS/etc/apt/preferences.d/99-backports" >/dev/null <<'EOF'
Package: *
Pin: release a=trixie-backports
Pin-Priority: 100
EOF
# Build-time egress proxy (v6 build, found 2026-11-22): this host reaches
# the internet only via hatch-egress-proxy:3128 (see the host's
# /etc/apt/apt.conf.d/80hatch-egress-proxy — no credentials in it).
# `sudo chroot` strips the host's proxy env vars, so apt inside the
# chroot connects directly and fails ("Connection failed"). Copy the
# host's proxy config in for setup.sh, and REMOVE it right after setup
# finishes (see below) — it must never ship in the image, or the user's
# own apt would try a proxy that doesn't exist on their network.
if [ -f /etc/apt/apt.conf.d/80hatch-egress-proxy ]; then
  sudo cp /etc/apt/apt.conf.d/80hatch-egress-proxy "$ROOTFS/etc/apt/apt.conf.d/80hatch-egress-proxy"
fi
printf 'aegis\n' | sudo tee "$ROOTFS/etc/hostname" >/dev/null
printf '127.0.0.1 localhost aegis\n::1 localhost ip6-localhost ip6-loopback\n' | sudo tee "$ROOTFS/etc/hosts" >/dev/null
# Build-time egress proxy host entries (v6 build, found 2026-11-22): the
# host's /etc/hosts maps hatch-egress-proxy to the veth gateway
# (198.19.0.1 / fd8b:4f84:7d32:99::1). Without these lines the chroot
# resolves the proxy via DNS to an unreachable address and apt fails
# with "Connection failed". Removed after setup.sh (see below) — they
# must never ship in the image.
grep -E "^[0-9a-fA-F:.]+[[:space:]]+[^#]*hatch-egress-proxy" /etc/hosts 2>/dev/null | sudo tee -a "$ROOTFS/etc/hosts" >/dev/null || true

sudo mkdir -p "$ROOTFS/etc/systemd/system/getty.target.wants"
sudo ln -sf /usr/lib/systemd/system/getty@.service \
  "$ROOTFS/etc/systemd/system/getty.target.wants/getty@tty1.service"
sudo ln -sf /usr/lib/systemd/system/serial-getty@.service \
  "$ROOTFS/etc/systemd/system/getty.target.wants/serial-getty@ttyS0.service"

cp "$SRC/src/server.py" "$ROOTFS/usr/local/lib/aegis-server.py" 2>/dev/null || sudo cp "$SRC/src/server.py" "$ROOTFS/usr/local/lib/aegis-server.py"
sudo chmod 755 "$ROOTFS/usr/local/lib/aegis-server.py"
sudo mkdir -p "$ROOTFS/opt/aegis"

# Chrome .deb (downloaded at build time; version-less URL = latest stable).
CHROME_DEB="$WORK/google-chrome-stable_current_amd64.deb"
if [ ! -f "$CHROME_DEB" ]; then
  log "downloading Google Chrome .deb..."
  curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o "$CHROME_DEB" || die "Chrome .deb download failed"
fi
CHROME_SHA="$(sha256sum "$CHROME_DEB" | cut -d' ' -f1)"
log "Chrome .deb sha256: $CHROME_SHA"
cp "$CHROME_DEB" "$ROOTFS/tmp/google-chrome.deb"

sudo mount -t proc proc "$ROOTFS/proc" 2>/dev/null || true
sudo mount --bind /dev "$ROOTFS/dev" 2>/dev/null || true
sudo mount -t sysfs sysfs "$ROOTFS/sys" 2>/dev/null || true
sudo tee "$ROOTFS/tmp/setup.sh" >/dev/null <<'SETUP_EOF'
set -eux
export DEBIAN_FRONTEND=noninteractive
apt-get update
# Hyprland + Quickshell come from trixie-backports (-t); everything else
# from trixie main. Pin check happens after install (see below).
apt-get install -y -t trixie-backports \
  hyprland hyprlock hypridle hyprpaper hyprlauncher hyprcursor-util \
  quickshell xdg-desktop-portal-hyprland
# NOTE (v6 build, found 2026-11-22): there is no binary package named
# `hyprcursor` (the CLI is in `hyprcursor-util`, Source: hyprcursor
# 0.1.13-2~bpo13+1) and no binary named `aquamarine` (only
# libaquamarine* libs, pulled in automatically as Hyprland deps).
# Installing either name fails the whole apt run with
# "Unable to locate package".
# Backports-drift fix (v6 build, found 2026-11-22): the first install
# (`-t trixie-backports`) pulls backports libatk1.0-0t64 2.62.1 and
# libxkbcommon0 1.13.1. The trixie gir1.2-atk-1.0 and libxkbregistry0
# demand the exact trixie versions of those libs, so apt refuses the
# whole transaction ("held broken packages"). Both packages exist in
# backports at matching versions, so request them from backports
# explicitly with the /release suffix.
apt-get install -y --no-install-recommends \
  linux-image-amd64 systemd systemd-sysv openssh-server dbus dbus-x11 \
  python3 python3-pil libjpeg62-turbo python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  gir1.2-atk-1.0/trixie-backports libxkbregistry0/trixie-backports \
  iproute2 iputils-ping procps psmisc nmap sqlmap hydra john aircrack-ng \
  tcpdump tshark wireshark-common openssl curl ca-certificates sudo \
  netbase ifupdown isc-dhcp-client kmod e2fsprogs util-linux \
  foot grim slurp mako-notifier playerctl waybar xwayland \
  libgtk-layer-shell0 gir1.2-gtklayershell-0.1 \
  adwaita-icon-theme \
  libgl1-mesa-dri mesa-utils-bin \
  firefox-esr \
  network-manager wpasupplicant wireless-tools iw \
  pciutils usbutils lshw firmware-linux upower acpi htop auditd nftables \
  plymouth plymouth-themes qml6-module-qtmultimedia \
  qml6-module-qtquick qml6-module-qtquick-layouts qml6-module-qtquick-controls qml6-module-qtquick-templates \
  thunar
# nikto lives in non-free (sources.list has it above).
apt-get install -y --no-install-recommends nikto || echo "NIKTO_INSTALL_FAILED (non-free may be unavailable; aegis-tools still lists it)"
# Version pins (PLAN §10: backports drift). Fail loudly on a wrong major.
HYPR_VER="$(dpkg-query -W -f='${Version}' hyprland 2>/dev/null || echo none)"
QS_VER="$(dpkg-query -W -f='${Version}' quickshell 2>/dev/null || echo none)"
echo "hyprland=$HYPR_VER quickshell=$QS_VER"
case "$HYPR_VER" in 0.55.*) ;; *) echo "ERROR: unexpected hyprland version $HYPR_VER (expected 0.55.x)" >&2; exit 1;; esac
case "$QS_VER" in 0.3.*) ;; *) echo "ERROR: unexpected quickshell version $QS_VER (expected 0.3.x)" >&2; exit 1;; esac
# Google Chrome (.deb adds Google's APT repo, so Chrome updates via apt).
apt-get install -y /tmp/google-chrome.deb
dpkg-query -W -f='google-chrome-stable ${Version}\n' google-chrome-stable || echo "CHROME_VERSION_UNKNOWN"
rm -f /tmp/google-chrome.deb
# xdg-desktop-portal-hyprland SIGSEGVs on wlr-screencopy (omarchy finding);
# mask it — screenshots still work via grim.
ln -sf /dev/null /etc/systemd/user/xdg-desktop-portal-hyprland.service
# OpenSSH: installed but MASKED by default (lab use only, see README-v6).
systemctl disable ssh.service ssh.socket || true
ln -sf /dev/null /etc/systemd/system/ssh.service
ln -sf /dev/null /etc/systemd/system/ssh.socket
ln -sf /dev/null /etc/systemd/system/sshd.service
# User analyst / password "secure" — LAB ONLY, change on first login.
useradd -m -s /bin/bash -G sudo analyst
echo 'analyst:secure' | chpasswd
mkdir -p /home/analyst/Documents /home/analyst/Downloads /home/analyst/Projects /home/analyst/Logs
chown -R analyst:analyst /home/analyst
mkdir -p /var/log/journal
printf 'auto lo\niface lo inet loopback\n' > /etc/network/interfaces
systemctl enable NetworkManager 2>/dev/null || true
# Lab users (created here in the clean build; setup-v6.sh recreates them idempotently)
id labweb 2>/dev/null || useradd -r -d /srv/labapp -s /usr/sbin/nologin labweb
id labuser 2>/dev/null || useradd -m -s /bin/bash labuser
echo 'labuser:lab123' | chpasswd
# AegisOS console service (localhost only, see server.py).
cp /usr/local/lib/aegis-server.py /opt/aegis/server.py
cat > /etc/systemd/system/aegis.service <<'UNIT_EOF'
[Unit]
Description=AegisOS v6 console (localhost by default, LAN only in lab mode)
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/aegis/server.py
Restart=on-failure
User=root
Environment=SECUREOS_ALLOW_PUBLIC=0
EnvironmentFile=-/etc/aegis-lab/env
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
UNIT_EOF
systemctl enable aegis.service
chmod 644 /etc/systemd/system/aegis.service
# Default target: multi-user (CLI). No display manager is enabled on purpose:
# the GUI starts ONLY when the user runs `aegis-gui` (see bin/aegis-gui).
ln -sf /lib/systemd/system/multi-user.target /etc/systemd/system/default.target
apt-get clean
rm -rf /var/lib/apt/lists/*
SETUP_EOF
sudo chmod +x "$ROOTFS/tmp/setup.sh"
sudo chroot "$ROOTFS" /bin/bash /tmp/setup.sh
sudo rm -f "$ROOTFS/tmp/setup.sh"
# Remove the build-time egress proxy config (see above): it must never
# ship in the image.
sudo rm -f "$ROOTFS/etc/apt/apt.conf.d/80hatch-egress-proxy"
# Remove the build-time proxy host entries from /etc/hosts too.
sudo sed -i '/hatch-egress-proxy/d' "$ROOTFS/etc/hosts"
sudo umount "$ROOTFS/sys" 2>/dev/null || true
sudo umount "$ROOTFS/dev" 2>/dev/null || true
sudo umount "$ROOTFS/proc" 2>/dev/null || true
fi  # end REUSE=0 configure+setup block

# --- 2b. GUI stack gates (fail loudly instead of shipping a broken desktop)
# NOTE: the rootfs is root-owned after sudo debootstrap, so host-side
# writes below use sudo. (v5's fakechroot rootfs was user-owned.)
[ -x "$ROOTFS/usr/bin/Hyprland" ] || die "Hyprland missing from rootfs after setup (clean build failed)"
[ -x "$ROOTFS/usr/bin/qs" ] || die "Quickshell (qs) missing from rootfs after setup"
[ -x "$ROOTFS/usr/bin/hyprlock" ] || die "hyprlock missing from rootfs after setup"
# NOTE (v6 build, found 2026-11-22): /usr/bin/google-chrome is a symlink
# to /etc/alternatives/google-chrome, an ABSOLUTE symlink chain. A host-side
# [ -x ] test resolves that chain against the HOST root, where it does not
# exist, so it always fails even though Chrome is correctly installed
# inside the rootfs. Check the real binary instead.
[ -x "$ROOTFS/opt/google/chrome/google-chrome" ] || die "Google Chrome missing from rootfs after setup"
[ -f "$ROOTFS/usr/share/icons/Adwaita/cursors/left_ptr" ] || die "Adwaita cursor theme missing from rootfs (adwaita-icon-theme not installed)"
if [ -x "$ROOTFS/usr/bin/sway" ]; then
  die "sway present in v6 rootfs — the v5 compositor must not ship in v6"
fi
# Plymouth theme source must exist (it is installed into the rootfs below;
# the initramfs content is checked after install).
[ -d "$SRC/plymouth/aegis" ] || die "Plymouth aegis theme source missing: $SRC/plymouth/aegis/"

# --- Install ALL aegis-* CLI helpers (always, from src/bin, so none is stale)
sudo mkdir -p "$ROOTFS/usr/local/bin"
for h in aegis-gui aegis-autostart aegis-wallpaper aegis-status aegis-logs aegis-net aegis-drivers aegis-lab aegis-ir aegis-fim aegis-lab-reset-flags aegis-update aegis-tools; do
  if [ -f "$SRC/src/bin/$h" ]; then sudo cp "$SRC/src/bin/$h" "$ROOTFS/usr/local/bin/$h"; sudo chmod 755 "$ROOTFS/usr/local/bin/$h";
  elif [ -f "$SRC/bin/$h" ]; then sudo cp "$SRC/bin/$h" "$ROOTFS/usr/local/bin/$h"; sudo chmod 755 "$ROOTFS/usr/local/bin/$h";
  else die "missing helper: bin/$h (checked src/bin and bin)"; fi
done
# --- v6 lab files (always, so they are never stale) -----------------------
sudo mkdir -p "$ROOTFS/srv/labapp/plugins" "$ROOTFS/srv/labapp/public" "$ROOTFS/srv/labapp/flags" "$ROOTFS/var/log/aegis-lab" "$ROOTFS/var/lib/aegis-lab" "$ROOTFS/etc/aegis-lab"
sudo cp "$SRC/src/labapp.py" "$ROOTFS/srv/labapp/labapp.py"
sudo cp "$SRC/src/server.py" "$ROOTFS/opt/aegis/server.py"
sudo cp "$SRC/src/v5-console.js" "$ROOTFS/opt/aegis/v5-console.js"
sudo cp "$SRC/src/aegis-labapp.service" "$SRC/src/aegis-ssh-lab.service" "$SRC/src/aegis.service" "$ROOTFS/etc/systemd/system/"
# Lab units must NEVER be enabled at boot (v5 repack #3 regression).
#  1. The lab unit files have NO [Install] section, so preset/enable
#     cannot enable them; they start only via explicit `systemctl restart`.
#  2. This preset file explicitly disables them, so even if an [Install]
#     section is re-added later, first-boot preset population keeps them off.
sudo mkdir -p "$ROOTFS/etc/systemd/system-preset"
printf 'disable aegis-labapp.service\ndisable aegis-ssh-lab.service\n' | sudo tee "$ROOTFS/etc/systemd/system-preset/00-aegis-lab.preset" >/dev/null
printf 'disabled\n' | sudo tee "$ROOTFS/etc/aegis-lab/state" >/dev/null
# Auditd rules
sudo mkdir -p "$ROOTFS/etc/audit/rules.d"
cat > "$WORK/aegis-lab.rules" <<'EOF'
-w /srv/labapp -p wa -k aegis_lab
-w /home/labuser -p wa -k aegis_labuser
-w /etc/aegis-lab -p wa -k aegis_labstate
EOF
sudo cp "$WORK/aegis-lab.rules" "$ROOTFS/etc/audit/rules.d/aegis-lab.rules"
# --- Saral 0.3.0 ------------------------------------------------------------
sudo mkdir -p "$ROOTFS/usr/local/lib/saral/libs"
sudo cp "$SRC/src/saral/saral.py" "$ROOTFS/usr/local/bin/saral"
sudo chmod 755 "$ROOTFS/usr/local/bin/saral"
sudo cp -r "$SRC/src/saral/libs/." "$ROOTFS/usr/local/lib/saral/libs/"
# --- Hyprland desktop: config, Quickshell shell, wallpapers, swww ----------
sudo mkdir -p "$ROOTFS/home/analyst/.config/hypr" "$ROOTFS/home/analyst/.config/quickshell/aegis" "$ROOTFS/etc/aegis/quickshell" "$ROOTFS/usr/share/aegis/wallpapers" "$ROOTFS/home/analyst/.config/aegis"
# Hyprland config (written by the build; see README-v6.md for what each
# section does). Cursor: Hyprland-native software-cursor fallback
# (v5.0.3 lesson: the hardware-cursor plane failed on virtio-vga/VMSVGA).
sudo tee "$ROOTFS/home/analyst/.config/hypr/hyprland.conf" >/dev/null <<'HYPR_EOF'
# AegisOS v6 — Hyprland config (Nebula-style desktop)
monitor=,preferred,auto,1
exec-once = /usr/local/bin/aegis-autostart
input {
    kb_layout = us
    follow_mouse = 1
    touchpad {
        natural_scroll = false
    }
    sensitivity = 0
}
general {
    gaps_in = 6
    gaps_out = 12
    border_size = 2
    col.active_border = rgba(ffd682ee) rgba(ff7a3dee) 45deg
    col.inactive_border = rgba(2a2f4aee)
    layout = dwindle
}
decoration {
    rounding = 12
    active_opacity = 1.0
    inactive_opacity = 0.95
    blur {
        enabled = true
        size = 6
        passes = 2
        new_optimizations = true
    }
    shadow {
        enabled = true
        range = 8
        render_power = 3
        color = rgba(00000066)
    }
}
animations {
    enabled = true
    bezier = easeOut, 0.05, 0.9, 0.1, 1.05
    animation = windows, 1, 5, easeOut, slide
    animation = windowsOut, 1, 5, easeOut, slide
    animation = border, 1, 8, default
    animation = fade, 1, 5, default
    animation = workspaces, 1, 6, easeOut, slide
}
dwindle {
    preserve_split = true
}
# NOTE (v6, 2026-11-22): `dwindle:pseudotile` does not exist in Hyprland
# 0.55 — it produced a red config-error banner on every boot. Removed.
misc {
    force_default_wallpaper = 0
    disable_hyprland_logo = true
    disable_splash_rendering = true
}
cursor {
    # v5.0.3 lesson, Hyprland-native form: the DRM hardware-cursor plane
    # failed on QEMU virtio-vga and VirtualBox VMSVGA, leaving the
    # pointer invisible. Software cursors draw into the framebuffer.
    no_hardware_cursors = true
}
env = XDG_CURRENT_DESKTOP,Hyprland
env = XDG_SESSION_TYPE,wayland
env = MOZ_ENABLE_WAYLAND,1
env = QT_QPA_PLATFORM,wayland
env = XCURSOR_THEME,Adwaita
env = XCURSOR_SIZE,24
# Keybinds — the shell exposes IPC (see quickshell/shell.qml):
#   qs -c aegis ipc call aegis lock / toggleLauncher / showDesktopMenu
# NOTE (v6, 2026-11-22): `-c aegis` is REQUIRED — without it the IPC
# client looks for a "default" config and errors out ("Could not find
# \"default\" config directory"), so no bind ever reached the shell.
$mainMod = SUPER
bind = $mainMod, Return, exec, foot
bind = $mainMod, D, exec, qs -c aegis ipc call aegis toggleLauncher
bind = $mainMod, L, exec, qs -c aegis ipc call aegis lock
bind = , mouse:273, exec, qs -c aegis ipc call aegis showDesktopMenu
bind = $mainMod SHIFT, E, exit,
bind = $mainMod, Q, killactive,
bind = $mainMod, F, fullscreen, 0
bind = $mainMod, 1, workspace, 1
bind = $mainMod, 2, workspace, 2
bind = $mainMod, 3, workspace, 3
bind = $mainMod, 4, workspace, 4
bind = $mainMod, 5, workspace, 5
# Windows opened by the shell (lock screen, bar, menus) are layer-shell
# surfaces — they float above the desktop and are borderless by nature,
# so no windowrule is needed for them.
# NOTE (v6, 2026-11-22): `windowrulev2` was deprecated in Hyprland 0.55
# and its plain rename to `windowrule` does NOT work either — 0.55
# rejects `windowrule = float, ...` ("invalid field float: missing a
# value"). The two rules were removed instead: they are no-ops for
# layer-shell windows, and the invalid lines drew a red config-error
# banner on every boot (which also covered the top bar).
HYPR_EOF
# Quickshell shell: master copy in /etc/aegis/quickshell, user config copy
# in ~/.config/quickshell/aegis (qs -c aegis reads the user copy).
sudo cp -r "$SRC/quickshell/." "$ROOTFS/etc/aegis/quickshell/"
sudo cp -r "$SRC/quickshell/." "$ROOTFS/home/analyst/.config/quickshell/aegis/"
# hypridle config (idle lock after 600 s, same timing as v5).
sudo cp "$SRC/src/hypr/hypridle.conf" "$ROOTFS/home/analyst/.config/hypr/hypridle.conf"
# Wallpapers: v6 draft (default) + animated GIF + v5 alternates.
sudo cp "$SRC/wallpaper-draft.png" "$ROOTFS/usr/share/aegis/wallpapers/aegis-v6.png"
sudo cp "$SRC/wallpaper-animated.gif" "$ROOTFS/usr/share/aegis/wallpapers/aegis-v6-animated.gif"
sudo cp "$SRC/src/wayland/wallpapers/"*.png "$ROOTFS/usr/share/aegis/wallpapers/" 2>/dev/null || true
sudo cp "$ROOTFS/usr/share/aegis/wallpapers/aegis-v6.png" "$ROOTFS/home/analyst/.config/aegis/wallpaper.png"
# swww (built from source; see swww-BUILD.md) + aegis-wallpaper helper.
# Both binaries are required: swww-daemon serves the wallpaper, swww is
# the client that sets/changes it.
sudo cp "$SRC/swww-bin/swww" "$ROOTFS/usr/local/bin/swww"
sudo cp "$SRC/swww-bin/swww-daemon" "$ROOTFS/usr/local/bin/swww-daemon"
sudo chmod 755 "$ROOTFS/usr/local/bin/swww" "$ROOTFS/usr/local/bin/swww-daemon"
sudo cp "$SRC/src/wayland/aegis-colours.py" "$ROOTFS/usr/local/lib/aegis-colours.py"
sudo chmod 755 "$ROOTFS/usr/local/lib/aegis-colours.py"
sudo ln -sf /usr/local/lib/aegis-colours.py "$ROOTFS/usr/local/bin/aegis-colours"
# Logo slot (user supplies the logo later — see README-v6.md). No logo
# image is shipped; the slot is a documented path, not a file.
sudo tee "$ROOTFS/usr/share/aegis/LOGO-SLOT-README.md" >/dev/null <<'LOGO_EOF'
# AegisOS logo slot (v6.0.0 — logo skipped by the user, supplied later)
Place the finished logo file here as:
  /usr/share/aegis/logo.png   (512x512 PNG, transparent background preferred)
It is then picked up automatically by:
  * Boot splash — Plymouth theme reads /usr/share/aegis/logo.png if present.
  * Lock screen — Quickshell shows it above the clock disc if present.
  * Desktop bar — the launcher button shows it (text "AegisOS" until then).
  * App launcher — the launcher header shows it if present.
Until the file exists, the OS uses the text "AegisOS" everywhere.
LOGO_EOF
# Chrome: Wayland by default (falls back to XWayland if needed).
sudo mkdir -p "$ROOTFS/usr/share/applications"
if [ -f "$ROOTFS/usr/share/applications/google-chrome.desktop" ]; then
  sudo sed -i 's|^Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable --ozone-platform-hint=auto|' "$ROOTFS/usr/share/applications/google-chrome.desktop"
fi
# Plymouth: install the text-only aegis theme and rebuild initramfs.
sudo mkdir -p "$ROOTFS/usr/share/plymouth/themes/aegis"
sudo cp -r "$SRC/plymouth/aegis/." "$ROOTFS/usr/share/plymouth/themes/aegis/"
# Logo slot: the theme loads logo.png from its own dir; point it at the
# single master location. Dangling until the user drops a logo in
# (aegis.script null-checks a missing logo and stays text-only).
sudo ln -sf /usr/share/aegis/logo.png "$ROOTFS/usr/share/plymouth/themes/aegis/logo.png"
sudo mount -t proc proc "$ROOTFS/proc" 2>/dev/null || true
sudo mount --bind /dev "$ROOTFS/dev" 2>/dev/null || true
sudo mount -t sysfs sysfs "$ROOTFS/sys" 2>/dev/null || true
sudo chroot "$ROOTFS" plymouth-set-default-theme aegis || die "plymouth-set-default-theme aegis failed"
sudo chroot "$ROOTFS" update-initramfs -u || die "update-initramfs failed (Plymouth theme not in initramfs)"
# Plymouth theme must be inside the initramfs (not just on disk).
sudo chroot "$ROOTFS" lsinitramfs /boot/initrd.img-$(ls "$ROOTFS/boot"/vmlinuz-* | head -1 | xargs basename | sed 's/vmlinuz-//') 2>/dev/null | grep -q "plymouth/themes/aegis" || die "Plymouth aegis theme NOT found inside initramfs"
log "Plymouth aegis theme verified inside initramfs"
sudo umount "$ROOTFS/sys" 2>/dev/null || true
sudo umount "$ROOTFS/dev" 2>/dev/null || true
sudo umount "$ROOTFS/proc" 2>/dev/null || true
# Permission normalization (host umask 0007 makes cp'ed files unreadable):
sudo chmod 755 "$ROOTFS/usr/share/aegis" "$ROOTFS/usr/share/aegis/wallpapers" \
  "$ROOTFS/usr/local/lib/saral" "$ROOTFS/usr/local/lib/saral/libs" "$ROOTFS/etc/aegis/quickshell"
sudo chmod 644 "$ROOTFS/usr/share/aegis/wallpapers/"*.png "$ROOTFS/usr/share/aegis/wallpapers/"*.gif "$ROOTFS/usr/local/lib/saral/libs/"*.py 2>/dev/null || true
sudo chmod 644 "$ROOTFS/usr/local/lib/saral/libs/greet_bridge/"* 2>/dev/null || true
sudo chmod 644 "$ROOTFS/home/analyst/.config/hypr/hyprland.conf"
# --- Version file + updater state dirs --------------------------------------
sudo mkdir -p "$ROOTFS/var/lib/aegis/update" "$ROOTFS/var/lib/aegis/backup"
sudo cp "$SRC/src/VERSION" "$ROOTFS/etc/aegis-version"
sudo chmod 644 "$ROOTFS/etc/aegis-version"
# --- Lab DB/flags + FIM manifest + theme, inside the chroot -----------------
sudo mount -t proc proc "$ROOTFS/proc" 2>/dev/null || true
sudo mount --bind /dev "$ROOTFS/dev" 2>/dev/null || true
sudo mount -t sysfs sysfs "$ROOTFS/sys" 2>/dev/null || true
cat > "$WORK/v6-labinit.sh" <<'LABINIT_EOF'
set -eux
python3 - <<'PY'
import sys
sys.argv = ["labapp.py", "127.0.0.1"]
sys.path.insert(0, "/srv/labapp")
import labapp
labapp.init_db()
print("lab DB + flag3 created")
PY
chown -R labweb:labweb /srv/labapp
chmod 700 /srv/labapp/flags
chmod 600 /srv/labapp/lab.db /srv/labapp/flags/flag3.txt 2>/dev/null || true
python3 -c 'import uuid; open("/home/labuser/flag2.txt","w").write("flag{"+uuid.uuid4().hex[:16]+"}\n")'
chown labuser:labuser /home/labuser/flag2.txt
chmod 600 /home/labuser/flag2.txt
/usr/local/bin/aegis-fim --init || echo "FIM_INIT_FAILED (see log)"
python3 /usr/local/lib/aegis-colours.py /home/analyst/.config/aegis/wallpaper.png --out /home/analyst/.config/aegis || \
  echo "COLOURS_FAILED (theme will be regenerated on first GUI start)"
chown -R analyst:analyst /home/analyst/.config
# Saral check (guest python + installed libs)
/usr/local/bin/saral version || echo "SARAL_CHECK_FAILED (see log)"
# Desktop stack sanity (binaries + QML files present)
command -v Hyprland qs hyprlock swww google-chrome || echo "DESKTOP_BIN_CHECK_FAILED (see log)"
ls /etc/aegis/quickshell/shell.qml || echo "QML_SHELL_MISSING (see log)"
LABINIT_EOF
sudo cp "$WORK/v6-labinit.sh" "$ROOTFS/tmp/v6-labinit.sh"
sudo chmod +x "$ROOTFS/tmp/v6-labinit.sh"
sudo chroot "$ROOTFS" /bin/bash /tmp/v6-labinit.sh || log "WARNING: v6-labinit.sh failed — DB/flags/FIM/theme may be incomplete (guest setup-v6.sh redoes them)"
sudo rm -f "$ROOTFS/tmp/v6-labinit.sh"
sudo umount "$ROOTFS/sys" 2>/dev/null || true
sudo umount "$ROOTFS/dev" 2>/dev/null || true
sudo umount "$ROOTFS/proc" 2>/dev/null || true
sudo chown -R 1000:1000 "$ROOTFS/home/analyst/.config" 2>/dev/null || sudo chown -R 1000:1000 "$ROOTFS/home/analyst" 2>/dev/null || true

# --- 3. console frontend into /opt/aegis ------------------------------------
REPO_ROOT="${AEGIS_REPO_ROOT:-}"
if [ -z "$REPO_ROOT" ]; then
  if [ -f "$SRC/src/frontend/index.html" ]; then REPO_ROOT="$SRC/src/frontend";
  else die "no frontend found: $SRC/src/frontend/index.html missing and AEGIS_REPO_ROOT unset"; fi
fi
log "repo root for console frontend: $REPO_ROOT"
for f in index.html app.js style.css; do
  [ -f "$REPO_ROOT/$f" ] && sudo cp "$REPO_ROOT/$f" "$ROOTFS/opt/aegis/"
done
sudo cp -r "$REPO_ROOT/apps" "$ROOTFS/opt/aegis/" 2>/dev/null || true
if [ -d "$REPO_ROOT/aegis" ]; then
  sudo cp -r "$REPO_ROOT/aegis" "$ROOTFS/opt/aegis/"
elif [ -d "$REPO_ROOT/secureos" ]; then
  sudo cp -r "$REPO_ROOT/secureos" "$ROOTFS/opt/aegis/aegis"
fi
sudo cp "$SRC/src/server.py" "$ROOTFS/opt/aegis/server.py"
sudo cp "$SRC/src/v5-console.js" "$ROOTFS/opt/aegis/v5-console.js"
if grep -q 'app.js' "$ROOTFS/opt/aegis/index.html" 2>/dev/null; then
  sudo python3 - "$ROOTFS/opt/aegis/index.html" <<'PYEOF'
import os, sys
p = sys.argv[1]
s = open(p).read()
if os.path.exists(os.path.join(os.path.dirname(p), "v5-console.js")) and "v5-console.js" not in s:
    s = s.replace("</body>", '<script src="v5-console.js"></script>\n</body>')
open(p, "w").write(s)
PYEOF
fi

# --- 4. grub.cfg inside the rootfs -----------------------------------------
for d in dev proc; do
  if [ -L "$ROOTFS/$d" ]; then sudo rm "$ROOTFS/$d"; sudo mkdir "$ROOTFS/$d"; fi
done
sudo ln -sf /dev/null "$ROOTFS/etc/systemd/system/ssh.service"
sudo ln -sf /dev/null "$ROOTFS/etc/systemd/system/ssh.socket"
sudo ln -sf /dev/null "$ROOTFS/etc/systemd/system/sshd.service"
sudo ln -sf /lib/systemd/system/multi-user.target "$ROOTFS/etc/systemd/system/default.target"
sudo chroot "$ROOTFS" systemctl disable aegis-labapp.service aegis-ssh-lab.service 2>/dev/null || true
sudo chmod 644 "$ROOTFS/etc/systemd/system/aegis.service" 2>/dev/null || true
sudo chmod 644 "$ROOTFS/etc/systemd/system/aegis-labapp.service" "$ROOTFS/etc/systemd/system/aegis-ssh-lab.service" 2>/dev/null || true
sudo chmod -R a+rX "$ROOTFS/opt/aegis" 2>/dev/null || true
python3 - "$ROOTFS" <<'PYEOF'
import os, sys
root = sys.argv[1]
fixed = 0
for dirpath, dirnames, filenames in os.walk(root):
    for name in dirnames + filenames:
        p = os.path.join(dirpath, name)
        if os.path.islink(p):
            t = os.readlink(p)
            if t.startswith(root):
                os.unlink(p)
                os.symlink(t[len(root):], p)
                fixed += 1
            elif "/.build/rootfs" in t:
                new = t.split("/.build/rootfs", 1)[1] or "/"
                os.unlink(p); os.symlink(new, p); fixed += 1
print(f"[build] final symlink sweep fixed {fixed}")
PYEOF
sudo rm -f "$ROOTFS/boot"/initrd.img-*.dpkg-bak "$ROOTFS/boot"/initrd.img-*.new
KERNEL="$(ls "$ROOTFS/boot"/vmlinuz-* | head -1 | xargs basename)"
INITRD="$(ls "$ROOTFS/boot"/initrd.img-* | head -1 | xargs basename)"
[ -n "$KERNEL" ] || die "no kernel found in rootfs /boot"
sudo mkdir -p "$ROOTFS/boot/grub"
sudo tee "$ROOTFS/boot/grub/grub.cfg" >/dev/null <<GRUB_EOF
set timeout=5
set default=0
menuentry "AegisOS v6" {
  set root=(hd0,msdos1)
  linux /boot/$KERNEL root=/dev/sda1 rw splash console=tty0 console=ttyS0,115200
  initrd /boot/$INITRD
}
GRUB_EOF
printf '/dev/sda1 / ext4 defaults 0 1\n' | sudo tee "$ROOTFS/etc/fstab" >/dev/null

# --- 5. pack rootfs into ext4 WITHOUT mounting (mkfs.ext4 -d) --------------
log "packing ext4 filesystem (${IMG_SIZE_MB}MB image, partition at ${PART_OFFSET_MB}MiB)..."
FS_SIZE_MB=$((IMG_SIZE_MB - PART_OFFSET_MB))
sudo mkfs.ext4 -q -O ^metadata_csum,^64bit -d "$ROOTFS" -L aegis "$WORK/root.ext4" "${FS_SIZE_MB}M"
sudo chmod 644 "$WORK/root.ext4"  # the python assembly step runs as the build user

# --- 6. assemble raw disk: MBR partition table + GRUB BIOS ------------------
log "assembling raw disk image..."
python3 - "$IMG" "$WORK/root.ext4" "$PART_OFFSET_MB" <<'PYEOF'
import os, shutil, struct, sys
img_path, fs_path, off_mb = sys.argv[1], sys.argv[2], int(sys.argv[3])
off = off_mb * 1024 * 1024
# NOTE (v6 build, found 2026-11-22): the old code did `fs = f.read()`,
# loading the whole 7.5 GiB root.ext4 into RAM — the build cell OOM-kills
# at 137 (v5's 5.3 GiB image fit; v6's 7168 MiB does not). Stream it in
# 64 MiB chunks instead; peak memory stays flat.
fs_size = os.path.getsize(fs_path)
total = off + fs_size
with open(img_path, "wb") as out:
    out.truncate(total)
    mbr = bytearray(512)
    sectors = fs_size // 512
    entry = struct.pack("<BBBBBBBBII", 0x80, 0, 2, 0, 0x83, 0xFE, 0xFF, 0xFF,
                        off // 512, sectors)
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    out.seek(0); out.write(mbr)
    out.seek(off)
    with open(fs_path, "rb") as f:
        shutil.copyfileobj(f, out, length=64 * 1024 * 1024)
print(f"image bytes={total} fs_bytes={fs_size}")
PYEOF

GRUB_DIR="$(dirname "$(command -v grub-mkimage)")/../lib/grub/i386-pc"
[ -f "$GRUB_DIR/boot.img" ] || GRUB_DIR="/usr/lib/grub/i386-pc"
[ -f "$GRUB_DIR/boot.img" ] || die "grub i386-pc boot.img not found under $GRUB_DIR"
grub-mkimage -O i386-pc -o "$WORK/core.img" \
  -p '(hd0,msdos1)/boot/grub' biosdisk part_msdos ext2 normal linux \
  search search_fs_uuid configfile
python3 - "$IMG" "$GRUB_DIR/boot.img" "$WORK/core.img" <<'PYEOF'
import sys
img, boot, core = sys.argv[1], sys.argv[2], sys.argv[3]
bootimg = open(boot, "rb").read()
coreimg = open(core, "rb").read()
with open(img, "r+b") as f:
    mbr = bytearray(f.read(512))
    newboot = bytearray(bootimg[:446])
    newboot += mbr[446:512]
    f.seek(0); f.write(newboot)
    f.seek(512); f.write(coreimg)
print(f"grub: boot.img={len(bootimg)} core.img={len(coreimg)}")
PYEOF

# --- 6b. lab-off-by-default gate -------------------------------------------
if debugfs -R "ls /etc/systemd/system/multi-user.target.wants" "$WORK/root.ext4" 2>/dev/null | grep -q "aegis-labapp\|aegis-ssh-lab"; then
  echo "[build] ERROR: lab-off gate failed — lab units are enabled in the packed filesystem:" >&2
  debugfs -R "ls /etc/systemd/system/multi-user.target.wants" "$WORK/root.ext4" 2>/dev/null | grep "aegis-lab" >&2
  exit 1
fi
log "lab-off gate passed (no lab wants-symlinks in packed filesystem)"

# --- 6c. proxy gate: the build-time egress proxy config must NOT be in the
# packed filesystem (it is removed after setup.sh; if it survived, the
# user's own apt would point at a proxy that doesn't exist for them).
# Same for the proxy host entries in /etc/hosts.
if debugfs -R "ls /etc/apt/apt.conf.d" "$WORK/root.ext4" 2>/dev/null | grep -q "80hatch-egress-proxy"; then
  echo "[build] ERROR: proxy gate failed — 80hatch-egress-proxy is in the packed filesystem" >&2
  exit 1
fi
if debugfs -R "cat /etc/hosts" "$WORK/root.ext4" 2>/dev/null | grep -q "hatch-egress-proxy"; then
  echo "[build] ERROR: proxy gate failed — hatch-egress-proxy is in the packed /etc/hosts" >&2
  exit 1
fi
log "proxy gate passed (no build-time proxy config in packed filesystem)"

# --- 7. rename gate: no 'secureos' (case-insensitive) in shipped v6 files ---
# Exception, documented in README-v6.md: SECUREOS_BIND_IP and
# SECUREOS_ALLOW_PUBLIC are kept unchanged (4 places must agree).
# Excluded by design: audit-v4.md, research-hyprland.md (historical docs),
# README-v6.md (its rename map documents the old names), build-image.sh
# itself (holds this gate's own search pattern). Binary artifacts excluded.
if grep -ri "secureos" "$SRC/src" "$SRC/quickshell" "$SRC/plymouth" "$SRC/bin" \
     --exclude-dir=__pycache__ \
     --exclude=audit-v4.md --exclude=research-hyprland.md --exclude=README-v6.md \
     --exclude="*.img" --exclude="*.test" --exclude="*.sha256" --exclude="*.pyc" \
     | grep -v "SECUREOS_BIND_IP" | grep -v "SECUREOS_ALLOW_PUBLIC" | grep -q .; then
  echo "[build] ERROR: rename gate failed — 'secureos' leftovers (excluding the env-var exception):" >&2
  grep -ri "secureos" "$SRC/src" "$SRC/quickshell" "$SRC/plymouth" "$SRC/bin" \
     --exclude-dir=__pycache__ \
     --exclude=audit-v4.md --exclude=research-hyprland.md --exclude=README-v6.md \
     --exclude="*.img" --exclude="*.test" --exclude="*.sha256" --exclude="*.pyc" \
     | grep -v "SECUREOS_BIND_IP" | grep -v "SECUREOS_ALLOW_PUBLIC" >&2
  exit 1
fi
log "rename gate passed (only SECUREOS_BIND_IP / SECUREOS_ALLOW_PUBLIC remain)"

(cd "$OUT" && sha256sum "$(basename "$IMG")" | tee "$IMG.sha256")
log "DONE: $IMG"
ls -lh "$IMG"
sudo du -sh "$ROOTFS"
