import QtQuick
import qs

// big off / ANC / ambient segmented control: icon over label,
// a red pill glides to the clicked mode at once and breathes while the headphones haven't
// confirmed it (`busy`).
Rectangle {
    id: seg
    property string current: ""
    property bool busy: false
    signal picked(string m)

    readonly property var items: [
        { m: "off", icon: 0xf02cb, text: "Off" },                   // headphones
        { m: "anc", icon: 0xf0a45, text: "Noise Cancel" },          // ear-hearing-off
        { m: "ambient", icon: 0xf07c5, text: "Ambient" }            // ear-hearing
    ]
    readonly property int idx: items.findIndex(i => i.m === current)
    readonly property int inset: 5
    readonly property real cellW: (width - 2 * inset) / items.length

    implicitHeight: 62
    radius: 16
    color: Theme.surface
    border.width: 1
    border.color: Theme.barBorder

    Rectangle {
        id: hl
        visible: seg.idx >= 0
        x: seg.inset + seg.idx * seg.cellW
        y: seg.inset
        width: seg.cellW
        height: seg.height - 2 * seg.inset
        radius: 12
        color: Theme.accent
        Behavior on x { NumberAnimation { duration: 280; easing.type: Easing.OutBack; easing.overshoot: 0.9 } }
        SequentialAnimation on opacity {
            running: seg.busy
            loops: Animation.Infinite
            alwaysRunToEnd: true
            NumberAnimation { to: 0.45; duration: 500; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1; duration: 500; easing.type: Easing.InOutSine }
        }
    }

    Row {
        x: seg.inset
        y: seg.inset
        Repeater {
            model: seg.items
            delegate: Item {
                id: cell
                required property var modelData
                required property int index
                readonly property bool sel: seg.idx === index
                readonly property bool lit: sel || mouse.containsMouse
                width: seg.cellW
                height: seg.height - 2 * seg.inset
                Rectangle {
                    anchors.fill: parent
                    radius: 12
                    color: Theme.pill
                    opacity: !cell.sel && mouse.containsMouse ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 3
                    scale: mouse.pressed ? 0.94 : 1
                    Behavior on scale { NumberAnimation { duration: 90 } }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Theme.glyph(cell.modelData.icon)
                        color: cell.lit ? Theme.fg : Theme.pdim
                        Behavior on color { ColorAnimation { duration: 150 } }
                        font.family: Theme.font
                        font.pixelSize: 20
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: cell.modelData.text
                        color: cell.lit ? Theme.fg : Theme.dim
                        Behavior on color { ColorAnimation { duration: 150 } }
                        font.family: Theme.font
                        font.pixelSize: 11
                        font.bold: cell.sel
                    }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (!cell.sel) seg.picked(cell.modelData.m)
                }
            }
        }
    }
}
