// AegisOS v6 — shared Nebula theme tokens.
// Plain QtObject component (instantiated per file as `Theme { id: theme }`).
// No images: the launcher button and lock screen use the text "AegisOS"
// until the user supplies a logo.
import QtQuick

QtObject {
    readonly property color navy: "#0b1026"       // deep navy background
    readonly property color navyDeep: "#070b1d"   // darker navy
    readonly property color panel: "#141b3d"      // floating island fill
    readonly property color panelSolid: "#171f45"
    readonly property color panelHover: "#1e2760"
    readonly property color border: "#2a3468"
    readonly property color text: "#e8eaf6"
    readonly property color muted: "#9aa3c7"
    readonly property color gold: "#ffd682"       // sunset accent
    readonly property color orange: "#ff9a5c"
    readonly property color ember: "#ff5e62"
    readonly property color danger: "#ff5e62"
    readonly property int radius: 14
    readonly property int islandRadius: 12
    readonly property string fontFamily: "Sans"
}
