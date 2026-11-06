import QtQuick
import Quickshell
import qs
import "earbuds"

// EarFun Air Pro 4 popup (`earfun watch`):
//   hero card     name, connection, then a battery ring per bud + the case (bud in the case /
//                 case lid shut = the part reports 0xFF → null → empty ring + "in case"; the case falls
//                 back to the daemon's case_last, dimmed, with "Xm ago")
//   noise control big segmented switch + the picked mode's style (ANC style / transparency)
//   Sound         10-band equaliser (preset strip + response curve), game mode, codec, …
//   Device        in-ear detection, touch, dual connection, mic, voice prompts, … + any other
//                 settable key the backend adds
//   Controls      tap gestures per bud
// Settings not verified on the real buds carry a warm dot; a SET the daemon refuses locks its
// control quietly (EarbudsState.locked). State + actions: earbuds/EarbudsState.qml.
Item {
    id: root
    readonly property var scr: Quickshell.screens.find(s => s.name === Popups.screen) ?? null
    readonly property int maxH: (scr ? scr.height : 1080) - Theme.popupTop - 2 * 16 - 24
    implicitHeight: Math.min(col.implicitHeight, maxH)

    readonly property var eb: EarbudsState
    readonly property var modeNames: ({ off: "Off", anc: "Noise Cancelling", ambient: "Ambient" })
    readonly property string modeText: eb.shownMode === "" ? "Noise mode unknown"
        : eb.shownMode === "off" ? "Noise control off" : modeNames[eb.shownMode]
    readonly property string styleText: eb.shownMode === "anc" && styleOf("anc_style") ? eb.optLabel(styleOf("anc_style"))
        : eb.shownMode === "ambient" && styleOf("transparency_style") ? eb.optLabel(styleOf("transparency_style")) : ""
    // "TW600-3091_20250919_v0.4.1" → "0.4.1"
    readonly property string fw: (/v?(\d+(\.\d+)+)$/.exec(eb.firmware) || [])[1] || eb.firmware
    function styleOf(k) { return eb.value(k) || (k === "anc_style" ? eb.ancStyle : eb.transparencyStyle) || ""; }

    // placement of the generated settings; anything else settable lands in Device
    readonly property var soundKeys: ["game_mode", "audio_codec", "advanced_audio", "balance"]
    readonly property var deviceKeys: ["in_ear_detection", "touch", "dual_connection", "mic_mode",
                                       "voice_prompt_volume", "voice_protect"]
    readonly property var extraKeys: eb.plainKeys.filter(k => soundKeys.indexOf(k) < 0 && deviceKeys.indexOf(k) < 0)
    function shown_(k) { return eb.shownKey(k) && eb.value(k) !== null && eb.value(k) !== undefined; }
    readonly property var deviceShown: deviceKeys.concat(extraKeys).filter(k => shown_(k))
    readonly property var icons: ({
        game_mode: 0xf0297, audio_codec: 0xf0387, advanced_audio: 0xf062e, balance: 0xf05d1,
        in_ear_detection: 0xf07c5, touch: 0xf0741, dual_connection: 0xf00b1, mic_mode: 0xf036c,
        voice_prompt_volume: 0xf057e, voice_protect: 0xf0565
    })
    readonly property var subs: ({
        game_mode: "Lower latency for games and video", audio_codec: "Bluetooth codec",
        in_ear_detection: "Pause when a bud comes out", touch: "Which buds react to taps",
        dual_connection: "Two devices at once · buds reboot", voice_protect: "Caps the volume"
    })

    component Caption: Text {
        color: Theme.faint
        font.family: Theme.font
        font.pixelSize: 10
        font.bold: true
        font.letterSpacing: 1.6
    }
    component Divider: Rectangle { height: 1; color: Theme.barBorder }
    component Part: Column {       // one battery ring + its name
        id: part
        property string name
        property var level: null          // null = not reported (0xFF)
        property var last: null           // case: last real level (daemon's case_last) shown dimmed
        property var seen: null           // ... and when (epoch s)
        property var charging: null
        property string idleText: "in case"
        property string idleGlyph: ""
        readonly property bool live: level !== null && level !== undefined
        readonly property bool stale: !live && last !== null && last !== undefined
        width: 96
        spacing: 2
        BatteryRing {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 56; height: 56
            level: part.live ? part.level : part.stale ? part.last : -1
            charging: part.live && part.charging === true
            idle: part.idleGlyph
            opacity: part.stale ? 0.45 : 1
            Behavior on opacity { NumberAnimation { duration: 220 } }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: part.name
            color: Theme.dim
            font.family: Theme.font
            font.pixelSize: 11
            font.bold: true
        }
        Text {      // full width: an empty Text would be skipped by the Column (no jump)
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: part.stale ? EarbudsState.ago(part.seen)
                : !part.live ? part.idleText
                : part.level <= 15 ? "low" : part.level >= 95 ? "full" : ""
            color: part.live && part.level <= 15 ? Theme.warm : Theme.faint
            font.family: Theme.font
            font.pixelSize: 10
            height: 12
        }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: col.implicitHeight
        clip: contentHeight > height
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
            id: col
            width: flick.width
            spacing: 14

            // ── hero ─────────────────────────────────────────────────────────
            Rectangle {
                width: parent.width
                height: eb.online ? 84 + 1 + parts.implicitHeight + 18 : 84
                Behavior on height { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                clip: true
                radius: 16
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: eb.online ? Theme.selection : Theme.card }
                    GradientStop { position: 0.75; color: Theme.card }
                }
                border.width: 1
                border.color: Theme.barBorder

                Item {
                    id: top
                    width: parent.width
                    height: 84
                    Rectangle {     // earbuds disk
                        id: disk
                        x: 14
                        anchors.verticalCenter: parent.verticalCenter
                        width: 52; height: 52; radius: 26
                        color: eb.online ? Theme.accent : Theme.surface
                        Behavior on color { ColorAnimation { duration: 200 } }
                        Text {
                            anchors.centerIn: parent
                            text: Theme.glyph(eb.online ? 0xf184f : 0xf1850)
                            color: eb.online ? Theme.fg : Theme.muted
                            font.family: Theme.font
                            font.pixelSize: 26
                        }
                    }
                    Column {
                        anchors.left: disk.right
                        anchors.leftMargin: 14
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: eb.name || "EarFun Air Pro 4"
                            color: eb.online ? Theme.fg : Theme.dim
                            font.family: Theme.font
                            font.pixelSize: 16
                            font.bold: true
                        }
                        Row {
                            spacing: 6
                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 7; height: 7; radius: 3.5
                                color: eb.switching ? Theme.warm : eb.online ? Theme.fg : Theme.muted
                                SequentialAnimation on opacity {
                                    running: eb.switching
                                    loops: Animation.Infinite
                                    alwaysRunToEnd: true
                                    NumberAnimation { to: 0.3; duration: 450 }
                                    NumberAnimation { to: 1; duration: 450 }
                                }
                            }
                            Text {
                                width: Math.min(implicitWidth, top.width - 66 - 14 - 14 - 13)
                                elide: Text.ElideRight
                                text: !eb.daemon ? "earfun daemon not running"
                                    : !eb.connected ? "not connected"
                                    : eb.switching ? "switching to " + (root.modeNames[eb.shownMode] ?? eb.shownMode) + "…"
                                    : "connected" + (root.fw ? "  ·  fw " + root.fw : "")
                                color: eb.switching ? Theme.warm : Theme.dim
                                font.family: Theme.font
                                font.pixelSize: 11
                            }
                        }
                        Text {
                            text: eb.online ? root.modeText + (root.styleText ? "  ·  " + root.styleText : "")
                                : eb.daemon ? "Connect the buds in Bluetooth" : "systemctl --user start earfun"
                            color: Theme.pdim
                            font.family: Theme.font
                            font.pixelSize: 11
                        }
                    }
                }
                Divider { visible: eb.online; x: 14; y: 84; width: parent.width - 28 }
                Row {
                    id: parts
                    visible: eb.online
                    y: 84 + 1 + 10
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8
                    Part { name: "LEFT"; level: eb.battery.left; idleGlyph: Theme.glyph(0xf1850) }
                    Part { name: "RIGHT"; level: eb.battery.right; idleGlyph: Theme.glyph(0xf1850) }
                    Part { name: "CASE"; level: eb.battery["case"]; idleText: "lid shut"; idleGlyph: Theme.glyph(0xf0e7b)
                           last: eb.battery.case_last ?? null; seen: eb.battery.case_seen ?? null
                           charging: eb.battery.charging ? eb.battery.charging["case"] : null }
                }
            }

            // ── last error ───────────────────────────────────────────────────
            Rectangle {
                visible: eb.error !== ""
                width: parent.width
                height: errText.implicitHeight + 16
                radius: 12
                color: Theme.selection
                border.width: 1
                border.color: Theme.accent
                Text {
                    id: errText
                    anchors.verticalCenter: parent.verticalCenter
                    x: 12
                    width: parent.width - 24
                    text: eb.error
                    wrapMode: Text.WordWrap
                    color: Theme.fg
                    font.family: Theme.font
                    font.pixelSize: 12
                }
                MouseArea { anchors.fill: parent; onClicked: eb.error = "" }
            }

            // ── noise control ────────────────────────────────────────────────
            Column {
                visible: eb.online
                width: parent.width
                spacing: 10

                Caption { text: "NOISE CONTROL"; x: 2 }

                ModeSwitch {
                    width: parent.width
                    current: eb.shownMode
                    busy: eb.switching
                    onPicked: m => eb.setMode(m)
                }

                // what the picked mode offers — slides between heights
                Rectangle {
                    width: parent.width
                    radius: 14
                    color: Theme.card
                    border.width: 1
                    border.color: Theme.barBorder
                    height: ctxCol.implicitHeight + 20
                    Behavior on height { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                    clip: true

                    Column {
                        id: ctxCol
                        x: 12; y: 10
                        width: parent.width - 24
                        spacing: 8

                        Repeater {
                            model: [
                                { key: "anc_style", title: "ANC style", mode: "anc", icon: 0xf0a45 },
                                { key: "transparency_style", title: "Transparency", mode: "ambient", icon: 0xf07c5 }
                            ]
                            delegate: Column {
                                id: style
                                required property var modelData
                                readonly property var s: eb.setting(modelData.key)
                                readonly property string cur: root.styleOf(modelData.key)
                                readonly property var opts: s && s.options && s.options.length ? s.options : (cur ? [cur] : [])
                                readonly property bool locked: eb.locked(modelData.key)
                                visible: eb.shownMode === modelData.mode && opts.length > 0
                                width: ctxCol.width
                                spacing: 8
                                Row {
                                    spacing: 6
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 20
                                        horizontalAlignment: Text.AlignHCenter
                                        text: Theme.glyph(style.modelData.icon)
                                        color: Theme.pdim
                                        font.family: Theme.font
                                        font.pixelSize: 15
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        leftPadding: 2
                                        text: style.modelData.title
                                        color: Theme.fg
                                        font.family: Theme.font
                                        font.pixelSize: Theme.popupFont
                                    }
                                    UntestedDot {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: !!style.s && style.s.live_verified === false && !style.locked
                                    }
                                    Text {
                                        visible: style.locked
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: Theme.glyph(0xf033e) + "  read-only for now"
                                        color: Theme.faint
                                        font.family: Theme.font
                                        font.pixelSize: 10
                                    }
                                }
                                Item {
                                    width: parent.width
                                    height: styleChips.implicitHeight
                                    opacity: style.locked ? 0.55 : 1
                                    Chips {
                                        id: styleChips
                                        width: parent.width
                                        options: style.opts
                                        current: style.cur || null
                                        onPicked: v => { if (style.s) eb.set(style.modelData.key, v); }
                                    }
                                    MouseArea { visible: style.locked; anchors.fill: parent }   // inert
                                }
                            }
                        }
                        Text {
                            visible: eb.shownMode === "off" || eb.shownMode === ""
                                || (eb.shownMode === "anc" && !root.styleOf("anc_style") && !eb.setting("anc_style"))
                            width: parent.width
                            height: 26
                            verticalAlignment: Text.AlignVCenter
                            text: eb.shownMode === "off" ? "Noise control is off — passive isolation only."
                                : eb.shownMode === "" ? "Waiting for the buds to report their mode…"
                                : "Blocking outside sound."
                            color: Theme.pdim
                            font.family: Theme.font
                            font.pixelSize: 11
                        }
                    }
                }
            }

            Divider { visible: eb.online; width: parent.width }

            // ── sound ────────────────────────────────────────────────────────
            Section {
                id: soundSec
                visible: eb.online && (eb.eqKeys.length > 0 || root.soundKeys.some(k => root.shown_(k)))
                width: parent.width
                title: "Sound"
                icon: 0xf00ec               // equalizer
                readonly property var eqv: eb.eqKeys.length ? eb.value(eb.eqKeys[0]) : null
                note: eb.eqKeys.length === 0 ? "" : !eqv ? "Default" : eqv.preset ? eb.optLabel(eqv.preset) : "Custom"
                expanded: eb.openEq
                onToggle: { eb.openEq = !eb.openEq; if (eb.openEq) { eb.openSettings = false; eb.openGestures = false; } }
                Repeater {
                    model: eb.eqKeys
                    delegate: EqCurve {
                        required property string modelData
                        width: soundSec.innerWidth
                        lead: false
                        labels: ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
                        value: eb.value(modelData) ?? { preset: "default", gains: [] }
                        presets: (eb.setting(modelData) || {}).options || []
                        labelFor: o => eb.optLabel(o)
                        onPreset: p => eb.setEq(modelData, p)
                        onGains: g => eb.setEq(modelData, g)
                    }
                }
                Repeater {
                    model: root.soundKeys
                    delegate: SettingRow {
                        required property string modelData
                        key: modelData
                        icon: root.icons[modelData] ?? 0
                        sub: root.subs[modelData] ?? ""
                        width: soundSec.innerWidth
                    }
                }
            }

            // ── device ───────────────────────────────────────────────────────
            Section {
                id: devSec
                visible: eb.online && root.deviceShown.length > 0
                width: parent.width
                title: "Device"
                icon: 0xf0493               // cog
                note: root.deviceShown.filter(k => eb.value(k) === true).length + " on"
                expanded: eb.openSettings
                onToggle: { eb.openSettings = !eb.openSettings; if (eb.openSettings) { eb.openEq = false; eb.openGestures = false; } }
                Repeater {
                    model: root.deviceKeys.concat(root.extraKeys)
                    delegate: SettingRow {
                        required property string modelData
                        key: modelData
                        icon: root.icons[modelData] ?? 0
                        sub: root.subs[modelData] ?? ""
                        width: devSec.innerWidth
                    }
                }
            }

            // ── controls (tap gestures) ──────────────────────────────────────
            Section {
                id: gest
                visible: eb.online && eb.gestureTaps.length > 0
                width: parent.width
                title: "Controls"
                icon: 0xf0741               // gesture-tap
                note: "tap gestures"
                expanded: eb.openGestures
                onToggle: { eb.openGestures = !eb.openGestures; if (eb.openGestures) { eb.openEq = false; eb.openSettings = false; } }
                readonly property int labelW: 64
                readonly property real colW: (innerWidth - labelW - 8) / 2
                Row {
                    x: gest.labelW
                    spacing: 8
                    Repeater {
                        model: ["LEFT", "RIGHT"]
                        delegate: Text {
                            required property string modelData
                            width: gest.colW
                            text: modelData
                            color: Theme.faint
                            font.family: Theme.font
                            font.pixelSize: 10
                            font.bold: true
                            font.letterSpacing: 1.6
                        }
                    }
                }
                Repeater {
                    model: eb.gestureTaps
                    delegate: Item {
                        id: tap
                        required property string modelData
                        width: gest.innerWidth
                        height: 28
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 5
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: eb.cap(tap.modelData)
                                color: Theme.fg
                                font.family: Theme.font
                                font.pixelSize: Theme.popupFont
                            }
                            UntestedDot {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: eb.untested(["gesture_" + tap.modelData + "_left", "gesture_" + tap.modelData + "_right"])
                            }
                        }
                        Row {
                            x: gest.labelW
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 8
                            Repeater {
                                model: ["left", "right"]
                                delegate: Item {
                                    required property string modelData
                                    readonly property string k: "gesture_" + tap.modelData + "_" + modelData
                                    readonly property bool locked: eb.locked(k)
                                    width: gest.colW
                                    height: 26
                                    opacity: locked ? 0.4 : 1
                                    Dropdown {
                                        anchors.fill: parent
                                        visible: eb.shownKey(parent.k)
                                        options: (eb.setting(parent.k) || {}).options || []
                                        current: eb.value(parent.k)
                                        onPicked: v => eb.set(parent.k, v)
                                    }
                                    MouseArea { visible: parent.locked; anchors.fill: parent }
                                }
                            }
                        }
                    }
                }
            }

            // legend for the warm dots / locks
            Row {
                visible: eb.online
                spacing: 6
                x: 2
                UntestedDot { anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: Object.keys(eb.refused).length ? "not yet verified on the real buds  ·  " + Theme.glyph(0xf033e) + " refused"
                                                         : "not yet verified on the real buds"
                    color: Theme.faint
                    font.family: Theme.font
                    font.pixelSize: 10
                }
            }
        }
    }

    Rectangle {     // scroll position
        visible: flick.interactive
        anchors.right: parent.right
        anchors.rightMargin: -10
        y: flick.visibleArea.yPosition * flick.height
        width: 3
        height: flick.visibleArea.heightRatio * flick.height
        radius: 1.5
        color: Theme.pill
    }
}
