# Technical reference

The daemon's behaviour, the JSON interface for widgets, the wire format and the full command
table. For install and usage, see [the README](../README.md).

## Layout

| file | what |
|---|---|
| `earfun/protocol.py` | frame encode/decode, `FrameSplitter` (concatenated + partial frames), the setting table with provenance |
| `earfun/fake.py` | `FakeBuds`: socketpair simulator (no reply to the mode set, ~1.5 s delayed apply, unsolicited 0358/0350/034D, optional chunked writes) |
| `earfun/daemon.py` | `Core` (selectors loop, JSON-lines server, polling, pending sets, Fast Pair battery, case memory), `FakeLink`, `BluezLink` (Profile1 + ConnectProfile in a GLib thread) |
| `earfun/connect.py` | `pick_buds` (which device), `Connector` (when to call `ConnectProfile`: A2DP first, heal lock, backoff), shared by both links |
| `earfun/heal.py`, `bin/earfun-audio-heal` | the audio heal service |
| `earfun/client.py`, `earfun/cli.py`, `bin/earfun` | client and CLI |
| `probe.py` | standalone read-only probe: sends GETs and prints the raw frames |
| `modetest.py` | standalone mode test: changes the noise mode and reads it back |
| `widget/quickshell/` | the bar module and popup |

## How the daemon behaves

* **Single owner.** Only one client can hold the SPP channel, so only the daemon
  opens it; the CLI and the widget talk to the daemon. A second daemon on the
  same socket refuses to start. Stop other users of the channel (e.g. the
  omarchy-headphones bridge) first.
* **Connect.** Registers an `org.bluez.Profile1` client for SPP
  `00001101-0000-1000-8000-00805f9b34fb`, finds the first paired device whose
  name contains "EarFun" and offers SPP (or `--address`), watches
  `PropertiesChanged.Connected`, and calls `Device1.ConnectProfile` ≥1.5 s after
  the buds connect — but only once A2DP is up (a `MediaTransport1` for the buds
  exists) or 6 s have passed, never while `earfun-audio-heal` holds its lock, and
  one call at a time. LIVE: an SPP `ConnectProfile` right after a
  reconnect (`br-connection-busy`) knocked the buds off again. Failures back off
  3 / 6 / 12 / 24 s, then every 30 s. Channel lost while the buds stay
  connected: reopened after 3 s. Buds disconnected: channel closed, state
  cleared (firmware and the last case level kept). bluetoothd restart: profiles
  re-registered.
* **Fast Pair stream.** A second read-only Profile1 client on the Google Fast
  Pair Message Stream (`df21fe2c-2515-4fdb-8886-f12c4d67927c`), opened 2 s after
  SPP when the buds list that UUID (they do with `advanced_audio` = `fast_pair`).
  The buds push battery there on open and on every change (group 3 code 3: one
  byte per L/R/case, high bit = charging, `0x7F` = no reading). A bud's GAIA
  value wins; Fast Pair fills the gaps. The case level is second-hand (the buds
  only learn it when a bud docks), so it can be old.
* **Case memory.** The last real case level and when it was seen are kept in
  `$XDG_STATE_HOME/earfun/state.json` (`--state`, `$EARFUN_STATE`; none under
  `--fake`) and survive restarts.
* **Reads.** On open: every GET Gadgetbridge sends for the Air Pro 4, plus the
  verified ones. Every 10 s: battery L/R/case + mode. Frames are spaced 80 ms.
  No frame at all for 8 s after opening, or none for 45 s, reopens the channel.
* **Sets.** The mode set (`0314`) gets no reply; the daemon re-reads the mode
  every 1 s, up to 6 times, until the buds report the new value. Meanwhile
  `pending_mode` holds the target. Same for every set that has a GET.
  Write-only keys (`eq`, `device_name`) keep the last value sent.
* **Safety gate.** Against the real buds the daemon only sends SETs verified
  live (today: `mode`, `audio_codec`, `advanced_audio`). Every other SET is refused (`"refused": true`) unless the
  daemon runs with `--allow-unverified-sets`. `--fake` allows everything.
  `find_device` plays a loud sound in the buds.

## JSON interface

This is the contract for the Quickshell widget. Extra keys may be added later;
the ones below will not be renamed.

