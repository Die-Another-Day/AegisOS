# AegisOS v6

Real bootable Debian 13 "trixie" OS — Nebula-style Hyprland desktop,
Red vs Blue lab (off by default), Saral 0.3.0 built in.

## What's new in v6 (vs v5.0.3)

- **Debian 13 trixie** (kernel 6.12 LTS) instead of Debian 12 bookworm.
- **Real Hyprland 0.55.2 + Quickshell 0.3.0** (trixie-backports) replace
  sway + the GTK layer-shell shell. Animations, rounded corners, blur,
  a Quickshell top bar, app launcher, right-click desktop menu, and a
  Nebula-style Quickshell lock screen (PAM unlock).
- **Plymouth boot splash** — text-only "AegisOS" fade-in theme.
- **Google Chrome** is the default browser (Firefox-ESR stays as fallback).
- **Animated wallpaper** via swww (built from source) with the new
  `aegis-v6` wallpaper; hyprpaper is the static fallback.
- **`aegis-tools`** — install security tools by command: Debian-packaged
  tools (nmap, sqlmap, nikto, hydra, john, aircrack-ng, tshark) are
  pre-installed; Burp Suite Community and OWASP ZAP install on demand
  from the vendors' official installers.
- **Logo slot** — the user designs the logo himself later (see below).
  No logo image is baked into v6.0.0.

## What carries over unchanged from v5

- Red vs Blue lab: labapp, SSH lab, IR (`aegis-ir`), FIM, flags,
  nftables containment. Lab is **OFF by default**; enable with
  `aegis-lab --enable`. Never binds 0.0.0.0; refuses public IPs.
- Console server on http://127.0.0.1:8000 (`/api/health` → AegisOS 6.0).
- Saral 0.3.0 (`saral version`).
- `aegis-update` + `bootstrap-update.sh` (full-image updates, streamed).
- BIOS GRUB, hostname `aegis`, login `analyst` / `secure` (change it),
  lab user `labuser` / `lab123` (lab only).
- The v5.0.3 cursor lesson: software cursors
  (`cursor:no_hardware_cursors = true` in hyprland.conf) — the DRM
  hardware-cursor plane failed on QEMU virtio-vga and VirtualBox VMSVGA.

## Logo slot (logo skipped in v6.0.0 — supplied later by the user)

Place the finished logo file at:

  /usr/share/aegis/logo.png   (512x512 PNG, transparent background preferred)

It is then picked up automatically by:
  * Boot splash — the Plymouth theme reads /usr/share/aegis/logo.png if present.
  * Lock screen — Quickshell shows it above the clock disc if present.
  * Desktop bar — the launcher button shows it (text "AegisOS" until then).
  * App launcher — the launcher header shows it if present.
Until the file exists, the OS uses the text "AegisOS" everywhere.
See also /usr/share/aegis/LOGO-SLOT-README.md inside the image.

## Updating (v6.0.0)

- `aegis-update check` — installed version (from /etc/aegis-version)
  vs latest GitHub release. Works as any user; fails gracefully offline.
- `aegis-update apply` (as root) — fetches the release's full image,
  streamed one part at a time (download, verify, append, delete — no
  combine step), verifies the staged image, prints STOP with flashing
  instructions — it never touches the booted disk. If the staged image
  already exists and verifies, the download is skipped; a corrupt
  staged image is deleted and re-downloaded. Patch bundles were
  removed 2026-11-24 (none was ever published, no builder exists).
- `bootstrap-update.sh` — for v6.0.0 systems: fetches changed files
  from GitHub main with SHA256 verification (installs are verified,
  see v5.0.3).

## GUI — where it can and cannot start (v6)

Hyprland needs the VM's own display (a real VT/seat). It can NEVER
start from a serial console, SSH session, or a WSL terminal window —
`aegis-gui` fails fast there with a clear message naming the working
paths (QEMU `-vnc :1` + VNC viewer, or VirtualBox's own display).
Run `aegis-gui` on tty1. QEMU needs a DRM-capable virtual GPU:
`qemu-system-x86_64 -m 2048 -hda aegis-v6.img -vga virtio -vnc :1`,
VNC to localhost:5901. Always shut down cleanly (`sudo poweroff`) —
a hard power-off can corrupt the ext4 filesystem ("Structure needs
cleaning"), which no updater can fix.

## Tools

- `aegis-tools list` — installed + on-demand tools.
- `aegis-tools install burpsuite` / `aegis-tools install zaproxy` —
  official vendor installers, checksum-verified where published.
- Plain `sudo apt install <anything>` works for everything in Debian's
  repos (the VM needs internet — VirtualBox NAT or QEMU user networking).

## Rename map (SecureOS → AegisOS)

Old name `secureos` must not appear anywhere in shipped files, except
the two environment variables kept deliberately unchanged (4 places must
agree): `SECUREOS_BIND_IP` and `SECUREOS_ALLOW_PUBLIC`. The build fails
(``rename gate``) on any other occurrence. Historical docs
(`audit-v4.md`, `research-hyprland.md`) are exempt.

## Building (from source)

  bash build-image.sh [output-dir]     # needs passwordless sudo (root debootstrap)
  # Produces aegis-v6.img (raw, MBR + GRUB BIOS) + aegis-v6.img.sha256

## Honest caveats (v6.0.0)

- Console API reports version 6.0; /etc/aegis-version is 6.0.0.
- Chrome launch is tested in QEMU; a live page load needs real internet
  (proven on the user's machine, not in the build sandbox).
- Burp Suite / ZAP installers are third-party downloads; the install
  itself is tested where the sandbox allows it, and labelled otherwise.
- Plymouth splash rendering in a VM is attempted in QEMU and labelled
  if the VM path cannot show it.
- VirtualBox cursor + lock-screen unlock are re-verified on the user's
  machine; QEMU is the proof available from the build machine.
