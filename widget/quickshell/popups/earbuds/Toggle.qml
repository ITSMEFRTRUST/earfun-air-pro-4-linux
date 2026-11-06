import QtQuick
import qs

// GTK-style switch: 38×20 pill, red when on, light knob
Rectangle {
    id: sw
    property bool on: false
    signal toggled(bool v)

    implicitWidth: 38
    implicitHeight: 20
    radius: 10
    color: on ? Theme.accent : mouse.containsMouse ? Theme.faint : Theme.pill
    Behavior on color { ColorAnimation { duration: 120 } }

    Rectangle {
        width: 14; height: 14; radius: 7
        anchors.verticalCenter: parent.verticalCenter
        x: sw.on ? sw.width - width - 3 : 3
        color: Theme.fg
        Behavior on x { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        anchors.margins: -4
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: sw.toggled(!sw.on)
    }
}