### `earfun watch`

Prints one JSON object per line: the full state immediately on connect, then
again on every change (no line when a poll changes nothing). If the daemon is
not running it prints `{"daemon":false}` (once per outage), retries every 3 s
by itself, and never exits.

### State object

```json
{
  "daemon": true,
  "connected": true,
  "name": "EarFun Air Pro 4",
  "mode": "off",
  "pending_mode": null,
  "battery": {"left": 100, "right": 100, "case": null, "case_last": 85, "case_seen": 1700000000,
              "charging": {"left": false, "right": false, "case": null}},
  "anc_style": "strong",
  "transparency_style": "default",
  "firmware": "TW600-3091_20250919_v0.4.1",
  "settings": {
    "mode":      {"value": "off", "options": ["off", "anc", "ambient"], "type": "enum", "live_verified": true},
    "game_mode": {"value": false, "options": null, "type": "bool", "live_verified": false},
    "voice_prompt_volume": {"value": 3, "options": null, "type": "int", "min": 0, "max": 4, "live_verified": false},
    "eq":        {"value": null, "options": ["default", "natural", "..."], "type": "eq", "live_verified": false}
  },
  "source": "live",
  "device_connected": true,
  "channel": "connected",
  "address": "XX:XX:XX:XX:XX:XX",
  "playing": false,
  "error": null
}
```

| field | meaning |
|---|---|
| `daemon` | `true` from the daemon; the CLI prints `{"daemon":false}` when it is not running |
| `connected` | the SPP channel is open and talking (settings can be read/changed) |
| `name` | BlueZ alias of the buds (`"... (fake)"` under `--fake`) |
| `mode` | `"off"` \| `"anc"` \| `"ambient"` \| `null` (unknown / not connected) |
| `pending_mode` | target of a mode set the buds have not reported yet, else `null` |
| `battery.left/right/case` | percent, or `null` when unknown or the part reports `0xFF` (e.g. case lid shut / bud in case); GAIA reading, else the Fast Pair one |
| `battery.case_last` | last real case percent ever seen (kept across disconnects and daemon restarts), or `null` |
| `battery.case_seen` | epoch seconds when `case_last` was last seen (moves on a change, when the case stops reporting, else at most every 5 min), or `null` |
| `battery.charging.left/right/case` | charging bit from the Fast Pair stream, `null` when unknown / no stream |
| `anc_style`, `transparency_style`, `firmware` | as in `settings`, lifted for convenience |
| `settings.<key>` | every key in the table below: `value` (null = unknown), `options` (list for enum/action/eq presets, else `null`), `type`, `live_verified` (every direction the key supports was measured on the real buds), plus `settable`, `readable`, `verified_get`, `verified_set`, `kind`, `min`/`max` for ints, and `pending` while a set is unconfirmed |
| `source` | `"live"` or `"fake"` |
| `device_connected` | BlueZ says the buds are connected (the channel may still be opening) |
| `channel` | `"disconnected"` \| `"connecting"` \| `"connected"` |
| `playing` | from the buds' unsolicited `0350` frame (`true`/`false`/`null`) |
| `error` | last connection problem, cleared when the channel opens |

`type` is `enum`, `bool`, `int`, `eq` for settable keys, and `percent`, `text`,
`version`, `raw`, `action` for the rest. `bool` values are JSON booleans; a
set accepts `on|off|true|false|1|0`. `eq` values are
`{"preset": name|null, "gains": [10 ints -10..10]}`; a set accepts a preset name
or ten integers (`"3,2,0,0,0,0,0,0,0,0"`).

### Socket protocol

`$XDG_RUNTIME_DIR/earfun.sock`, mode 0600, one JSON object per line each way.
An optional `"id"` is echoed in the reply.

