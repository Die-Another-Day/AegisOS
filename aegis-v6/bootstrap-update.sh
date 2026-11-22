#!/bin/bash
# bootstrap-update.sh — pull the latest AegisOS v6.0.x scripts straight
# from GitHub main onto a running v6 system, without re-downloading the
# whole image. (v6.0.0 ships with aegis-update; this is the escape hatch
# for script-only fixes that land on main between image releases.)
#
# Fetches the files below, verifies every file's SHA256 against the
# hashes baked into this script, and only then installs them. ANY hash
# mismatch aborts everything — nothing is installed and nothing is
# half-updated. Every install is verified afterwards too (the v5.0.3
# install-verification fix: a failed cp/chmod or a post-install hash
# mismatch aborts with a clear error, never a false "done").
#
# Usage (inside the running VM, as analyst):
#   curl -fsSL https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main/aegis-v6/bootstrap-update.sh -o /tmp/bootstrap-update.sh
#   sudo bash /tmp/bootstrap-update.sh
#
# Test hook: AEGIS_RAW_BASE overrides the download base URL
# (default https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main).
# The QEMU test rig points it at a local HTTP server; normal use never sets it.
#
# WARNING: do NOT run this on a corrupted disk (e.g. a WSL disk that
# reports "Structure needs cleaning") — repair/replace the disk first.
# The script aborts on a failed install, but it cannot fix a bad disk.
set -u
BASE="${AEGIS_RAW_BASE:-https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main}"
TMP="$(mktemp -d /tmp/aegis-bootstrap.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

if [ "$(id -u)" -ne 0 ]; then
  echo "bootstrap-update: run as root — sudo bash bootstrap-update.sh" >&2
  exit 2
fi

# src-path | destination | sha256 (hashes of the v6.0.0 files in this
# folder — re-compute the hashes if any of these files changes before
# pushing an update to this script).
# Recomputed 2026-11-22 after the -c aegis IPC fix (aegis-gui) and the
# v5-regex fix (aegis-update).
FILES="aegis-v6/src/bin/aegis-gui|/usr/local/bin/aegis-gui|943532f09479b61dbeed0b4272beecf6312d0757cb421141c795b16496f247a6
aegis-v6/bin/aegis-tools|/usr/local/bin/aegis-tools|7c3930e8fcfd8bac9cbdf3e5c64ebccbc1b21f6fd79eb182ce16df3d6470a22c
aegis-v6/src/bin/aegis-update|/usr/local/bin/aegis-update|222cf879c5c6204e4b41ed2f9688122adb899173b4c07e394c4410a1d31fbefb"

echo "bootstrap-update: downloading 3 files from $BASE ..."
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
install_failed=0
while IFS='|' read -r src dest hash; do
  [ -n "$src" ] || continue
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

printf '6.0.0\n' > /etc/aegis-version
chmod 644 /etc/aegis-version
echo "bootstrap-update: done — system is now 6.0.0 with the latest v6 scripts."
echo "Run: aegis-update check"
