#!/bin/bash
# bootstrap-update.sh — bring a running AegisOS v5.0.0 / v5.0.1 system up
# to v5.0.1 AND install the aegis-update command, without re-downloading
# the whole 5 GB image.
#
# Those images shipped before the updater existed, so this script fetches
# the four changed/new files straight from GitHub main, verifies every
# file's SHA256 against the hashes baked into this script, and only then
# installs them. ANY hash mismatch aborts everything — nothing is
# installed and nothing is half-updated.
#
# Usage (inside the running VM, as analyst):
#   curl -fsSL https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main/aegis-v5/bootstrap-update.sh -o /tmp/bootstrap-update.sh
#   sudo bash /tmp/bootstrap-update.sh
#
# Test hook: AEGIS_RAW_BASE overrides the download base URL
# (default https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main).
# The QEMU test rig points it at a local HTTP server; normal use never sets it.
set -u
BASE="${AEGIS_RAW_BASE:-https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main}"
TMP="$(mktemp -d /tmp/aegis-bootstrap.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

if [ "$(id -u)" -ne 0 ]; then
  echo "bootstrap-update: run as root — sudo bash bootstrap-update.sh" >&2
  exit 2
fi

# src-path | destination | sha256 (hashes of the v5.0.1 files on main, commit
# cc3cd36, plus bin/aegis-update as written for v5.0.2 — re-compute the
# hashes if any of these files changes. NOTE: the aegis-gui hash below is
# the v5.0.2 file (preflight guard added after cc3cd36), so a bootstrapped
# system also gets the serial-console preflight; the version file still
# reads 5.0.1, so `aegis-update` may later offer the v5.0.2 patch again —
# re-applying identical files, harmless.)
FILES="aegis-v5/wayland/aegis-shell.py|/usr/local/bin/aegis-shell|a862c7aa67987f82f5dd94e38fd4fe9c0c53b0cda64a74c4033cdfe49ea60edb
aegis-v5/bin/aegis-gui|/usr/local/bin/aegis-gui|9c96c90f343f7945b4a71f95a0db59537fa29a0509ce356243ab42d02cc2058d
aegis-v5/serial-shell-test-v501.py|/usr/local/bin/serial-shell-test-v501.py|53e0703bdd1400d7a0e36ba805ee2a5ba71b1a3e13b42a50b7f3b806b5154a6b
aegis-v5/bin/aegis-update|/usr/local/bin/aegis-update|a17a47bb25504514557362e13e87aa802e9411f2e2af53cf3494e79796daea63"

echo "bootstrap-update: downloading 4 files from $BASE ..."
while IFS='|' read -r src dest hash; do
  [ -n "$src" ] || continue
  if ! curl -fsSL "$BASE/$src" -o "$TMP/$(basename "$src")"; then
    echo "bootstrap-update: DOWNLOAD FAILED for $src — aborting, nothing installed" >&2
    exit 1
  fi
done <<EOF
$FILES
EOF

# Verify every hash BEFORE installing anything.
while IFS='|' read -r src dest hash; do
  [ -n "$src" ] || continue
  f="$TMP/$(basename "$src")"
  got="$(sha256sum "$f" | cut -d' ' -f1)"
  if [ "$got" != "$hash" ]; then
    echo "bootstrap-update: HASH MISMATCH for $src (got $got, expected $hash) — aborting, nothing installed" >&2
    exit 1
  fi
  echo "  ok $src"
done <<EOF
$FILES
EOF

echo "bootstrap-update: all hashes verified — installing ..."
while IFS='|' read -r src dest hash; do
  [ -n "$src" ] || continue
  # cp follows the /usr/local/bin/aegis-shell symlink, so the real file
  # under /usr/local/lib/aegis-shell/ is what gets replaced.
  cp "$TMP/$(basename "$src")" "$dest"
  chmod 755 "$dest"
  echo "  installed $dest"
done <<EOF
$FILES
EOF

printf '5.0.1\n' > /etc/aegis-version
chmod 644 /etc/aegis-version
echo "bootstrap-update: done — system is now 5.0.1 with aegis-update installed."
echo "Run: aegis-update check"
