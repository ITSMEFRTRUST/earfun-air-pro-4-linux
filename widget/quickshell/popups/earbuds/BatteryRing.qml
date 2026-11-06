import QtQuick
import qs

// battery ring: 270° arc (gap at the bottom), red fill animated to `level`, % in the middle
Item {
    id: ring
    property int level: -1                // -1 = unknown
    property bool charging: false
    property string idle: ""              // shown instead of "–" / "%" while level < 0 (bud in case)
    property real shown: Math.max(0, level)
    Behavior on shown { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
    onShownChanged: cv.requestPaint()

    implicitWidth: 66
    implicitHeight: 66

    Canvas {
        id: cv
        anchors.fill: parent
        onPaint: {
            const c = getContext("2d");
            c.reset();
            const r = width / 2 - 5, cx = width / 2, cy = height / 2;
            const a0 = Math.PI * 0.75, span = Math.PI * 1.5;
            c.lineCap = "round";
            c.lineWidth = 6;
            c.strokeStyle = Theme.pill;
            c.beginPath(); c.arc(cx, cy, r, a0, a0 + span); c.stroke();
            if (ring.level < 0) return;
            c.strokeStyle = ring.level <= 15 ? Theme.warm : Theme.accent;
            c.beginPath(); c.arc(cx, cy, r, a0, a0 + span * Math.max(0.01, ring.shown / 100)); c.stroke();
        }
    }
    Column {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 1
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: ring.level >= 0 ? Math.round(ring.shown) : ring.idle || "–"
            color: ring.level < 0 && ring.idle ? Theme.muted : Theme.fg
            font.family: Theme.font
            font.pixelSize: ring.level < 0 && ring.idle ? 15 : 18
            font.bold: true
        }
        Text {
            visible: ring.level >= 0 || !ring.idle
            anchors.horizontalCenter: parent.horizontalCenter
            text: ring.charging ? Theme.glyph(0xf140b) + "%" : "%"   // lightning-bolt
            color: ring.charging ? Theme.warm : Theme.pdim
            font.family: Theme.font
            font.pixelSize: 10
        }
    }
}
