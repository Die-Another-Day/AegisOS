// AegisOS v6 — top bar.
//
// One PanelWindow per screen (instantiated by shell.qml via Variants over
// Quickshell.screens). Nebula style: transparent bar, three rounded
// floating islands (left: launcher + workspaces, centre: clock,
// right: network / CPU / memory / battery / system tray).
//
// Launcher button is the TEXT "AegisOS" — no logo image (the user will
// supply the logo later).
//
// Data sources (all local, no network calls from the shell):
//   - Workspaces: Quickshell.Hyprland (Hyprland IPC singleton).
//   - Clock: SystemClock.
//   - Battery: Quickshell.Services.UPower. Shows "No battery (VM)" when no
//     laptop battery is present (e.g. QEMU/VirtualBox).
//   - Network / CPU / memory: polled from /proc and /sys via Quickshell
//     Process + SplitParser (no NetworkManager dependency).
//   - Tray: Quickshell.Services.SystemTray, rendered with IconImage.
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Services.UPower
import Quickshell.Services.SystemTray
import Quickshell.Widgets

PanelWindow {
    id: root

    required property var modelData
    screen: modelData

    signal launcherRequested()
    signal lockRequested()

    anchors {
        top: true
        left: true
        right: true
    }
    implicitHeight: 46
    color: "transparent"
    WlrLayershell.namespace: "aegis:bar"

    Theme {
        id: theme
    }

    // ------------------------------------------------------------------
    // Clock. Qt.formatDate(t, fmt, locale) 3-arg form is broken on
    // Qt 6.8, so the date is formatted by hand from month/day tables.
    // ------------------------------------------------------------------
    readonly property var monthNames: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    readonly property var dayNames: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    SystemClock {
        id: sysClock
        precision: SystemClock.Seconds
    }

    property string timeText: {
        const d = sysClock.date;
        return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    }
    property string dateText: {
        const d = sysClock.date;
        return dayNames[d.getDay()] + ", " + d.getDate() + " " + monthNames[d.getMonth()] + " " + d.getFullYear();
    }

    // ------------------------------------------------------------------
    // CPU + memory, sampled from /proc every 2 s.
    // ------------------------------------------------------------------
    property string cpuText: "CPU --%"
    property string memText: "MEM --%"
    property var prevCpu: null
    property int memTotalKb: 0

    function handleStatLine(line) {
        if (line.startsWith("cpu ")) {
            const parts = line.trim().split(/\s+/).slice(1).map(Number);
            const total = parts.reduce(function (a, b) {
                return a + b;
            }, 0);
            const idle = parts[3] + (parts.length > 4 ? parts[4] : 0);
            if (root.prevCpu) {
                const dt = total - root.prevCpu.total;
                const di = idle - root.prevCpu.idle;
                if (dt > 0)
                    root.cpuText = "CPU " + Math.round(100 * (1 - di / dt)) + "%";
            }
            root.prevCpu = {
                total: total,
                idle: idle
            };
        } else if (line.startsWith("MemTotal:")) {
            root.memTotalKb = parseInt(line.split(/\s+/)[1], 10);
        } else if (line.startsWith("MemAvailable:")) {
            const avail = parseInt(line.split(/\s+/)[1], 10);
            if (root.memTotalKb > 0)
                root.memText = "MEM " + Math.round(100 * (1 - avail / root.memTotalKb)) + "%";
        }
    }

    Process {
        id: statProc
        command: ["sh", "-c", "head -n 1 /proc/stat; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo"]
        stdout: SplitParser {
            onRead: data => root.handleStatLine(data)
        }
    }

    Timer {
        interval: 2000
        repeat: true
        running: true
        onTriggered: {
            if (!statProc.running)
                statProc.running = true;
        }
    }

    // ------------------------------------------------------------------
    // Network: is there a default route in /proc/net/route?
    // ------------------------------------------------------------------
    property string netText: "Offline"

    function handleNetLine(line) {
        if (line.startsWith("online:")) {
            const iface = line.slice("online:".length).trim();
            if (iface.startsWith("wl"))
                root.netText = "Wi-Fi";
            else
                root.netText = "Wired";
        } else if (line.trim() === "offline") {
            root.netText = "Offline";
        }
    }

    Process {
        id: netProc
        command: ["sh", "-c", "awk '$2 == \"00000000\" {print \"online:\" $1; found=1; exit} END {if (!found) print \"offline\"}' /proc/net/route"]
        stdout: SplitParser {
            onRead: data => root.handleNetLine(data)
        }
    }

    Timer {
        interval: 5000
        repeat: true
        running: true
        onTriggered: {
            if (!netProc.running)
                netProc.running = true;
        }
    }

    // ------------------------------------------------------------------
    // Battery via UPower. A VM has no battery: UPower reports no laptop
    // battery device, and the bar shows "No battery (VM)".
    // ------------------------------------------------------------------
    function laptopBattery() {
        const devs = UPower.devices.values;
        for (let i = 0; i < devs.length; i++) {
            if (devs[i].isLaptopBattery)
                return devs[i];
        }
        return null;
    }

    property string batteryText: {
        const dev = root.laptopBattery();
        if (!dev || !dev.isPresent)
            return "No battery (VM)";
        const raw = Number(dev.percentage);
        const pct = Math.round((raw > 1 ? raw / 100 : raw) * 100);
        let suffix = "";
        if (dev.state === UPowerDeviceState.Charging)
            suffix = " +";
        else if (dev.state === UPowerDeviceState.FullyCharged)
            suffix = " full";
        return "BAT " + pct + "%" + suffix;
    }

    Component.onCompleted: {
        statProc.running = true;
        netProc.running = true;
    }

    // ------------------------------------------------------------------
    // Layout: three floating islands.
    // ------------------------------------------------------------------
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 5
        anchors.bottomMargin: 5
        spacing: 8

        // -- Left island: launcher button + workspaces ----------------
        Rectangle {
            Layout.fillHeight: true
            implicitWidth: leftRow.implicitWidth + 20
            radius: theme.islandRadius
            color: theme.panel
            opacity: 0.92
            border.color: theme.border
            border.width: 1

            RowLayout {
                id: leftRow
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 6

                // Launcher button: TEXT "AegisOS", no logo image.
                Rectangle {
                    Layout.fillHeight: true
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    implicitWidth: launcherLabel.implicitWidth + 18
                    radius: 8
                    color: launcherMouse.containsMouse ? theme.panelHover : "transparent"

                    Text {
                        id: launcherLabel
                        anchors.centerIn: parent
                        text: "AegisOS"
                        color: theme.gold
                        font.family: theme.fontFamily
                        font.pixelSize: 14
                        font.bold: true
                    }

                    MouseArea {
                        id: launcherMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: root.launcherRequested()
                    }
                }

                Rectangle {
                    Layout.fillHeight: true
                    Layout.topMargin: 8
                    Layout.bottomMargin: 8
                    width: 1
                    color: theme.border
                }

                // Workspaces 1-9 via Hyprland IPC.
                Repeater {
                    model: 9
                    delegate: Rectangle {
                        required property int index
                        property var ws: Hyprland.workspaces.values.find(function (w) {
                            return w.id === index + 1;
                        })
                        property bool isActive: Hyprland.focusedWorkspace !== null && Hyprland.focusedWorkspace.id === index + 1
                        property bool isOccupied: ws !== undefined && ws !== null

                        Layout.fillHeight: true
                        Layout.topMargin: 5
                        Layout.bottomMargin: 5
                        implicitWidth: 26
                        radius: 7
                        color: isActive ? theme.gold : (wsMouse.containsMouse ? theme.panelHover : "transparent")
                        border.color: isActive ? theme.gold : (isOccupied ? theme.border : "transparent")
                        border.width: 1

                        Text {
                            anchors.centerIn: parent
                            text: index + 1
                            color: isActive ? theme.navy : theme.text
                            font.family: theme.fontFamily
                            font.pixelSize: 13
                            font.bold: isActive
                        }

                        MouseArea {
                            id: wsMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: Hyprland.dispatch("workspace " + (index + 1))
                        }
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
        }

        // -- Centre island: clock -------------------------------------
        Rectangle {
            Layout.fillHeight: true
            implicitWidth: clockRow.implicitWidth + 24
            radius: theme.islandRadius
            color: theme.panel
            opacity: 0.92
            border.color: theme.border
            border.width: 1

            RowLayout {
                id: clockRow
                anchors.centerIn: parent
                spacing: 10

                Text {
                    text: root.timeText
                    color: theme.text
                    font.family: theme.fontFamily
                    font.pixelSize: 16
                    font.bold: true
                }
                Text {
                    text: root.dateText
                    color: theme.muted
                    font.family: theme.fontFamily
                    font.pixelSize: 12
                }
            }
        }

        Item {
            Layout.fillWidth: true
        }

        // -- Right island: net / cpu / mem / battery / tray -----------
        Rectangle {
            Layout.fillHeight: true
            implicitWidth: rightRow.implicitWidth + 20
            radius: theme.islandRadius
            color: theme.panel
            opacity: 0.92
            border.color: theme.border
            border.width: 1

            RowLayout {
                id: rightRow
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 12

                Text {
                    text: root.netText
                    color: root.netText === "Offline" ? theme.ember : theme.text
                    font.family: theme.fontFamily
                    font.pixelSize: 12
                }
                Text {
                    text: root.cpuText
                    color: theme.text
                    font.family: theme.fontFamily
                    font.pixelSize: 12
                }
                Text {
                    text: root.memText
                    color: theme.text
                    font.family: theme.fontFamily
                    font.pixelSize: 12
                }
                Text {
                    text: root.batteryText
                    color: theme.muted
                    font.family: theme.fontFamily
                    font.pixelSize: 12
                }

                // System tray icons (StatusNotifier). Click activates
                // the item; tray menus are not wired (see README).
                Repeater {
                    model: SystemTray.items.values
                    delegate: Item {
                        required property var modelData
                        width: 20
                        height: 20
                        IconImage {
                            anchors.fill: parent
                            source: Quickshell.iconPath(modelData.icon)
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: modelData.activate()
                        }
                    }
                }
            }
        }
    }
}
