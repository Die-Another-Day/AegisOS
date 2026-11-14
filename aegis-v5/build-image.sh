#!/usr/bin/env bash
# AegisOS v5 — build a REAL bootable Debian bookworm disk image.
# v5 = v4 lab (renamed to AegisOS) + Nebula-style Wayland desktop
# (sway 1.7 + original GTK3/Python layer-shell shell) + Saral 0.3.0.
# Default boot is still CLI + web console on http://127.0.0.1:8000;
# lab is OFF until aegis-lab --enable; GUI starts only via `aegis-gui`.
#
# Base stays Debian 12 bookworm. Real Hyprland/Quickshell are NOT in this
# image: current Hyprland needs C++26 (gcc>=16; bookworm has gcc 12.2) and
# Quickshell needs Qt>=6.6 (bookworm has 6.4.2). See README-v5.md.
# A Debian 13 trixie rebase for real Hyprland is a v6 candidate only.
#
# Usage:  ./build-image.sh [output-dir]
# Default output dir: the directory containing this script.
# Produces: aegis-v5.img (raw, MBR + GRUB BIOS, single ext4 partition)
#           aegis-v5.img.sha256
# Image size default 5120 MiB (matches the live v4 image size).
#
# Why no loop devices? Same as v4: rootfs built with debootstrap +
# chroot, packed with `mkfs.ext4 -d <rootfs>`, GRUB BIOS installed
# manually. Boots in QEMU and can be dd'd to a USB stick.
#
# Requirements (host): debootstrap, grub-mkimage, mkfs.ext4, python3.
# Set -euo pipefail; every step logs to stdout (redirect to logs/ to keep).
set -euo pipefail

OUT="${1:-$(cd "$(dirname "$0")" && pwd)}"
# Canonicalize OUT to an absolute path: fakechroot needs an ABSOLUTE
# FAKECHROOT_BASE (v5 bug found 2026-11-14 — with a relative base,
# `chown -R` inside the labinit failed with ENOENT on every child, so
# labinit died at chown and flag2/FIM/colours were never created on
# REUSE builds; on clean builds setup-v5.sh had already made them, which
# masked it). ROOTFS/WORK/IMG all derive from OUT, so fix it once here.
OUT="$(cd "$OUT" && pwd)"
SRC="$(cd "$(dirname "$0")" && pwd)"
WORK="$OUT/.build"
ROOTFS="$WORK/rootfs"
IMG="$OUT/aegis-v5.img"
IMG_SIZE_MB="${IMG_SIZE_MB:-5120}"
PART_OFFSET_MB=1

log() { echo "[build] $*"; }
die() { echo "[build] ERROR: $*" >&2; exit 1; }

command -v debootstrap >/dev/null || die "debootstrap not found"
command -v grub-mkimage >/dev/null || die "grub-mkimage not found (install grub-pc-bin)"
command -v mkfs.ext4 >/dev/null || die "mkfs.ext4 not found"
command -v debugfs >/dev/null || die "debugfs not found (install e2fsprogs)"
command -v python3 >/dev/null || die "python3 not found"

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

# --- 1. debootstrap: real Debian bookworm, minimal -------------------------
log "debootstrap bookworm (this downloads ~300MB)..."
fakechroot fakeroot debootstrap --arch=amd64 --variant=fakechroot bookworm "$ROOTFS" http://deb.debian.org/debian
if [ -x "$ROOTFS/debootstrap/debootstrap" ]; then
  log "running debootstrap second stage under fakechroot..."
  fakechroot fakeroot chroot "$ROOTFS" /debootstrap/debootstrap --second-stage || true
fi
fi
mkdir -p "$WORK" "$ROOTFS"

# --- 2. inside the chroot: real kernel, systemd, defensive tools -----------
if [ "$REUSE" = 0 ]; then
log "configuring rootfs..."
cat > "$ROOTFS/etc/apt/sources.list" <<'EOF'
deb http://deb.debian.org/debian bookworm main contrib non-free-firmware
deb http://deb.debian.org/debian-security bookworm-security main contrib non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib non-free-firmware
EOF
printf 'aegis\n' > "$ROOTFS/etc/hostname"
printf '127.0.0.1 localhost aegis\n::1 localhost ip6-localhost ip6-loopback\n' > "$ROOTFS/etc/hosts"

