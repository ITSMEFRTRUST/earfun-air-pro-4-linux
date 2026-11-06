import QtQuick
import qs
import "../popups/earbuds"

// bar module: earbuds glyph + split battery donut (left half = left bud, right half = right bud,
// empty = in the case) + noise mode as a small pill (ANC red, ambient grey, off none).
// Hidden while the earfun daemon isn't running, dim "earbuds off" glyph while the buds aren't connected.
// Click -> `clicked` (open the popup there), right-click / scroll -> next mode (off -> ANC -> ambient).
// `tip` and `hovered` are there if your bar shows tooltips.
// While the buds haven't applied a new mode yet (~2 s) its glyph breathes.
Item {
    id: root
    signal clicked(int button, real x)

    readonly property var eb: EarbudsState
    readonly property bool online: eb.online
    readonly property int lvl: eb.level
    readonly property string modeGlyph: eb.shownMode === "anc" ? Theme.glyph(0xf0a45)
                                      : eb.shownMode === "ambient" ? Theme.glyph(0xf07c5) : ""
    readonly property int cell: Math.round(Theme.barFont * 0.6)
    readonly property color base: !online ? Theme.muted
                                : lvl >= 0 && lvl <= 10 ? Theme.accentHover
                                : lvl >= 0 && lvl <= 20 ? Theme.warn : Theme.dim
    readonly property color shown: online && mouse.containsMouse ? Theme.fg : base
    readonly property bool hovered: mouse.containsMouse

    visible: eb.daemon
    implicitWidth: eb.daemon ? row.implicitWidth + 18 : 0
    implicitHeight: Theme.barHeight

    Row {
        id: row
        x: 9
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
        Text {      // one monospace cell like BarLabel's icon
            width: root.cell
            anchors.verticalCenter: parent.verticalCenter
            text: Theme.glyph(root.online ? 0xf184f : 0xf1850)
            color: root.online ? (mouse.containsMouse ? Theme.fg : Theme.dim) : Theme.muted
            font.family: Theme.font
            font.pixelSize: Theme.barFont
            font.hintingPreference: Font.PreferFullHinting
        }
        Item {      // split battery donut (left half = left bud, right half = right bud); % only in popup/tip
            visible: root.online && (eb.battery.left !== null || eb.battery.right !== null)
            anchors.verticalCenter: parent.verticalCenter
            width: mini.width
            height: 16
            Canvas {
                id: mini
                width: 14; height: 14
                anchors.verticalCenter: parent.verticalCenter
                property var l: eb.battery.left
                property var r: eb.battery.right
                property color c: root.base === Theme.dim ? Theme.accent : root.base
                onLChanged: requestPaint()
                onRChanged: requestPaint()
                onCChanged: requestPaint()
                onPaint: {
                    const g = getContext("2d");
                    g.reset();
                    const gap = 0.22, half = Math.PI - 2 * gap, bot = Math.PI / 2;
                    g.lineWidth = 2.5; g.lineCap = "butt";
                    g.strokeStyle = Theme.pill;     // tracks: left half, right half
                    g.beginPath(); g.arc(7, 7, 5.5, bot + gap, bot + gap + half); g.stroke();
                    g.beginPath(); g.arc(7, 7, 5.5, bot - gap - half, bot - gap); g.stroke();
                    g.strokeStyle = c;              // each half fills from the bottom up; null = empty
                    if (l !== null && l !== undefined)
                        { g.beginPath(); g.arc(7, 7, 5.5, bot + gap, bot + gap + half * Math.max(0.04, l / 100)); g.stroke(); }
                    if (r !== null && r !== undefined)
                        { g.beginPath(); g.arc(7, 7, 5.5, bot - gap - half * Math.max(0.04, r / 100), bot - gap); g.stroke(); }
                }
            }
        }
        Rectangle {     // mode as a small pill: ANC red, ambient grey, off none
            visible: root.online && root.modeGlyph !== ""
            anchors.verticalCenter: parent.verticalCenter
            width: 22; height: 18; radius: 9
            color: eb.shownMode === "anc" ? Theme.accent : Theme.pill
            Behavior on color { ColorAnimation { duration: 180 } }
            SequentialAnimation on opacity {
                running: eb.switching
                loops: Animation.Infinite
                alwaysRunToEnd: true
                NumberAnimation { to: 0.3; duration: 450; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 450; easing.type: Easing.InOutSine }
            }
            Text {
                anchors.centerIn: parent
                text: root.modeGlyph
                color: Theme.fg
                font.family: Theme.font
                font.pixelSize: Theme.barFont - 2
                font.hintingPreference: Font.PreferFullHinting
            }
        }
    }

    readonly property string tip: !online ? "Earbuds not connected"
        : (eb.name || "Earbuds") + " · L " + (eb.battery.left ?? "in case") + (eb.battery.left !== null ? "%" : "")
          + " · R " + (eb.battery.right ?? "in case") + (eb.battery.right !== null ? "%" : "")
          + " · case " + (eb.battery["case"] !== null && eb.battery["case"] !== undefined ? eb.battery["case"] + "%"
                          : eb.battery.case_last !== null && eb.battery.case_last !== undefined
                            ? eb.battery.case_last + "% " + eb.ago(eb.battery.case_seen) : "—")
          + " · " + (eb.shownMode === "anc" ? "ANC" : eb.shownMode === "ambient" ? "Ambient" : eb.shownMode === "off" ? "Off" : "—")

    Timer { id: cool; interval: 600 }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: e => {
            if (e.button === Qt.RightButton) { if (root.online) eb.cycle(); }
            else root.clicked(e.button, root.mapToItem(null, root.width / 2, 0).x);
        }
        property real acc: 0
        onWheel: e => {
            if (!root.online) return;
            acc += e.angleDelta.y / 120;
            const n = Math.trunc(acc);
            acc -= n;
            if (n !== 0 && !cool.running) { eb.cycle(); cool.restart(); }   // one step per scroll burst
        }
    }
}