| request | reply |
|---|---|
| `{"cmd":"status"}` | `{"ok":true,"state":{...}}` |
| `{"cmd":"watch"}` | the state object, then one per change (no `ok` wrapper) |
| `{"cmd":"get","key":"anc_style"}` | re-reads from the buds: `{"ok":true,"key":..,"value":..}`; `"cached":true` when it could not (write-only key, not connected, 3 s timeout, or `"refresh":false`) |
| `{"cmd":"set","key":"mode","value":"anc"}` | `{"ok":true,"key":"mode","value":"anc","pending":true}` at once |
| `{"cmd":"set",...,"wait":true}` | after read-back: `{"ok":true,...,"confirmed":true}`, or `"confirmed":false,"reported":<value>` after ~6 s, or `"superseded":true` |
| `{"cmd":"keys"}` | `{"ok":true,"keys":[{key,title,kind,values,get,set,settable,verified_get,verified_set,source,note}]}` |
| `{"cmd":"ping"}` | `{"ok":true,"source":"live"}` |
| errors | `{"ok":false,"error":"..."}`, plus `"refused":true` from the safety gate |

`mode` also takes `"cycle"`: off -> anc -> ambient -> off, from the pending
target if there is one.

## Wire format

```
FF <ver> <flags> <len u8> <vendor u16 BE> <cmd u16 BE> <payload>      no checksum
host -> buds  ver 04, flags 00, vendor 000A (EQ: 001D)
buds -> host  ver 03, cmd | 0x8000 for answers, payload <status> <value...>
```

```
->  ff 04 00 00 00 0a 03 15              get mode
<-  ff 03 00 02 00 0a 83 15 00 01        status 00, anc
->  ff 04 00 01 00 0a 03 14 02           set ambient (no reply; reads back ~1-2.5 s later)
<-  ff 03 00 05 00 0a 03 58 00 5c 3b 4d 01   unsolicited, no ack bit
```

## Command table

`live` = measured on real buds (firmware `TW600-3091_20250919_v0.4.1`).
Everything else is ported from Gadgetbridge (https://codeberg.org/Freeyourgadget/Gadgetbridge,
commit `edbea98`, `app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/earfun/`,
abbreviated `GB/`) and has **not** been sent to the real buds as a SET.
"COMMENT" = only a comment in `GB/EarFunPacket.java` documents it; Gadgetbridge
never sends it. `bin/earfun keys` prints the same table from the code.