mkdir -p "$ROOTFS/etc/systemd/system/getty.target.wants"
ln -sf /usr/lib/systemd/system/getty@.service \
  "$ROOTFS/etc/systemd/system/getty.target.wants/getty@tty1.service"
ln -sf /usr/lib/systemd/system/serial-getty@.service \
  "$ROOTFS/etc/systemd/system/getty.target.wants/serial-getty@ttyS0.service"

cp "$SRC/server.py" "$ROOTFS/usr/local/lib/aegis-server.py"
chmod 755 "$ROOTFS/usr/local/lib/aegis-server.py"
mkdir -p "$ROOTFS/opt/aegis"

mount -t proc proc "$ROOTFS/proc" 2>/dev/null || true
cat > "$ROOTFS/tmp/setup.sh" <<'SETUP_EOF'
set -eux
export DEBIAN_FRONTEND=noninteractive
if [ -x /usr/bin/systemd-sysusers ]; then
  cp /usr/bin/systemd-sysusers /tmp/systemd-sysusers.real || true
  printf '#!/bin/sh\nexit 0\n' > /usr/bin/systemd-sysusers
  chmod +x /usr/bin/systemd-sysusers || true
  trap 'cp /tmp/systemd-sysusers.real /usr/bin/systemd-sysusers 2>/dev/null || true' EXIT
  groupadd -r polkitd 2>/dev/null || true
  useradd -r -g polkitd -d /nonexistent -s /usr/sbin/nologin -c "polkit" polkitd 2>/dev/null || true
fi
apt-get update
apt-get install -y --no-install-recommends \
  linux-image-amd64 systemd systemd-sysv openssh-server dbus dbus-x11 \
  python3 python3-pil libjpeg62-turbo python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  iproute2 iputils-ping procps psmisc nmap tcpdump \
  tshark wireshark-common openssl curl ca-certificates sudo \
  netbase ifupdown isc-dhcp-client kmod e2fsprogs util-linux \
  sway swaybg swayidle swaylock xwayland waybar \
  libgtk-layer-shell0 gir1.2-gtklayershell-0.1 foot grim slurp mako-notifier playerctl \
  libgl1-mesa-dri mesa-utils-bin \
  firefox-esr \
  network-manager wpasupplicant wireless-tools iw \
  pciutils usbutils lshw firmware-linux upower acpi htop auditd nftables
# OpenSSH: installed but MASKED by default (lab use only, see README-v5).
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
# Lab users (created here in the clean build; setup-v5.sh recreates them idempotently)
id labweb 2>/dev/null || useradd -r -d /srv/labapp -s /usr/sbin/nologin labweb
id labuser 2>/dev/null || useradd -m -s /bin/bash labuser
echo 'labuser:lab123' | chpasswd
# AegisOS console service (localhost only, see server.py).
cp /usr/local/lib/aegis-server.py /opt/aegis/server.py
cat > /etc/systemd/system/aegis.service <<'UNIT_EOF'
[Unit]
Description=AegisOS v5 console (localhost by default, LAN only in lab mode)
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
if [ -f /tmp/systemd-sysusers.real ]; then
  cp /tmp/systemd-sysusers.real /usr/bin/systemd-sysusers || true
  rm -f /tmp/systemd-sysusers.real
