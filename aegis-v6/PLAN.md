# AegisOS v6 — Rebase Plan (Debian 13 trixie + Hyprland + Quickshell)

Status: **Phase 1 — feasibility + logo options. GO. No hard blockers.**
Base: remote main head `edb867a` (v5.0.3). Nothing built, pushed, or released yet.

## 1. Feasibility verdict: GO

Every core component is available through official Debian channels
(trixie main + trixie-backports). The two pieces that are *not* in Debian
(swww, mpvpaper) have proven build-from-source precedents on Debian 13.

### Version table (all verified 2026-11-21/22, sources in §8)

| Component | Version | Source |
|---|---|---|
| Debian base | 13.7 "trixie" (point release) | deb.debian.org |
| Kernel | 6.12 LTS (6.12.113–6.12.117 current) | linux-image-amd64, trixie |
| systemd / glibc | 257 / 2.41 | trixie |
| Qt | 6.8.2 | trixie main |
| Hyprland | **0.55.2+ds-1~bpo13+1** | **trixie-backports** (NOT in trixie main) |
| aquamarine | 0.15.1-1~bpo13+1 | trixie-backports |
| hyprlock | 0.9.6-1~bpo13+1 | trixie-backports |
| hypridle | 0.1.8-1~bpo13+1 | trixie-backports |
| hyprpaper | 0.8.4-1~bpo13+1 | trixie-backports (static fallback) |
| hyprlauncher | 0.1.6-1~bpo13+1 | trixie-backports |
| hyprcursor | 0.1.13-2~bpo13+1 | trixie-backports |
| xdg-desktop-portal-hyprland | 1.4.1-1~bpo13+1 | trixie-backports |
| Quickshell | **0.3.0-1~bpo13+1** | **trixie-backports** (sid has 0.3.2) |
| Plymouth | 24.004.60-5 | trixie main (+ plymouth-themes) |
| waybar (fallback bar) | 0.12.0-1 | trixie main |
| nmap | 7.95+dfsg-3 (7.98 in backports) | trixie main |
| sqlmap | 1.9.6-1 | trixie main |
| nikto | 1:2.1.5-3.1 | trixie **non-free** (sources.list must add `non-free`) |
| hydra | 9.5-3 | trixie main |
| tcpdump | 4.99.5-2 | trixie main |
| Google Chrome | stable ~157.x, .deb ~138 MB | dl.google.com (official) |
| swww / mpvpaper | NOT in Debian (swww ITP #1084753) | build from source (see §4) |
| Burp Suite Community | NOT in Debian (Kali-only apt) | PortSwigger Linux installer |
| OWASP ZAP | NOT in Debian (Kali has 2.17.0) | official ZAP_x_unix.sh installer (2.15.0+ / 2.17.0) |

### Host toolchain — proven on this machine (2026-11-21)
- Host is Ubuntu 24.04. `debootstrap`, `qemu-system-x86` 8.2.2,
  `grub-pc-bin` 2.12, `fakechroot`, `fakeroot` were all missing and are
  now installed from Ubuntu repos.
- **Trixie debootstrap — fakechroot path FAILS, root path WORKS.**
  `fakechroot fakeroot debootstrap --variant=fakechroot trixie`
  downloads and unpacks fine (153 packages, `/etc/debian_version`
  13.8) but the second stage dies: `cron-daemon-common` postinst
  fails (`systemd-sysusers` can't load `libsystemd-shared-257.so`),
  then `fakechroot fakeroot chroot … --second-stage` aborts with
  `*** stack smashing detected ***` (SIGABRT, RC=134). Almost
  certainly the trixie glibc 2.41 > host glibc 2.39 preload mismatch
  (bookworm's 2.36 < host 2.39 is why v5's method worked).
  **Proven instead: plain root debootstrap** —
  `sudo debootstrap --variant=minbase trixie` completed cleanly
  ("I: Base system installed successfully.", 13.8, 211 MB),
  `sudo chroot … /bin/true` and apt 3.0.4 verified inside.
  `sudo mount -t proc` works on this host; `/dev` and `/proc` in a
  fakechroot rootfs are symlinks to the host (by design).
  **Phase 2 must switch the build from fakechroot to root
  (sudo) debootstrap + `sudo chroot` for setup** — the v5
  `systemd-sysusers` stub is no longer needed (drop it, verify).

### Proven combo (third-party, Debian 13)
Omarchy-on-Debian tested on **Debian 13.6 + Hyprland 0.55.2 (bpo13) +
Quickshell 0.3.0 (bpo13) + Qt 6.8.2** — the exact stack v6 will use,
with backports pinned to 100 so it only fills gaps and never upgrades
stable packages. Known Qt 6.8 QML quirks to code around: `transient` is
a reserved word in QML, `Qt.formatDate(t, fmt, locale)` 3-arg form fails
(use 2-arg + manual month names), Quickshell's process name is `qs`.

## 2. What carries over from v5 unchanged

- Red vs Blue lab: labapp, SSH lab, IR (`aegis-ir`), FIM, flags,
  nftables containment — all of it, byte-for-byte behaviour.
- Console server (`server.py` + frontend) on 127.0.0.1:8000.
- Saral 0.3.0.
- `aegis-update` + `bootstrap-update.sh` (VERSION bumps to 6.0.0;
  bootstrap's baked hashes update for the new `aegis-gui`).
- Lab OFF by default (units without `[Install]` + disable preset).
- BIOS GRUB + MBR raw image layout, hostname `aegis`,
  analyst / `secure`, `aegis-gui` as the GUI entry point.
- `adwaita-icon-theme` (cursor theme) stays installed.

## 3. What gets replaced

| v5 (sway) | v6 (Hyprland) |
|---|---|
| sway 1.7 + swaylock + swayidle + swaybg | Hyprland 0.55.2 + hyprlock + hypridle (+ hyprpaper static fallback) |
| GTK3/Python layer-shell shell (`aegis-shell.py`) — RETIRED | Quickshell 0.3.0 QML shell (bar, widgets, launcher, lock screen, right-click menu) |
| waybar (v5 top bar) | Quickshell bar (waybar kept as fallback only) |
| No boot splash | Plymouth 24.004.60-5 + custom AegisOS theme |
| Static wallpaper (swaybg) | swww (animated GIFs + transitions), built from source |
| Firefox-ESR only | Firefox-ESR + Google Chrome (default browser) |
| No tools installer | `aegis-tools install <name>` (see §5) |

### Desktop pieces to write in QML
- **Top bar**: workspaces, clock, network, battery, CPU/mem, system tray,
  app launcher button carrying the logo.
- **Lock screen**: Nebula-style, like the reel — starfield wallpaper,
  huge clock in a scalloped disc, music card, password field, logo.
  hyprlock is the fallback if the Quickshell lock proves unstable.
  Password check via PAM (Quickshell) — must be proven in the build
  gate; v5's `sudo -S true` check does not carry over.
- **Right-click menu** on the desktop: terminal, files, Chrome, tools,
  wallpaper picker, lock, power. (Hyprland has no built-in desktop
  menu; this is new code in the shell.)
- **Launcher**: hyprlauncher (backports) or Quickshell launcher.
- **Idle lock**: hypridle → hyprlock after 600 s (same timing as v5).

### Cursor note (carries a v5.0.3 lesson forward)
The v5.0.3 software-cursor workaround (`WLR_NO_HARDWARE_CURSORS=1`)
was wlroots+pixman specific and does **not** apply to Hyprland, which
renders with the GPU path. If the cursor vanishes on VirtualBox,
the Hyprland-native fallback is `cursor:no_hardware_cursors = true`
in `hyprland.conf`. Re-verify on the user's VirtualBox either way.

## 4. Logo — where it lands

Three options in `logo-options/` (1600×1600 PNG, dark navy background):
- `aegis-logo-ember-shield.png` — minimal gold shield, glowing ember
  star, circuit traces. Cleanest at small sizes. **Recommended.**
- `aegis-logo-hex-aegis.png` — angular hexagonal cyber-shield, teal
  facets, orange network node. Most "tech", weakest shield read.
- `aegis-logo-nebula-disc.png` — shield in a scalloped sunset disc,
  echoing the v5 lock-screen clock disc. Most Nebula, plainest centre.

**User must pick one before the build.** Once picked, the logo lands in:
- **Boot**: Plymouth theme (custom theme based on the stock `fade-in`
  theme — centred logo fading in/out with twinkling stars; needs
  initramfs rebuild + `splash` kernel parameter + GRUB config).
- **Lock screen**: centred above/below the clock disc (Quickshell).
- **Desktop**: launcher button in the top bar + a desktop widget.
- **Taskbar**: the launcher icon.
- **GRUB menu**: `grub2` theme background (optional, stretch goal).
- **Console web UI**: favicon + header (small, easy win).
- Sizes needed from the pick: 512 px master (have it), 256/128/64/48/32
  px downscales (generated at build time with Pillow), plus a
  monochrome single-colour variant for Plymouth (Plymouth themes are
  single-image; the disc option's flat shapes downscale best).

## 5. Wallpaper + animation

- Draft: `wallpaper-draft.png` (2048×1152, NEW — not the v5 starfield):
  deep navy starfield with nebula wisps, orange-red sunset band on the
  horizon, dark centre for icons/text.
- **Animation is not in the PNG.** It comes from the wallpaper engine:
  - **Primary: swww, built from source** with cargo at build time.
    Animated GIFs + smooth transitions. Proven on Debian 13 by the
    uConsole Hyprland dotfiles (same base, same backports Hyprland).
  - **Option: mpvpaper, built from source** — plays MP4/WebM video
    wallpapers (a rendered nebula drift loop). CPU-capped.
  - **Fallback: hyprpaper 0.8.4** (backports) — static only.
  - **Alternative: Quickshell QML Video background** via QtMultimedia
    (`qml6-module-qtmultimedia`, trixie main) — no extra daemon.
  - Known wart: `hyprctl hyprpaper wallpaper` can hang / spike CPU on
    some setups (uConsole finding) — prefer swww.
- Build-time decision: swww primary; mpvpaper if a video loop is wanted.
  An animated GIF/MP4 render of the draft wallpaper is a Phase 2 asset.

## 6. Tools installer + Chrome

### `aegis-tools install <name>` (new, `bin/aegis-tools`)
- **Debian-packaged (pre-installed in the image)**: nmap 7.95,
  sqlmap 1.9.6, nikto 2.1.5 (needs `non-free` in sources.list),
  hydra 9.5, tcpdump, tshark, john, aircrack-ng, plus the v5 set
  (wireshark-common, openssl, curl).
- **On-demand via installer (NOT pre-installed — size)**:
  - `burpsuite` → PortSwigger Linux installer
    (`https://portswigger.net/burp/communitydownload`), silent install,
    checksum verified, needs its bundled JRE.
  - `zaproxy` → official installer from zaproxy.org
    (`ZAP_<ver>_unix.sh`), silent install, checksum verified.
  - Refuses unknown names; prints the Debian-packaged list on
    `aegis-tools list`.
- Plain `sudo apt install <anything>` keeps working for everything in
  Debian's repos — the helper only exists for the two that aren't.

### Google Chrome (default browser, user's word)
- Download at build time:
  `https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb`
  (~138 MB, current stable ~157.x). Install with apt (pulls deps and
  adds the Google APT repo `google-chrome.sources`, so Chrome updates
  itself through normal `apt upgrade`).
- Wayland: patch the `.desktop` Exec to `--ozone-platform-hint=auto`
  (native Wayland under Hyprland; falls back to XWayland if needed).
- Firefox-ESR stays as the fallback browser.

## 7. Build pipeline changes (Phase 2)

- `build-image.sh`: debootstrap suite `bookworm` → `trixie`;
  **build method switches from fakechroot to root (sudo)
  debootstrap + `sudo chroot`** (fakechroot second stage aborts on
  trixie — see §1; the `systemd-sysusers` stub is dropped);
  sources.list gains `trixie-backports` (pin 100) + `non-free`;
  package list swaps sway stack → Hyprland stack + Quickshell +
  Plymouth + Qt6 multimedia + swww build deps (cargo/rustc from apt);
  Chrome .deb download + install; swww cargo build; Plymouth theme
  install; Quickshell QML deploy to `/etc/aegis/quickshell/` (or
  `~/.config/quickshell/`); logo downscales; `VERSION` → 6.0.0.
- New gates: Hyprland + `qs` binaries present; no sway remnants;
  Plymouth theme present in initramfs; Quickshell QML parses
  (`qs --help` / `qml` check); rename gate extended to trixie files.
- Image size grows: v5 was 5.0 GiB; v6 will be ~6–7 GiB (Chrome,
  Qt6, Quickshell, Plymouth). Release will be ~30+ parts at 20 MB.
  Flag to the user: bigger download.
- `aegis-gui` rewritten: start Hyprland (with the v5 preflight guard
  kept — serial console still fails fast), autostart Quickshell shell,
  hypridle, swww.

## 8. Test plan (QEMU gates, same discipline as v5)

1. CLI boot: console `/api/health` → AegisOS 6.0, lab off at boot.
2. GUI: Hyprland starts on VT (virtio-vga), lock screen renders with
   logo + visible cursor; unlock via typed password (PAM) works;
   desktop + Quickshell bar + right-click menu + launcher all render.
3. Wallpaper animation: swww running, GIF transitions proven in
   screenshots (two frames differ).
4. Chrome launches (page load needs real internet — launch-only in
   sandbox; live load on the user's machine).
5. Lab full test: all 3 flags, contain/eradicate/recover/reset/stop.
6. Updater + bootstrap regression (against v5.0.3 image).
7. Plymouth: verify theme + logo inside initramfs; boot splash
   screenshot attempted in QEMU — label partially proven if the
   VM path can't show it (BIOS + virtio-vga should).
8. `aegis-tools install` dry-run for a Debian-packaged tool; Burp/ZAP
   installer download verified by checksum (install itself needs
   internet + disk; run once in QEMU if feasible).

## 9. Decisions needed from the user

1. **Pick 1 of 3 logos** (ember-shield / hex-aegis / nebula-disc).
2. Confirm browser = Google Chrome (default; Chromium is the fallback).
3. Confirm tools split: Debian-packaged pre-installed, Burp/ZAP
   on-demand via `aegis-tools`. (Or pre-install everything and accept
   a much bigger image?)
4. Image size growth to ~6–7 GiB — OK?
5. Lock screen: Quickshell (Nebula-style, recommended) vs hyprlock
   (simpler, less pretty)?

## 10. Risks

- **Backports drift**: Hyprland 0.55.2 / Quickshell 0.3.0 are pinned
  by trixie-backports today; if backports moves, pin exact versions
  in the build (`apt install -t trixie-backports hyprland=0.55.2...`).
- **Quickshell Qt 6.8 quirks**: known and patchable (see §1); budget
  a QML debug round.
- **swww build**: needs Rust toolchain at build time (apt `cargo`
  + `rustc` in trixie — reproducible, no rustup needed).
- **Chrome .deb is a moving target**: URL is version-less (always
  latest stable); record the installed version in the build log.
- **Burp/ZAP are third-party downloads**: checksum-verify; they cannot
  be baked into the image without bloating it.
- **Plymouth on BIOS + QEMU/VirtualBox**: splash may not show in every
  VM config; verify what the VM path can show, label the rest.
- **xdg-desktop-portal-hyprland SIGSEGV** on `wlr-screencopy`
  (omarchy finding): mask the service; screenshots via `grim` still work.
- **VirtualBox cursor**: new compositor, new cursor path — re-verify
  on the user's machine; `cursor:no_hardware_cursors = true` is the
  fallback.

## 11. Sources

- packages.debian.org: hyprland (trixie-backports 0.55.2+ds-1~bpo13+1),
  quickshell (trixie-backports 0.3.0-1~bpo13+1; sid 0.3.2-1),
  plymouth 24.004.60-5, plymouth-themes, waybar 0.12.0-1,
  nmap 7.95+dfsg-3, sqlmap 1.9.6-1, nikto 1:2.1.5-3.1 (non-free),
  hydra 9.5-3, tcpdump 4.99.5-2, qml-qt6 6.8.2+dfsg-7 (Qt 6.8.2).
- qa.debian.org DDPO (Debian Hyprland Maintainers): backports versions
  for hyprland/hyprlock/hypridle/hyprpaper/hyprlauncher/hyprcursor/
  aquamarine, updated 15 Nov 2026.
- linuxiac.com: "Debian 13 Stable Users Can Now Install Hyprland
  from Backports" (hyprland 0.55.2 in trixie-backports).
- github.com/LeisureLinux/omarchy-on-debian: tested matrix Debian 13.6
  + Hyprland 0.55.2 bpo + Quickshell 0.3.0 bpo + Qt 6.8.2; backports
  pin 100; Qt 6.8 QML quirks; xdg-desktop-portal-hyprland SIGSEGV.
- github.com/AleReb/uconsole-hyprland-dotfiles: swww/mpvpaper built
  and run on Debian 13 + backports Hyprland; hyprpaper hang warning.
- wnpp.debian.net: swww ITP #1084753 (not in Debian).
- computingforgeeks.com / linuxize.com / golinuxcloud.com: Chrome
  .deb URL `https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb`
  (~138 MB), `sudo apt install ./google-chrome-stable_current_amd64.deb`,
  Google APT repo, current stable ~157.x (Nov 2026).
- gl0bal01.com CTF guide + gist.github.com/billfitzgerald: Burp Suite
  and ZAP are Kali-only via apt; on Debian use the official installers
  (portswigger.net/burp/communitydownload, zaproxy.org/download).
- computingforgeeks.com Debian 13 guide: kernel 6.12 series, Debian
  13.7, kernel 6.12.113 (Oct 2026 VM).
