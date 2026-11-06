import QtQuick
import Quickshell
import Quickshell.Wayland
import qs

// One per screen: a full-screen transparent overlay that stays mapped. While closed its input mask
// is empty, so it is click-through. While the popup is open on this screen, a click outside the
// panel or Esc closes it. The panel frame and the open/close animation live here, the content is
// popups/EarbudsPopup.qml.
PanelWindow {
    id: layer
    required property var modelData
    screen: modelData

    readonly property int panelWidth: 380
    readonly property int pad: 16
    readonly property bool mine: Popups.open && Popups.screen === modelData.name
    property bool shown: false        // kept true during the close animation
    property real progress: 0         // 0 closed, 1 open

    color: "transparent"
    mask: shown ? null : noInput
    Region { id: noInput }
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "earfun-popup"
    WlrLayershell.keyboardFocus: shown ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    onMineChanged: {
        if (mine) {
            shown = true;
            closeAnim.stop();
            openAnim.restart();
            keys.forceActiveFocus();
        } else if (shown) {
            openAnim.stop();
            closeAnim.restart();
        }
    }

    NumberAnimation { id: openAnim; target: layer; property: "progress"; to: 1; duration: 180; easing.type: Easing.OutCubic }
    NumberAnimation {
        id: closeAnim; target: layer; property: "progress"; to: 0; duration: 120; easing.type: Easing.InCubic
        onFinished: if (!layer.mine) layer.shown = false
    }

    MouseArea {   // click outside = close
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: Popups.close()
    }

    Item {
        id: keys
        focus: true
        Keys.onEscapePressed: Popups.close()
    }
    Shortcut {
        sequence: "Escape"
        enabled: layer.mine
        onActivated: Popups.close()
    }

    // the panel grows down out of the bar (clip reveal + fade + slight drop)
    Item {
        x: Popups.anchorX < 0 ? (layer.width - width) / 2
         : Math.max(Theme.barSide, Math.min(layer.width - Theme.barSide - width, Popups.anchorX - width / 2))
        y: Theme.popupTop - 6 * (1 - layer.progress)
        width: layer.panelWidth
        height: Math.max(1, frame.height * (0.35 + 0.65 * layer.progress))
        clip: true
        opacity: layer.progress

        Rectangle {
            id: frame
            width: parent.width
            height: (content.item ? content.item.implicitHeight : 0) + 2 * layer.pad
            color: Theme.popupBg
            border.color: Theme.popupBorder
            border.width: 1
            radius: Theme.popupRadius

            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }   // inside is not outside

            Loader {
                id: content
                x: layer.pad; y: layer.pad
                width: parent.width - 2 * layer.pad
                active: layer.shown
                source: Qt.resolvedUrl("popups/EarbudsPopup.qml")
                onLoaded: item.width = Qt.binding(() => content.width)
            }
        }
    }
}