fi
# Default target: multi-user (CLI). No display manager is enabled on purpose:
# the GUI starts ONLY when the user runs `aegis-gui` (see bin/aegis-gui).
ln -sf /lib/systemd/system/multi-user.target /etc/systemd/system/default.target
apt-get clean
rm -rf /var/lib/apt/lists/*
SETUP_EOF
chmod +x "$ROOTFS/tmp/setup.sh"
FC_LIB="$(ls /usr/lib/x86_64-linux-gnu/fakechroot/libfakechroot.so /usr/lib/*/fakechroot/libfakechroot.so 2>/dev/null | head -1)"
FR_LIB="$(ls /usr/lib/x86_64-linux-gnu/libfakeroot/libfakeroot-sysv.so /usr/lib/*/libfakeroot/libfakeroot-sysv.so 2>/dev/null | head -1)"
[ -n "$FC_LIB" ] && [ -n "$FR_LIB" ] || die "libfakechroot or libfakeroot not found (install fakechroot, fakeroot)"
FAKECHROOT_BASE="$ROOTFS" FAKECHROOT_EXCLUDE_PATH=/dev:/proc:/sys \
  LD_PRELOAD="$FC_LIB:$FR_LIB" "$ROOTFS/bin/bash" /tmp/setup.sh
rm -f "$ROOTFS/tmp/setup.sh"
python3 - "$ROOTFS" <<'PYEOF'
import os, sys
root = sys.argv[1]
marker = "/.build/rootfs"
fixed = 0
for dirpath, dirnames, filenames in os.walk(root):
    for name in dirnames + filenames:
        p = os.path.join(dirpath, name)
        if os.path.islink(p):
            t = os.readlink(p)
            # A stale host-prefixed target from an earlier build dir name
            # (e.g. after the secureos-v5 -> aegis-v5 rename) does not start
            # with the current root path — catch it via the marker too.
            # This exact miss broke run 4: 353 symlinks (incl. /sbin/init)
            # survived and the guest kernel-panicked with no /sbin/init.
            if not t.startswith(root) and marker in t:
                t = t.split(marker, 1)[1] or "/"
                os.unlink(p); os.symlink(t, p); fixed += 1; continue
            if t.startswith(root):
                os.unlink(p)
                os.symlink(t[len(root):], p)
                fixed += 1
print(f"[build] fixed {fixed} host-prefixed symlinks")
PYEOF
umount "$ROOTFS/proc" 2>/dev/null || true
fi  # end REUSE=0 configure+setup block

# --- 2b. GUI stack check (v4 bug fix: helpers must never be silently dropped)
# A clean build installs sway in setup.sh above. If it is missing, fail
# loudly instead of shipping an image whose GUI cannot start.
[ -x "$ROOTFS/usr/bin/sway" ] || die "sway missing from rootfs after setup (clean build failed)"
[ -x "$ROOTFS/usr/bin/swaylock" ] || die "swaylock missing from rootfs after setup"
# Layer-shell typelib check (v5 layout bug fix): aegis-shell.py drives the
# desktop through GtkLayerShell via PyGObject. The C library alone
# (libgtk-layer-shell0) is NOT enough — without the typelib
# gir1.2-gtklayershell-0.1, gi.require_version("GtkLayerShell") fails,
# the shell silently falls back to plain windows, and sway floats them all
# centred on top of each other (v5 repack #3 screenshots). Fail the build
# if the typelib is absent so a broken desktop can never ship again.
[ -f "$ROOTFS/usr/lib/x86_64-linux-gnu/girepository-1.0/GtkLayerShell-0.1.typelib" ] || die "GtkLayerShell typelib missing from rootfs (gir1.2-gtklayershell-0.1 not installed)"

# --- Install ALL aegis-* CLI helpers (always, from $SRC/bin, so none is stale)
mkdir -p "$ROOTFS/usr/local/bin"
for h in aegis-gui aegis-status aegis-logs aegis-net aegis-drivers aegis-lab aegis-ir aegis-fim aegis-lab-reset-flags; do
  if [ -f "$SRC/bin/$h" ]; then cp "$SRC/bin/$h" "$ROOTFS/usr/local/bin/$h"; chmod 755 "$ROOTFS/usr/local/bin/$h";
  else die "missing helper in v5 folder: bin/$h"; fi