| key | kind | GET | SET | values | live | source |
|---|---|---|---|---|---|---|
| `mode` | setting | 0315 | 0314 | off \| anc \| ambient | get+set | LIVE; GB/EarFunPacket.java SET/REQUEST_RESPONSE_AMBIENT_SOUND, GB/res/values/arrays.xml earfun_ambient_sound_control_values; SET has no reply; the new value reads back ~1-2.5 s later |
| `anc_style` | setting | 033B | 033A | strong \| balanced \| ai_environment_adaptive \| ai_ear_adaptive \| wind | get | GB/EarFunPacket.java SET/REQUEST_RESPONSE_ANC_MODE, GB/res/values/arrays.xml earfun_anc_mode_values |
| `transparency_style` | setting | 033D | 033C | default \| natural | get | GB/EarFunPacket.java SET/REQUEST_RESPONSE_TRANSPARENCY_MODE, GB/res/values/arrays.xml earfun_transparency_mode_values |
| `game_mode` | setting | 0313 | 0312 | on \| off | - | GB/EarFunResponseHandler.java handleGameModeInfo, GB/EarFunProtocol.java PREF_EARFUN_GAME_MODE |
| `battery_left` | readonly | 0306 | - | 0..100 or null | get | LIVE; GB/EarFunResponseHandler.java handleBatteryInfo |
| `battery_right` | readonly | 0307 | - | 0..100 or null | get | LIVE; GB/EarFunResponseHandler.java handleBatteryInfo |
| `battery_case` | readonly | 0317 | - | 0..100 or null | get | LIVE; GB/EarFunResponseHandler.java handleBatteryInfo; 0xFF (null) when the case cannot report |
| `firmware` | readonly | 0309 | - | text | get | LIVE; GB/EarFunResponseHandler.java handleFirmwareVersionInfo |
| `gaia_api` | readonly | 0300 | - | version | get | LIVE; GB/EarFunPacket.java comment '03 03 01 = GAIA v3, API v3.1' |
| `app_version` | readonly | 0304 | - | version | - | COMMENT GB/EarFunPacket.java '02 00 = APP v2.0' |
| `device_color` | readonly | 0318 | - | black | - | COMMENT GB/EarFunPacket.java '00 = black' |
| `phone_call_state` | readonly | 0337 | - | raw | - | COMMENT GB/EarFunPacket.java (no encoding documented; raw hex) |
| `connected_devices` | readonly | 032C | - | raw | - | COMMENT GB/EarFunPacket.java 'names of paired devices + something else' (raw hex) |
| `touch` | setting | 0335 | 0334 | both \| none \| right \| left | - | GB/EarFunResponseHandler.java handleTouchModeInfo + GB/EarFunPacket.java comment '00 both, 01 none, 02 right, 03 left'; GB UI only uses both/none |
| `in_ear_detection` | setting | 034A | 0349 | on \| off | - | GB/EarFunResponseHandler.java handleInEarDetectionModeInfo (wire byte 00 = enabled) |
| `audio_codec` | setting | 032F | 032E | stable \| aptx \| aptx_adaptive \| aptx_lossless \| ldac | get+set | LIVE (aptx_lossless -> ldac, read back ldac); GB/EarFunPacket.java SET/REQUEST_RESPONSE_AUDIO_CODEC, GB/res/values/arrays.xml earfun_audio_codec_values |
| `advanced_audio` | setting | 034C | 034B | fast_pair \| le_audio | get+set | LIVE (le_audio -> fast_pair, read back fast_pair); GB/EarFunResponseHandler.java handleAdvancedAudioModeInfo, GB/res/values/arrays.xml earfun_advanced_audio_mode_values |
| `dual_connection` | setting | 0326 | 0327 | on \| off | - | GB/EarFunProtocol.java PREF_EARFUN_CONNECT_TWO_DEVICES_MODE (SET then REBOOT); the buds reboot after this set |
| `mic_mode` | setting | 0331 | 0330 | auto \| left \| right | - | GB/EarFunPacket.java SET/REQUEST_RESPONSE_MICROPHONE_MODE, GB/res/values/arrays.xml earfun_microphone_mode_values |
| `voice_prompt_volume` | setting | 0339 | 0338 | 0..4 | - | GB/EarFunResponseHandler.java handleVoicePromptVolumeInfo (wire 00 = max, 04 = min/off; user 4 = loudest) |
| `voice_protect` | setting | 0354 | 0353 | 90db \| 80db \| 70db \| 60db \| 50db | - | COMMENT GB/EarFunPacket.java SET_VOICE_PROTECT '01 = 90 dB ... 05 = 50 dB'; not in GB's Air Pro 4 UI; may be unsupported |
| `balance` | setting | 0356 | 0355 | 0..100 | - | COMMENT GB/EarFunPacket.java SET_LEFTRIGHT_BALANCE '50 = default, 0 = left only, 100 = right only'; not in GB's Air Pro 4 UI; may be unsupported |
| `find_device` | setting | 0333 | 0332 | off \| left \| right \| both | - | GB/EarFunResponseHandler.java handleFindDeviceInfo, GB/res/values/arrays.xml earfun_find_device_values; plays a LOUD sound; never send while worn |
| `eq` | setting | - | - | preset (default \| natural \| bass_boost \| treble_boost \| soft \| dynamic \| clear \| relaxed \| vocal) or 10 ints -10..10 | - | GB/EarFunPacketEncoder.java encodeSetEqualizerBand + GB/prefs/Equalizer.java TenBandEqualizer/TenBandPreset; write-only (GB never reads 0E02); state shows the last value set via this daemon |
| `device_name` | setting | - | 0316 | text | - | GB/EarFunProtocol.java PREF_EARFUN_DEVICE_NAME (UTF-8); write-only; applies after case close + re-pair (GB strings.xml); 32-byte cap is ours |
| `reboot` | action | - | 0308 | now | - | GB/EarFunPacket.java COMMAND_REBOOT, used by GB/EarFunProtocol.java |
| `factory_reset` | action | - | 0305 | now | - | COMMENT GB/EarFunPacket.java FACTORY_RESET (no payload documented) |
| `trigger_pairing` | action | - | 032B | now | - | COMMENT GB/EarFunPacket.java TRIGGER_PAIRING (no payload documented) |
| `connect_device` | action | - | 0329 | first \| second | - | COMMENT GB/EarFunPacket.java CONNECT_DEVICE '00 = first, 01 = second' |
| `disconnect_device` | action | - | 032A | first \| second | - | COMMENT GB/EarFunPacket.java DISCONNECT_DEVICE '00 = first, 01 = second' |
| `power_off` | action | - | 0351 | now | - | COMMENT GB/EarFunPacket.java SET_CONTROL_PLAY '01 = turn off device' |
| `playing` | event | - | - | on \| off | get | LIVE unsolicited 0350 00 01; COMMENT GB/EarFunPacket.java '01: not playing, 02: playing' |
| `audio_mode_raw` | event | - | - | 0..255 | get | LIVE unsolicited 034D 00 03; COMMENT GB/EarFunPacket.java meaning unclear |
| `phone_list_raw` | event | - | - | raw | get | LIVE unsolicited 0358 (two frames: 00 5c3b4d01 / 00 334ee500); undecoded |
| `gesture_<single\|double\|triple\|long>_<left\|right>` | setting | 030B | 030A | none, volume_up, volume_down, next, previous, play_pause, game_mode, voice_assistant, noise_control_all, noise_control_normal_wind, noise_control_normal_ambient, noise_control_wind_ambient, redial | - | GB/EarFunPacketEncoder.java encodeSetGesture + GB/EarFunResponseHandler.java handleTouchActionInfo + GB/res/values/arrays.xml earfun_air_pro_4_tap_action_values |

