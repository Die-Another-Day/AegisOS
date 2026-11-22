// AegisOS v6 — app launcher.
//
// A dropdown panel under the top bar (PanelWindow, full width, transparent
// outside the centred card). Type to filter, Enter launches the first
// match, Esc closes. Apps launch via Quickshell Process (see Exec.qml).
//
// No logo images: entries use freedesktop icon names through IconImage,
// with the text label always visible as the fallback.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Widgets

PanelWindow {
    id: root

    property bool open: false
    visible: open

    signal lockRequested()
    signal powerRequested()

    anchors {
        top: true
        left: true
        right: true
    }
    implicitHeight: 480
    color: "transparent"
    WlrLayershell.namespace: "aegis:launcher"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore
    exclusiveZone: 0

    Theme {
        id: theme
    }
    Exec {
        id: exec
    }

    property string query: ""
    property var apps: [
        {
            name: "Google Chrome",
            desc: "Web browser",
            icon: "google-chrome",
            command: ["google-chrome", "--ozone-platform-hint=auto"]
        },
        {
            name: "Firefox",
            desc: "Web browser",
            icon: "firefox-esr",
            command: ["firefox-esr"]
        },
        {
            name: "Terminal",
            desc: "Command line",
            icon: "utilities-terminal",
            command: ["sh", "-c", "foot || alacritty || xterm"]
        },
        {
            name: "Files",
            desc: "File manager",
            icon: "system-file-manager",
            command: ["sh", "-c", "nautilus || thunar || dolphin || pcmanfm"]
        },
        {
            name: "Tools",
            desc: "aegis-tools — install security tools",
            icon: "applications-system",
            command: ["sh", "-c", "foot -e aegis-tools list || alacritty -e aegis-tools list || xterm -e aegis-tools list"]
        },
        {
            name: "Settings",
            desc: "Edit the Hyprland config",
            icon: "preferences-system",
            command: ["sh", "-c", "foot -e ${EDITOR:-nano} ~/.config/hypr/hyprland.conf || xterm -e ${EDITOR:-nano} ~/.config/hypr/hyprland.conf"]
        },
        {
            name: "Lock",
            desc: "Lock the screen",
            icon: "system-lock-screen",
            command: [],
            action: "lock"
        },
        {
            name: "Power Off",
            desc: "Shut down",
            icon: "system-shutdown",
            command: [],
            action: "power"
        }
    ]

    property var filteredApps: apps.filter(function (a) {
        return a.name.toLowerCase().includes(root.query.toLowerCase());
    })

    function activate(app) {
        if (!app)
            return;
        root.close();
        if (app.action === "lock") {
            root.lockRequested();
        } else if (app.action === "power") {
            root.powerRequested();
        } else {
            exec.run(app.command);
        }
    }

    function openOnFocusedScreen() {
        let s = Quickshell.screens[0];
        const mon = Hyprland.focusedMonitor;
        if (mon) {
            const found = Quickshell.screens.find(function (sc) {
                return sc.name === mon.name;
            });
            if (found)
                s = found;
        }
        root.screen = s;
    }

    function toggle() {
        if (!root.open)
            root.openOnFocusedScreen();
        root.open = !root.open;
        if (root.open)
            searchBox.forceActiveFocus();
    }

    function close() {
        root.open = false;
        root.query = "";
    }

    Keys.onEscapePressed: root.close()

    // Clicking the dimmed area outside the card closes the launcher.
    MouseArea {
        anchors.fill: parent
        onClicked: root.close()
    }

    Rectangle {
        id: card
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 8
        width: 600
        height: 440
        radius: theme.radius
        color: theme.panelSolid
        border.color: theme.border
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            TextField {
                id: searchBox
                Layout.fillWidth: true
                implicitHeight: 44
                padding: 10
                placeholderText: "Search apps…"
                color: theme.text
                placeholderTextColor: theme.muted
                font.family: theme.fontFamily
                font.pixelSize: 15

                background: Rectangle {
                    radius: 10
                    color: theme.panel
                    border.color: theme.border
                    border.width: 1
                }

                onTextChanged: root.query = this.text
                onAccepted: root.activate(root.filteredApps[0])
                Keys.onEscapePressed: root.close()
            }

            GridView {
                id: grid
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: root.filteredApps
                cellWidth: 140
                cellHeight: 120
                clip: true

                delegate: Item {
                    required property var modelData
                    width: grid.cellWidth
                    height: grid.cellHeight

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 4
                        radius: 10
                        color: cellMouse.containsMouse ? theme.panelHover : "transparent"
                        border.color: cellMouse.containsMouse ? theme.border : "transparent"
                        border.width: 1

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 4

                            Item {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: 40
                                Layout.preferredHeight: 40
                                // IconImage renders the freedesktop icon;
                                // the name label below is always shown.
                                IconImage {
                                    anchors.fill: parent
                                    source: Quickshell.iconPath(modelData.icon)
                                }
                            }

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.fillWidth: true
                                text: modelData.name
                                color: theme.text
                                font.family: theme.fontFamily
                                font.pixelSize: 13
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.fillWidth: true
                                text: modelData.desc
                                color: theme.muted
                                font.family: theme.fontFamily
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            id: cellMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.activate(modelData)
                        }
                    }
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                visible: root.filteredApps.length === 0
                text: "No apps match \"" + root.query + "\""
                color: theme.muted
                font.family: theme.fontFamily
                font.pixelSize: 13
            }
        }
    }
}