done
# --- v5 lab files (always, so they are never stale) -----------------------
mkdir -p "$ROOTFS/srv/labapp/plugins" "$ROOTFS/srv/labapp/public" "$ROOTFS/srv/labapp/flags" "$ROOTFS/var/log/aegis-lab" "$ROOTFS/var/lib/aegis-lab" "$ROOTFS/etc/aegis-lab"
cp "$SRC/labapp.py" "$ROOTFS/srv/labapp/labapp.py"
cp "$SRC/server.py" "$ROOTFS/opt/aegis/server.py"
cp "$SRC/v5-console.js" "$ROOTFS/opt/aegis/v5-console.js"
cp "$SRC/aegis-labapp.service" "$SRC/aegis-ssh-lab.service" "$SRC/aegis.service" "$ROOTFS/etc/systemd/system/"
# Lab units must NEVER be enabled at boot (v5 repack #3 regression — see
# README-v5.md). Defence in depth, two layers:
#  1. The lab unit files have NO [Install] section, so preset/enable
#     cannot enable them; they start only via explicit `systemctl restart`.
#  2. This preset file explicitly disables them, so even if an [Install]
#     section is re-added later, first-boot preset population keeps them off.
mkdir -p "$ROOTFS/etc/systemd/system-preset"
printf 'disable aegis-labapp.service\ndisable aegis-ssh-lab.service\n' > "$ROOTFS/etc/systemd/system-preset/00-aegis-lab.preset"
printf 'disabled\n' > "$ROOTFS/etc/aegis-lab/state"
# Auditd rules (renamed keys; watch the aegis paths)
cat > "$ROOTFS/etc/audit/rules.d/aegis-lab.rules" <<'EOF'
-w /srv/labapp -p wa -k aegis_lab
-w /home/labuser -p wa -k aegis_labuser
-w /etc/aegis-lab -p wa -k aegis_labstate
EOF
# --- Saral 0.3.0 (NEW in v5 — was never in the v4 image) -------------------
mkdir -p "$ROOTFS/usr/local/lib/saral/libs"
cp "$SRC/saral/saral.py" "$ROOTFS/usr/local/bin/saral"
chmod 755 "$ROOTFS/usr/local/bin/saral"
cp -r "$SRC/saral/libs/." "$ROOTFS/usr/local/lib/saral/libs/"
# --- Wayland desktop files --------------------------------------------------
mkdir -p "$ROOTFS/usr/local/lib/aegis-shell" "$ROOTFS/usr/share/aegis/wallpapers" "$ROOTFS/home/analyst/.config/sway" "$ROOTFS/home/analyst/.config/aegis"
cp "$SRC/wayland/aegis-shell.py" "$SRC/wayland/aegis-colours.py" "$ROOTFS/usr/local/lib/aegis-shell/"
cp "$SRC/wayland/aegis-wallpaper" "$ROOTFS/usr/local/bin/aegis-wallpaper"
chmod 755 "$ROOTFS/usr/local/lib/aegis-shell/aegis-shell.py" "$ROOTFS/usr/local/lib/aegis-shell/aegis-colours.py" "$ROOTFS/usr/local/bin/aegis-wallpaper"
ln -sf /usr/local/lib/aegis-shell/aegis-shell.py "$ROOTFS/usr/local/bin/aegis-shell"
ln -sf /usr/local/lib/aegis-shell/aegis-colours.py "$ROOTFS/usr/local/bin/aegis-colours"
cp "$SRC/wayland/wallpapers/"*.png "$ROOTFS/usr/share/aegis/wallpapers/"
cp "$SRC/wayland/sway-config" "$ROOTFS/home/analyst/.config/sway/config"
cp "$ROOTFS/usr/share/aegis/wallpapers/aegis-starfield.png" "$ROOTFS/home/analyst/.config/aegis/wallpaper.png"
# Permission fix (v5 bug, found by guest-test-v5 run 1): the host shell runs
# under umask 0007, so cp'ed dirs land 770 and files 660 — analyst could
# not read /usr/share/aegis/wallpapers or /usr/local/lib/saral/libs, and
# `which aegis-shell` failed (unresolvable symlink target). Normalize:
chmod 755 "$ROOTFS/usr/share/aegis" "$ROOTFS/usr/share/aegis/wallpapers" \
  "$ROOTFS/usr/local/lib/aegis-shell" "$ROOTFS/usr/local/lib/saral" "$ROOTFS/usr/local/lib/saral/libs"
