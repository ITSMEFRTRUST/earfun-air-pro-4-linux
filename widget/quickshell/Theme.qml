pragma Singleton
import QtQuick
import Quickshell

// Colours, fonts and sizes of the bar module and the popup. Change them here to match your setup.
Singleton {
    // palette
    readonly property color bg: "#0b0b0b"
    readonly property color pill: "#262626"
    readonly property color fg: "#e6e6e6"
    readonly property color dim: "#a8a8a8"
    readonly property color muted: "#5c5c5c"
    readonly property color accent: "#d7263d"
    readonly property color accentHover: "#ff4d5e"
    readonly property color selection: "#3a1418"
    readonly property color warm: "#e3a857"
    readonly property color warn: "#e3d3a4"
    readonly property color surface: "#1a1a1a"
    readonly property color card: "#141414"
    readonly property color pdim: "#8a8a8a"
    readonly property color faint: "#6a6a6a"

    // needs a Nerd Font for the icons
    readonly property string font: "JetBrainsMono Nerd Font"

    // bar geometry
    readonly property int barHeight: 34
    readonly property int barTop: 8
    readonly property int barSide: 10
    readonly property int barRadius: 12
    readonly property int barFont: 14
    readonly property color barBg: Qt.rgba(11 / 255, 11 / 255, 11 / 255, 0.92)
    readonly property color barBorder: "#1f1f1f"

    // popup
    readonly property int popupGap: 8                        // below the bar
    readonly property int popupTop: barTop + barHeight + popupGap
    readonly property color popupBg: Qt.rgba(11 / 255, 11 / 255, 11 / 255, 0.97)
    readonly property color popupBorder: "#262626"
    readonly property int popupRadius: 16
    readonly property int popupFont: 13

    function glyph(cp) { return String.fromCodePoint(cp); }
}
