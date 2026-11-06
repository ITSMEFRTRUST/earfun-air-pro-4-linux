import QtQuick
import qs

// wide int slider with a value bubble: 8 px trough, red fill,
// ringed knob, step ticks. Drags/wheel move it locally; the value is sent once, on release
// (or 400 ms after the wheel stops). The bubble rides the knob while hovered / dragged.
Item {
    id: root
    property int lo: 0
    property int hi: 100
    property var value: lo
    property bool active: true            // false = drawn muted (the mode it belongs to is off)
    readonly property bool holding: mouse.pressed || hold.running || wheelSend.running
    property int local: 0
    readonly property int shown: holding ? local : Math.max(lo, Math.min(hi, Number(value) || 0))
    readonly property real frac: hi > lo ? (shown - lo) / (hi - lo) : 0
    readonly property bool bubbleOn: mouse.containsMouse || mouse.pressed || wheelSend.running
    signal committed(int v)

    implicitHeight: 52                    // 26 bubble room + 26 track row

    Timer { id: hold; interval: 1500 }
    Timer { id: wheelSend; interval: 400; onTriggered: { root.committed(root.local); hold.restart(); } }

    Item {
        id: track
        x: 9
        y: 26
        width: parent.width - 18
        height: 26

        Rectangle {         // trough
            anchors.verticalCenter: parent.verticalCenter
            x: -9; width: parent.width + 18; height: 8; radius: 4
            color: Theme.pill
        }
        Repeater {          // ticks every 5 steps
            model: Math.floor((root.hi - root.lo) / 5) + 1
            delegate: Rectangle {
                required property int index
                readonly property real f: (index * 5) / (root.hi - root.lo)
                x: track.width * f - 1
                anchors.verticalCenter: parent.verticalCenter
                width: 2; height: 2; radius: 1
                color: f <= root.frac ? Qt.rgba(1, 1, 1, 0.35) : Theme.faint
            }
        }
        Rectangle {         // fill
            anchors.verticalCenter: parent.verticalCenter
            x: -9
            width: knob.x + 18
            height: 8; radius: 4
            color: root.active ? Theme.accent : Theme.muted
            Behavior on color { ColorAnimation { duration: 150 } }
        }
        Rectangle {
            id: knob
            width: 18; height: 18; radius: 9
            anchors.verticalCenter: parent.verticalCenter
            x: track.width * root.frac - 9
            Behavior on x { enabled: !mouse.pressed; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            color: Theme.fg
            border.width: 3
            border.color: root.active ? Theme.accent : Theme.muted
            scale: mouse.pressed ? 1.15 : 1
            Behavior on scale { NumberAnimation { duration: 100 } }
        }
        Rectangle {         // value bubble
            id: bubble
            width: Math.max(30, bt.implicitWidth + 14)
            height: 20
            radius: 6
            x: knob.x + knob.width / 2 - width / 2
            y: -height - 4
            color: Theme.fg
            opacity: root.bubbleOn ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 140 } }
            Rectangle {     // pointer
                width: 8; height: 8
                rotation: 45
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - 5
                color: Theme.fg
            }
            Text {
                id: bt
                anchors.centerIn: parent
                text: root.shown
                color: Theme.bg
                font.family: Theme.font
                font.pixelSize: 12
                font.bold: true
            }
        }
        MouseArea {
            id: mouse
            anchors.fill: parent
            anchors.margins: -9
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function pick(mx) {
                const f = Math.max(0, Math.min(1, (mx - 9) / track.width));
                root.local = Math.round(root.lo + f * (root.hi - root.lo));
            }
            onPressed: e => { root.local = root.shown; pick(e.x); }
            onPositionChanged: e => { if (pressed) pick(e.x); }
            onReleased: { hold.restart(); root.committed(root.local); }
            property real acc: 0
            onWheel: e => {
                acc += e.angleDelta.y / 120;
                const n = Math.trunc(acc);
                if (!n) return;
                acc -= n;
                const base = root.holding ? root.local : root.shown;
                root.local = Math.max(root.lo, Math.min(root.hi, base + n));
                wheelSend.restart();
            }
        }
    }
}
