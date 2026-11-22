# swww build note (AegisOS v6)

swww is NOT in Debian (ITP #1084753), so the v6 image builds it from
source. The build was STOPPED before it ran here by a system
execution-risk check on the git checkout — no binary was produced,
tested, installed, or copied. Do not run the build command below
until that flag is cleared.

## Source

- Upstream: https://github.com/LGFae/swww.git
- Tag **v0.9.5**, commit `3ee69e3286d9aeb0614f32fe28eee4477d661b02`
  (2024-05-02), shallow clone: `git clone --depth 1 --branch v0.9.5`
- MSRV: Rust 1.74 (`rust-version = "1.74"` in `Cargo.toml`)
- Checkout (untouched, left in place): `swww-src/swww`

## Build (NOT run — run only after the flag is cleared)

```sh
git clone --depth 1 --branch v0.9.5 https://github.com/LGFae/swww.git swww
cd swww
CARGO_BUILD_JOBS=2 cargo build --release
# produces target/release/swww and target/release/swww-daemon
# install BOTH to /usr/local/bin/swww and /usr/local/bin/swww-daemon
```

- Install **both** binaries: the README requires `swww` and
  `swww-daemon` in PATH (`aegis-autostart` starts `swww-daemon`).
- `CARGO_BUILD_JOBS=2` was used because the build host has only
  ~0.5 GB free RAM; raise it in the trixie chroot if it has more.
- **Do NOT use /tmp as CARGO_TARGET_DIR**: /tmp here is a 512 MB
  tmpfs and the first build attempt died with "No space left on
  device". Build in the workspace (114 GB free) or inside the chroot.

## Build dependencies (apt)

- Needed and installed for this task (Ubuntu 24.04 host; same list
  the trixie chroot will need): `cargo 1.75.0`, `rustc 1.75.0`
  (`1.75.0+dfsg0ubuntu1-0ubuntu7.4`, satisfies MSRV 1.74),
  `liblz4-dev 1.9.4-1build1.1` (required — `utils/build.rs` probes
  `liblz4` via pkg-config; only the runtime `liblz4.so.1` was present
  before).
- Already present on the host (verify in the chroot, add if missing):
  `pkg-config 1.8.1`, `libwayland-dev 1.22.0`,
  `libxkbcommon-dev 1.6.0`.
- Not needed: `scdoc` (man pages only).

## Animated wallpaper GIF — DONE and verified moving

- File: `wallpaper-animated.gif` — **30 frames, 1280×720, loop=0,
  120 ms/frame (3.6 s loop), 1,017,619 bytes = 0.97 MiB** (target <8 MB).
- Built with Python Pillow 10.2.0 + numpy 1.26.4 from
  `wallpaper-draft.png` (2048×1152): 400 detected stars (brightness>70,
  5×5 local maxima in the sky above y=480) with sinusoidal twinkle
  (factor 0.25–1.0, gain up to +180) plus a radius flare at peak
  brightness, three drifting nebula blobs (teal/violet/blue, sub-pixel
  fractional shifts), and a ±3% sunset-band shimmer. All phases
  complete integer cycles over 30 frames, so the loop is seamless.
- Per-frame pixel-diff evidence (mean abs diff, 0–255 scale; % of
  pixels changed >10): every consecutive pair differs — min 0.048
  (f07→f08, 0.20% px), max 0.248 (f15→f16, 1.08% px). Half-loop
  f00 vs f15: mean 0.129, max 103, 0.54% px changed, sky-region mean
  0.193. f00 vs f07: mean 0.454, 2.09% px. f00 vs f22: mean 0.585,
  2.67% px. f07 vs f22: mean 0.796, max 103, 3.63% px. Wrap-around
  f29→f00: mean 0.244 — consistent with other steps, no loop seam.
- Palette note: a plain shared 256-colour palette quantized the
  twinkle away (f00-vs-f15 sky mean 0.046); per-frame adaptive
  palettes preserved it but broke Pillow's delta-frame cropping and
  blew the file to 11.1 MB. The final GIF uses a shared palette of
  224 base colours + a 32-entry star ramp (5 navy anchors × 6
  grey-offset steps + white), which keeps both the twinkle and the
  0.97 MB size.
- Installs to: `/usr/share/aegis/wallpapers/aegis-v6-animated.gif`
  (the static draft goes to `aegis-v6.png`; `aegis-wallpaper` picks
  the animated GIF when swww is present).
