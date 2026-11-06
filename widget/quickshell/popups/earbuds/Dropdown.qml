import QtQuick
import QtQuick.Controls
import qs

// enum with many options (gestures, codec): a pill with the current value + chevron → menu
Rectangle {
    id: dd
    property var options: []
    property var current: null
    signal picked(string v)

    implicitHeight: 26
    radius: 8
    color: mouse.containsMouse || menu.visible ? Theme.pill : Theme.surface
    Behavior on color { ColorAnimation { duration: 120 } }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.right: chev.left
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        text: dd.current === null || dd.current === undefined ? "—" : EarbudsState.optLabel(dd.current)
        elide: Text.ElideRight
        color: Theme.fg
        font.family: Theme.font
        font.pixelSize: 12
    }
    Text {
        id: chev
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: Theme.glyph(0xf0140)
        color: Theme.pdim
        font.family: Theme.font
        font.pixelSize: 12
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: menu.visible ? menu.close() : menu.popup(dd, 0, dd.height + 4)
    }

    Menu {
        id: menu
        width: Math.max(dd.width, 150)
        padding: 4
        background: Rectangle {
            color: Theme.surface
            border.color: Theme.pill
            radius: 8
        }
        Instantiator {
            model: dd.options
            delegate: MenuItem {
                id: mi
                required property var modelData
                readonly property bool sel: dd.current === modelData
                height: 26
                contentItem: Text {
                    text: EarbudsState.optLabel(mi.modelData)
                    color: mi.sel ? Theme.accentHover : Theme.fg
                    font.family: Theme.font
                    font.pixelSize: 12
                    font.bold: mi.sel
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    radius: 5
                    color: mi.highlighted ? Theme.selection : "transparent"
                }
                onTriggered: if (!mi.sel) dd.picked(String(mi.modelData))
            }
            onObjectAdded: (i, o) => menu.insertItem(i, o)
            onObjectRemoved: (i, o) => menu.removeItem(o)
        }
    }
}
