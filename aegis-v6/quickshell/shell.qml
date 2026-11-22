// AegisOS v6 — Quickshell shell entry point.
//
// Run with:  qs -c <this directory>
// (from the build: qs -c /etc/aegis/quickshell, or ~/.config/quickshell/aegis)
//
// What this wires together:
//   - Bar.qml            — one top bar per screen (Variants over Quickshell.screens)
//   - LockContext.qml    — shared PAM auth state (Quickshell.Services.Pam)
//   - LockScreen.qml     — lock surface content, one per screen via WlSessionLock
//   - Launcher.qml       — app launcher dropdown (toggled from the bar)
//   - DesktopMenu.qml    — right-click desktop menu
//   - Desktop background — one full-screen Background-layer PanelWindow per
//     screen whose MouseArea catches right-clicks and opens DesktopMenu.
//
// Locking: `root.lock()` sets `locked`, which engages the WlSessionLock
// (ext-session-lock-v1). The compositor then shows the lock surfaces and
// blocks input to everything else. Unlocking happens ONLY through PAM:
// LockContext emits `unlocked` on PamResult.Success, which clears `locked`.
// There is no other unlock path in this file.
//
// IPC (for Hyprland binds and hypridle, see README.md):
//   qs -c aegis ipc call aegis lock
//   qs -c aegis ipc call aegis toggleLauncher
//   qs -c aegis ipc call aegis showDesktopMenu
// (`-c aegis` is required: without it the client looks for a "default"
// config and never reaches this shell.)
import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Io

ShellRoot {
    id: root

    property bool locked: false

    function lock() {
        launcher.close();
        desktopMenu.hide();
        root.locked = true;
    }

    function unlock() {
        root.locked = false;
    }

    // --- Shared PAM authentication state (one instance, all screens) ---
    LockContext {
        id: lockContext
        onUnlocked: root.unlock()
    }

    // --- IPC: Hyprland binds / hypridle reach the shell through these ---
    IpcHandler {
        target: "aegis"

        function lock(): void {
            root.lock();
        }

        function toggleLauncher(): void {
            launcher.toggle();
        }

        function showDesktopMenu(): void {
            // Fallback path when the desktop background window cannot
            // receive the click (e.g. swww's wallpaper surface is above
            // it). Opens the menu near the top-left of the first screen.
            desktopMenu.showAt(200, 200, Quickshell.screens[0]);
        }
    }

    // --- Session lock: engages the compositor-level lock ---------------
    // WlSessionLock auto-creates one WlSessionLockSurface per screen.
    // The surface content is LockScreen.qml, fed by the shared LockContext.
    WlSessionLock {
        id: sessionLock
        locked: root.locked

        WlSessionLockSurface {
            LockScreen {
                anchors.fill: parent
                context: lockContext
            }
        }
    }

    // --- Top bar, one per screen ---------------------------------------
    Variants {
        model: Quickshell.screens
        Bar {
            // NOTE (v6, 2026-11-22): do NOT redeclare `required property
            // var modelData` here — Bar.qml already declares it, and a
            // second declaration in this instantiation shadows it: the
            // Variants sets this copy, Bar.qml's own modelData (used by
            // `screen: modelData`) stays unset, and the delegate fails
            // with "Required property modelData was not initialized"
            // (proven by the qslog) — so no bar ever appears. The
            // inline PanelWindow below CAN declare it here because it
            // has no separate file; the property is the same one.
            screen: modelData
            // NOTE (v6, 2026-11-22): the bar is intentionally ALWAYS
            // visible, even while the session is locked. It used to be
            // `visible: !root.locked`, so its first frame was only
            // produced AFTER the PAM unlock — and under software
            // rendering (llvmpipe, 1 vCPU) that first Qt Quick frame
            // takes 2-4 minutes to appear, so the desktop sat bar-less
            // after every unlock (diag9: absent at t0/t2, first seen
            // at t4; diag10: 4 vCPUs cut it to under 30 s). With the
            // bar always visible its first frame is rendered at shell
            // startup, before the unlock, so it is already on screen
            // the instant the lock opens. While locked the session-lock
            // surface sits above it and the compositor blocks input to
            // it, so it is display-only on the lock screen (same as
            // the GNOME/macOS lock-screen top bar).
            onLauncherRequested: launcher.toggle()
            onLockRequested: root.lock()
        }
    }

    // --- Desktop background window, one per screen ---------------------
    // Background layer, reserves no space, transparent: the wallpaper
    // (swww / hyprpaper) shows through and this window only exists to
    // catch mouse clicks on the desktop. Right-click opens the menu,
    // left-click anywhere closes it.
    Variants {
        model: Quickshell.screens
        PanelWindow {
            required property var modelData
            screen: modelData

            anchors {
                top: true
                bottom: true
                left: true
                right: true
            }
            exclusionMode: ExclusionMode.Ignore
            exclusiveZone: 0
            color: "transparent"
            WlrLayershell.layer: WlrLayer.Background
            WlrLayershell.namespace: "aegis:desktop"
            // NOTE (v6, 2026-11-22): always visible, same reason as
            // the bar above — this window used to be hidden while
            // locked, so its first frame (and therefore right-click
            // handling) only existed after the unlock. It is fully
            // transparent, and while locked the session-lock surface
            // blocks input to it, so leaving it visible is safe.

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: mouse => {
                    if (mouse.button === Qt.RightButton) {
                        desktopMenu.showAt(mouse.x, mouse.y, modelData);
                    } else {
                        desktopMenu.hide();
                    }
                }
            }
        }
    }

    // --- Launcher + desktop menu (single instances) --------------------
    Launcher {
        id: launcher
        onLockRequested: root.lock()
        onPowerRequested: powerOffProc.run(["systemctl", "poweroff"])
    }

    DesktopMenu {
        id: desktopMenu
        onLockRequested: root.lock()
    }

    // One-shot process used for the launcher's Power Off action.
    Exec {
        id: powerOffProc
    }
}
