pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// EarFun Air Pro 4 state, shared by the bar module (modules/Earbuds.qml) and the popup.
// Source: `earfun watch` (one JSON state per line; prints {"daemon":false} and retries by itself
// while the daemon is down). Actions: `earfun mode <m>` / `earfun set <key> <value>`, run one at a
// time in click order; a failing one (non-zero exit) → inline error in the popup + notify-send.
// Binary: $EARFUN_BIN, else `earfun` on PATH.
Singleton {
    id: root

    readonly property string bin: Quickshell.env("EARFUN_BIN") || "earfun"
    readonly property var modes: ["off", "anc", "ambient"]

    // ── live state (contract fields) ─────────────────────────────────────
    property bool daemon: false
    property bool connected: false
    property string name: ""
    property string mode: ""              // "" = unknown
    property string pendingMode: ""       // the buds apply a mode ~2 s after the set
    property var battery: ({ left: null, right: null, "case": null })
    property string ancStyle: ""
    property string transparencyStyle: ""
    property string firmware: ""
    property var settings: ({})
    property string source: ""            // "live" | "fake"

    // SETs the daemon refused (not verified on the real buds, daemon without
    // --allow-unverified-sets): the control goes read-only with a lock, no notification. Forgotten when
    // the daemon / connection goes away (a restart may allow them).
    property var refused: ({})
    function locked(key) { return refused[key] === true; }

    // ── optimistic overrides: clicked, not confirmed by the state yet ────
    property string wantMode: ""
    property var want: ({})               // key → value
    property string error: ""             // last failed action (cleared after a while)

    // popup sections stay as you left them between opens
    property bool openEq: false
    property bool openSettings: false
    property bool openGestures: false

    // generated settings: contract types only, settable, minus what the popup shows elsewhere
    // (mode / styles / eq / gestures) and find_device (plays a loud sound in the buds — never from here)
    readonly property var special: ["mode", "anc_style", "transparency_style", "find_device"]
    readonly property var order: ["game_mode", "in_ear_detection", "dual_connection", "touch", "mic_mode",
                                  "audio_codec", "advanced_audio", "voice_prompt_volume", "voice_protect", "balance"]
    function shownKey(k) {
        const s = settings[k];
        return !!s && s.settable !== false && ["readonly", "action", "event"].indexOf(s.kind ?? "") < 0
            && special.indexOf(k) < 0;
    }
    readonly property var plainKeys: Object.keys(settings)
        .filter(k => shownKey(k) && ["bool", "enum", "int"].indexOf(settings[k].type) >= 0 && !k.startsWith("gesture_"))
        .sort((a, b) => {
            const ia = order.indexOf(a), ib = order.indexOf(b);
            return ia >= 0 && ib >= 0 ? ia - ib : ia >= 0 ? -1 : ib >= 0 ? 1 : a.localeCompare(b);
        })
    readonly property var eqKeys: Object.keys(settings).filter(k => shownKey(k) && settings[k].type === "eq")
    readonly property var gestureTaps: ["single", "double", "triple", "long"]
        .filter(t => shownKey("gesture_" + t + "_left") || shownKey("gesture_" + t + "_right"))
    function untested(keys) { return keys.some(k => settings[k] && settings[k].live_verified === false); }

    readonly property bool online: daemon && connected
    readonly property string shownMode: wantMode || pendingMode || mode
    readonly property bool switching: (wantMode !== "" && wantMode !== mode) || (pendingMode !== "" && pendingMode !== mode)
    // the lower bud is what runs out first; null = that bud can't report (in the case)
    readonly property var budLevels: [battery.left, battery.right].filter(v => v !== null && v !== undefined)
    readonly property int level: budLevels.length ? Math.min.apply(null, budLevels) : -1

    function setting(key) { return settings[key] ?? null; }
    function value(key) {
        if (want[key] !== undefined) return want[key];
        const s = settings[key];
        return s ? s.value : null;
    }

    // ── labels ───────────────────────────────────────────────────────────
    readonly property var names: ({
        game_mode: "Game mode", in_ear_detection: "In-ear detection", dual_connection: "Dual connection",
        touch: "Touch controls", audio_codec: "Codec", advanced_audio: "Advanced audio", mic_mode: "Microphone",
        voice_prompt_volume: "Voice prompts", voice_protect: "Hearing limit", balance: "Balance",
        eq: "Equaliser", anc_style: "ANC style", transparency_style: "Transparency"
    })
    readonly property var optNames: ({
        anc: "ANC", ai_environment_adaptive: "AI env", ai_ear_adaptive: "AI ear", aptx: "aptX",
        aptx_adaptive: "aptX Adaptive", aptx_lossless: "aptX Lossless", ldac: "LDAC", le_audio: "LE Audio",
        fast_pair: "Fast Pair", bass_boost: "Bass", treble_boost: "Treble", volume_up: "Volume up",
        volume_down: "Volume down", play_pause: "Play / pause", voice_assistant: "Assistant",
        noise_control_all: "Noise: all", noise_control_normal_wind: "Noise: off/wind",
        noise_control_normal_ambient: "Noise: off/ambient", noise_control_wind_ambient: "Noise: wind/ambient",
        "90db": "90 dB", "80db": "80 dB", "70db": "70 dB", "60db": "60 dB", "50db": "50 dB"
    })
    // "5m ago" / "3h ago" / "2d ago" for an epoch-seconds stamp (case_seen); "" when unknown
    property real now: Date.now() / 1000
    Timer { interval: 30000; running: true; repeat: true; onTriggered: root.now = Date.now() / 1000 }
    function ago(ts) {
        if (ts === null || ts === undefined) return "";
        const d = Math.max(0, root.now - ts);
        return (d < 60 ? "just now" : d < 3600 ? Math.floor(d / 60) + "m ago"
              : d < 172800 ? Math.floor(d / 3600) + "h ago" : Math.floor(d / 86400) + "d ago");
    }
    function cap(s) { s = String(s).replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); }
    function label(key) {
        const s = settings[key];
        if (s && s.label) return s.label;
        if (names[key]) return names[key];
        const g = /^gesture_(\w+)_(left|right)$/.exec(key);
        if (g) return cap(g[1]) + " tap";
        return cap(key);
    }
    function optLabel(o) { return optNames[o] ?? cap(o); }

    // `qs ipc call earbuds cycle | mode <m> | set <key> <value> | state | sections all|none|eq,settings,gestures`
    // (keybinds; same path as the bar's right-click). `sections` sets which popup sections are open.
    IpcHandler {
        target: "earbuds"
        function cycle(): void { if (root.online) root.cycle(); }
        function mode(m: string): void { if (root.online) root.setMode(m); }
        function set(key: string, value: string): void {
            const s = root.settings[key];
            if (!root.online || !s) return;
            if (s.type === "eq") root.setEq(key, value.indexOf(",") >= 0 ? value.split(",").map(Number) : value);
            else root.set(key, s.type === "bool" ? ["1", "on", "true", "yes"].indexOf(value) >= 0
                               : s.type === "int" ? parseInt(value) : value);
        }
        function state(): string {
            return JSON.stringify({ daemon: root.daemon, connected: root.connected, mode: root.mode,
                                    shown: root.shownMode, switching: root.switching, level: root.level, error: root.error });
        }
        function sections(which: string): void {    // "all", "none" or e.g. "eq,gestures"
            const w = which === "all" ? ["eq", "settings", "gestures"] : which.split(",");
            root.openEq = w.indexOf("eq") >= 0;
            root.openSettings = w.indexOf("settings") >= 0;
            root.openGestures = w.indexOf("gestures") >= 0;
        }
    }

    // an EQ preset is confirmed by its name (the gains come from the backend), the rest by value
    function confirmed(s, w) {
        if (s.type === "eq" && w && w.preset) return !!s.value && s.value.preset === w.preset;
        return JSON.stringify(s.value) === JSON.stringify(w);
    }

    // ── watch ────────────────────────────────────────────────────────────
    function ingest(line) {
        let d;
        try { d = JSON.parse(line); } catch (e) { return; }
        if (!d || typeof d !== "object") return;
        daemon = d.daemon === true;
        if (!daemon) { connected = false; refused = {}; return; }
        if (connected && d.connected !== true) refused = {};
        connected = d.connected === true;
        source = d.source ?? "";
        name = d.name ?? "";
        mode = d.mode ?? "";
        pendingMode = d.pending_mode ?? "";
        battery = d.battery ?? { left: null, right: null, "case": null };
        ancStyle = d.anc_style ?? "";
        transparencyStyle = d.transparency_style ?? "";
        firmware = d.firmware ?? "";
        settings = d.settings ?? {};
        // the backend took over (pending) or the buds already switched → drop our guess
        if (wantMode !== "" && (pendingMode === wantMode || mode === wantMode)) wantMode = "";
        let w = null;
        for (const k in want) {
            const s = settings[k];
            if (s && confirmed(s, want[k])) { w = w ?? Object.assign({}, want); delete w[k]; }
        }
        if (w) want = w;
    }

    Process {
        id: watch
        running: true
        command: [root.bin, "watch"]
        stdout: SplitParser { onRead: line => root.ingest(line) }
        // `watch` never exits on its own; if it does (or the binary is missing) → hide, retry
        onRunningChanged: if (!running) { root.daemon = false; root.connected = false; retry.restart(); }
    }
    Timer { id: retry; interval: 5000; onTriggered: watch.running = true }

    // ── actions ──────────────────────────────────────────────────────────
    function setMode(m) {
        if (modes.indexOf(m) < 0) return;
        wantMode = m;
        modeHold.restart();
        enqueue("mode", ["mode", m]);
    }
    // explicit next mode (not `earfun mode cycle`) so the optimistic state is what gets sent
    function cycle() {
        const i = modes.indexOf(shownMode);
        setMode(modes[(i + 1) % modes.length]);
    }
    function arg(v) {
        if (v === true) return "on";
        if (v === false) return "off";
        if (Array.isArray(v)) return v.join(",");
        return String(v);
    }
    function set(key, v) {
        const w = Object.assign({}, want);
        w[key] = v;
        want = w;
        wantHold.restart();
        enqueue(key, ["set", key, arg(v)]);
    }
    // EQ: a preset name, or ten gains; the shown value follows the contract's {preset, gains}
    function setEq(key, presetOrGains) {
        const g = Array.isArray(presetOrGains) ? presetOrGains : null;
        const w = Object.assign({}, want);
        // a preset's gains aren't known here: keep showing the old bands until the state has them
        w[key] = g ? { preset: null, gains: g } : { preset: presetOrGains, gains: (value(key) || {}).gains || [] };
        want = w;
        wantHold.restart();
        enqueue(key, ["set", key, g ? g.join(",") : presetOrGains]);
    }

    // no confirmation in time → show the real state again
    Timer { id: modeHold; interval: 6000; onTriggered: root.wantMode = "" }
    Timer { id: wantHold; interval: 5000; onTriggered: if (!runner.running && !root.queue.length) root.want = {} }
    Timer { id: errHold; interval: 8000; onTriggered: root.error = "" }

    // one in flight; a newer change of the same key replaces a queued one (slider drags, EQ bands)
    property var queue: []
    function enqueue(key, args) {
        queue = queue.filter(j => j.key !== key).concat([{ key: key, args: args }]);
        runNext();
    }
    function runNext() {
        if (runner.running || runner.job || !queue.length) return;
        runner.job = queue[0];
        queue = queue.slice(1);
        runner.command = ["sh", "-c", 'out=$("$0" "$@" 2>&1) || { printf "%s" "${out:-exit $?}"; exit 1; }',
                          root.bin].concat(runner.job.args);
        runner.running = true;
    }
    function fail(job, msg) {
        msg = String(msg).trim().split("\n").pop().replace(/^earfun:\s*/, "");
        if (/^refused\b/.test(msg)) {          // safety gate, not an error: lock the control quietly
            const r = Object.assign({}, refused); r[job.key] = true; refused = r;
            if (want[job.key] !== undefined) { const w = Object.assign({}, want); delete w[job.key]; want = w; }
            return;
        }
        error = (job.key === "mode" ? "Noise mode" : label(job.key)) + ": " + (msg || "earfun " + job.args.join(" ") + " failed");
        errHold.restart();
        if (job.key === "mode") wantMode = "";
        else if (want[job.key] !== undefined) { const w = Object.assign({}, want); delete w[job.key]; want = w; }
        Quickshell.execDetached(["notify-send", "-a", "Earbuds", "Earbuds", error]);
    }
    // the collector and the exit can arrive in either order: finish the job once both are in
    Process {
        id: runner
        property var job: null
        property int code: -1
        property string text: ""
        property bool streamed: false
        function done() {
            if (code < 0 || !streamed) return;
            const j = job;
            job = null;
            if (code !== 0 && j) root.fail(j, text);
            code = -1;
            streamed = false;
            root.runNext();
        }
        stdout: StdioCollector {
            onStreamFinished: { runner.text = text; runner.streamed = true; runner.done(); }
        }
        onExited: (code, status) => { runner.code = code; runner.done(); }
    }
}
