# SecureOS v4 audit — for the AegisOS v5 (Nebula-style) build

Audit date: 2026-11-12. Audit only — no code written, nothing pushed, nothing modified.
Scope: `~/workspace/secureos-build/secureos-v4/` (+ `secureos-v3/bin/secureos-gui`),
`loveos-repo/` (stale snapshot), live image `secureos-v4.img` (5,368,709,120 bytes).
Repo note: GitHub repo was renamed SecureOS → **AegisOS**
(`https://github.com/Die-Another-Day/AegisOS`, head unchanged `1a10d2db`) on
2026-11-12; the rename is repo-only so far — all code/docs still say SecureOS.

## 1. How the v4 image is built

### 1a. The live v4 image was NOT built by build-image.sh alone

Two build paths exist, and the live image came from the **guest-apply path**:

1. Start from the **v3 image** (`secureos-v3.img`, built by the v3
   `build-image.sh` — Debian bookworm + XFCE).
2. Host serves the payload over HTTP on the QEMU user-net gateway
   (`http://10.0.2.2:18765/`, see `logs/http-server.log` — repeated
   `GET /v4-payload.tar.gz` 200s).
3. `guest-setup-v4.py <image> <logfile>` boots a **copy of the v3 image**
   in QEMU (see §4 for the exact command), logs in as `analyst` / `secure`,
   downloads `v4-payload.tar.gz`, extracts it to `~/v4`, runs
   `sudo bash ~/v4/setup-v4.sh`, then `poweroff`. Log: `logs/setup-v4.log`
   (note: that file is mostly a kernel boot transcript; the real setup output
   went to `/tmp/v4-setup.log` *inside the guest* and was only tail-printed).
4. `setup-v4.sh` (guest side) installs `auditd` + `nftables` via apt, creates
   `labweb`/`labuser` (`labuser:lab123`), creates `/srv/labapp`,
   `/var/log/secureos-lab`, `/var/lib/secureos-lab`, `/etc/secureos-lab`,
   copies `labapp.py`/`server.py`/`v4-console.js`, the three systemd units and
   the four `bin/secureos-*` lab helpers, injects `v4-console.js` into
   `/opt/secureos/index.html`, writes auditd rules
   (`/etc/audit/rules.d/secureos-lab.rules`), writes `disabled` to
   `/etc/secureos-lab/state`, starts labapp once on 127.0.0.1:8080 to create
   the SQLite DB + flag3, runs `secureos-lab-reset-flags` (flag2) and
   `secureos-fim --init`, then stops labapp again. **Lab is OFF by default.**
5. Follow-up guest-apply runs fixed things in place: `guest-fix-auditd.py`
   (installed the six `debs/*.deb` via `dpkg -i` — auditd 3.0.9 + libs,
   fetched from the same host HTTP server), `guest-fix-lab.py`,
   `guest-apply.py` / `guest-apply2.py` / `guest-apply3.py`
   (re-applied labapp/server/units). Logs: `logs/apply*.log`,
   `logs/fix-*.log`. Final regression: `logs/guest-test-v4f.log`.

### 1b. What build-image.sh does (clean-build path — NOT how the live image was made)

`build-image.sh [output-dir]`, default `IMG_SIZE_MB=6144` (6 GiB). No loop
devices (container-safe). Steps:

1. **debootstrap** Debian **bookworm** amd64, `--variant=fakechroot`, via
   `fakechroot fakeroot debootstrap ... http://deb.debian.org/debian`
   (~300 MB download), second stage if pending. `SECUREOS_REUSE_ROOTFS=1`
   skips this if `$WORK/rootfs` already has a kernel. No `.build/` cache
   survives in the v4 folder (deleted after the build).
2. **Chroot setup** (`/tmp/setup.sh` run via direct guest-bash exec with
   `LD_PRELOAD=libfakechroot:libfakeroot`, because the util-linux `chroot`
   binary dies on guest-libc GLIBC mismatches): apt sources = bookworm +
   bookworm-security + bookworm-updates (main, contrib, non-free-firmware);
   hostname `secureos`; `/etc/hosts` with `secureos`; getty on tty1 +
   serial-getty on ttyS0; installs kernel `linux-image-amd64`, systemd,
   openssh-server, dbus, python3, iproute2, nmap, tcpdump, tshark,
   wireshark-common, curl, sudo, auditd, nftables, **Xorg + XFCE4**
   (xfce4, xfce4-panel, thunar, xfce4-terminal, xfce4-taskmanager,
   xfce4-power-manager, mousepad, firefox-esr, x11-xserver-utils, xvfb),
   network-manager, wpasupplicant, firmware-linux, upower, htop.
   Stubs `systemd-sysusers` during install (fakechroot breaks it), pre-creates
   `polkitd` user/group, restores the real binary after.
   SSH is **masked** (`/dev/null` symlinks for ssh.service/ssh.socket/
   sshd.service). User `analyst` / `secure` (sudo), home dirs
   Documents/Downloads/Projects/Logs. Persistent journal `/var/log/journal`.
   Writes `secureos.service` unit (v3 description — see bug §6.1), enables it,
   sets default target `multi-user.target` (CLI boot).
3. **v3-upgrade block (§2b)**: runs only if `startxfce4` or
   `secureos-gui` is missing — installs the GUI packages into a reused
   (v2-era) rootfs. Skipped on a clean build.
