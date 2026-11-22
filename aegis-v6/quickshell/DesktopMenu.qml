// AegisOS v6 — right-click desktop menu.
//
// A small PanelWindow anchored top-left whose margins are set to the click
// position by showAt(), so the menu opens exactly where the user
// right-clicked. It is shown by the desktop background window in shell.qml
// (a full-screen Background-layer PanelWindow whose MouseArea catches
// right-clicks) and, as a fallback, by Hyprland key/mouse binds calling
// `qs -c aegis ipc call aegis showDesktopMenu` (see README.md).
//
// Actions launch via Quickshell Process (see Exec.qml); Lock is a signal
// handled by shell.qml, which owns the WlSessionLock state.
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    property bool open: false
    property int anchorX: 100
    property int anchorY: 100
    property var menuScreen: null

    visible: open
    screen: menuScreen !== null ? menuScreen : Quickshell.screens[0]

    signal lockRequested()

    anchors {
        top: true
        left: true
    }
    margins {
        top: anchorY
        left: anchorX
    }
    implicitWidth: 250
    implicitHeight: menuColumn.implicitHeight + 16
    color: "transparent"
    WlrLayershell.namespace: "aegis:desktopmenu"
    exclusionMode: ExclusionMode.Ignore
    exclusiveZone: 0

    Theme {
        id: theme
    }
    Exec {
        id: exec
    }

    function showAt(x, y, scr) {
        const s = scr ? scr : Quickshell.screens[0];
        root.menuScreen = s;
        // Keep the whole menu on-screen.
        root.anchorX = Math.max(8, Math.min(x, s.width - 270));
        root.anchorY = Math.max(8, Math.min(y, s.height - 330));
        root.open = true;
    }

    function hide() {
        root.open = false;
    }

    function doAction(action) {
        root.hide();
        if (action === "lock") {
            root.lockRequested();
        } else if (action === "poweroff") {
            exec.run(["systemctl", "poweroff"]);
        } else if (action === "reboot") {
            exec.run(["systemctl", "reboot"]);
        } else if (action === "terminal") {
            exec.runShell("foot || alacritty || xterm");
        } else if (action === "files") {
            exec.runShell("nautilus || thunar || dolphin || pcmanfm");
        } else if (action === "chrome") {
            exec.run(["google-chrome", "--ozone-platform-hint=auto"]);
        } else if (action === "tools") {
            exec.runShell("foot -e aegis-tools list || alacritty -e aegis-tools list || xterm -e aegis-tools list");
        } else if (action === "wallpaper") {
            // Pick a random wallpaper from the installed set and hand it
            // to swww (Phase 2 installs swww). Without swww, open the
            // wallpaper folder instead so the user can pick by hand.
            exec.runShell("p=$(ls /usr/share/aegis/wallpapers/*.png /usr/share/aegis/wallpapers/*.jpg 2>/dev/null | shuf -n 1); if [ -n \"$p\" ] && command -v sww >/dev/null; then sww img \"$p\" --transition-type random; else xdg-open /usr/share/aegis/wallpapers; fi");
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: theme.radius
        color: theme.panelSolid
        border.color: theme.border
        border.width: 1

        ColumnLayout {
            id: menuColumn
            anchors.fill: parent
            anchors.margins: 8
            spacing: 2

            Repeater {
                model: [
                    { label: "Open Terminal", action: "terminal" },
                    { label: "Files", action: "files" },
                    { label: "Google Chrome", action: "chrome" },
                    { label: "Tools", action: "tools" },
                    { label: "Change Wallpaper", action: "wallpaper" },
                    { label: "Lock", action: "lock" },
                    { label: "Power Off", action: "poweroff" },
                    { label: "Reboot", action: "reboot" }
                ]
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 34
                    radius: 8
                    color: itemMouse.containsMouse ? theme.panelHover : "transparent"

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        text: modelData.label
                        color: modelData.action === "poweroff" || modelData.action === "reboot" ? theme.ember : theme.text
                        font.family: theme.fontFamily
                        font.pixelSize: 13
                    }

                    MouseArea {
                        id: itemMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: root.doAction(modelData.action)
                    }
                }
            }
        }
    }
}
