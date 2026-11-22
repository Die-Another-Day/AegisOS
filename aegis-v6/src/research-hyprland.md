# AegisOS v5 — Hyprland / Nebula-style shell research

**Date:** 2026-11-12
**Scope:** Research only. No code written, nothing pushed, nothing installed.
**Question:** Can AegisOS v5 (Debian 12 bookworm base, kernel 6.1.0-54-amd64) get a
Nebula-style desktop — real Hyprland + Quickshell like
[LilaccFlowerr/Nebula](https://github.com/LilaccFlowerr/Nebula) — or what is the
closest honest alternative on bookworm?

## Verdict up front

**Real, current Hyprland is NOT feasible on Debian 12 bookworm. Quickshell is
not feasible either.** Both are blocked by bookworm's toolchain/library floor,
not by effort:

- Current Hyprland requires **C++26 — gcc ≥ 16 or clang ≥ 19**
  (Hyprland wiki, Installation). Bookworm ships **gcc 12.2.0**.
- Quickshell requires **Qt ≥ 6.6** (`qt_standard_project_setup(REQUIRES 6.6)` in
  its CMakeLists). Bookworm ships **Qt 6.4.2**.
- Neither `hyprland` nor `quickshell` exists as a bookworm package at all
  (packages.debian.org returns "Package not available in this suite" for both),
  and neither is in bookworm-backports.

**Recommendation for v5 on the bookworm base: sway 1.7 (from apt) +
an original GTK3/Python layer-shell shell + swaylock + Pillow colour
extraction.** Everything comes from bookworm apt; no source builds of system
components; proven to run in VMs. It reproduces the Nebula *look* (floating
islands, scalloped panels, wallpaper-derived colours, starfield lock screen)
with two honest losses: no live blur and no live-animated lock screen.
Details in §5.

**If the real thing is required** (live blur, Hyprland animations, Quickshell
QML), the correct move is **rebase AegisOS on Debian 13 trixie +
trixie-backports**, where `hyprland 0.55.2` and `quickshell 0.3.0` install via
apt. That is a base-OS migration, not a v5 feature — recommend treating it as
a v6 decision, not forcing Hyprland onto bookworm.

---

## 1. Hyprland on Debian 12 — evidence

| Check | Result | Source |
|---|---|---|
| `hyprland` in bookworm | **Absent** — "Package not available in this suite" | packages.debian.org/bookworm/hyprland, checked 2026-11-12 |
| `hyprland` in bookworm-backports | Absent (wiki: only trixie-backports) | Hyprland wiki Installation |
| `hyprland` in trixie-backports | **Present: 0.55.2+ds-1~bpo13+1** | packages.debian.org/trixie-backports/hyprland |
| `hyprland` in Debian 14 (Forky) | Present (per wiki) | Hyprland wiki Installation |
| Current Hyprland compiler floor | **C++26: gcc ≥ 16 or clang ≥ 19** | Hyprland wiki, Manual build |
| Bookworm gcc | **12.2.0** (`gcc` 4:12.2.0-3) | packages.debian.org/bookworm/gcc |
| Bookworm wayland | 1.21.x (current Hyprland needs ≥ 1.22–1.23; trixie-backports hyprland 0.55.2 depends on libwayland-server0 ≥ 1.23.0) | Hyprland discussion #1797; trixie-backports hyprland deps |
| Bookworm libwlroots | 0.15.x (`libwlroots10` ≥ 0.15.0) | sway 1.7-6 deps, packages.debian.org |

Wiki's own words: *"Hyprland is not available for Bookworm as its packages are
too old."* Upstream only guarantees Arch and NixOS; point-release distros
"will have **major** issues running Hyprland."

### Building current Hyprland from source on bookworm: NO

The compiler floor alone kills it: gcc 12 cannot compile C++26 code. Getting
gcc 16 onto bookworm would mean building a whole modern toolchain from source
first — out of scope and unmaintainable for a security OS image.

### Building OLD Hyprland (v0.24.1, Oct 2023) from source: technically possible, NOT recommended

Per Hyprland discussion #1797, v0.24.1 is "the last version with wlroots
targeting Wayland 1.21" (bookworm's Wayland), and one reporter built a
then-current Hyprland on bookworm after simple-backporting `wayland`,
`wayland-protocols` and `libinput` from trixie. Caveats that make this a bad
idea for AegisOS:

- v0.24.1 is a 3-year-old snapshot: no security fixes, no current features,
  incompatible with every modern Hyprland config/plugin/tutorial.
- It still needs wlroots built from source as a subproject
  (libdisplay-info / libliftoff submodules in that era) plus backported
  Wayland stack packages — i.e. AegisOS would own a forked graphics stack.
- Build time on the 4-CPU / ~8 GB VM was **not verified** (no reliable source
  found; expect tens of minutes for Hyprland + wlroots, RAM should be OK).
- Hyprland's own wiki warns against manual builds: mismatched `.so` versions
  are "entirely your fault".

### Other Hyprland-adjacent notes

- JaKooLit's Debian-Hyprland installer targets **Trixie/Sid only**, builds from
  source, and warns: *"On VMs, enable 3D acceleration or Hyprland may not
  start."* Relevant: AegisOS is built/tested in a VM. Sway/labwc tolerate
  software rendering (llvmpipe / pixman) far better than Hyprland.
- No Debian package exists for `matugen` either (packages.debian.org/bookworm/matugen
  → not available). See §4.

## 2. Quickshell on Debian 12 — evidence

| Check | Result | Source |
|---|---|---|
| `quickshell` in bookworm | **Absent** | packages.debian.org/bookworm/quickshell |
| `quickshell` in bookworm-backports | Absent | (no package; Dux docs only list trixie-backports) |
| `quickshell` in trixie-backports | **Present: 0.3.0-1~bpo13+1** (needs Qt ≥ 6.8.2, libstdc++6 ≥ 14) | packages.debian.org/trixie-backports/quickshell |
| Quickshell minimum Qt | **Qt 6.6.0** | Quickshell CMakeLists.txt / BUILD.md (via DeepWiki) |
| Bookworm Qt | **6.4.2+dfsg-10** | packages.debian.org/bookworm/qt6-base-dev |
| Trixie Qt | 6.8.2+dfsg-9+deb13u1 | Debian QA debcheck |

Quickshell also depends on **private Qt APIs** and must be rebuilt against
each Qt release — so even a source build on bookworm is blocked by the Qt
version, not just by effort. Building Qt 6.6+ from source on bookworm to
unblock it would be a multi-hour, multi-GB side quest. **Not feasible for v5.**

## 3. Alternatives that REALLY run on Debian 12

All versions below verified on packages.debian.org (bookworm) on 2026-11-12
unless marked otherwise.

| Compositor | In bookworm apt? | Version | Blur | Rounded corners | Layer-shell | Notes / loss vs Hyprland |
|---|---|---|---|---|---|---|
| **sway** | ✅ Yes | **1.7-6** (wlroots 0.15) | ❌ No (stock sway has no blur) | ❌ No (window corners square) | ✅ Yes | Rock-solid, great IPC (`swaymsg`), full ecosystem in bookworm (waybar, swaylock, swayidle, mako). Tiling-first but floating windows fully supported. Best VM behaviour (software rendering OK). |
| **Wayfire** | ✅ Yes | **0.7.4-3+deb12u1** (wlroots 0.15) | ✅ Yes (blur plugin; Compiz-style effects are its whole point) | ✅ Yes (via plugins/decorations) | ✅ Yes | Closest to Hyprland's eye candy from apt. But 0.7.4 is old (2022), INI config, smaller community, weaker IPC. Whether the blur plugin ships in the bookworm `wayfire` package vs `wayfire-plugins-extra` was **not verified**. |
| **labwc** | ❌ No (not in bookworm or bookworm-backports) | — | ❌ No blur | Partial (rounded corners only in newer versions; **unverified** for 0.5.x) | ✅ Yes | Stacking/floating compositor — the most natural fit for floating islands. **Buildable from source:** labwc **0.5.3** targets wlroots **0.15.1**, exactly bookworm's wlroots (labwc NEWS.md; a Slackware build log shows 0.5.1 building against wlroots 0.15.1 / wayland 1.20). But 0.5.3 is from Jul 2022, and meson will otherwise auto-download wlroots via its subproject wrap. AegisOS would own an old compositor build. labwc 0.6.x needs wlroots 0.16.2; current labwc needs wlroots 0.20 + wayland ≥ 1.22.90. |
| **river** | ❌ No | — | ❌ | ❌ | ✅ Yes | Not in bookworm at all (entered Debian in trixie). Would need a from-source build incl. Zig toolchain — not pursued. |
| **swayfx** (sway + eye candy) | ❌ No | — | ✅ | ✅ | ✅ | Not packaged in Debian. Every release needs newer wlroots than bookworm's: 0.3.2 → wlroots 0.17, 0.4 → wlroots 0.17.4 (sway 1.9), 0.6 → wlroots 0.20. Cannot build against wlroots 0.15. |
| **Xorg + XFCE + picom** (current v4 GUI) | ✅ Yes | picom **9.1-1** | ✅ Yes (picom dual-kawase blur) | ✅ Yes (picom `corner-radius`) | ❌ N/A (no layer-shell on X11) | Keeps the proven v4 GUI stack; blur + rounded corners work. But no layer-shell means bar/lock/widgets must be ordinary shaped windows (doable, weaker); no Wayland security/isolation story; animations weaker. Lowest risk, least "Nebula". |

### Key nuance: the compositor is NOT the main look

Nebula's look (scalloped shapes, floating islands, blurred panels) is drawn
by the **shell**, not the compositor. On sway, a layer-shell panel with a
transparent background + toolkit-drawn rounded rectangle gives rounded
floating islands with zero compositor support — that is exactly how Waybar
draws its rounded bar. The only things genuinely lost on sway are:

1. **Live blur** behind panels (sway cannot blur). Fake it convincingly by
   pre-blurring wallpaper regions with Pillow (§4) and using them as panel
   backgrounds, or use translucent solid fills.
2. **Window animations / animated window corners** (no compositor animation
   framework in sway 1.7).
3. **Live-animated lock screen** — swaylock is a static image locker. A
   Nebula-style lock screen needs either Quickshell (unavailable) or a custom
   layer-shell lock surface with PAM (e.g. `gtklock`-style; **not verified**
   in bookworm — do not assume it is packaged).

### Shell toolkit options on bookworm (all apt)

- **GTK3 + gtk-layer-shell 0.8.0** (`libgtk-layer-shell-dev` 0.8.0-1 in
  bookworm) + Python: the pragmatic shell. CSS gives rounded corners,
  transparency, shadows; Cairo can draw scalloped/blob shapes.
- **Waybar 0.9.17-2** (bookworm, depends on gtk-layer-shell): a solid bar
  today, but only a bar — launcher/widgets/lock still need custom code.
- **Qt6 QML without Quickshell**: Qt 6.4.2 has QtQuick, but layer-shell
  integration without Quickshell is awkward; not recommended over GTK.
- **Eww / AGS (Astal)**: not in Debian; source builds (Rust/JS) — not
  verified on bookworm, adds toolchain burden. Skip for v5.

## 4. Wallpaper-derived colours with Python/PIL on bookworm

**Verified: `python3-pil` 9.4.0-1.1+deb12u1 in bookworm** (Pillow 9.4.0,
Python 3.11). This is fully sufficient for a Nebula-style colour pipeline:

- **Dominant/seed colour:** downscale the wallpaper, `Image.quantize()` /
  `getcolors()`, or a small k-means over pixels — a few dozen lines of
  stdlib + Pillow. (No `colorthief` in Debian; pip-only — avoid for an OS
  image.)
- **Palette:** derive light/dark tonal variants in HSV/HSL with
  `colorsys`, or implement the Material 3 tonal-palette math directly
  (HCT colour space). Pillow gives the seed; the tonal ramps are pure math.
- **Fake blur:** `ImageFilter.GaussianBlur` — pre-render blurred wallpaper
  slices for panel backgrounds (the sway blur workaround in §3).
- **Lock screen art:** render the starfield + huge clock + disc as a PNG at
  lock time and hand it to swaylock as the background image. Static, but
  visually very close to the reel's lock frame.

**matugen** (the tool Nebula uses: Rust, GPL-2.0, latest release **4.2.0**,
Aug 2026, github.com/InioX/matugen) is **not in Debian**. Options, in order
of sanity: (a) reimplement the small part we need in Python/Pillow (above);
(b) use a prebuilt matugen release binary — **not verified** whether release
assets include a linux-x86_64 tarball, check at build time; (c) `cargo build`
matugen — **not verified** whether bookworm's Rust toolchain (1.63-era) is
new enough for matugen 4.x; likely not. Prefer (a).

## 5. Recommendation

### Primary path for AegisOS v5 (bookworm base) — RECOMMENDED

**sway 1.7 + original GTK3/Python layer-shell shell + swaylock + Pillow
colour pipeline.**

Concrete stack (all `apt install` from bookworm):

- `sway` 1.7-6, `swaybg` 1.2.0-1, `swayidle` 1.8.0-1, `swaylock` 1.7.2-1,
  `xdg-desktop-portal-wlr` 0.7.0-1
- `waybar` 0.9.17-2 (bar now; replace with custom GTK islands later) — or go
  straight to custom GTK islands
- `libgtk-layer-shell-dev` 0.8.0-1 / `libgtk-layer-shell0` + `python3`,
  `python3-pil` 9.4.0, `python3-gi` (GTK bindings)
- `mako-notifier` (notifications), `foot` (terminal), `grim`/`slurp` (screenshots)
- Sway config: **all windows floating by default** (`for_window [class=".*"] floating enable`
  style rule) to get Nebula's floating feel out of a tiling compositor
- Lock: `swaylock` with a Pillow-rendered starfield+clock background image,
  regenerated on wallpaper change; idle → lock via `swayidle`

What it delivers: floating-island top bar, scattered scalloped widgets
(GTK/CSS + Cairo blob shapes), wallpaper-derived colours live-applied,
starfield lock screen with huge clock, radial launcher (custom GTK popup).
What it honestly loses vs the reel: no live blur (faked with pre-blurred
images), no window open/close animations, lock screen is a still image, not
orbiting live widgets, and no Quickshell QML hot-reload ergonomics.

### Runner-up (only if live blur is non-negotiable)

**Wayfire 0.7.4 from apt** + the same GTK shell. Real blur and animations,
same layer-shell shell code (shell is compositor-agnostic). Accept an old
compositor (2022) and verify the blur plugin actually ships in bookworm's
`wayfire` package before committing.

### Do NOT do

- **Old Hyprland 0.24.1 from source on bookworm** — 3-year-old snapshot,
  forked graphics stack, no security updates. Looks like Hyprland, is not
  maintainable Hyprland.
- **labwc 0.5.3 from source as the v5 default** — viable build, but 2022-era
  and AegisOS would own it. Keep as a stretch option only if sway's tiling
  model proves unworkable (it shouldn't — floating-by-default fixes it).
- **Backporting half of trixie into bookworm** (wayland, wlroots, libinput,
  gcc, Qt) to force modern Hyprland/Quickshell in — at that point you have
  rebuilt trixie badly; just rebase.

### The real-Hyprland path (v6 candidate, not v5)

**Rebase AegisOS on Debian 13 trixie + trixie-backports**, then:

- `apt install -t trixie-backports hyprland` → **0.55.2**
- `apt install -t trixie-backports quickshell` → **0.3.0**
- Qt 6.8.2, kernel 6.12, glibc 2.38 — all apt, no source builds
- Then port Nebula's *architecture* (not its code) into original QML:
  shell.qml + services + widgets + matugen templates + a from-scratch
  scalloped-shape QML component (m3shapes is a separate repo — see §6)

This is the only honest route to "real Hyprland + Quickshell". It is a
base-OS migration affecting the whole image build, kernel, and the v4 lab
stack — needs its own decision, testing, and a full regression pass. Do not
smuggle it into v5.

## 6. Nebula architecture summary (own words, from README + repo tree)

Repo: https://github.com/LilaccFlowerr/Nebula — public, **AGPL-3.0**
(the task brief said "unknown licence"; the repo page lists GNU AGPL v3.0),
122 commits, created 2026-09-27, 14 stars, 0 releases. Arch-only by design:
README says *"Nebula is made for arch linux. most packages depend on the aur,
so it most likely wont work on your fedora or debian install."* It is a
dotfiles repo + installer, not a distro or an OS image.

**Layers (top to bottom):**

1. **Hyprland** — the compositor. Its config is *generated from Lua*:
   `hypr/hyprland.lua` + `hypr/variables.lua` produce the config; the user
   overrides apps/borders/keybinds in `~/.config/nebula/hypr-vars.lua` and
   appends their own in `hypr-user.lua`. `hypr/hyprland/` holds the generated
   output. `hypridle.conf` (idle → lock/suspend) and `hyprlock.conf` sit
   alongside.
2. **Quickshell (`qs -c nebula`)** — the entire shell, one QML process.
   Entry `quickshell/nebula/shell.qml`; subfolders:
   - `widgets/` — one directory per surface: `bar` (the three floating
     islands: workspaces / pinned+running apps / power+settings), `desktop`,
     `galaxy`, `launcher` (Super key; `>` commands for theme, wallpaper,
     settings, lock, sleep, restart, shutdown, logout, record, dark/light),
     `lock`, `popups`, `recorder`, `screenshot`, `settings`, `wallpaper`.
   - `services/` — one QML singleton per system domain: Audio, Battery,
     BluetoothStatus, Brightness, Cava, Dock, Equalizer, HyprConfig,
     Launcher, Lock, Media, Notifications, Power, Scheme, Screenshot,
     Settings, SystemInfo, SystemStats, Time, Wallpaper, Weather, Wifi,
     Workspaces, Apps, Events, GlobalStates, Tiles, Widgets, etc.
   - `components/` — reusable QML pieces: `GlassShape` / `GlassRect`
     (frosted panels), `Island`, `FloatingShapes`, `BatteryRing`,
     `Visualizer`, `MirroredCava`, `MorphButton`, `Orbits.js`, `Curves.js`,
     `LoadingIndicator`, `WavyProgress`, sliders/switches/tiles.
   - `theme/`, `shaders/`, `assets/` — theme data, GLSL shaders, images.
   - IPC: everything is script-addressable —
     `qs -c nebula ipc call <target> <function>` (targets include launcher,
     settings, quicksettings, media, missed, calendar, tray, system,
     recorder, screenshot, wallpaper, scheme, lock).
3. **matugen** — wallpaper → Material You colour scheme generator.
   `matugen/config.toml` + `matugen/templates/`; the flow is
   `matugen image <wallpaper>` → generated colour files consumed by both
   Hyprland and the Quickshell `Scheme` service, so picking a wallpaper
   recolours the whole desktop live with no reload. Settings UI writes
   `~/.config/nebula/settings.json`; changes apply immediately.
4. **m3shapes** — a *separate* repo (github.com/soramanew/m3shapes), a QML
   port of Google's Material 3 Expressive shapes; built with CMake/Ninja
   (`qt6-shadertools` needed) and installed system-wide. This is what makes
   the shapes morph. The README notes the bar may disappear after a Qt
   update until m3shapes is rebuilt.
5. **Apps/tooling** (Arch packages): `ghostty`, `firefox`, `nautilus`,
   `fuzzel` (clipboard picker only), `cliphist`, `wl-clipboard`, `grim`,
   `slurp`, `mate-polkit`, `playerctl`, `brightnessctl`, `cava`, `zenity`,
   `libnotify`, `ffmpeg`, `jq`, `gpu-screen-recorder`, Papirus icons,
   Inter + Material Symbols fonts.
6. **install.sh** — guided installer: full system upgrade, installs
   packages, builds m3shapes, symlinks `hypr`, `quickshell`, `matugen`,
   `ghostty` into `~/.config`, backs up existing configs to
   `~/.config/nebula-backup-*`, runs matugen once. Does not configure a
   login manager, networking, or audio — it assumes a working Arch desktop.

**Lock screen:** the README advertises *"a lockscreen with a black hole
music player and orbiting planets"* and the repo has both `widgets/lock/` and
`services/Lock.qml` **and** a `hypr/hyprlock.conf`. Which one actually locks
the screen (Quickshell lock vs hyprlock) was **not verified** from the tree
listing alone — and the README's own Roadmap still lists "Lock screen" as a
to-do, so treat the lock screen as possibly incomplete/aspirational despite
the feature blurb. Do not promise the orbiting-widgets lock screen until
someone reads the lock QML.

**Licence note:** Nebula is AGPL-3.0, and m3shapes has its own licence
(unchecked). Our plan is original code inspired by the look, not a copy, so
this is a non-issue — but do not lift Nebula's QML/Lua or m3shapes code into
AegisOS without a licence review.

## 7. Open risks / things NOT verified

1. **VM graphics:** any Wayland path in the AegisOS test VM depends on
   software rendering (llvmpipe) unless 3D accel is enabled. Sway is the
   safest here; Wayfire/Hyprland are pickier. Must be tested by actually
   booting the image in the VM — no amount of repo reading settles it.
2. **Wayfire blur packaging:** whether bookworm's `wayfire` 0.7.4 package
   includes the blur plugin or whether `wayfire-plugins-extra` is needed —
   unverified.
3. **Hyprland 0.24.1 build time / RAM** on 4 CPU / 8 GB — unverified; only
   a rough "tens of minutes" estimate. (Moot: not recommended.)
4. **matugen prebuilt binaries** — whether GitHub releases ship a
   linux-x86_64 tarball, and whether bookworm's Rust toolchain can build
   matugen 4.x — both unverified. Moot if we use the Pillow approach.
5. **Nebula lock-screen implementation** (Quickshell lock vs hyprlock;
   completeness) — unverified; tree listing only.
6. **Exact trixie labwc version** — labwc is in trixie (and is Raspberry Pi
   OS Trixie's default compositor), but the exact version number was not
   checked on packages.debian.org.
7. **gtklock / waylock availability in bookworm** — not checked; do not
   assume a packaged custom lock screen exists.
8. **bookworm-backports gcc version** — not checked; irrelevant to the
   verdict anyway (nothing short of gcc 16 unblocks current Hyprland).
9. **Debian 13 trixie rebase impact** on the existing v4 lab stack
   (Suricata/auditd rules, lab services, GRUB/BIOS image build) — not
   assessed here; that is a separate piece of work if v6 goes the trixie
   route.

## 8. Sources checked 2026-11-12

- packages.debian.org/bookworm: `hyprland` (absent), `quickshell` (absent),
  `labwc` (absent), `river` (absent), `matugen` (absent), `sway` 1.7-6,
  `wayfire` 0.7.4-3+deb12u1, `python3-pil` 9.4.0-1.1+deb12u1, `gcc`
  4:12.2.0-3, `qt6-base-dev` 6.4.2+dfsg-10, `picom` 9.1-1, `waybar`
  0.9.17-2, `libgtk-layer-shell-dev` 0.8.0-1, `libwayland-server0` (version
  line not shown in fetch; 1.21.x per discussion #1797)
- packages.debian.org/bookworm-backports: `labwc` (absent)
- packages.debian.org/trixie-backports: `hyprland` 0.55.2+ds-1~bpo13+1,
  `quickshell` 0.3.0-1~bpo13+1
- Hyprland wiki, Installation (github.com/hyprwm/hyprland-wiki):
  C++26 / gcc ≥ 16 / clang ≥ 19; "not available for Bookworm"
- Hyprland discussion #1797 (building on Debian sid / bookworm):
  v0.24.1 last version for Wayland 1.21; backports needed for wayland,
  wayland-protocols, libinput
- Quickshell BUILD.md / CMakeLists (via DeepWiki): Qt ≥ 6.6, private Qt APIs
- labwc NEWS.md (github.com/labwc/labwc): version ↔ wlroots table
  (0.5.x → 0.15.1; 0.6.x → 0.16.2; current → 0.20)
- Dux (DankMaterialShell) docs: quickshell from trixie-backports;
  compositor support table (labwc/sway/river/wayfire)
- matugen releases (github.com/InioX/matugen): latest 4.2.0 (Aug 2026),
  GPL-2.0; lib.rs listing
- Nebula repo (github.com/LilaccFlowerr/Nebula): README + tree listings
  for `quickshell/nebula` (components/services/widgets), `hypr/`, `matugen/`;
  AGPL-3.0, 122 commits, 14 stars, commit 0028e65
- FreshPorts swayfx 0.6 (wlroots 0.20) + changelog (0.4 → wlroots 0.17)
