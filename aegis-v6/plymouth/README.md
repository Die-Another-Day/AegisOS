# AegisOS Plymouth theme — `aegis`

Text-only boot splash for AegisOS v6. No image files ship with this
theme — the user will supply the logo later, and until then the splash
is pure text.

## Files

```
plymouth/aegis/
  aegis.plymouth   theme description (ModuleName=script)
  aegis.script     the theme itself (Plymouth script plugin)
```

There are deliberately **no `.png` files** in this directory. The
title ("AegisOS") and the stars are rendered from text by the script,
so the theme works with nothing but these two files.

## What it looks like

- Deep-navy gradient background (Nebula palette: near-black navy at
  the top, slightly lighter navy at the bottom).
- 42 small `*` star glyphs scattered at random positions, each
  twinkling independently (sine-driven opacity, random phase/speed).
- `AegisOS` in large bold text, centred at ~42% screen height,
  fading in and out at 0.5 Hz — the look of the stock `fade-in`
  theme, re-implemented as a script (upstream's fade-in is a C
  plugin, `fade-throbber`, not a script, so this is a from-scratch
  equivalent, not a copy).
- Disk-unlock password prompt: the prompt is rendered as text with
  the typed password shown as a centred row of `*` bullets.
  No box/lock/entry images are used.
- Boot messages appear as small text at the top-left.
- On quit (desktop taking over) the title is left fully opaque.
- There is deliberately **no progress bar**: a bar needs an image
  asset to crop/scale, and this theme ships none. Boot progress is
  visible in the console/details view instead.

## How the build installs it

`setup-v6.sh` and `build-image.sh` already carry these steps; this
theme only fills the source directory they copy from:

```sh
mkdir -p /usr/share/plymouth/themes/aegis
cp -r plymouth/aegis/. /usr/share/plymouth/themes/aegis/
plymouth-set-default-theme aegis
update-initramfs -u
```

`build-image.sh` additionally gates on the theme being present
inside the initramfs (`lsinitramfs … | grep "plymouth/themes/aegis"`).
For the splash to actually show at boot, the kernel command line
also needs the `splash` parameter (GRUB config — see PLAN.md §4);
without it Plymouth still runs, but the splash is skipped.

## Logo slot — where the future logo goes

The user designs the logo himself later. When it exists, **one
master file feeds every surface**:

```
Master file:  /usr/share/aegis/logo.png   (512x512 PNG, transparent background preferred)
```

| Surface | How it picks the logo up |
|---|---|
| Boot splash (this theme) | The build creates a symlink `/usr/share/plymouth/themes/aegis/logo.png -> /usr/share/aegis/logo.png`. The script loads `Image("logo.png")` from its own theme directory, scales it to at most 240 px wide, and shows it centred above the title. **If the file/symlink target is missing, `Image()` returns null and the theme silently stays text-only.** |
| Lock screen | Quickshell shows it above the clock disc if present. |
| Desktop bar | The launcher button shows it (text "AegisOS" until then). |
| App launcher | The launcher header shows it if present. |

**Open item for the build scripts:** the `logo.png` symlink step
above is *not* yet in `setup-v6.sh` / `build-image.sh` — they copy
the theme directory but do not create the symlink. Add this to the
Plymouth install step (a dangling symlink is harmless before the
logo exists):

```sh
ln -sf /usr/share/aegis/logo.png /usr/share/plymouth/themes/aegis/logo.png
```

Do **not** bake any of the `logo-options/` PNGs into the build —
the user skipped those three options and will supply his own file.

## What was checked

- Every Plymouth API call in `aegis.script` was cross-checked
  against the upstream Plymouth source (2026-11-22):
  `Image.Text(text, red, green, blue, alpha, font, align)` and the
  `Image()` null-on-missing-file behaviour come from
  `src/plugins/splash/script/script-lib-image.c`; `Math.Random`,
  `Math.Int`, `Math.Cos`, `Math.Sin` from `script-lib-math.c`; the
  overall structure (refresh / display-normal / display-password /
  message / quit callbacks, `Sprite.SetPosition/SetOpacity/SetImage`)
  follows the stock `themes/script/script.script` example theme.
- `aegis.plymouth` follows the stock script theme's description
  format (`ModuleName=script`, `[script]` section with `ImageDir`
  and `ScriptFile`).

## What could NOT be verified

- **No live render.** Plymouth is not installed on this host, so
  the script was never parsed or executed by the Plymouth script
  engine, and there was no QEMU/VirtualBox boot to screenshot.
  Syntax and runtime behaviour are unproven until the v6 image
  boots with this theme (PLAN.md §8 test 7).
- **Font rendering in initramfs.** The title uses Pango font
  description `"Sans Bold 64"` (resolved to DejaVu Sans in the
  initramfs) and the stars use `"Sans Bold 6/9/13"`. Whether those
  sizes and the `*` glyph render as intended at boot resolution is
  unproven until a real boot.
- **Logo symlink behaviour.** The null-check path (no logo file)
  is by design; the with-logo path (symlink resolves, logo scales
  and centres) is unproven until a logo file exists and the image
  boots.
- **Password-prompt layout.** The centred prompt + `*` bullets
  layout has not been seen on screen; the prompt text width and
  bullet row are computed at runtime and could mis-centre on
  unusual framebuffer sizes.
- **Progress feedback.** As noted above, the theme shows no
  progress bar by design; if the build wants one, it needs an
  image asset or a different approach.
