import QtQuick
import qs

// one-of-N chips (enum settings, ANC / transparency style, EQ presets): selected = red fill
Flow {
    id: flow
    property var options: []
    property var current: null
    property var labelFor: o => EarbudsState.optLabel(o)
    property bool dimmed: false          // the style row of the mode that isn't active
    signal picked(string v)

    spacing: 6
    opacity: dimmed ? 0.55 : 1
    Behavior on opacity { NumberAnimation { duration: 150 } }

    Repeater {
        model: flow.options
        delegate: Rectangle {
            id: chip
            required property var modelData
            readonly property bool sel: flow.current === modelData
            width: lbl.implicitWidth + 20
            height: 26
            radius: 13
            color: sel ? Theme.accent : mouse.containsMouse ? Theme.pill : Theme.surface
            Behavior on color { ColorAnimation { duration: 120 } }
            Text {
                id: lbl
                anchors.centerIn: parent
                text: flow.labelFor(chip.modelData)
                color: chip.sel ? Theme.fg : mouse.containsMouse ? Theme.fg : Theme.dim
                font.family: Theme.font
                font.pixelSize: 12
            }
            MouseArea {
                id: mouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (!chip.sel) flow.picked(String(chip.modelData))
            }
        }
    }
}
