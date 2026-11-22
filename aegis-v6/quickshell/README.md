# AegisOS v6 — Quickshell desktop shell

Quickshell 0.3.0 (trixie-backports) + Qt 6.8.2 + Hyprland 0.55.2.
Replaces the v5 GTK3/Python layer-shell shell (`aegis-shell.py`, retired).

**No logo images anywhere in this shell.** The launcher button and the lock
screen use the text "AegisOS". The user will supply the logo later; when it
lands, it replaces the text in `Bar.qml` (launcher button) and
`LockScreen.qml` (wordmark) only. The rejected files under
`../logo-options/` are not copied or referenced.

## Files

| File | What it is |
|---|---|
| `shell.qml` | Entry point. `ShellRoot`: bars, desktop background windows, lock, launcher, menu, IPC. |
| `Bar.qml` | Top bar (one `PanelWindow` per screen): launcher button, Hyprland workspaces 1–9, clock + date, network, CPU/mem, battery, system tray. |
| `LockScreen.qml` | Lock surface content: starfield + wallpaper, scalloped clock disc, music card (MPRIS), password field + Unlock button. |
| `LockContext.qml` | Shared PAM auth state (`Scope` + `PamContext`), one instance for all screens. |
| `Launcher.qml` | App launcher dropdown (search + grid). Launches via Quickshell `Process`. |
| `DesktopMenu.qml` | Right-click desktop menu (`PanelWindow` positioned at the click). |
| `Exec.qml` | One-shot `Process` helper used by Launcher / DesktopMenu / shell. |
| `Theme.qml` | Shared Nebula colours (dark navy, `#ffd682` sunset gold accent). |
| `pam/password.conf` | Password-only PAM stack used by `PamContext`. |

## How to run it

```sh
qs -c /etc/aegis/quickshell        # installed location (Phase 2 build)
# or, from this directory while developing:
qs -c .
```

`aegis-gui` should autostart it after Hyprland comes up (same place the v5
shell was started). The process name is `qs`.

Hyprland + runtime requirements (Phase 2 build must install):

- `quickshell` 0.3.0 (trixie-backports), Qt 6.8.2
- QML modules: `qml6-module-qtquick`, `qml6-module-qtquick-layouts`,
  `qml6-module-qtquick-controls` (TextField/Button in the lock screen and
  launcher use QtQuick.Controls)
- `upower` (battery), `google-chrome`, `firefox-esr`, a terminal
  (`foot` preferred, `alacritty`/`xterm` fall back), a file manager
  (`nautilus` preferred, `thunar`/`dolphin`/`pcmanfm` fall back)
- `swww` for the Change Wallpaper action (falls back to opening the
  wallpaper folder if `swww` is absent)

## Lock screen and PAM (real PAM, no bypass)

Authentication is `Quickshell.Services.Pam` — the exact API from the
official Quickshell 0.3 lockscreen example:

```qml
import Quickshell.Services.Pam
PamContext {
    user: "analyst"
    configDirectory: "pam"
    config: "password.conf"
    onPamMessage: { if (this.responseRequired) this.respond(root.currentText); }
    onCompleted: result => { /* PamResult.Success -> unlocked() */ }
}
```

- `LockContext.qml` is a near-verbatim adaptation of the upstream example's
  `LockContext.qml`; `pam/password.conf` (`auth required pam_unix.so`) is
  the upstream example's `pam/password.conf`. The custom config exists so
  the system `/etc/pam.d/login` stack is never disturbed; `pam_unix`
  verifies the typed password against the system account database for
  user `analyst`.
- The typed password lives only in `LockContext.currentText` while typing
  and is cleared on every `onCompleted`. **No hardcoded credentials, no
  test-mode bypass, no sudo-based check.**
- Enforcement is compositor-level: `shell.qml` holds a `WlSessionLock`
  (`ext-session-lock-v1`, `locked: root.locked`) with one
  `WlSessionLockSurface` per screen. The only code path that clears
  `locked` is `LockContext.onUnlocked`, which only fires on
  `PamResult.Success`.