4. **v4 lab files**: creates `/srv/labapp/{plugins,public,flags}`,
   `/var/log/secureos-lab`, `/var/lib/secureos-lab`, `/etc/secureos-lab`;
   copies `labapp.py`, `server.py`, `v4-console.js`, the three units and the
   four lab helpers; writes `disabled` to `/etc/secureos-lab/state`;
   writes the XFCE autostart desktop file `secureos-console.desktop`
   (Firefox → http://127.0.0.1:8000), `chown 1000:1000` on analyst `.config`.
5. **Console frontend (§3)**: copies `index.html`, `app.js`, `style.css`,
   `apps/`, `secureos/` from the repo root — resolved as
   `$SRC/../loveos-repo` first, then `$SRC/..` (see bug §6.5: the source is
   the **stale** loveos-repo snapshot, not remote main). Copies
   `v3-console.js` from `$SRC` (missing in v4 — see §6.2) and
   `v2-console.js` from `loveos-repo/secureos-v2/` if present, then injects
   `<script>` tags for both into `index.html` (see §6.3).
6. **GRUB**: replaces fakechroot's `/dev`+`/proc` symlinks with real dirs;
   re-asserts ssh mask + multi-user target; fixes host-prefixed symlinks;
   writes `/boot/grub/grub.cfg` — menuentry `"SecureOS v4"`,
   `linux /boot/vmlinuz-… root=/dev/sda1 rw console=tty0 console=ttyS0,115200`;
   writes `/etc/fstab` (`/dev/sda1 / ext4 defaults 0 1`).
7. **Pack**: `mkfs.ext4 -q -O ^metadata_csum,^64bit -d $ROOTFS -L secureos
   $WORK/root.ext4 ${IMG_SIZE_MB-1}M` (no mount needed).
8. **Assemble**: Python writes an MBR (one bootable 0x83 partition at 1 MiB),
   appends the ext4 fs, then `grub-mkimage -O i386-pc` builds `core.img`
   (biosdisk, part_msdos, ext2, linux, search, configfile; prefix
   `(hd0,msdos1)/boot/grub`), `boot.img` into the MBR (partition table
   preserved) + `core.img` into the post-MBR gap. Writes
   `secureos-v4.img.sha256`.

Result: raw, MBR + GRUB BIOS, single ext4 partition, boots in QEMU and is
`dd`-able to USB. Live kernel (from boot logs): **6.1.0-54-amd64**
(Debian 6.1.190-1).

**Size discrepancy:** `build-image.sh` defaults to 6144 MiB, but the live
`secureos-v4.img` is exactly 5,368,709,120 bytes = **5120 MiB** — so the live
image was built with `IMG_SIZE_MB=5120` or by the guest-apply path from a
5 GiB v3 image. The v4 `.sha256` file is absent from the folder.

### 1c. How it boots, and how the GUI starts

- Default target `multi-user.target` → **CLI + web console**. `secureos.service`
  runs `/usr/bin/python3 /opt/secureos/server.py` as root,
  `SECUREOS_ALLOW_PUBLIC=0`, `EnvironmentFile=-/etc/secureos-lab/env`
  (present only in lab mode). Console on **http://127.0.0.1:8000**.
- Login: `analyst` / `secure`. Serial console on ttyS0 (QEMU `-nographic`).
- GUI is **on-demand only**: `secureos-gui` (from `secureos-v3/bin/`,
  see §6.4) writes `~/.xinitrc` (`exec startxfce4`), writes autostart
  `.desktop` files (`secureos-console.desktop` → Firefox to :8000,
  `nm-applet.desktop`, optional fullscreen `xrandr` one), then `exec startx`.
  `--window` (default) / `--fullscreen` / `--stop` (pkills xfce4-session,
  Xorg, xfwm4). No display manager is enabled. XFCE + Firefox ESR.
- Lab mode: `sudo secureos-lab --enable` (private LAN IP only) restarts
  `secureos.service` (binds console to LAN IP), starts
  `secureos-labapp.service` (labapp.py on :8080, bound to that LAN IP, never
  0.0.0.0) and `secureos-ssh-lab.service` (SSH on :2222), applies nftables
  rules. `--stop` kills all lab services and restores localhost-only.
- Server API (all in `server.py`, stdlib only): `GET /api/health`
  (`{"name": "SecureOS", "version": "4.0", …}`), `/api/system-logs`,
  `/api/system`, `/api/processes`, `/api/files`, `/api/drivers`,
  `/api/logs`, `/api/battery`, `/api/network`, `/api/lab`, `/api/alerts`,
  `/api/incidents`, `/api/flags`; `POST /api/scan`, `/api/logs`,
  `/api/hash`. **No `/api/*` path contains "secureos"** — endpoints need no
  rename. Console frontend served from `/opt/secureos`.

### 1d. Saral status

**Saral is NOT in the v4 image.** Zero `saral` matches in the whole v4
folder. Saral lives only in the repo: `loveos-repo/saral/` (`saral.py` +
`libs/` + `SARAL-README.md`). The "SecureOS integration" pushed 2026-11-02
was repo-side (Saral blocks) and was never baked into a booted image. v5
must add an explicit Saral install step (see §3).

## 2. Rename map: SecureOS/secureos → AegisOS/aegis

Counts are case-insensitive matches per file in `secureos-v4/` (plus v3
helpers and the repo frontend, which the image also contains).

### 2a. Files and the strings in them

| File | # | What the strings are |
|---|---|---|
| `build-image.sh` | 55 | comments, `secureos` hostname/hosts, `/opt/secureos`, `/usr/local/lib/secureos-server.py`, unit text, `SECUREOS_REUSE_ROOTFS`, fs label `secureos`, GRUB menuentry "SecureOS v4", v2/v3-console.js, `secureos-*` helper copy loops |
| `server.py` | 24 | docstrings, `SECUREOS_BIND_IP`, `SECUREOS_ALLOW_PUBLIC`, `/etc/secureos-lab/state`, `/var/log/secureos-lab/*.log`, `/opt/secureos` allowlist, `"name": "SecureOS", "version": "4.0"`, `"secureos"`/`"secureos-labapp.service"` in `/api/lab` services dict, `secureos-fim --check` allowlist call, `secureos-net` in a help string, `secureos-gui` in `/api/health` gui string |
| `labapp.py` | 10 | docstrings, `/var/log/secureos-lab/app.log`, `SECUREOS_BIND_IP`, `logger -t secureos-labapp`, HTML `<h1>SecureOS Lab…</h1>`, "SecureOS Lab — internal notes" |
| `bin/secureos-lab` | 33 | docstrings/usage, `/etc/secureos-lab/*`, `/var/log/secureos-lab/*`, nft table `secureos_lab`, `logger -t secureos-lab`, unit names `secureos*.service`, calls `secureos-lab-reset-flags`, `secureos-fim --init` |
| `bin/secureos-ir` | 26 | docstrings, `/var/log/secureos-lab/ir.log`, nft table `secureos_lab`, units `secureos-labapp.service` / `secureos-ssh-lab.service`, `logger -t secureos-ir` |
| `bin/secureos-fim` | 8 | docstring, manifest `/var/lib/secureos-lab/manifest.json`, watched `/etc/secureos-lab/state` + `/home/labuser/flag2.txt` |
| `bin/secureos-lab-reset-flags` | 1 | comment referencing `secureos-lab --reset` |
| `secureos.service` | 4 | Description, `ExecStart … /opt/secureos/server.py`, `SECUREOS_ALLOW_PUBLIC`, `EnvironmentFile=-/etc/secureos-lab/env` |
| `secureos-labapp.service` | 3 | Description, `EnvironmentFile=-/etc/secureos-lab/env`, `ExecStart … /srv/labapp/labapp.py $SECUREOS_BIND_IP` |
| `secureos-ssh-lab.service` | 1 | Description |
| `v4-console.js` | 3 | comment, DOM id `secureos-v4-lab` |
| `setup-v4.sh` | 29 | paths `/opt/secureos`, `/etc/secureos-lab/*`, `/var/log/secureos-lab`, units, `secureos-lab-reset-flags`, `secureos-fim --init`, curl `:8000/api/health` |
| `README-v4.md` | 29 | title, prose, all command names, paths, units |
| `run-qemu.sh` / `run-qemu-gui.sh` | 5 / 11 | comments, image name `secureos-v4.img`, `SECUREOS_DISPLAY` env var, "SecureOS v4 GUI mode" |
| `guest-test-v4.py` | 16 | docstring, markers `MARK_V4_*`, `analyst@secureos` prompt wait, `secureos-lab` commands |
| `guest-setup-v4.py` | 2 | `secureos login:` and `analyst@secureos` prompt waits |
| `guest-apply*.py`, `guest-fix-*.py` | 2–5 each | docstrings, payload/HTTP paths |
| `host-ssh-flag.py` | 0 | no brand strings — keep as-is |
| `secureos-v3/bin/secureos-gui` | 20 | help text, autostart `secureos-console.desktop`, `secureos-fullscreen.desktop`, console URL strings |
| `secureos-v3/bin/secureos-status` | 4 | — |
| `secureos-v3/bin/secureos-{drivers,logs,net}` | 1 each | — |
| Repo frontend `index.html` / `app.js` | ~10 | `<title>SecureOS — Analyst Console</title>`, `<h1>SecureOS</h1>`, "SecureOS v1.0", ticker, taskbar, `localStorage "secureos_user"`, `window.SecureOS_openApp`, `secureos/filesystem.js`, `secureos/vfs.js` |
| Repo `apps/` + `secureos/` JS | 18 | `secure-apps.js` (9), `filesystem.js` (3), `terminal.js`/`terminal.html` (5), `vfs.js` (1) |
| **Inside the image (not in the v4 folder)** | — | `/etc/hostname` = `secureos`, `/etc/hosts`, `/opt/secureos/*`, `/usr/local/lib/secureos-server.py`, `/etc/secureos-lab/*`, `/var/log/secureos-lab/*`, `/var/lib/secureos-lab/*`, `/etc/audit/rules.d/secureos-lab.rules`, autostart `secureos-console.desktop`, GRUB menuentry, ext4 label `secureos`, `secureos.service` unit |

### 2b. Proposed renames, with risk

| Old | New | Risk | Notes |
|---|---|---|---|
| hostname `secureos` (+ `/etc/hosts` line) | `aegis` | **Safe** | Cosmetic; also changes shell prompt `analyst@aegis` — update `guest-test-v5.py` / `guest-setup-v5.py` prompt waits (`secureos login:`, `analyst@secureos`) or they time out |
| `secureos.service` | `aegis.service` | Medium | Referenced by: `aegis-lab` (restart), `server.py` `/api/lab` services dict (`"secureos": svc("secureos.service")`), `setup-v5.sh` (`systemctl enable/restart`), build-image.sh unit write. Rename in all four places atomically |
| `secureos-labapp.service` | `aegis-labapp.service` | Medium | Referenced by: `aegis-lab`, `aegis-ir` (stop/restart/status), `server.py` `/api/lab` dict, `setup-v5.sh`. Same atomic-rename rule |
| `secureos-ssh-lab.service` | `aegis-ssh-lab.service` | Medium | Same set of referrers as labapp |
| `bin/secureos-lab` | `bin/aegis-lab` | Medium | Calls `aegis-lab-reset-flags`, `aegis-fim --init`, `systemctl … aegis*.service`; invoked by user + `setup-v5.sh`; docs |
| `bin/secureos-ir` | `bin/aegis-ir` | Medium | Same unit + nft-table references as `aegis-lab` |
| `bin/secureos-fim` | `bin/aegis-fim` | Medium | Manifest path changes with `/var/lib/aegis-lab`; called by `server.py` allowlist (`["secureos-fim", "--check"]`) — **must update that allowlist or /api/alerts breaks** |
| `bin/secureos-lab-reset-flags` | `bin/aegis-lab-reset-flags` | Low | Called by `aegis-lab --reset` and `setup-v5.sh` |
| `bin/secureos-gui` (+ `secureos-{status,logs,net,drivers}` from v3) | `bin/aegis-gui`, `aegis-status`, `aegis-logs`, `aegis-net`, `aegis-drivers` | Low–Medium | `aegis-gui` is the v5 desktop launcher (see §3 — may be replaced by the Wayland session; if kept as XFCE fallback, rename). `server.py` only mentions `secureos-net` inside a help string. `aegis-status` output text should say AegisOS |
| `/opt/secureos` | `/opt/aegis` | **Safe if atomic** | `server.py` serves from here + allowlists `/opt/secureos`; units `ExecStart`; build-image.sh copies; `setup-v5.sh` copies. All four must move together |
| `/usr/local/lib/secureos-server.py` | `/usr/local/lib/aegis-server.py` | Safe | Build-time staging copy only |
| `/etc/secureos-lab` | `/etc/aegis-lab` | **RISKY** | State file, `env` file, `nft.conf`, auditd rules watch this path, FIM watches `…/state`. Rename in: `server.py` (LAB_STATE), `aegis-lab`, `aegis-fim` watched list, `aegis-ir` (via units only — check), audit rules file, `setup-v5.sh`, build-image.sh mkdir. **A missed reference = lab enable/status silently broken or audit rules watching a dead path.** Recommend a single `grep -r secureos` gate in the v5 build that fails the build on any leftover |
| `/var/log/secureos-lab` | `/var/log/aegis-lab` | Medium | `server.py` LAB_LOG/LAB_IRLOG, `labapp.py` LOG, all three lab helpers, `setup-v5.sh`, build-image.sh mkdir |
| `/var/lib/secureos-lab` | `/var/lib/aegis-lab` | Medium | FIM manifest path; `aegis-lab --reset` / `setup-v5.sh` |
| nft table `secureos_lab` | `aegis_lab` | **RISKY** | Created/deleted/listed by `aegis-lab` (`nft -f`, `delete table inet secureos_lab`, `list table inet secureos_lab`) and by `aegis-ir` contain/uncontain (add/delete rule, `--handle list`). A half-rename leaves stale rules or `contain` failing. Also `aegis-ir`'s docstring tells users to verify with `nft list table inet …` — update the docstring too |
| auditd keys `secureos_lab`, `secureos_labuser`, `secureos_labstate` + rules file `secureos-lab.rules` | `aegis_lab`, `aegis_labuser`, `aegis_labstate` / `aegis-lab.rules` | Low | `-k` tags are labels; old logs keep old keys. Safe, but do it for consistency |
| `logger -t secureos-lab[app]`, `secureos-ir` | `aegis-lab[app]`, `aegis-ir` | Low | Journal grep strings only |
| Env vars `SECUREOS_BIND_IP`, `SECUREOS_ALLOW_PUBLIC` | `AEGIS_BIND_IP`, `AEGIS_ALLOW_PUBLIC` | **RISKY — decision needed** | Four places must agree: `aegis-lab` writes `/etc/aegis-lab/env`; `aegis.service` + `aegis-labapp.service` read it via `EnvironmentFile`; `server.py` reads `SECUREOS_BIND_IP`/`SECUREOS_ALLOW_PUBLIC`; `labapp.py` reads `SECUREOS_BIND_IP` (and the labapp unit passes `$SECUREOS_BIND_IP` as argv). **Cheapest safe option: keep the env-var names unchanged** (they're not user-visible) and only rename files/paths/UI. If renamed, do it in one commit with a grep gate |
| `SECUREOS_REUSE_ROOTFS` (build-time) | `AEGIS_REUSE_ROOTFS` | Safe | Host-side build env var only; rename + update docs |
| `SECUREOS_DISPLAY` (run-qemu-gui.sh) | `AEGIS_DISPLAY` | Safe | Host-side only |
| `SECUREOS_REPO_ROOT` (build-image.sh) | `AEGIS_REPO_ROOT` | Safe | Host-side only |
| `/api/health` `"name": "SecureOS", "version": "4.0"` | `"name": "AegisOS", "version": "5.0"` | Low | Display-only; `v5-console.js` does not consume `name`. Keep the JSON shape identical |
| DOM id `secureos-v4-lab` | `aegis-v5-lab` | Safe | Created and queried only inside `v5-console.js` |
| `localStorage "secureos_user"`, `window.SecureOS_openApp` | `aegis_user`, `window.AegisOS_openApp` | Low | Per-browser key; rename orphans the stored login name (cosmetic). Internal global — rename with its callers in `app.js`/`index.html` |
| Frontend dir `secureos/` (vfs.js, filesystem.js) | `aegis/` | Low | Script `src=` paths in `index.html` must move with it |
| ext4 label `secureos` | `aegis` | Safe | Label is not used at boot (GRUB uses `(hd0,msdos1)`, kernel uses `root=/dev/sda1`) |
| GRUB menuentry `"SecureOS v4"` | `"AegisOS v5"` | Safe | Cosmetic |
| Autostart `secureos-console.desktop` / `secureos-fullscreen.desktop`, Name "SecureOS Console" | `aegis-console.desktop` / `aegis-fullscreen.desktop`, "AegisOS Console" | Safe | Written in two places: build-image.sh and `aegis-gui` at runtime — rename both |
| `secureos-v4.img`, `v4-payload.tar.gz`, `v4-console.js` | `aegis-v5.img`, `v5-payload.tar.gz`, `v5-console.js` | Safe | Filenames; update all references (scripts, README, guest-test) |
| **KEEP unchanged** | — | — | Users `analyst`, `labweb`, `labuser`; `/srv/labapp` (+ `lab.db`, `flags/flag*.txt`, `plugins/`); ports 8000 (console) / 8080 (labapp) / 2222 (lab SSH); all `/api/*` paths; guest IP 10.0.2.15 under QEMU user-net; flag mechanics. These carry no brand string and renaming them adds risk for zero benefit |

**What must stay working through the rename:** Red vs Blue lab
(`aegis-lab --enable/--status/--stop/--reset`, SQLi/SSH/plugin flags,
real journal/FIM alerts, `aegis-ir` contain/uncontain/kill-session/
eradicate/recover), Saral (new in v5 — see §3), web console on
127.0.0.1:8000. The rename is safe only as an **atomic, grep-gated**
change: after renaming, `grep -ri secureos` over the v5 folder **and**
over the built image's `/opt/aegis`, `/etc`, `/usr/local/bin` must return
zero (excluding historical docs if any are deliberately kept).

## 3. Proposed v5 file set (`~/workspace/secureos-build/secureos-v5/`)

NOT created — list only.

### 3a. Carry over from v4 (copy + rename)

| v5 file | From | Purpose |
|---|---|---|
| `build-image.sh` | v4 `build-image.sh` | Clean-build the v5 image (debootstrap → chroot → ext4 → GRUB). Needs the §6 fixes + Wayland install step + Aegis renames |
| `setup-v5.sh` | v4 `setup-v4.sh` | Guest-install path: install lab inside a booted image (fallback if clean build lags) |
| `server.py` | v4 `server.py` | Console backend (stdlib only), renamed paths/vars, version 5.0 |
| `labapp.py` | v4 `labapp.py` | Vulnerable lab web app (:8080), renamed strings |
| `v5-console.js` | v4 `v4-console.js` | Lab-status wiring for the console frontend |
| `aegis.service` | v4 `secureos.service` | Console unit (localhost; LAN in lab mode) |
| `aegis-labapp.service` | v4 `secureos-labapp.service` | Lab app unit |
| `aegis-ssh-lab.service` | v4 `secureos-ssh-lab.service` | Lab SSH (:2222) unit |
| `bin/aegis-lab` | v4 `bin/secureos-lab` | Lab enable/stop/status/reset + nftables |
| `bin/aegis-ir` | v4 `bin/secureos-ir` | Incident response actions |
| `bin/aegis-fim` | v4 `bin/secureos-fim` | SHA-256 file-integrity checker |
| `bin/aegis-lab-reset-flags` | v4 `bin/secureos-lab-reset-flags` | Regenerate flag2 |
| `bin/aegis-gui` | **v3** `bin/secureos-gui` (NOT in v4/bin) | XFCE on-demand launcher — keep only if XFCE stays as fallback; otherwise replaced by the Wayland session (§3c) |
| `bin/aegis-status`, `bin/aegis-logs`, `bin/aegis-net`, `bin/aegis-drivers` | **v3** `bin/secureos-*` (NOT in v4/bin) | CLI helpers — must be sourced from v3, see bug §6.4 |
| `run-qemu.sh` | v4 `run-qemu.sh` | CLI-mode QEMU runner (image name → `aegis-v5.img`) |
| `run-qemu-gui.sh` | v4 `run-qemu-gui.sh` | Graphical QEMU runner — needs virtio-GPU/virgl flags for Wayland (see §4) |
| `guest-test-v5.py` | v4 `guest-test-v4.py` | Full headless regression (markers `MARK_V5_*`, same hostfwd) |
| `guest-setup-v5.py` | v4 `guest-setup-v4.py` | First-boot payload install into a base image (only if the guest-apply path is kept) |
| `host-ssh-flag.py` | v4 `host-ssh-flag.py` | PTY driver for the SSH-flag test step (no brand strings) |
| `README-v5.md` | v4 `README-v4.md` | Rewritten for AegisOS v5 + Nebula desktop + lab |
| `aegis-v5.img` / `aegis-v5.img.sha256` | (build artifacts) | The built image + checksum — **do not forget the .sha256 this time** (v4's is missing) |

### 3b. Drop

| Item | Why |
|---|---|
| `guest-apply.py`, `guest-apply2.py`, `guest-apply3.py` | One-off fix scripts for the v3→v4 in-guest upgrade; v5 is a clean build. Keep one generic `guest-apply-v5.py` only if a guest-patch path is needed later |
| `guest-fix-auditd.py`, `guest-fix-lab.py` | One-off v4 fixes; superseded by a correct clean build (auditd via apt in chroot) |
| `debs/` (auditd 3.0.9 + 5 libs) | Workaround for a guest apt failure in the v4 timeline; `build-image.sh` already installs auditd via apt. Drop, or keep as a documented fallback — do not silently rely on it |
| `v4-payload.tar.gz` | Regenerate as `v5-payload.tar.gz` from the v5 sources at build time |
| `logs/` (old v4 logs) | History only; v5 runs create fresh logs |
| `secureos-v2/`, `secureos-v3/` copies inside the repo snapshot | Stale; v5 sources live in `secureos-v5/` + the renamed `AegisOS` repo |

### 3c. NEW files for the Nebula-style Wayland desktop

| New file | Purpose |
|---|---|
| `wayland/install-wayland.sh` | Install Hyprland + Quickshell + matugen (see base decision below — **not** plain `apt install` on bookworm) |
| `wayland/hyprland.conf` | Hyprland config: gaps, rounding, blur, animations, keybinds, workspace rules |
| `wayland/aegis.desktop` | Wayland session entry (`/usr/share/wayland-sessions/aegis.desktop`) so greetd/SDDM can launch it |
| `wayland/greetd.toml` (or SDDM config) | Display manager that boots straight to the lock screen (Nebula reel: lid-open → lock screen → desktop, no splash) |
| `shell/shell.qml` | Quickshell root shell (loads bar, lock, launcher, widgets) |
| `shell/lock/LockScreen.qml` | Lock screen: huge clock in scalloped disc, orbiting widgets, music-player card |
| `shell/bar/Bar.qml` | Floating-island top bar |
| `shell/launcher/Launcher.qml` | App launcher (Nebula-style, blurred wallpaper behind) |
| `shell/widgets/Widgets.qml` (+ `Clock.qml`, `Music.qml`, `System.qml`) | Scattered scalloped widgets (clock, music, system stats) |
| `shell/notifications/Notifications.qml` | Notification centre / OSD |
| `shell/theme/Theme.qml` + `matugen/` templates | Material 3 Expressive shapes + wallpaper-derived colours (matugen config + QML colour bindings) |
| `wallpapers/aegis-starfield-*.png` | Dark navy starfield wallpapers (the Nebula opening look) |
| `theme/gtk.css`, `theme/qt.conf`, cursor theme | GTK/Qt/cursor theme matching the shell so Firefox/Thunar don't look alien |
| `fonts/` (e.g. Inter / JetBrains Mono) | Shell + UI fonts (check licensing before shipping) |
| `saral/` (copied from repo root `saral/`) | **Saral integration, first time in a booted image**: `saral.py` + `libs/`, installed to `/opt/aegis/saral` (or `/usr/local/bin/saral` wrapper) + a console/launcher entry |
| `docs/NEBULA-REFERENCE.md` | Reel notes: what the reference actually shows (lock screen → desktop, no boot splash), what is/isn't being copied |
| `docs/CHANGELOG-v5.md` | v5 changes: rename, Wayland desktop, Saral, base decision |

### 3d. Base-distro decision — the biggest v5 risk (verified by web search)

- **Hyprland is NOT available for Debian bookworm** (Hyprland wiki:
  "Hyprland is not available for Bookworm as its packages are too old";
  packaged from Debian 14 Forky, and in Debian 13 **trixie-backports**).
- **Quickshell is packaged in Debian unstable/testing and in
  trixie-backports** (`apt install -t trixie-backports quickshell`); not in
  bookworm. It needs Qt ≥ 6.6 (bookworm ships Qt 6.4) and must be rebuilt
  against each Qt release (private Qt APIs).
- **Therefore v5 cannot stay on a bookworm base with plain apt.**
  Options, in order of sanity: **(A) rebase v5 on Debian trixie**
  (stable; kernel 6.12) + trixie-backports for `hyprland` + `quickshell` +
  `matugen` (matugen is not in Debian either — build from source/cargo or
  fetch a release binary); **(B)** stay on bookworm and build
  Hyprland + Quickshell + Qt from source (needs backported wayland,
  wayland-protocols, libinput, wlroots, Qt — heavy, fragile);
  **(C)** bookworm + a compositor that *is* packaged there (sway/labwc)
  with Quickshell built from source (still needs newer Qt).
  **Recommendation: (A).** This also changes the kernel (6.1 → 6.12),
  the debootstrap suite, and the apt sources in `build-image.sh`.
- QEMU graphics caveat (JaKooLit Debian-Hyprland script): "On VMs, enable
  3D acceleration or Hyprland may not start." The v4 QEMU command uses
  `-vga std` (no GL). Graphical verification of v5 needs virtio-GPU +
  virgl or software rendering (`WLR_RENDERER_ALLOW_SOFTWARE=1`); plan for
  that in `run-qemu-gui.sh` (see §4).

## 4. QEMU test method (how v4 was tested)

Environment: **QEMU 8.2.2** (`/usr/bin/qemu-system-x86_64`), displays
available: `none, gtk, sdl, egl-headless, curses, spice-app, dbus`.
Disk: `/home/hatch` 150 G, **135 G free** — plenty. Host RAM: 7.7 GiB
total, **only ~535 MiB available at audit time** — a `-m 2048` guest plus
a graphical session is tight on this host right now; free RAM or accept
slower runs before graphical v5 verification.

### 4a. CLI / headless regression — `guest-test-v4.py` (the proven harness)

Exact QEMU invocation (from `guest-test-v4.py:24-30`):

```
qemu-system-x86_64 -m 2048 -machine pc -cpu qemu64 \
  -drive file=<IMG>,format=raw,if=ide \
  -netdev user,id=net0,hostfwd=tcp::18000-:8000,hostfwd=tcp::18080-:8080,hostfwd=tcp::12222-:2222 \
  -device e1000,netdev=net0 \
  -display none -serial stdio -monitor none
```

- PTY-driven: waits for `secureos login:` → `analyst` / `secure` →
  `analyst@secureos` prompt; default timeout **1500 s**.
- Guest IP under user-net: **10.0.2.15**; host gateway **10.0.2.2**
  (payload/debs served from host HTTP on :18765).
- Host-side attacks via forwarded ports: console on
  `127.0.0.1:18000`, labapp on `127.0.0.1:18080`, lab SSH on
  `127.0.0.1:12222` (`host-ssh-flag.py` PTY driver, no sshpass on host).
- Proves, in order (markers `MARK_V4_*` in the log): default lab OFF →
  `secureos-lab --enable` on a private IP → nmap finds lab services →
  SQLi flag → SSH flag → plugin flag → alerts from real logs → nft
  contain/uncontain → kill-session → eradicate → recover → reset →
  `--stop` shuts everything down. Final run `logs/guest-test-v4f.log`
  passes all of these; transcript ends with lab `disabled`,
  `secureos.service: active`, labapp/ssh `inactive`, `LABAPP_OFF_AFTER_STOP`.
- For v5: same harness as `guest-test-v5.py`, markers `MARK_V5_*`,
  prompt waits updated to `aegis login:` / `analyst@aegis`.

### 4b. Manual CLI run — `run-qemu.sh`

```
./run-qemu.sh secureos-v4.img 2048
# qemu-system-x86_64 -m 2048 -machine pc -cpu qemu64 \
#   -drive file=IMG,format=raw,if=ide \
#   -netdev user,id=net0 -device e1000,netdev=net0 -nographic
# Quit: Ctrl-A then X. Inside: curl http://127.0.0.1:8000/api/health ; secureos-status
```

### 4c. Manual GUI run — `run-qemu-gui.sh`

```
./run-qemu-gui.sh secureos-v4.img 2048   # SECUREOS_DISPLAY=gtk (default) | sdl | vnc=:1
# same QEMU flags as CLI +: -vga std -display gtk -serial stdio -monitor none
# Guest still boots to CLI; log in, then: secureos-gui [--window|--fullscreen|--stop]
```

### 4d. Graphical verification plan for v5 (not run in this audit)

- Reuse `run-qemu-gui.sh` but with a GPU path for the compositor, e.g.
  `-display gtk,gl=on -device virtio-vga-gl` (virgl) or
  `-display sdl,gl=on`; if Hyprland refuses without acceleration, fall
  back to software rendering in the guest session. Keep `-m 2048` as the
  proven baseline; try `-m 3072` for the Wayland session if host RAM
  allows. Serial stays on stdio for the test transcript.
- **Not verifiable by mounting:** this container has **no /dev/loop**
  (`losetup: cannot find an unused loop device`), so the live image's
  contents could not be inspected by mounting. Image contents in this
  audit are established from the build scripts + guest logs only. The one
  claim that depends on that: "live v4 image contains the v3 helpers
  (`secureos-gui` etc.)" rests on `setup-v4.sh`'s comment
  ("keep v3 helpers (already in /usr/local/bin from v3 image)") + the
  guest-test logs showing `secureos-gui`-era behaviour — it was **not**
  directly confirmed by listing the image.

## 5. Bugs / stale references found in v4

1. **`build-image.sh` §2, setup.sh heredoc (~line 147): unit Description
   says `SecureOS v3 console`** — the "v4" build writes a v3-named unit
   into the rootfs. (The later v4 unit copy overwrites the file, so the
   live image is correct — but a reader of the script is misled, and any
   reordering breaks it.)
2. **`build-image.sh` §3 (~lines 325–326, 331–336): phantom console JS.**
   `cp "$SRC/v3-console.js" … 2>/dev/null || true` — `v3-console.js` does
   **not exist** in `secureos-v4/` (it lives in `secureos-v3/`), so the
   copy silently fails. But the Python injection that follows adds
   `<script src="v2-console.js">` and `<script src="v3-console.js">` to
   `index.html` **unconditionally** — so a clean-built image's console
   requests JS files that were never copied (404s in the console; the
   `v2-console.js` copy only succeeds if `loveos-repo/secureos-v2/`
   still has it). v5 must copy `v5-console.js` from the v5 folder and
   inject only files that exist.
3. **`build-image.sh` §2b/§3 (~lines 207–269, 272–278): v3 helpers silently
   dropped on a clean rebuild.** The copy loop
   `for h in secureos-gui secureos-status secureos-logs secureos-net
   secureos-drivers; do [ -f "$SRC/bin/$h" ] && cp …; done` reads from
   `$SRC/bin` = `secureos-v4/bin`, which contains **only the four lab
   helpers**. `secureos-gui` etc. live in `secureos-v3/bin/` and are
   **never copied**. The live v4 image has them only because it was
   guest-applied onto the v3 image. **A clean `build-image.sh` run from
   the v4 folder produces an image with no `secureos-gui` — the GUI
   cannot start.** v5 must source these helpers explicitly (copy them
   into the v5 folder, renamed — see §3a).
4. **`build-image.sh` comments are stale:** line 126 "see README-v2";
   line 138 "(v3 logging system)"; lines 207–209 "v3 upgrade … (v2 rootfs
   cache)"; line 309 "SRC=.../secureos-build/secureos-v3". All predate v4
   and mislead the next editor.
5. **`build-image.sh` §3 (~lines 309–316): frontend source is the stale
   snapshot.** `REPO_ROOT` resolves to `$SRC/../loveos-repo`, which still
   contains deleted `secureos-v2/` and `secureos-v3/` folders, old test
   scripts and an old root README, and predates the remote-main rename.
   The console frontend baked into the image is therefore **not** remote
   main. v5 should take the frontend from the renamed `AegisOS` repo
   (fresh clone) or from an explicit vendored copy in the v5 folder.
6. **Image-size mismatch (§1b):** default `IMG_SIZE_MB=6144` vs live image
   5120 MiB. Either the live build passed a non-default size or came from
   the guest-apply path; the default was never exercised for v4.
   Also `secureos-v4.img.sha256` is **missing** from the folder although
   `build-image.sh` writes it.
7. **`server.py` stale strings:** line 30 docstring references
   "README-v2.md"; lines 120–121 error text says "SecureOS v2 scans only
   localhost…"; `/api/health` hardcodes `"version": "4.0"`; line 214
   hardcodes `` `secureos-gui` `` in the gui string.
8. **`setup-v4.sh` assumes the guest-apply layout** (`$P/bin/$h`,
   payload dir) and comments "keep v3 helpers (already in /usr/local/bin
   from v3 image)" — it is not a standalone installer and silently
   depends on the v3 image's contents. Same dependency as bug 3, guest side.
9. **`logs/setup-v4.log` is misnamed** — it is a QEMU boot transcript
   (kernel log), not the setup-v4.sh output (which lived in the guest's
   `/tmp/v4-setup.log` and was only tail-printed into the transcript).
10. **Minor:** `build-image.sh` has a redundant `mkdir -p "$WORK"
    "$ROOTFS"` after the REUSE block; `run-qemu-gui.sh` prints "SecureOS
    v4 GUI mode" (cosmetic, rename with the rest).

## 6. Open decisions for the v5 builder (not decided in this audit)

1. Base: **Debian trixie + trixie-backports (recommended)** vs bookworm +
   source builds — see §3d. This changes kernel, debootstrap suite,
   apt sources, and possibly the QEMU `-cpu`/`-machine` baseline.
2. Env vars: rename `SECUREOS_*` → `AEGIS_*` (4 places must agree) or
   keep the old names (cheapest, invisible to users) — see §2b.
3. Display manager: greetd (+tuigreet) vs SDDM vs none (v4 has no DM;
   the Nebula reel goes lid-open → lock screen, which argues for a DM
   that launches straight into the Quickshell lock screen).
4. XFCE fallback: keep `aegis-gui` (XFCE) as a fallback session, or
   Wayland-only? Keeping it costs one more session entry and the v3
   helpers; dropping it removes the only proven GUI.
5. Lock screen implementation: Quickshell lock surface vs `hyprlock`
   (both need the Qt/Wayland stack from decision 1; Quickshell lock has a
   known fractional-scale bug on Qt < 6.10 — another vote for trixie,
   whose Qt is 6.8+, and even then check the exact Qt version).
6. Matugen source: not in Debian — build from source (cargo) or fetch a
   release binary; pin a version.
7. Saral install location: `/opt/aegis/saral` + `/usr/local/bin/saral`
   wrapper, or a `.deb`; plus a console/launcher entry.