chmod 644 "$ROOTFS/usr/share/aegis/wallpapers/"*.png "$ROOTFS/usr/local/lib/saral/libs/"*.py
chmod 644 "$ROOTFS/usr/local/lib/saral/libs/greet_bridge/"* 2>/dev/null || true
# --- Lab DB/flags + FIM manifest + theme, inside the chroot -----------------
# labapp.init_db() creates the SQLite DB + flag3 (random); flag2 is
# generated the same way aegis-lab-reset-flags does it. FIM manifest is
# written after the DB exists so --check starts clean.
mount -t proc proc "$ROOTFS/proc" 2>/dev/null || true
FC_LIB="$(ls /usr/lib/x86_64-linux-gnu/fakechroot/libfakechroot.so /usr/lib/*/fakechroot/libfakechroot.so 2>/dev/null | head -1)"
FR_LIB="$(ls /usr/lib/x86_64-linux-gnu/libfakeroot/libfakeroot-sysv.so /usr/lib/*/libfakeroot/libfakeroot-sysv.so 2>/dev/null | head -1)"
[ -n "$FC_LIB" ] && [ -n "$FR_LIB" ] || die "libfakechroot or libfakeroot not found (install fakechroot, fakeroot)"
cat > "$ROOTFS/tmp/v5-labinit.sh" <<'LABINIT_EOF'
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
python3 /usr/local/lib/aegis-shell/aegis-colours.py /home/analyst/.config/aegis/wallpaper.png --out /home/analyst/.config/aegis || \
  echo "COLOURS_FAILED (fakechroot cannot load libjpeg.so.62 — library IS in the image; aegis-gui regenerates the theme on first GUI start)"
chown -R analyst:analyst /home/analyst/.config
# Saral check (guest python + installed libs)
/usr/local/bin/saral version || echo "SARAL_CHECK_FAILED (see log)"
LABINIT_EOF
chmod +x "$ROOTFS/tmp/v5-labinit.sh"
FAKECHROOT_BASE="$ROOTFS" FAKECHROOT_EXCLUDE_PATH=/dev:/proc:/sys \
  LD_PRELOAD="$FC_LIB:$FR_LIB" "$ROOTFS/bin/bash" /tmp/v5-labinit.sh || log "WARNING: v5-labinit.sh failed — DB/flags/FIM/theme may be incomplete (guest setup-v5.sh redoes them)"
rm -f "$ROOTFS/tmp/v5-labinit.sh"
umount "$ROOTFS/proc" 2>/dev/null || true
chown -R 1000:1000 "$ROOTFS/home/analyst/.config"

# --- 3. console frontend into /opt/aegis ------------------------------------
# Frontend source: a FRESH checkout of remote main (AegisOS repo, HEAD
# 1a10d2db on 2026-11-12), vendored into $SRC/frontend with the rename
# applied. AEGIS_REPO_ROOT may point at a fresh clone instead; the stale
# loveos-repo snapshot is NEVER used. Only v5-console.js is injected —
# no phantom v2/v3 console JS (v4 bug fix).
REPO_ROOT="${AEGIS_REPO_ROOT:-}"
if [ -z "$REPO_ROOT" ]; then
  if [ -f "$SRC/frontend/index.html" ]; then REPO_ROOT="$SRC/frontend";
  else die "no frontend found: $SRC/frontend/index.html missing and AEGIS_REPO_ROOT unset"; fi
fi
log "repo root for console frontend: $REPO_ROOT"
for f in index.html app.js style.css; do
  [ -f "$REPO_ROOT/$f" ] && cp "$REPO_ROOT/$f" "$ROOTFS/opt/aegis/"
done
cp -r "$REPO_ROOT/apps" "$ROOTFS/opt/aegis/" 2>/dev/null || true
if [ -d "$REPO_ROOT/aegis" ]; then
  cp -r "$REPO_ROOT/aegis" "$ROOTFS/opt/aegis/"
