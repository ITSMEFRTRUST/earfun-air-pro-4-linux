import QtQuick
import qs

// one generated setting from the backend's `settings` map, as one row:
// optional glyph, label (+ dim hint line), control on the right —
//   bool → switch · enum ≤ 4 short options → chips, else a dropdown ·
//   int (min/max from the backend) → value on the right + IntSlider below.
// Not verified on the real buds → small warm dot after the label. The daemon refused the SET
// (EarbudsState.locked) → control dimmed + inert, a lock and "not verified on these buds yet".
// Hidden while the buds haven't reported a value.
Column {
    id: row
    property string key
    property string label: EarbudsState.label(key)
    property string sub: ""
    property int icon: 0
    readonly property var s: EarbudsState.setting(key) ?? ({})
    readonly property var v: EarbudsState.value(key)
    readonly property string type: s.type ?? ""
    readonly property var opts: s.options ?? []
    // chips only when they fit beside the label, else a dropdown
    readonly property bool chips: type === "enum" && opts.length <= 4
                                  && textX + lblRow.implicitWidth + 12 + ch.implicitWidth <= width
    readonly property bool locked: EarbudsState.locked(key)
    readonly property real textX: icon ? 28 : 0
    readonly property string subShown: locked ? "Not verified on these buds yet" : sub

    visible: EarbudsState.shownKey(key) && v !== null && v !== undefined
    spacing: 2

    Item {
        width: parent.width
        height: row.subShown !== "" ? 40 : 30

        Text {
            visible: row.icon !== 0
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            horizontalAlignment: Text.AlignHCenter
            text: row.icon ? Theme.glyph(row.icon) : ""
            color: row.type === "bool" && row.v === true && !row.locked ? Theme.fg : Theme.pdim
            Behavior on color { ColorAnimation { duration: 150 } }
            font.family: Theme.font
            font.pixelSize: 15
        }
        Column {
            x: row.textX
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Row {
                id: lblRow
                spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.label
                    color: row.locked ? Theme.dim : Theme.fg
                    font.family: Theme.font
                    font.pixelSize: Theme.popupFont
                }
                UntestedDot {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: row.s.live_verified === false && !row.locked
                }
                Text {
                    visible: row.locked
                    anchors.verticalCenter: parent.verticalCenter
                    text: Theme.glyph(0xf033e)      // lock
                    color: Theme.faint
                    font.family: Theme.font
                    font.pixelSize: 11
                }
            }
            Text {
                visible: row.subShown !== ""
                width: Math.min(implicitWidth, row.width - row.textX - ctl.width - 10)
                elide: Text.ElideRight
                text: row.subShown
                color: Theme.faint
                font.family: Theme.font
                font.pixelSize: 10
            }
        }
        Item {      // the control; inert + dimmed while locked
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: ctl.width
            height: ctl.height
            opacity: row.locked ? 0.4 : 1
            Behavior on opacity { NumberAnimation { duration: 150 } }
            Item {
                id: ctl
                width: row.type === "bool" ? tg.width : row.chips ? ch.width : row.type === "enum" ? dd.width : val.implicitWidth
                height: Math.max(26, val.implicitHeight)
                Toggle {
                    id: tg
                    visible: row.type === "bool"
                    anchors.verticalCenter: parent.verticalCenter
                    on: row.v === true
                    onToggled: b => EarbudsState.set(row.key, b)
                }
                Chips {
                    id: ch
                    visible: row.chips
                    anchors.verticalCenter: parent.verticalCenter
                    options: row.opts
                    current: row.v
                    onPicked: o => EarbudsState.set(row.key, o)
                }
                Dropdown {
                    id: dd
                    visible: row.type === "enum" && !row.chips
                    anchors.verticalCenter: parent.verticalCenter
                    width: 140
                    options: row.opts
                    current: row.v
                    onPicked: o => EarbudsState.set(row.key, o)
                }
                Text {
                    id: val
                    visible: row.type === "int"
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.key === "balance" ? (sl.shown === 50 ? "centre" : sl.shown < 50 ? "L " + (50 - sl.shown) : "R " + (sl.shown - 50))
                                                : sl.shown + " / " + sl.hi
                    color: Theme.pdim
                    font.family: Theme.font
                    font.pixelSize: 11
                }
            }
            MouseArea { visible: row.locked; anchors.fill: parent; hoverEnabled: true }   // swallow clicks
        }
    }
    Item {      // the slider's track row; its bubble room overlaps the label row above
        visible: row.type === "int"
        width: parent.width
        height: 24
    IntSlider {
        id: sl
        y: -25
        width: parent.width
        height: 40
        enabled: !row.locked
        opacity: row.locked ? 0.4 : 1
        lo: row.s.min ?? 0
        hi: row.s.max ?? 100
        value: row.v
        onCommitted: n => EarbudsState.set(row.key, n)
    }
    }
}
