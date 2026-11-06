import QtQuick
import qs

// collapsible section: icon + bold title + dim note + chevron on a
// hover-lit header row; the body slides open / shut (height + fade).
Column {
    id: sec
    property string title
    property string note
    property int icon: 0
    property bool expanded: true
    signal toggle()
    default property alias content: body.data
    readonly property real innerWidth: width - 16

    spacing: 0

    Rectangle {
        width: parent.width
        height: 38
        radius: 10
        color: hm.containsMouse ? Theme.surface : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
        Text {
            id: ic
            visible: sec.icon !== 0
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            text: sec.icon ? Theme.glyph(sec.icon) : ""
            color: sec.expanded ? Theme.accent : Theme.pdim
            Behavior on color { ColorAnimation { duration: 150 } }
            font.family: Theme.font
            font.pixelSize: 16
        }
        Text {
            x: sec.icon ? 34 : 8
            anchors.verticalCenter: parent.verticalCenter
            text: sec.title
            color: hm.containsMouse || sec.expanded ? Theme.fg : Theme.dim
            font.family: Theme.font
            font.pixelSize: Theme.popupFont
            font.bold: true
        }
        Rectangle {         // note as a small pill
            visible: sec.note !== ""
            anchors.right: chev.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: nt.implicitWidth + 14
            height: 20
            radius: 10
            color: Theme.pill
            Text {
                id: nt
                anchors.centerIn: parent
                text: sec.note
                color: Theme.dim
                font.family: Theme.font
                font.pixelSize: 10
            }
        }
        Text {
            id: chev
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: Theme.glyph(0xf0140)      // chevron-down
            rotation: sec.expanded ? 0 : -90
            Behavior on rotation { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            color: hm.containsMouse ? Theme.fg : Theme.faint
            font.family: Theme.font
            font.pixelSize: 14
        }
        MouseArea {
            id: hm
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: sec.toggle()
        }
    }
    Item {
        id: clipper
        width: parent.width
        height: sec.expanded ? body.implicitHeight + 14 : 0
        Behavior on height { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        clip: true
        visible: height > 0
        opacity: sec.expanded ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Column {
            id: body
            x: 8
            y: 6
            width: parent.width - 16
            spacing: 8
        }
    }
}