elif [ -d "$REPO_ROOT/secureos" ]; then
  # Fresh-clone layout (pre-rename dir name): copy as aegis/ so the
  # renamed index.html script paths resolve.
  cp -r "$REPO_ROOT/secureos" "$ROOTFS/opt/aegis/aegis"
fi
cp "$SRC/server.py" "$ROOTFS/opt/aegis/server.py"
cp "$SRC/v5-console.js" "$ROOTFS/opt/aegis/v5-console.js"
# Inject ONLY v5-console.js, and only if the file actually exists in /opt/aegis.
if grep -q 'app.js' "$ROOTFS/opt/aegis/index.html" 2>/dev/null; then
  python3 - "$ROOTFS/opt/aegis/index.html" <<'PYEOF'
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
  if [ -L "$ROOTFS/$d" ]; then rm "$ROOTFS/$d"; mkdir "$ROOTFS/$d"; fi
done
ln -sf /dev/null "$ROOTFS/etc/systemd/system/ssh.service"
ln -sf /dev/null "$ROOTFS/etc/systemd/system/ssh.socket"
ln -sf /dev/null "$ROOTFS/etc/systemd/system/sshd.service"
ln -sf /lib/systemd/system/multi-user.target "$ROOTFS/etc/systemd/system/default.target"
# Lab services must stay OFF by default (v5 repack #3: systemd's first-boot
# preset population enabled them because they had [Install] sections —
# since fixed by removing [Install]; see README-v5.md. Explicit disable
# here is a no-op if they are already off, and removes any stray wants
# symlink.)
chroot "$ROOTFS" systemctl disable aegis-labapp.service aegis-ssh-lab.service 2>/dev/null || true
chmod 644 "$ROOTFS/etc/systemd/system/aegis.service" 2>/dev/null || true
chmod 644 "$ROOTFS/etc/systemd/system/aegis-labapp.service" "$ROOTFS/etc/systemd/system/aegis-ssh-lab.service" 2>/dev/null || true  # units were 660 (systemd "world-inaccessible" warning)
chmod -R a+rX "$ROOTFS/opt/aegis" 2>/dev/null || true
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
                # stale host-prefixed target from an earlier build dir name
                # (e.g. after the secureos-v5 -> aegis-v5 rename); see above
                new = t.split("/.build/rootfs", 1)[1] or "/"
                os.unlink(p); os.symlink(new, p); fixed += 1
print(f"[build] final symlink sweep fixed {fixed}")
PYEOF
rm -f "$ROOTFS/boot"/initrd.img-*.dpkg-bak "$ROOTFS/boot"/initrd.img-*.new
KERNEL="$(ls "$ROOTFS/boot"/vmlinuz-* | head -1 | xargs basename)"
INITRD="$(ls "$ROOTFS/boot"/initrd.img-* | head -1 | xargs basename)"
[ -n "$KERNEL" ] || die "no kernel found in rootfs /boot"
mkdir -p "$ROOTFS/boot/grub"
cat > "$ROOTFS/boot/grub/grub.cfg" <<GRUB_EOF
set timeout=5
set default=0
menuentry "AegisOS v5" {
  set root=(hd0,msdos1)
  linux /boot/$KERNEL root=/dev/sda1 rw console=tty0 console=ttyS0,115200
  initrd /boot/$INITRD
}
GRUB_EOF
printf '/dev/sda1 / ext4 defaults 0 1\n' > "$ROOTFS/etc/fstab"

# --- 5. pack rootfs into ext4 WITHOUT mounting (mkfs.ext4 -d) --------------
log "packing ext4 filesystem (${IMG_SIZE_MB}MB image, partition at ${PART_OFFSET_MB}MiB)..."
FS_SIZE_MB=$((IMG_SIZE_MB - PART_OFFSET_MB))
mkfs.ext4 -q -O ^metadata_csum,^64bit -d "$ROOTFS" -L aegis "$WORK/root.ext4" "${FS_SIZE_MB}M"