- IPC: there is deliberately **no** `qs -c aegis ipc call aegis unlock`. Locking is
  exposed (`lock`, `toggleLauncher`, `showDesktopMenu`); unlocking requires
  the password.

Sources:

- Official Quickshell lockscreen example (current upstream):
  <https://git.outfoxxed.me/quickshell/quickshell-examples/commit/a64b477deaba210102bae11bcf054d973803d3f3>
  (`LockContext.qml`, `LockSurface.qml`, `shell.qml`, `pam/password.conf`)
- Quickshell docs: <https://quickshell.org/docs/v0.3.0/> — type definitions
  for `Quickshell.Services.Pam` (`PamContext`, `PamResult`),
  `Quickshell.Wayland` (`WlSessionLock`, `WlSessionLockSurface`,
  `PanelWindow`, `WlrLayershell`), `Quickshell.Hyprland` (`Hyprland`,
  `HyprlandWorkspace`), `Quickshell.Io` (`Process`, `SplitParser`,
  `IpcHandler`), `Quickshell.Services.UPower` (`UPower`,
  `UPowerDeviceState`), `Quickshell.Services.SystemTray` (`SystemTray`),
  `Quickshell.Services.Mpris` (`Mpris`).

**Build gate (must be proven on the real image, not assumed):** unlock as
user `analyst` with the system password in QEMU. Quickshell's PAM runs
through a privileged helper/subprocess; if unlock fails with a permission
error on the image, check how the Debian `quickshell` package installs its
PAM helper before changing any QML. hyprlock (backports) remains the
fallback lock if the Quickshell lock proves unstable (PLAN.md §3).

## Desktop right-click menu — how Hyprland lets it receive the click

Hyprland has no built-in desktop menu, so the shell provides its own
background window: `shell.qml` creates one full-screen `PanelWindow` per
screen at `WlrLayershell.layer: WlrLayer.Background`, with
`exclusionMode: ExclusionMode.Ignore`, `exclusiveZone: 0` and a transparent
colour. The wallpaper (swww/hyprpaper) shows through; the window only
exists to catch mouse clicks. Its `MouseArea` opens `DesktopMenu` at the
click position (right button) or closes the menu (left button).

Two things the Phase 2 Hyprland config must get right:

1. **Nothing else may cover the background layer.** swww also draws on the
   background layer; layer-shell surfaces on the same layer stack in
   creation order, so if swww starts after `qs` it can sit above the
   desktop window and swallow clicks. Start `qs` after swww in
   `exec-once`, and verify right-click works in the QEMU gate. If it does
   not, the fallback is a Hyprland mouse bind that calls the shell's IPC
   (already implemented — see below); do not add a second menu.
2. **Idle lock + keybinds** (add to `hyprland.conf` / `hypridle.conf`):
   ```ini
   exec-once = qs -c /etc/aegis/quickshell
   bind = SUPER, L, exec, qs -c aegis ipc call aegis lock
   bind = SUPER, D, exec, qs -c aegis ipc call aegis toggleLauncher
   bind = , mouse:273, exec, qs -c aegis ipc call aegis showDesktopMenu   # right-click fallback
   ```
   and in `hypridle.conf`: `lock_cmd = qs -c aegis ipc call aegis lock`
   (600 s, same timing as v5). The `mouse:273` bind is a fallback only and
   still needs proving in the QEMU gate — Hyprland mouse binds fire on
   press and may conflict with app bindings, so prefer the background
   window path when it works.

## Qt 6.8 quirks worked around

- `transient` is a reserved word in QML — never used as an identifier.
- `Qt.formatDate(t, fmt, locale)` 3-arg form fails on Qt 6.8 — the bar and
  lock screen format dates by hand from month/day-name tables
  (`Bar.qml`, `LockScreen.qml`).
- Quickshell's process name is `qs` (`qs -c <dir>`, `qs -c aegis ipc call …`).

## Validation done here (2026-11-22, this host = Ubuntu 24.04, Qt 6.4.2)