### Encodings worth knowing

* **Gestures.** GET `030B` answers `<status>` + eight u16 in the order single
  L, single R, double L, double R, triple L, triple R, long L, long R; only the
  low byte is the action. SET `030A` payload is `<type> <action> 00 00` for the
  left bud, `00 00 <type> <action>` for the right; type `01` single, `02`
  double, `03` triple, `11` long. Action ids: none 16, play/pause 1, vol+ 2,
  vol- 3, previous 4, next 5, voice assistant 6, game mode 7, noise control
  (all) 8, (normal+wind) 9, (normal+ambient) 10, (wind+ambient) 11, redial 13.
  LIVE (fw v0.4.1): the answer carries **32** value bytes, as (type, action)
  pairs: `01 01 01 01 02 05 02 05 03 10 03 10 11 09 11 09` then
  `04 00 04 00 05 00 05 00 06 06 06 06 13 04 13 04`. The first 16 decode as
  Gadgetbridge expects; the last 16 (types 04/05/06/13, unknown to Gadgetbridge)
  are exposed raw as `gesture_extra_raw`.
* **Missing ack bit.** LIVE: the answer to GET `0333` (find device) comes back
  as `ff 03 00 02 00 0a 03 33 00 00`, without the `0x8000` bit. The daemon
  matches answers by command, ack bit or not.
* **Equaliser.** Ten SETs `0E01` on vendor `001D`, one per band, payload
  `<band A1..AA> FF 98 <freq u16> <gain i16> <q u16>`; gain = slider x 36
  (slider -10..10 = +-6 dB). Bands 31.5, 63, 125, 250, 500, 1k, 2k, 4k, 8k, 16k Hz,
  q `0B33`. The buds answer each with `0F81 01` (per Gadgetbridge). Presets from
  `GB/prefs/Equalizer.java` TenBandPreset.
* **Inverted bytes.** `in_ear_detection`: wire `00` = enabled (the command is
  "disable in-ear detection"). `touch`: wire `00` = both enabled.
  `voice_prompt_volume`: wire `00` = loudest, `04` = quietest/off; exposed as
  0..4 with 4 = loudest (as Gadgetbridge does).
* **Dual connection.** Gadgetbridge sends the SET and then REBOOT `0308`; so do we.
* **Battery.** `0xFF` = that part cannot report (case seen live); exposed as `null`.

### In Gadgetbridge but not exposed as settings

GAIA v3 vendor-`001D` commands (`0001` supported features, `0007` register
notification, `000D` transport parameter and their answers `0101`/`0107`/
`0187`/`018D`), the earbud notification `0282`, the audio-curation notifications
`1080`-`1085`, and `0E02` equaliser config (defined, never decoded by
Gadgetbridge). They are named in `protocol.COMMAND_NAMES` so the splitter and
logs recognise them; nothing sends them.