# --- 6. assemble raw disk: MBR partition table + GRUB BIOS ------------------
log "assembling raw disk image..."
python3 - "$IMG" "$WORK/root.ext4" "$PART_OFFSET_MB" <<'PYEOF'
import struct, sys
img_path, fs_path, off_mb = sys.argv[1], sys.argv[2], int(sys.argv[3])
off = off_mb * 1024 * 1024
with open(fs_path, "rb") as f:
    fs = f.read()
total = off + len(fs)
with open(img_path, "wb") as out:
    out.truncate(total)
    mbr = bytearray(512)
    sectors = len(fs) // 512
    entry = struct.pack("<BBBBBBBBII", 0x80, 0, 2, 0, 0x83, 0xFE, 0xFF, 0xFF,
                        off // 512, sectors)
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    out.seek(0); out.write(mbr)
    out.seek(off); out.write(fs)
print(f"image bytes={total} fs_bytes={len(fs)}")
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

# --- 6b. lab-off-by-default gate: the packed filesystem must contain NO
# wants-symlink for the lab units. (v5 repack #3 packed clean, yet the
# first boot enabled them via systemd's first-boot preset population —
# the units have since lost their [Install] sections, so this gate also
# guards against an [Install] section silently coming back.)
if debugfs -R "ls /etc/systemd/system/multi-user.target.wants" "$WORK/root.ext4" 2>/dev/null | grep -q "aegis-labapp\|aegis-ssh-lab"; then
  echo "[build] ERROR: lab-off gate failed — lab units are enabled in the packed filesystem:" >&2
  debugfs -R "ls /etc/systemd/system/multi-user.target.wants" "$WORK/root.ext4" 2>/dev/null | grep "aegis-lab" >&2
  exit 1
fi
log "lab-off gate passed (no lab wants-symlinks in packed filesystem)"

# --- 7. rename gate: no 'secureos' (case-insensitive) in shipped v5 files ---
# Exception, documented in README-v5.md: SECUREOS_BIND_IP and
# SECUREOS_ALLOW_PUBLIC are kept unchanged (4 places must agree).
# Excluded from the gate by design (they deliberately name the old brand):
#   audit-v4.md, research-hyprland.md (historical docs),
#   README-v5.md (its rename map documents the old names),
#   build-image.sh itself (it holds the upstream pre-rename directory
#   compatibility check and this gate's own search pattern).
# Binary artifacts are excluded from the text gate (they cannot be
# line-filtered for the env-var exception; the image contents are
# verified separately on the rootfs before packing).
# Everything that ships INTO the image is gated: server.py, labapp.py,
# bin/*, units, wayland/*, frontend/*, saral/*, setup-v5.sh, guest scripts.
if grep -ri "secureos" "$SRC" --exclude-dir=.build --exclude-dir=logs --exclude-dir=screenshots --exclude-dir=__pycache__ \
     --exclude=audit-v4.md --exclude=research-hyprland.md --exclude=README-v5.md --exclude=build-image.sh \
     --exclude="*.img" --exclude="*.sha256" --exclude="*.pyc" \
     | grep -v "SECUREOS_BIND_IP" | grep -v "SECUREOS_ALLOW_PUBLIC" | grep -q .; then
  echo "[build] ERROR: rename gate failed — 'secureos' leftovers (excluding the env-var exception):" >&2
  grep -ri "secureos" "$SRC" --exclude-dir=.build --exclude-dir=logs --exclude-dir=screenshots --exclude-dir=__pycache__ \
     --exclude=audit-v4.md --exclude=research-hyprland.md --exclude=README-v5.md --exclude=build-image.sh \
     --exclude="*.img" --exclude="*.sha256" --exclude="*.pyc" \
     | grep -v "SECUREOS_BIND_IP" | grep -v "SECUREOS_ALLOW_PUBLIC" >&2
  exit 1
fi
log "rename gate passed (only SECUREOS_BIND_IP / SECUREOS_ALLOW_PUBLIC remain)"

(cd "$OUT" && sha256sum "$(basename "$IMG")" | tee "$IMG.sha256")
log "DONE: $IMG"
ls -lh "$IMG"
du -sh "$ROOTFS"
