import QtQuick
import Quickshell
import Quickshell.Wayland
import qs
import "modules"
import "popups/earbuds"

// The standalone pill: only the earbuds module, floating over the top-right corner.
// Hidden while the earfun daemon isn't running.
PanelWindow {
    id: win
    required property var modelData
    screen: modelData

    visible: EarbudsState.daemon
    anchors { top: true; right: true }
    margins { top: Theme.barTop; right: Theme.barSide }
    implicitWidth: Math.max(1, module.implicitWidth)
    implicitHeight: Theme.barHeight
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "earfun-bar"

    Rectangle {
        anchors.fill: parent
        color: Theme.barBg
        radius: Theme.barRadius
        border.width: 1
        border.color: Theme.barBorder
        Earbuds {
            id: module
            anchors.fill: parent
            onClicked: (button, x) => Popups.toggle(win.modelData.name, win.modelData.width - Theme.barSide - win.width + x)
        }
    }
}
