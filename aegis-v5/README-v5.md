# AegisOS v5 — Nebula-style Wayland desktop + Red vs Blue Lab

v5 is the renamed SecureOS (the GitHub repo was renamed SecureOS →
**AegisOS**, https://github.com/Die-Another-Day/AegisOS, head `1a10d2db`)
with a new desktop: **sway 1.7 + an original GTK3/Python layer-shell
shell** in the style of the Nebula reel (floating islands, scalloped
panels, wallpaper-derived colours, starfield lock screen). The v4 lab is
carried over unchanged in behaviour, renamed. **Saral 0.3.0 is installed
in the image for the first time** (it was never in the v4 image).

Default boot is still **CLI + web console on http://127.0.0.1:8000**.
The GUI starts only when you run `aegis-gui`.

> **FIXED 2026-11-14 — lab services no longer start at boot.**
> In v5 repack #3 the lab units started at boot even though lab state was
> `disabled`. Root cause, found 2026-11-14: **systemd's first-boot preset
> population.** On the first boot of a fresh image systemd logs
> `Populated /etc with preset unit settings` and creates
> `multi-user.target.wants/` symlinks for every unit with an `[Install]`
> section — including the lab units, which no v5 code ever enabled
> (the packed filesystem was verified clean with debugfs; the symlinks
> appeared in the booted image at 18:43:15, during first boot, alongside
> the preset-listed `remote-fs.target` / `systemd-networkd.service`).
> A pack-time `systemctl disable` could never fix this: it only removes
> symlinks present at build time, and PID 1 re-creates them at first boot.
> Fix, at the source: **the lab unit files have no `[Install]` section**
> (they are static units — startable only by an explicit
> `systemctl restart` from `aegis-lab --enable` / `aegis-ir recover`),
> plus a preset file `/etc/systemd/system-preset/00-aegis-lab.preset`
> that explicitly disables them, plus a build-time debugfs gate that
> fails the build if lab wants-symlinks exist in the packed filesystem.
> Verified on a fresh boot of the final image (guest-test run 7,
> 2026-11-14): both units `static`/`inactive` with lab disabled, no
> listeners on 2222/8080, journal shows no lab-unit entries for the
> boot. `aegis-lab --enable` still starts them; `--stop` still stops
> them; all 3 flags captured after enable.
> Follow-on found during verification (guest-test run 5): the build's
> labinit step ran fakechroot with a *relative* `FAKECHROOT_BASE`
> (`./.build/rootfs`), under which `chown -R` fails with ENOENT on
> every child — so on REUSE builds labinit died at `chown` and flag2,
> the FIM manifest and the theme were never created (clean builds were
> masked because setup had already made them). The lab app then could
> not start (`/srv/labapp` stayed root-owned, unreadable by `labweb`)
> and flags 1/3 went uncaptured. Fixed by canonicalising the build
> output dir to an absolute path in `build-image.sh`; re-verified in
> runs 6 and 7.

## Current image (2026-11-15, v5.0.2 — full clean build + REUSE repacks for the updater fixes; guest-test + vt-gui-test + update-test + bootstrap-test all pass)

- `aegis-v5.img` — 5.0 GiB (5120 MiB), clean debootstrap build
  (build 3, then REUSE repacks from the same rootfs for the
  `aegis-update` fixes only; never a guest-apply upgrade).
  `/etc/aegis-version` reads `5.0.2`; `aegis-update` installed.
- SHA256:
  `6da6fc6387adf52874c58fe524392ac512064101c55bb2c4a8a24b6993c7677d`
  (also in `aegis-v5.img.sha256`; the shipped image is never booted
  directly — every test boots a `*.test` copy, so the hash stays valid
  after testing).
- Kernel 6.1.0-54-amd64, GRUB "AegisOS v5", hostname `aegis`.

## What is in v5

| Area | v5 |
|---|---|
| Base | Debian 12 bookworm, kernel 6.1 (same as v4) |
| Desktop | sway 1.7 + `aegis-shell` (GTK3/Python, gtk-layer-shell 0.8.0) + swaylock + Pillow colour pipeline |
| Lock screen | Starfield, large clock in a Cairo-drawn **scalloped** disc, date, real-track music card, orbiting widget dots (animated) |
| Widgets | Battery ring (real upower), system monitor (real /proc CPU/mem), music (real playerctl or "No track"), top bar (real workspaces/network/battery/time) |
| Colours | `aegis-colours.py` (Pillow): wallpaper → dominant/accent → theme.json/theme.css; `aegis-wallpaper starfield\|sunset\|<file>` re-runs it |
| Wallpapers | Two original Pillow-generated wallpapers: dark navy starfield + warm sunset (no copied anime art) |
| Lab | Same Red vs Blue lab as v4, renamed: `aegis-lab`, `aegis-ir`, `aegis-fim`, flags, auditd, nftables |
| Saral | 0.3.0: `/usr/local/bin/saral` + `/usr/local/lib/saral/libs`; `saral version` prints `Saral 0.3.0` |
| Console | http://127.0.0.1:8000, `/api/*` unchanged, `{"name": "AegisOS", "version": "5.0"}` |

## The sway-not-Hyprland decision (and why)

Real, current Hyprland is **not feasible on Debian 12 bookworm**, and
this was verified, not assumed (see `research-hyprland.md`):

- Current Hyprland requires **C++26 — gcc ≥ 16 or clang ≥ 19**.
  Bookworm ships **gcc 12.2.0**. There is no bookworm Hyprland package
  at all, and none in bookworm-backports.
- Quickshell requires **Qt ≥ 6.6**. Bookworm ships **Qt 6.4.2**. No
  bookworm Quickshell package exists either.
- Building old Hyprland 0.24.1 from source was rejected: a 3-year-old
  snapshot with no security fixes, plus a forked graphics stack.

So v5 uses **sway 1.7 from bookworm apt + an original GTK3/Python
layer-shell shell + swaylock + Pillow**. The shell is original code
inspired by the Nebula *look*; no Nebula code was copied (Nebula is
AGPL-3.0, Arch-only). The v6 candidate — and the only honest route to
real Hyprland + Quickshell — is a **Debian 13 trixie rebase**
(trixie-backports has hyprland 0.55.2 and quickshell 0.3.0). That is a
base-OS migration, not a v5 feature; it was **not** done here.

## What is real vs faked (honest list)

- **Real:** sway compositor; GTK layer-shell bar/widgets; workspaces,
  network, battery, CPU/mem, music track — all read live from the
  system; password unlock (verified with `sudo -S true` against the
  real analyst account); wallpaper colour extraction (real Pillow
  analysis — starfield gives accent `#3748a9`, sunset gives `#ffd682`);
  lab, flags, alerts, IR — all real as in v4.
- **Graphical desktop — PROVEN in QEMU 2026-11-14.**
  Real QEMU monitor screendumps in `screenshots/` (never mockups),
  from `vt-gui-test-v5.py` run 10 on the final image — every shot
  viewed by the verifier: `01-lock-screen.png` (scalloped disc
  CENTRED, clock 08:15, date, orbiting dots, "No track playing"
  music card, password + Unlock + test-unlock all on-screen),
  `02-desktop.png` (starfield; three top-bar islands separate,
  Battery bottom-left, System bottom-right, Music top-right below
  the bar — no overlap, real CPU/MEM, "No battery (VM)"),
  `03-desktop-sunset.png` (after `aegis-wallpaper sunset`: the
  sunset wallpaper is visibly on screen and the islands recoloured
  gold — theme accent `#3748a9` → `#ffd682`, `WALLPAPER_RC=0`),
  `04-launcher.png` (radial launcher ring on the sunset desktop:
  dark pills, white bold labels — Console :8000, Terminal, Browser,
  Saral, Lock screen, Firefox ESR, Foot, Foot Client, Foot Server,
  Htop — all readable). See `logs/vt-gui-test-v5-run10.log` for the
  full transcript (sway + lock + desktop + launcher all gated alive
  before each shot). **Renderer:** sway's default GLES2 renderer
  **segfaults in Mesa kms_swrast** on virtio-vga / no-GPU guests
  (`egl: failed to create dri2 screen`, `sway: segfault … in
  kms_swrast_dri.so`). The desktop only works with the software
  renderer, so `aegis-gui` defaults to `WLR_RENDERER=pixman`
  (override with `WLR_RENDERER=gles2` on a real GPU) — and that
  default is now **proven end-to-end from the image itself**: the
  vt runs launch `aegis-gui` with no `WLR_RENDERER` set at all.
  Sway **cannot** start from a serial-console login (libseat cannot
  open a VT there — "Could not open target tty: Permission denied");
  it must be started from a VT login (tty1), which is the real usage
  path. The old `gui-test-v5.py` started sway from the serial
  console, so it could never work — it is superseded by
  `vt-gui-test-v5.py` (see fix #10 below).
- **Layout bugs from repack #3 — FIXED 2026-11-14, re-screenshotted
  and viewed (vt-gui-test run 10):** the lock-screen disc sat
  right-of-centre and the unlock controls were cut off (the
  background was a 1920x1080 image, so the overlay laid out at 1920
  wide on a 1280x800 display); the Battery and System widgets
  overlapped each other and the top bar (the GtkLayerShell typelib
  was missing, so every window fell back to plain centred floating
  windows); the launcher's pill labels were pale-on-pale (transparent
  window over a bright wallpaper, and Adwaita's button gradient
  painted over the dark background colour). Fixes: wallpaper now
  painted scaled to the real allocation; the typelib is installed
  and build-gated, and the shell refuses to start a broken desktop;
  the launcher has an opaque background, solid buttons with
  `background-image: none`, and a light title colour. Fresh
  screenshots 01–04 (run 10) show the fixed layout.
- **Faked / approximated, and labelled as such:**
  - **Blur:** sway 1.7 has **no live blur**. Panels use Pillow
    pre-blurred wallpaper slices (`~/.config/aegis/blurred.png`,
    `blurred-top.png`). It looks blurred; it is not live blur.
  - **Lock-screen orbit animation:** the dots rotate on a GLib timer
    in the shell lock screen (animated). The **swaylock** path
    (`--secure-lock`) is a **static rendered image** — no animation.
  - **Weather widget: omitted.** There is no real weather source
    available offline in the guest, so v5 shows no weather widget
    rather than inventing a temperature.
  - **Battery:** shows "No battery (VM)" when upower finds none —
    never a faked 100%.
  - **Music:** shows "No track playing" when no player exists —
    never a faked track.
  - **Window animations / rounded window corners:** sway 1.7 has
    none. Rounded corners exist only on the shell's own panels
    (GTK/CSS + Cairo).
- **Test-mode unlock:** in QEMU verification the lock screen is
  unlocked with the labelled "Unlock (test mode)" button
  (`AEGIS_TEST_UNLOCK=1`). The password path is the real one; the
  test-mode click is a test convenience, not a security claim.

## Rename map (SecureOS → AegisOS)

| Old | New |
|---|---|
| hostname `secureos` | `aegis` (prompt becomes `analyst@aegis`) |
| `secureos.service` / `secureos-labapp.service` / `secureos-ssh-lab.service` | `aegis.service` / `aegis-labapp.service` / `aegis-ssh-lab.service` |
| `bin/secureos-{lab,ir,fim,lab-reset-flags,gui,status,logs,net,drivers}` | `bin/aegis-{lab,ir,fim,lab-reset-flags,gui,status,logs,net,drivers}` (gui/status/logs/net/drivers sourced from v3 — v4's clean build silently dropped them; v5 copies them explicitly) |
| `/opt/secureos` | `/opt/aegis` |
| `/etc/secureos-lab`, `/var/log/secureos-lab`, `/var/lib/secureos-lab` | `/etc/aegis-lab`, `/var/log/aegis-lab`, `/var/lib/aegis-lab` |
| nft table `secureos_lab`, audit keys `secureos_lab*` | `aegis_lab`, `aegis_lab*` |
| ext4 label `secureos`, GRUB `"SecureOS v4"` | label `aegis`, GRUB `"AegisOS v5"` |
| `secureos-v4.img`, `v4-console.js`, `v4-payload.tar.gz` | `aegis-v5.img`, `v5-console.js`, `v5-payload.tar.gz` |
| `SECUREOS_REUSE_ROOTFS`, `SECUREOS_DISPLAY`, `SECUREOS_REPO_ROOT` | `AEGIS_REUSE_ROOTFS`, `AEGIS_DISPLAY`, `AEGIS_REPO_ROOT` |

**Exception — env vars kept unchanged (do not "fix" these):**
`SECUREOS_BIND_IP` and `SECUREOS_ALLOW_PUBLIC` are **kept** exactly as
in v4. Four places must agree (`aegis-lab` writes `/etc/aegis-lab/env`;
`aegis.service` + `aegis-labapp.service` read it via `EnvironmentFile`;
`server.py` and `labapp.py` read the variables). They are not
user-visible, and renaming them adds risk for zero benefit. The build
gate enforces this: `grep -ri secureos` over every file that ships into
the image (all code, units, scripts, frontend, Wayland files, Saral)
must return zero **except** those two variable names. Deliberately
excluded from the gate: `audit-v4.md` and `research-hyprland.md`
(historical docs), `README-v5.md` (its rename map documents the old
names — that is its purpose), and `build-image.sh` itself (it holds the
upstream pre-rename directory compatibility check and the gate pattern).

**Kept unchanged on purpose:** users `analyst`, `labweb`, `labuser`;
`/srv/labapp` (+ `lab.db`, `flags/flag*.txt`, `plugins/`); ports 8000 /
8080 / 2222; all `/api/*` paths; guest IP 10.0.2.15 under QEMU user-net;
flag mechanics. These carry no brand string.

**Audit bugs fixed in v5 (see `audit-v4.md` §5):**
1. `aegis-gui`/`aegis-status`/`aegis-logs`/`aegis-net`/`aegis-drivers`
   are sourced from v3 `bin/` and copied by the build — a clean build
   no longer silently drops them (v4's clean build had no GUI).
2. No phantom console JS: only `v5-console.js` (which exists in the
   v5 folder) is injected into `index.html`. v4 injected `v2`/`v3`
   script tags for files that were never copied (console 404s).
3. Unit Description strings fixed: `aegis.service` says
   "AegisOS v5 console" (v4's build script wrote "SecureOS v3 console").
4. Frontend comes from a **fresh checkout of remote main**
   (`https://github.com/Die-Another-Day/AegisOS`, HEAD `1a10d2db`,
   vendored into `frontend/`), not the stale `loveos-repo` snapshot.
5. Image size default is **5120 MiB** (matches the live v4 image);
   v4's 6144 default never matched its live image. A `.sha256` file is
   written (v4's was missing).

## How to build

```bash
cd ~/workspace/secureos-build/aegis-v5
./build-image.sh            # clean debootstrap build -> aegis-v5.img (5120 MiB)
# Faster rebuild reusing a complete rootfs:
AEGIS_REUSE_ROOTFS=1 ./build-image.sh
```

Host needs: `debootstrap grub-mkimage mkfs.ext4 python3 fakechroot fakeroot`.
The build runs the rename gate at the end and fails if any `secureos`
(other than the two env vars) remains in the v5 sources.

**Guest-apply fallback** (only if the clean build fails after one genuine
retry of the failing step): copy `secureos-v4.img` → `aegis-v5.img`,
serve a `v5-payload.tar.gz` on the host, and run `guest-setup-v5.py`
to apply `setup-v5.sh` inside the guest. If that path was used, it is
stated in the build report and in `logs/` — a repacked v4 is never
presented as a clean v5 build.

## How to run

```bash
./run-qemu.sh aegis-v5.img 2048            # CLI: log in as analyst / secure
curl -s http://127.0.0.1:8000/api/health   # inside the guest
aegis-status                                # kernel, services, net, battery, disk
saral version                               # Saral 0.3.0
./run-qemu-gui.sh aegis-v5.img 2048        # graphical window (AEGIS_GL=1 for virtio-GPU)
# inside the guest, after login ON A VIRTUAL TERMINAL (tty1 — the
# QEMU window, not the serial console: sway cannot start from a
# serial login, libseat cannot open a VT there):
aegis-gui                                   # sway + lock screen -> desktop
aegis-gui --lock                            # lock screen only
aegis-gui --secure-lock                     # swaylock (analyst password)
aegis-gui --stop                            # back to CLI
aegis-wallpaper sunset                      # switch wallpaper, widgets recolour
aegis-shell --launcher                      # radial launcher (Super+Space in sway)
```

## GUI — where it can and cannot start (v5.0.2)

`aegis-gui` starts sway, and sway needs a real VT/seat — the VM's own
display. It can NEVER start from a serial console, an SSH session, or a
WSL terminal window: there is no screen there for sway to draw on.
Since v5.0.2 `aegis-gui` detects that case before launching sway and
fails fast (well under a second) with a clear message instead of ~12 s
of libseat errors. The message names the two working paths:

* **From WSL:** stop QEMU and relaunch with `-vnc :1`, connect a VNC
  viewer on Windows to `localhost:5901`, log in and run `aegis-gui`
  on the VM's screen.
* **In VirtualBox:** boot the image there and run `aegis-gui` from the
  VM's own display (tty1). v5.0.1 also made the shell wait up to 10 s
  for a display and made `aegis-gui` wait up to 15 s for sway to report
  an active output, covering the slow VMSVGA buffer-allocation race
  seen on VirtualBox. A VirtualBox run of the fixed image is still
  unproven from this sandbox (no VirtualBox/KVM here) — the user's
  machine is the decisive test.

`aegis-gui --stop` / `--help` / `--restart-shell` are unaffected and
still work from any terminal. `aegis-shell` on its own still fails
fast with its own one-line no-display message (v5.0.1) when run with
no display at all.

## Mouse cursor + QEMU display + clean shutdown (v5.0.3)

* **No cursor on the lock screen (fixed v5.0.3).** The pointer was
  invisible on both QEMU virtio-vga and VirtualBox VMSVGA, so the
  lock-screen password box could not be clicked. The Adwaita cursor
  theme files were already in the image — the cause was wlroots
  failing to use the DRM hardware-cursor plane with the pixman
  renderer (`Failed to pick cursor format` / `Failed to render
  cursor buffer` in the sway log). `aegis-gui` now sets
  `WLR_NO_HARDWARE_CURSORS=1` so wlroots draws the pointer into the
  framebuffer itself, and `sway-config` sets
  `seat * xcursor_theme Adwaita 24` explicitly.
* **QEMU needs a DRM-capable virtual GPU.** The default VGA device
  has no DRM device and sway fails with `Failed to open any DRM
  device` / `Unable to create backend`. Working launch:
  `qemu-system-x86_64 -m 2048 -hda aegis-v5.img -vga virtio -vnc :1`
  (then a VNC viewer to `localhost:5901`).
* **Always shut the VM down cleanly** (`sudo poweroff`). A hard
  power-off (closing the VM window, `kill` on QEMU) can corrupt the
  ext4 filesystem — the guest then reports `Structure needs
  cleaning` and files fail to install or update. No updater can fix
  a corrupted filesystem; the only repair is `fsck` from outside
  the guest or a fresh image.

Lab (same as v4, renamed):

```bash
sudo aegis-lab --enable    # private LAN IP only, never 0.0.0.0
sudo aegis-lab --status
sudo aegis-lab --stop
sudo aegis-lab --reset
sudo aegis-ir contain <private-IP> | uncontain <IP> | kill-session | eradicate | recover
sudo aegis-fim --init | --check
```

Full headless regression (lab enable → SQLi/SSH/plugin flags → alerts →
IR → reset → stop): `python3 guest-test-v5.py aegis-v5.img logs/guest-test-v5.log`

## Updating (v5.0.2 — no more full re-downloads for small fixes)

Every release before v5.0.2 shipped as a 5 GB image, so even a 3-file
fix meant downloading all of it again. From v5.0.2 the system updates
itself in place:

```bash
aegis-update check          # installed version (from /etc/aegis-version) vs latest GitHub release
sudo aegis-update apply     # patch bundle if the release carries one, else full image
```

- **Patch bundle** (`<tag>-patch.tar.gz` on the release): a tar.gz with
  `manifest.json` (release tag, files with target paths + SHA256 each,
  optional `post_apply` commands) and the changed files only. The
  updater verifies every file's SHA256 *before* applying anything,
  backs up every replaced file to `/var/lib/aegis/backup/<old-version>/`,
  applies, runs the post-apply hooks (allowlisted: `systemctl
  restart/reload` of an `aegis-*.service` unit, or
  `aegis-lab-reset-flags`), then writes the new version to
  `/etc/aegis-version`. Any hash mismatch or disallowed hook refuses the
  whole bundle and nothing is applied.
- **Full-image fallback**: if a release has no patch bundle, the updater
  downloads all `aegis-v5.img.xz.part-*` + `SHA256SUMS.txt` into
  `/var/lib/aegis/update/<tag>/`, verifies every checksum, reassembles
  and integrity-checks the `.xz` — then **stops**. It never overwrites
  the disk the running system booted from; the printed instructions say
  how to flash the new image to USB or attach it as a new VM disk.
- `check` works as any user and handles no-network with a clear
  message; `apply` needs root (`sudo`). No new packages: curl, python3,
  tar, sha256sum, coreutils only.
- Systems on v5.0.0/v5.0.1 have no updater and no `/etc/aegis-version`
  (they report as 5.0). One-time bootstrap, run inside the VM:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/Die-Another-Day/AegisOS/main/aegis-v5/bootstrap-update.sh -o /tmp/bootstrap-update.sh
  sudo bash /tmp/bootstrap-update.sh
  ```
  It downloads the v5.0.1 fix files (`aegis-shell`, `aegis-gui`, the
  serial test) plus `aegis-update` from GitHub main, verifies every
  SHA256 against hashes baked into the script, installs them, and writes
  `/etc/aegis-version` as `5.0.1`. Any hash mismatch aborts with nothing
  installed. After that, `aegis-update check` works normally.

## What is NOT proven

- **Lab OFF-by-default — VERIFIED 2026-11-14 on a fresh boot of the
  final image** (guest-test run 7; see Known Issue above). Lab units
  are static (no `[Install]`), explicitly disabled by preset, and
  gated at build time.
- **Desktop layout — VERIFIED 2026-11-14, screenshots viewed**
  (vt-gui-test run 10; see "Graphical desktop" above): the lock
  screen background is now drawn scaled to the real screen size
  (was: a 1920x1080 image laid the overlay out at 1920 wide,
  shifting content right and cutting the unlock controls off); the
  desktop now runs on real layer-shell surfaces (was: the
  GtkLayerShell typelib was missing, so every window fell back to
  plain centred floating windows that overlapped); the launcher has
  an opaque dark background and solid buttons (was: pale-on-pale
  through the transparent window, plus Adwaita's button gradient).
  CPU hit 100% in screenshots taken during a shell restart under
  pixman software rendering — expected for software rendering, but
  not measured as a sustained load. One timing note: right after
  `aegis-wallpaper sunset`, the screen briefly shows a flat grey
  frame while the new swaybg loads under load — the sunset appears
  once it presents (run 10 shot 03 waited for swaybg alive first).
- **Wayland on real hardware / with 3D acceleration:** only tested
  under QEMU software rendering (`WLR_RENDERER=pixman`).
  `AEGIS_GL=1` (virtio-GPU + host GL) is provided but not the default
  path and may behave differently on other hosts. The pixman default
  **was** re-verified end-to-end from the final image (vt-gui-test
  runs 7–10 launch `aegis-gui` with no `WLR_RENDERER` set).
- **Real two-machine LAN lab** was not re-proven in v5; the v4 proof
  was host-forwarded ports under QEMU user-net, and v5 reuses that
  harness (`guest-test-v5.py`).
- **swaylock idle-lock timing** (10 min via swayidle) was not
  waited out in testing; the lock *mechanism* was tested directly.
- **Debian 13 trixie / real Hyprland:** not attempted in v5 (v6
  candidate only, see above).
- **XFCE is gone:** there is no XFCE fallback session in v5. If sway
  fails to start on a machine, the fallback is the CLI + web console.
- **FIM manifest on a clean build** is written before first boot; if
  the lab DB is regenerated later without `--reset`, run
  `aegis-fim --init` again (or `aegis-lab --reset`, which does it).

## Bugs found and fixed in the 2026-11-12 wrap-up

1. **libjpeg / colour pipeline (build failure).** `aegis-colours.py`
   failed inside the chroot (`ImportError: libjpeg.so.62`) because
   the labinit step ran under fakechroot. Fixed: `libjpeg62-turbo`
   added to the package lists in `build-image.sh` / `setup-v5.sh`;
   the labinit colours step is now non-fatal; `aegis-gui`
   regenerates the theme on first GUI start if missing. **Proven
   fixed in-guest** (guest-test run 2 and run 3): `COLOURS_RC=0`,
   dominant `#0c1136` accent `#3748a9` (starfield); wallpaper switch
   gives accent `#ffd682` (sunset).
2. **Permission/umask bug.** Host umask 0007 left copied dirs 770
   and files 660, so `analyst` could not read wallpapers or Saral
   libs and `which aegis-shell` failed. Fixed: explicit permission
   normalisation in `build-image.sh`, `setup-v5.sh`,
   `wayland/install-wayland.sh` (dirs 755, files 644). Proven fixed
   in-guest (run 2/3).
3. **Rename-gate flaws.** The gate grepped the 5 GB image and
   `.pyc` files and tripped on the `.sha256` absolute path. Fixed:
   gate excludes `*.img`, `*.sha256`, `*.pyc`, `__pycache__`,
   `logs/`, `screenshots/`; `.sha256` uses a relative filename.
4. **Unit files world-inaccessible (cosmetic).** `aegis-labapp.service`
   / `aegis-ssh-lab.service` were mode 660; systemd logged
   "Configuration file … is marked world-inaccessible" at boot.
   Fixed in the sources (`chmod 644` in `build-image.sh` and
   `setup-v5.sh`); included in repack #3.
5. **sway segfault on the default renderer (graphical blocker).**
   See "Graphical desktop — PROVEN" above. Fixed in the sources by
   defaulting `WLR_RENDERER=pixman` in `bin/aegis-gui`; included in
   repack #3. The serial-console launch failure (libseat/VT) is a
   harness limitation, not an image bug — sway must start from tty1.
6. **guest-test path bug.** `guest-test-v5.py` referenced a
   nonexistent `host-ssh-flag.py` path (rename ordering); fixed to a
   path derived from the script's own directory. SSH flag2 captured
   in runs 2 and 3.
7. **FIXED 2026-11-14 — lab services start at boot.** Mechanism found:
   systemd's first-boot preset population ("Populated /etc with preset
   unit settings", in every guest-test boot log) creates wants symlinks
   for every unit with an `[Install]` section. Fix: lab units have no
   `[Install]` section (static), preset file `00-aegis-lab.preset`
   explicitly disables them, build-time debugfs gate fails the build
   if lab wants-symlinks exist in the packed filesystem, and the test
   harnesses now boot a copy so test runs can never mutate the shipped
   image. Re-verified on a fresh boot of the final image (guest-test
   run 7: static/inactive, no journal entries, no listeners).
8. **FIXED 2026-11-14 — desktop layout.** Root causes: (a) the lock
   background was a bare Gtk.Image at 1920x1080 natural size, so the
   overlay laid out at 1920 wide on a 1280x800 display; fixed by
   painting the wallpaper scaled (cover fit) to the real allocation.
   (b) The GtkLayerShell typelib (`gir1.2-gtk-layer-shell-0.1`) was
   never installed — only the C library was — so the shell silently
   fell back to plain windows and sway floated them all centred and
   overlapping; fixed by installing the typelib, adding a build-time
   typelib gate, and making the shell refuse to start a broken desktop.
   (c) The launcher window was transparent (BASE_CSS) over a bright
   wallpaper; fixed with an opaque background and solid buttons.
   Re-verified with fresh screenshots (01–04, vt-gui-test run 10,
   all four viewed).
9. **FIXED 2026-11-14 — labinit died on REUSE builds (fakechroot
   relative base).** `build-image.sh` invoked fakechroot with
   `FAKECHROOT_BASE=./.build/rootfs` (relative); under a relative
   base, `chown -R` fails with ENOENT on every child, so labinit
   aborted at `chown` and flag2, the FIM manifest and the theme were
   never created on REUSE builds (clean builds were masked because
   setup had already made them). Consequence, seen in guest-test run
   5: `/srv/labapp` stayed root-owned, `labweb` could not read the
   DB, the lab app never started, flags 1/3 went uncaptured (host
   curls rc=56) and FIM reported "no usable manifest". Fixed by
   canonicalising the build output dir to an absolute path
   (`OUT="$(cd "$OUT" && pwd)"`); the same bug also affected the
   setup invocation (same call pattern). Re-verified in guest-test
   runs 6 and 7 (all 3 flags, FIM detects the state change + the
   uploaded plugin). Also found in passing: the host lost
   `qemu-system-x86_64`/`grub-mkimage` mid-task to a platform
   package replay (07:03 UTC) — both were restored by the replay
   within a minute; the build failure that day was that transient
   gap, not a code bug.
10. **FIXED 2026-11-14 — desktop crash on layer-shell 0.8 API +
    launcher still pale-on-pale + `gui-test-v5.py` superseded.**
    (a) With the typelib installed, `do_desktop()` crashed on the
    first window: `Layer.KeyboardInteractivity` does not exist in
    bookworm's gtk-layer-shell 0.8.0 typelib (added in 0.9), so
    `layer_win()` raised `AttributeError` and the desktop never
    started (vt-gui-test runs 7–8: lock fine, desktop timed out).
    Fixed with a `hasattr` guard — the default interactivity is
    NONE anyway. (b) The launcher was STILL pale-on-pale in run 9:
    Adwaita's button `background-image` gradient paints over any
    `background-color`, and the centre "AegisOS" label inherited
    Adwaita's dark text on the dark panel. Fixed with
    `background-image: none` on the launcher buttons and a light
    colour on `.aegis-title` (run 10 shot 04: dark pills, white
    labels, all readable). (c) `gui-test-v5.py` never worked — it
    starts sway from the serial console (no seat: "Unable to create
    backend" on every run, including Nov 12) yet reported ok=True
    because its markers only proved serial echo. It is superseded
    by `vt-gui-test-v5.py`, which logs in on tty1, starts the GUI
    the real way (`aegis-gui`, no `WLR_RENDERER` set — proving the
    pixman default), and gates every shot on the real process/window
    state (a dead GUI now fails the run instead of screenshotting
    the login prompt).

## Files in this folder

`build-image.sh`, `setup-v5.sh`, `server.py`, `labapp.py`,
`v5-console.js`, `aegis.service`, `aegis-labapp.service`,
`aegis-ssh-lab.service`, `bin/aegis-{lab,ir,fim,lab-reset-flags,gui,status,logs,net,drivers,update}`,
`VERSION` (5.0.3), `bootstrap-update.sh` (one-time updater install for
v5.0.0/v5.0.1 systems), `run-qemu.sh`, `run-qemu-gui.sh`, `guest-test-v5.py`,
`guest-setup-v5.py`, `host-ssh-flag.py`, `vt-gui-test-v5.py`,
`serial-shell-test-v501.py` (serial-console no-display test),
`update-test-v502.py` (updater test: check, patch apply, tampered-bundle
refusal, full-image fallback)
(graphical verification driver — boots a copy, logs in on tty1,
gates every shot on live process/window state),
`gui-test-v5.py` (SUPERSEDED by the vt driver — its serial-console
sway start can never work, see fix #10), `wayland/` (shell, colour
pipeline, sway config, wallpapers, installer), `saral/` (vendored
runtime from remote main), `frontend/` (vendored console frontend from
remote main, HEAD `1a10d2db`), `research-hyprland.md`, `audit-v4.md`,
`README-v5.md`, `screenshots/`, `logs/`, `aegis-v5.img` (+ `.sha256`).

Graphical verification: `python3 vt-gui-test-v5.py aegis-v5.img
logs/vt-gui-test-v5-runN.log` — lock → unlock → desktop → wallpaper
change → launcher, with real QEMU screendumps. Headless lab
regression: `python3 guest-test-v5.py aegis-v5.img
logs/guest-test-v5-runN.log 1500`.
