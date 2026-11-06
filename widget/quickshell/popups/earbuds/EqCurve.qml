import QtQuick
import qs

// Equaliser: a single-line, scrollable strip of preset chips, then a drawn response curve with
// draggable nodes. All -10..10. A drag moves a node locally; on release all values go out through
// gains(). Wheel over a column nudges it. With `lead: false` (what the popup uses) `labels` can be
// any length and value is { preset, gains[n] }. `lead: true` adds a separate bass column on the left.
Column {
    id: eq
    property var value: null              // { preset, clearBass, bands[5] } — null = not read yet
    property var presets: []
    property var labelFor: o => o
    signal preset(string name)
    signal custom(int clearBass, var bands)
    signal gains(var g)                   // lead: false only

    property var labels: ["Bass", "400", "1k", "2.5k", "6.3k", "16k"]
    property bool lead: true              // first column = Clear Bass bar, apart from the curve
    readonly property int n: labels.length
    readonly property int first: lead ? 1 : 0
    // lead: [clearBass, b1..b5]; else value.gains
    readonly property var cur: lead
        ? ((value && value.bands && value.bands.length === 5) ? [value.clearBass ?? 0].concat(value.bands) : [0, 0, 0, 0, 0, 0])
        : ((value && value.gains && value.gains.length === n) ? value.gains : Array(n).fill(0))
    property var local: null              // values while dragging / just released
    readonly property var shown: local ?? cur
    onShownChanged: curve.requestPaint()
    Timer { id: hold; interval: 1500; onTriggered: eq.local = null }
    function send() {
        if (eq.local) { if (eq.lead) eq.custom(eq.local[0], eq.local.slice(1)); else eq.gains(eq.local); }
        hold.restart();
    }
    readonly property string curPreset: eq.local ? "" : (eq.value ? eq.value.preset : "")

    spacing: 12

    // ── presets ──────────────────────────────────────────────────────────
    Item {
        width: parent.width
        height: strip.height
        Flickable {
            id: strip
            width: parent.width
            height: 30
            contentWidth: chips.implicitWidth
            contentHeight: height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.HorizontalFlick
            Behavior on contentX { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            function reveal(item) {
                const max = Math.max(0, contentWidth - width);
                if (item.x < contentX + 8) contentX = Math.max(0, item.x - 24);
                else if (item.x + item.width > contentX + width - 8) contentX = Math.min(max, item.x + item.width - width + 24);
            }
            WheelHandler {     // vertical wheel scrolls the strip sideways
                onWheel: e => {
                    const max = Math.max(0, strip.contentWidth - strip.width);
                    strip.contentX = Math.max(0, Math.min(max, strip.contentX - (e.angleDelta.y || e.angleDelta.x) / 2));
                }
            }
            Row {
                id: chips
                spacing: 6
                Repeater {
                    model: eq.presets
                    delegate: Rectangle {
                        id: chip
                        required property var modelData
                        readonly property bool sel: eq.curPreset === modelData
                        onSelChanged: if (sel) strip.reveal(chip)
                        Component.onCompleted: if (sel) strip.reveal(chip)
                        width: lbl.implicitWidth + 24
                        height: 30
                        radius: 15
                        color: sel ? Theme.accent : cm.containsMouse ? Theme.pill : Theme.surface
                        border.width: sel ? 0 : 1
                        border.color: Theme.barBorder
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Text {
                            id: lbl
                            anchors.centerIn: parent
                            text: eq.labelFor(chip.modelData)
                            color: chip.sel || cm.containsMouse ? Theme.fg : Theme.dim
                            font.family: Theme.font
                            font.pixelSize: 12
                            font.bold: chip.sel
                        }
                        MouseArea {
                            id: cm
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (!chip.sel) { eq.local = null; eq.preset(String(chip.modelData)); }
                        }
                    }
                }
            }
        }

        Rectangle {     // right-edge fade while more chips lie beyond
            visible: strip.contentX < strip.contentWidth - strip.width - 2
            anchors.right: parent.right
            width: 28; height: strip.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: Theme.popupBg }
            }
        }
    }

    // ── curve ────────────────────────────────────────────────────────────
    Rectangle {
        id: plot
        width: parent.width
        height: 136
        radius: 14
        color: Theme.card
        border.width: 1
        border.color: Theme.barBorder

        readonly property int padT: 14
        readonly property int trackH: 84
        readonly property real mid: padT + trackH / 2
        readonly property real cellW: width / eq.n
        readonly property real x0: eq.lead ? cellW + 6 : 8      // where the curve area starts
        function yFor(g) { return mid - g / 10 * (trackH / 2); }
        function cx(i) { return cellW * i + cellW / 2; }

        Canvas {
            id: curve
            anchors.fill: parent
            onPaint: {
                const c = getContext("2d");
                c.reset();
                const p = plot, s = eq.shown;
                // grid: 0 line + ±10 dashes across the band area
                c.lineWidth = 1;
                c.strokeStyle = Theme.pill;
                c.beginPath(); c.moveTo(p.x0, p.mid + 0.5); c.lineTo(p.width - 8, p.mid + 0.5); c.stroke();
                c.strokeStyle = Theme.surface;
                for (const gy of [p.yFor(10), p.yFor(5), p.yFor(-5), p.yFor(-10)]) {
                    for (let x = p.x0; x < p.width - 8; x += 6) { c.beginPath(); c.moveTo(x, gy + 0.5); c.lineTo(x + 3, gy + 0.5); c.stroke(); }
                }
                if (eq.lead) {      // Clear Bass bar (from 0)
                    const by = p.yFor(s[0]);
                    c.fillStyle = Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.85);
                    if (s[0] !== 0) c.fillRect(p.cx(0) - 7, Math.min(by, p.mid), 14, Math.abs(by - p.mid));
                    c.fillStyle = Theme.pill;
                    c.fillRect(p.cx(0) - 7, p.mid - 0.5, 14, 1);
                }
                // band curve: Catmull-Rom through the band nodes, flat ends out to the edges
                const pts = [];
                for (let i = eq.first; i < eq.n; i++) pts.push([p.cx(i), p.yFor(s[i])]);
                const all = [[p.x0, pts[0][1]]].concat(pts).concat([[p.width - 8, pts[pts.length - 1][1]]]);
                const path = () => {
                    c.moveTo(all[0][0], all[0][1]);
                    for (let i = 0; i < all.length - 1; i++) {
                        const p0 = all[Math.max(0, i - 1)], p1 = all[i], p2 = all[i + 1], p3 = all[Math.min(all.length - 1, i + 2)];
                        c.bezierCurveTo(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                                        p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, p2[0], p2[1]);
                    }
                };
                const g = c.createLinearGradient(0, p.padT, 0, p.padT + p.trackH);
                g.addColorStop(0, Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.32));
                g.addColorStop(1, Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.02));
                c.beginPath(); path();
                c.lineTo(all[all.length - 1][0], p.padT + p.trackH); c.lineTo(all[0][0], p.padT + p.trackH); c.closePath();
                c.fillStyle = g; c.fill();
                c.beginPath(); path();
                c.lineWidth = 2.5; c.lineJoin = "round"; c.strokeStyle = Theme.accent; c.stroke();
            }
        }
        Rectangle {     // Clear Bass | bands
            visible: eq.lead
            x: plot.cellW + 2; width: 1
            y: plot.padT - 4; height: plot.trackH + 8
            color: Theme.pill
        }

        Repeater {
            model: eq.n
            delegate: Item {
                id: band
                required property int index
                readonly property int g: eq.shown[index] ?? 0
                readonly property bool hot: bm.pressed || bm.containsMouse
                x: plot.cellW * index
                width: plot.cellW
                height: plot.height
                Rectangle {      // column highlight on hover
                    x: 4; width: parent.width - 8
                    y: 6; height: parent.height - 12
                    radius: 10
                    color: Qt.rgba(1, 1, 1, 0.03)
                    opacity: band.hot ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }
                }
                Rectangle {      // node
                    width: band.hot ? 14 : 11; height: width; radius: width / 2
                    Behavior on width { NumberAnimation { duration: 100 } }
                    x: parent.width / 2 - width / 2
                    y: plot.yFor(band.g) - height / 2
                    color: band.hot ? Theme.fg : (band.index === 0 && eq.lead ? Theme.dim : Theme.fg)
                    border.width: 2
                    border.color: Theme.accent
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: plot.padT + plot.trackH + 10
                    text: eq.labels[band.index]
                    color: band.hot ? Theme.fg : Theme.faint
                    font.family: Theme.font
                    font.pixelSize: 10
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: plot.padT + plot.trackH + 23
                    text: (band.g > 0 ? "+" : "") + band.g
                    color: band.hot ? Theme.accentHover : band.g !== 0 ? Theme.dim : Theme.muted
                    font.family: Theme.font
                    font.pixelSize: 10
                    font.bold: band.hot
                }
                MouseArea {
                    id: bm
                    width: parent.width
                    height: plot.height
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    preventStealing: true
                    function pick(my) {
                        const v = Math.round(Math.max(-10, Math.min(10, (plot.mid - my) / (plot.trackH / 2) * 10)));
                        if (v === band.g && eq.local) return;
                        const g = (eq.local ?? eq.cur).slice();
                        g[band.index] = v;
                        eq.local = g;
                    }
                    onPressed: e => { hold.stop(); pick(e.y); }
                    onPositionChanged: e => { if (pressed) pick(e.y); }
                    onReleased: eq.send()
                    onWheel: e => {
                        const g = (eq.local ?? eq.cur).slice();
                        g[band.index] = Math.max(-10, Math.min(10, g[band.index] + (e.angleDelta.y > 0 ? 1 : -1)));
                        eq.local = g;
                        wheelSend.restart();
                    }
                }
            }
        }
        Timer { id: wheelSend; interval: 400; onTriggered: eq.send() }
    }
}
