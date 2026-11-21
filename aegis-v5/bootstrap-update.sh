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
# the v5.0.3 file (preflight guard from v5.0.2 + WLR_NO_HARDWARE_CURSORS
# cursor fix), so a bootstrapped system also gets the serial-console
# preflight and the visible cursor; the version file still reads 5.0.1,
# so `aegis-update` may later offer the v5.0.2/v5.0.3 update again —
# re-applying identical files, harmless.)
FILES="aegis-v5/wayland/aegis-shell.py|/usr/local/bin/aegis-shell|a862c7aa67987f82f5dd94e38fd4fe9c0c53b0cda64a74c4033cdfe49ea60edb
aegis-v5/bin/aegis-gui|/usr/local/bin/aegis-gui|b92cc53595ef7cca9f26f9779b976dc15f82b20c34797ca2bd8ff154e62dbd98
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
# v5.0.3: verify EVERY install, file by file. The old loop printed
# "installed ..." unconditionally and finished with "done" even when
# cp/chmod failed — on a corrupted filesystem ("Structure needs
# cleaning") two of four files failed to install and the script still
# claimed success. Now a failed copy, a failed chmod, or a hash
# mismatch AFTER install aborts everything with a clear error naming
# the file, no "done" line, and a non-zero exit.
install_failed=0
while IFS='|' read -r src dest hash; do
  [ -n "$src" ] || continue
  # cp follows the /usr/local/bin/aegis-shell symlink, so the real file
  # under /usr/local/lib/aegis-shell/ is what gets replaced.
  if ! cp "$TMP/$(basename "$src")" "$dest"; then
    echo "bootstrap-update: INSTALL FAILED for $src -> $dest (cp failed — check the disk, e.g. filesystem corruption) — aborting, system is NOT updated" >&2
    install_failed=1; break
  fi
  if ! chmod 755 "$dest"; then
    echo "bootstrap-update: INSTALL FAILED for $dest (chmod failed — check the disk) — aborting, system is NOT updated" >&2
    install_failed=1; break
  fi
  got="$(sha256sum "$dest" 2>/dev/null | cut -d' ' -f1)"
  if [ "$got" != "$hash" ]; then
    echo "bootstrap-update: INSTALL FAILED for $dest (installed file hash $got != expected $hash — the write did not land) — aborting, system is NOT updated" >&2
    install_failed=1; break
  fi
  echo "  installed $dest (verified)"
done <<EOF
$FILES
EOF
if [ "$install_failed" != "0" ]; then
  exit 1
fi

printf '5.0.1\n' > /etc/aegis-version
chmod 644 /etc/aegis-version
echo "bootstrap-update: done — system is now 5.0.1 with aegis-update installed."
echo "Run: aegis-update check"