No Quickshell exists on this host, so full runtime validation was **not**
possible. What was done:

- `qmllint` 6.4.2 (installed `qt6-declarative-dev-tools` +
  `qml6-module-qtquick{,-layouts,-controls,-templates}` for this check):
  **0 errors in all 8 QML files** — no parse errors, no syntax errors.
  Remaining output is warnings only, all of two expected classes:
  (a) unknown `Quickshell.*` types/modules (Quickshell is not installed
  here, so `PanelWindow`, `PamContext`, `Hyprland`, `UPower`,
  `SystemTray`, `Mpris`, `WlrLayershell`, `Process`, `SplitParser`,
  `IpcHandler`, `IconImage` etc. cannot resolve); (b) qmllint 6.4.2
  qmltypes gaps, proven to be false positives with a minimal test file
  using only stock Qt (`Qt.AlignHCenter`, `Qt.LeftButton`, `Qt.NoFocus`,
  `Qt.ImhSensitiveData`, `Layout.alignment`, `focusPolicy`,
  `acceptedButtons` all warn identically on plain valid Qt code).
- `grep` checks: no reference to `logo-options` or any `.png` logo, no
  hardcoded password, no `sudo` password check, no test-mode bypass.
- The PAM code path is copied from the official upstream lockscreen
  example (linked above), not invented.

## What is NOT verified (needs the Phase 2 QEMU gate on the real image)

- Nothing here has ever run under `qs`: bar rendering, workspace
  switching, tray icons, UPower battery text, CPU/mem/net polling,
  launcher, desktop menu, and the lock screen are all **unproven at
  runtime**. The QEMU gate in PLAN.md §8 (item 2) is the first real test.
- API details taken from docs/community configs rather than the installed
  0.3.0 qmltypes, in decreasing order of confidence:
  - **High** (official example / tutorial): `PamContext` + `PamResult`,
    `WlSessionLock` + `WlSessionLockSurface`, `PanelWindow` anchors,
    `Hyprland.workspaces` / `focusedWorkspace` / `dispatch("workspace N")`,
    `Process` + `SplitParser`, `SystemClock`, `Variants` over
    `Quickshell.screens`.
  - **Medium** (used across many 0.3 dotfiles, not in the official
    example): `UPower.devices.values` / `displayDevice` /
    `UPowerDeviceState.Charging` / `isLaptopBattery` / `isPresent`;
    `SystemTray.items.values` + `item.icon` + `Quickshell.iconPath()` +
    `item.activate()`; `Mpris.players.values` + `trackTitle` /
    `trackArtist` / `isPlaying`; `WlrLayershell.layer` /
    `WlrLayershell.namespace` / `WlrLayershell.keyboardFocus` +
    `WlrLayer` / `WlrKeyboardFocus` enums; `ExclusionMode.Ignore`;
    `IpcHandler` function exposure via `qs -c aegis ipc call` (`-c aegis` is required).
  - **Known gaps / deliberate simplifications:**
    - Tray **menus** are not wired — left-click calls `item.activate()`
      only. Showing a tray item's DBusMenu needs `Quickshell.DBusMenu`
      (`QMenuOpener` + `PopupWindow`); add it in Phase 2 if tray menus
      matter.
    - The launcher opens on the focused monitor (mapped via
      `Hyprland.focusedMonitor.name`); multi-monitor behaviour is
      otherwise untested.
    - Terminal / file-manager commands are fallback chains
      (`foot || alacritty || xterm`, `nautilus || thunar || …`) — repoint
      at the exact apps the image ships.
    - "Settings" in the launcher opens the Hyprland config in a terminal
      editor (there is no settings GUI in the image yet); "Tools" opens a
      terminal running `aegis-tools list`. Repoint both in Phase 2 if a
      real settings app lands.
    - "Change Wallpaper" needs swww (Phase 2); without it, it opens the
      wallpaper folder.
    - The lock screen music card reads only the **first** MPRIS player.
- `qml6-module-qtquick-controls` must be in the image or the lock screen
  and launcher fail to load (they use `TextField`/`Button`).
