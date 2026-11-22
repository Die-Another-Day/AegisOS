// AegisOS v6 — lock screen (content of each WlSessionLockSurface).
//
// Nebula style: starfield wallpaper background (procedural starfield
// underneath, the installed wallpaper on top), huge clock inside a
// scalloped sunset disc, a music card, and a password field + Unlock
// button. The "AegisOS" wordmark is TEXT — no logo image (the user will
// supply the logo later).
//
// Authentication is real PAM via LockContext (Quickshell.Services.Pam).
// There is no bypass: the surface only dismisses when LockContext emits
// `unlocked`, which only happens on PamResult.Success. See README.md.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import Quickshell.Services.Mpris

Rectangle {
    id: root

    required property LockContext context

    color: theme.navy

    Theme {
        id: theme
    }

    // Clock, updated every second (same pattern as the official
    // Quickshell lockscreen example: Timer + new Date()).
    // Qt.formatDate(t, fmt, locale) 3-arg form is broken on Qt 6.8,
    // so the date is formatted by hand from month/day tables.
    readonly property var monthNames: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    readonly property var dayNames: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    property var now: new Date()

    Timer {
        interval: 1000
        repeat: true
        running: true
        onTriggered: root.now = new Date()
    }

    property string timeText: String(root.now.getHours()).padStart(2, "0") + ":" + String(root.now.getMinutes()).padStart(2, "0")
    property string dateText: dayNames[root.now.getDay()] + ", " + root.now.getDate() + " " + monthNames[root.now.getMonth()] + " " + root.now.getFullYear()

    // Now-playing track from the first MPRIS player, if any.
    property var player: Mpris.players.values.length > 0 ? Mpris.players.values[0] : null
    property string trackText: {
        if (!root.player || !root.player.trackTitle)
            return "No track playing";
        const artist = root.player.trackArtist ? " — " + root.player.trackArtist : "";
        return root.player.trackTitle + artist;
    }

    // ------------------------------------------------------------------
    // Background: procedural starfield, then the installed wallpaper.
    // If the wallpaper file is missing the starfield still shows.
    // ------------------------------------------------------------------
    Repeater {
        model: 110
        delegate: Rectangle {
            required property int index
            width: 1 + (index % 3)
            height: width
            radius: width / 2
            color: "white"
            opacity: 0.25 + ((index * 37) % 70) / 100
            x: ((index * 7919) % 1000) / 1000 * root.width
            y: ((index * 104729) % 1000) / 1000 * root.height
        }
    }

    // Soft nebula wisps (translucent discs; no QtGraphicalEffects on Qt 6).
    Rectangle {
        x: root.width * 0.08
        y: root.height * 0.62
        width: 420
        height: 420
        radius: 210
        color: theme.orange
        opacity: 0.10
    }
    Rectangle {
        x: root.width * 0.68
        y: root.height * 0.08
        width: 380
        height: 380
        radius: 190
        color: theme.ember
        opacity: 0.10
    }
    Rectangle {
        x: root.width * 0.55
        y: root.height * 0.70
        width: 300
        height: 300
        radius: 150
        color: "#7c5cff"
        opacity: 0.08
    }

    Image {
        anchors.fill: parent
        source: "/usr/share/aegis/wallpapers/aegis-v6.png"
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        opacity: status === Image.Ready ? 0.92 : 0
    }

    // Dim the wallpaper a touch so the disc and text stay readable.
    Rectangle {
        anchors.fill: parent
        color: "#05081a"
        opacity: 0.25
    }

    // ------------------------------------------------------------------
    // Centred column: wordmark, scalloped clock disc, music card,
    // password field + Unlock button.
    // ------------------------------------------------------------------
    ColumnLayout {
        anchors.centerIn: parent
        spacing: 22

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "AegisOS"
            color: theme.gold
            font.family: theme.fontFamily
            font.pixelSize: 34
            font.bold: true
            font.letterSpacing: 4
        }

        // Scalloped disc: a ring of small gold circles around a navy disc.
        Item {
            Layout.alignment: Qt.AlignHCenter
            width: 350
            height: 350

            Repeater {
                model: 28
                delegate: Rectangle {
                    required property int index
                    width: 26
                    height: 26
                    radius: 13
                    color: theme.gold
                    opacity: 0.85
                    x: 175 + 162 * Math.cos(index / 28 * 2 * Math.PI) - 13
                    y: 175 + 162 * Math.sin(index / 28 * 2 * Math.PI) - 13
                }
            }

            Rectangle {
                anchors.centerIn: parent
                width: 322
                height: 322
                radius: 161
                color: "#101736"
                opacity: 0.92
                border.color: theme.gold
                border.width: 2

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 6

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: root.timeText
                        color: theme.text
                        font.family: theme.fontFamily
                        font.pixelSize: 72
                        font.bold: true
                        renderType: Text.NativeRendering
                    }
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: root.dateText
                        color: theme.muted
                        font.family: theme.fontFamily
                        font.pixelSize: 16
                    }
                }
            }
        }

        // Music card.
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: 340
            implicitHeight: musicCol.implicitHeight + 24
            radius: theme.radius
            color: theme.panel
            opacity: 0.92
            border.color: theme.border
            border.width: 1

            ColumnLayout {
                id: musicCol
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                anchors.topMargin: 12
                anchors.bottomMargin: 12
                spacing: 2

                Text {
                    text: "Now playing"
                    color: theme.gold
                    font.family: theme.fontFamily
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 2
                }
                Text {
                    text: root.trackText
                    color: theme.text
                    font.family: theme.fontFamily
                    font.pixelSize: 14
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

        // Password field + Unlock button.
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 10

            TextField {
                id: passwordBox
                implicitWidth: 300
                implicitHeight: 44
                padding: 10
                focus: true
                enabled: !root.context.unlockInProgress
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhSensitiveData
                placeholderText: "Password"
                color: theme.text
                placeholderTextColor: theme.muted
                font.family: theme.fontFamily
                font.pixelSize: 15

                background: Rectangle {
                    radius: 10
                    color: theme.panel
                    opacity: 0.95
                    border.color: root.context.showFailure ? theme.danger : theme.border
                    border.width: 1
                }

                onTextChanged: root.context.currentText = this.text
                onAccepted: root.context.tryUnlock()

                // Keep every monitor's box in sync with the shared context.
                Connections {
                    target: root.context
                    function onCurrentTextChanged() {
                        passwordBox.text = root.context.currentText;
                    }
                }

                Component.onCompleted: passwordBox.forceActiveFocus()
            }

            Button {
                id: unlockButton
                text: root.context.unlockInProgress ? "Unlocking…" : "Unlock"
                implicitHeight: 44
                padding: 10
                focusPolicy: Qt.NoFocus
                enabled: !root.context.unlockInProgress && root.context.currentText !== ""
                font.family: theme.fontFamily
                font.pixelSize: 15
                onClicked: root.context.tryUnlock()

                background: Rectangle {
                    radius: 10
                    color: theme.gold
                    opacity: unlockButton.enabled ? 1 : 0.5
                }
                contentItem: Text {
                    text: unlockButton.text
                    color: theme.navy
                    font.family: theme.fontFamily
                    font.pixelSize: 15
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            visible: root.context.showFailure
            text: "Incorrect password — try again"
            color: theme.danger
            font.family: theme.fontFamily
            font.pixelSize: 13
        }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 18
        text: "analyst  •  AegisOS 6.0"
        color: theme.muted
        font.family: theme.fontFamily
        font.pixelSize: 12
    }
}
