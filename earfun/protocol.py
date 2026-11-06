"""EarFun Air Pro 4 protocol: GAIA-shaped frames on plain SPP.

Pure Python, stdlib only, no I/O. Everything the daemon, the fake buds and the
tests need to build and read frames, plus the table of every setting.

Frame layout (no checksum, ever):

    FF <version> <flags> <len u8> <vendor u16 BE> <command u16 BE> <payload>

Host -> buds: version 04, flags 00, vendor 000A (GAIA v3 "non-standard" 001D for
the equaliser).  Buds -> host: version 03.  An answer carries the command with
bit 0x8000 set and the payload <status> <value...>.  The buds also send frames
on their own (0358, 0350, 034D) without the ack bit; their payload has the same
<status> <value> shape in the captures.

Provenance markers used throughout:
    LIVE   = measured on real buds (fw TW600-3091_20250919_v0.4.1)
    SOURCE = ported from Gadgetbridge (AGPL-3.0, see THIRD_PARTY.md), commit edbea98, files under
             app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/earfun/
             (abbreviated below as GB/<file>) and app/src/main/res (GB/res/...).
    COMMENT = only a comment in GB/EarFunPacket.java documents it; GB never sends it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
# Google Fast Pair Message Stream (RFCOMM).  LIVE: listed in SDP once advanced_audio =
# fast_pair; the buds push model id / BLE address / battery unprompted when it opens.
FP_UUID = "df21fe2c-2515-4fdb-8886-f12c4d67927c"

SOP = 0xFF
HEADER = 8
VERSION_TX = 0x04
VERSIONS_RX = (0x03, 0x04)          # GB/EarFunPacket.java SUPPORTED_VERSIONS
FLAGS = 0x00
VENDOR = 0x000A                     # GB/EarFunPacket.java VENDOR_ID_V1_V2
VENDOR_V3 = 0x001D                  # GB/EarFunPacket.java VENDOR_ID_V3
VENDORS = (VENDOR, VENDOR_V3)
ACK = 0x8000
CMD_MASK = 0x7FFF

UNAVAILABLE = 0xFF                  # battery byte when that part cannot report (LIVE: case, bud in case)

LIVE, SOURCE, COMMENT = "live", "source", "comment"


# --------------------------------------------------------------------------- frames

@dataclass(frozen=True)
class Frame:
    version: int
    vendor: int
    command: int
    payload: bytes = b""
    flags: int = FLAGS

    @property
    def ack(self) -> bool:
        return bool(self.command & ACK)

    @property
    def base(self) -> int:
        """Command without the ack bit."""
        return self.command & CMD_MASK

    @property
    def status(self) -> int | None:
        return self.payload[0] if self.payload else None

    @property
    def value(self) -> bytes:
        """Payload after the status byte (buds -> host frames)."""
        return self.payload[1:]

    def encode(self) -> bytes:
        return encode(self.command, self.payload, self.vendor, self.version)

    def name(self) -> str:
        return COMMAND_NAMES.get((self.vendor, self.base), "unknown")

    def __str__(self) -> str:
        return "%s(%04X%s %s)" % (self.name(), self.base, " ack" if self.ack else "",
                                  self.payload.hex(" ") or "-")


def encode(command: int, payload: bytes = b"", vendor: int = VENDOR,
           version: int = VERSION_TX) -> bytes:
    payload = bytes(payload)
    if len(payload) > 0xFF:
        raise ValueError("payload too long (%d > 255)" % len(payload))
    return (bytes([SOP, version, FLAGS, len(payload)])
            + vendor.to_bytes(2, "big") + command.to_bytes(2, "big") + payload)


def encode_get(command: int, vendor: int = VENDOR) -> bytes:
    return encode(command, b"", vendor)


def decode(data: bytes) -> Frame:
    """Decode exactly one whole frame; raises ValueError otherwise."""
    frames = FrameSplitter().feed(data)
    if len(frames) != 1 or HEADER + len(frames[0].payload) != len(data):
        raise ValueError("not exactly one frame: %s" % bytes(data).hex(" "))
    return frames[0]


class FrameSplitter:
    """Turns a byte stream into frames: handles several frames in one read and a
    frame split over several reads.  A start byte not followed by a known
    version/flags/vendor is skipped one byte at a time, so garbage cannot stall
    the stream (the length is one byte, so no length is absurd)."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.dropped = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buf += data
        out: list[Frame] = []
        b = self.buf
        while True:
            start = b.find(SOP)
            if start < 0:
                self.dropped += len(b)
                b.clear()
                break
            if start:
                self.dropped += start
                del b[:start]
            if ((len(b) >= 2 and b[1] not in VERSIONS_RX)
                    or (len(b) >= 3 and b[2] != FLAGS)
                    or (len(b) >= 6 and int.from_bytes(b[4:6], "big") not in VENDORS)):
                self.dropped += 1
                del b[:1]
                continue
            if len(b) < HEADER or len(b) < HEADER + b[3]:
                break                      # partial frame: wait for more bytes
            n = HEADER + b[3]
            out.append(Frame(b[1], int.from_bytes(b[4:6], "big"),
                             int.from_bytes(b[6:8], "big"), bytes(b[HEADER:n]), b[2]))
            del b[:n]
        return out


# --------------------------------------------------------------------------- command ids
# Every id of GB/EarFunPacket.java enum Command, (vendor, id) -> name.

C = {
    "gaia_api_version": 0x0300, "application_version": 0x0304, "factory_reset": 0x0305,
    "battery_left": 0x0306, "battery_right": 0x0307, "reboot": 0x0308,
    "firmware_version": 0x0309, "set_touch_action": 0x030A, "touch_action": 0x030B,
    "set_game_mode": 0x0312, "game_mode": 0x0313, "set_ambient_sound": 0x0314,
    "ambient_sound": 0x0315, "set_device_name": 0x0316, "battery_case": 0x0317,
    "device_color": 0x0318, "connect_two_devices": 0x0326, "set_connect_two_devices": 0x0327,
    "connect_device": 0x0329, "disconnect_device": 0x032A, "trigger_pairing": 0x032B,
    "connected_devices": 0x032C, "set_audio_codec": 0x032E, "audio_codec": 0x032F,
    "set_microphone_mode": 0x0330, "microphone_mode": 0x0331, "set_find_device": 0x0332,
    "find_device": 0x0333, "set_touch_mode": 0x0334, "touch_mode": 0x0335,
    "phone_call_state": 0x0337, "set_voice_prompt_volume": 0x0338,
    "voice_prompt_volume": 0x0339, "set_anc_mode": 0x033A, "anc_mode": 0x033B,
    "set_transparency_mode": 0x033C, "transparency_mode": 0x033D,
    "set_disable_in_ear_detection": 0x0349, "disable_in_ear_detection": 0x034A,
    "set_advanced_audio_mode": 0x034B, "advanced_audio_mode": 0x034C, "audio_mode": 0x034D,
    "play_state": 0x0350, "control_play": 0x0351, "set_voice_protect": 0x0353,
    "voice_protect": 0x0354, "set_leftright_balance": 0x0355, "leftright_balance": 0x0356,
    "play_phone_list": 0x0358,
}
C_V3 = {
    "basic_get_supported_features": 0x0001, "basic_register_notification": 0x0007,
    "basic_set_transport_parameter": 0x000D, "basic_response_get_supported_features": 0x0101,
    "basic_response_register_notification": 0x0107, "basic_error_register_notification": 0x0187,
    "basic_error_set_transport_parameter": 0x018D, "earbud_notification_unknown": 0x0282,
    "ac_notification_state_change": 0x1080, "ac_notification_mode_change": 0x1081,
    "ac_notification_gain_change": 0x1082, "ac_notification_toggle_config": 0x1083,
    "ac_notification_scenario_config": 0x1084, "ac_notification_demo_state": 0x1085,
    "set_equalizer_band": 0x0E01, "equalizer_config": 0x0E02, "response_equalizer_band": 0x0F81,
}
COMMAND_NAMES = {(VENDOR, v): k for k, v in C.items()}
COMMAND_NAMES.update({(VENDOR_V3, v): k for k, v in C_V3.items()})


# --------------------------------------------------------------------------- codecs

class Codec:
    """value bytes (after status) <-> JSON value; parse() takes CLI/JSON input."""
    kind = "raw"

    def decode(self, value: bytes):
        return value.hex()

    def encode(self, v) -> bytes:
        raise ValueError("not settable")

    def parse(self, s):
        return s

    def describe(self) -> str:
        return self.kind


class Enum(Codec):
    kind = "enum"

    def __init__(self, names: dict[int, str]):
        self.names = names
        self.values = {v: k for k, v in names.items()}

    def decode(self, value):
        if not value:
            return None
        return self.names.get(value[0], "unknown_%d" % value[0])

    def parse(self, s):
        s = str(s).strip().lower().replace("-", "_")
        if s not in self.values:
            raise ValueError("expected one of: %s" % ", ".join(self.values))
        return s

    def encode(self, v):
        return bytes([self.values[self.parse(v)]])

    def describe(self):
        return "|".join(self.values)


class Bool(Codec):
    """true_byte is the byte meaning True (GB inverts some, e.g. 'disable in-ear')."""
    kind = "bool"
    TRUE = ("1", "on", "true", "yes", "enable", "enabled")
    FALSE = ("0", "off", "false", "no", "disable", "disabled")

    def __init__(self, true_byte: int = 1):
        self.t = true_byte

    def decode(self, value):
        return None if not value else value[0] == self.t

    def parse(self, s):
        if isinstance(s, bool):
            return s
        s = str(s).strip().lower()
        if s in self.TRUE:
            return True
        if s in self.FALSE:
            return False
        raise ValueError("expected on|off")

    def encode(self, v):
        return bytes([self.t if self.parse(v) else (1 - self.t)])

    def describe(self):
        return "on|off"


class Int(Codec):
    """User integer lo..hi; to_byte/from_byte convert to the wire byte."""
    kind = "int"

    def __init__(self, lo, hi, to_byte=lambda v: v, from_byte=lambda b: b):
        self.lo, self.hi, self.to_byte, self.from_byte = lo, hi, to_byte, from_byte

    def decode(self, value):
        return None if not value else self.from_byte(value[0])

    def parse(self, s):
        try:
            v = int(s)
        except (TypeError, ValueError):
            raise ValueError("expected an integer %d..%d" % (self.lo, self.hi)) from None
        if not self.lo <= v <= self.hi:
            raise ValueError("expected an integer %d..%d" % (self.lo, self.hi))
        return v

    def encode(self, v):
        return bytes([self.to_byte(self.parse(v)) & 0xFF])

    def describe(self):
        return "%d..%d" % (self.lo, self.hi)


class Battery(Codec):
    kind = "percent"

    def decode(self, value):
        # LIVE: 0xFF = that part cannot report (e.g. case while a bud sits in it).
        # GB/EarFunResponseHandler.java handleBatteryInfo treats <=0 (signed) as unknown.
        if not value or value[0] == UNAVAILABLE or value[0] > 100:
            return None
        return value[0]

    def describe(self):
        return "0..100 or null"


class Text(Codec):
    kind = "text"

    def __init__(self, max_bytes=32):
        self.max = max_bytes

    def decode(self, value):
        return value.decode("utf-8", "replace")

    def parse(self, s):
        s = str(s)
        if not s or len(s.encode()) > self.max:
            raise ValueError("expected 1..%d UTF-8 bytes" % self.max)
        return s

    def encode(self, v):
        return self.parse(v).encode("utf-8")


class Version(Codec):
    """0300 GAIA API: 03 03 01 -> '3.3.1' (GB: 'GAIA v3, API v3.1'); 0304 app: 02 00 -> '2.0'."""
    kind = "version"

    def decode(self, value):
        return ".".join(str(b) for b in value) or None


class Action(Codec):
    """Fire-and-forget command with a fixed or enumerated payload."""
    kind = "action"

    def __init__(self, names: dict[str, bytes] | None = None):
        self.names = names or {"now": b""}

    def parse(self, s):
        s = str(s).strip().lower()
        if s not in self.names:
            raise ValueError("expected one of: %s" % ", ".join(self.names))
        return s

    def encode(self, v):
        return self.names[self.parse(v)]

    def describe(self):
        return "|".join(self.names)


# --------------------------------------------------------------------------- equaliser
# GB/prefs/Equalizer.java TenBandEqualizer + GB/EarFunPacketEncoder.java encodeSetEqualizerBand.
# Air Pro 4 uses the ten-band table (GB/airpro4/EarFunAirPro4Protocol.java).

EQ_BANDS = [  # (band id, frequency Hz as sent, q factor)
    (0xA1, 0x005E, 0x0B33), (0xA2, 0x00BD, 0x0B33), (0xA3, 0x0177, 0x0B33),
    (0xA4, 0x02EE, 0x0B33), (0xA5, 0x05DC, 0x0B33), (0xA6, 0x0BB8, 0x0B33),
    (0xA7, 0x1770, 0x0B33), (0xA8, 0x2EE0, 0x0B33), (0xA9, 0x5DC0, 0x0B33),
    (0xAA, 0xBB80, 0x0B33),
]
EQ_LABELS = ["31.5", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
EQ_GAIN_FACTOR = 60 * 0.6           # GB: slider -10..10 spans +-6 dB, GAIA 60 units/dB
EQ_PRESETS = {                       # GB/prefs/Equalizer.java TenBandPreset
    "default": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "natural": [0, 0, 1, 2, 2, -1, -1, -1, -2, 1],
    "bass_boost": [8, 6, 4, 2, 0, 0, 0, 0, 0, 0],
    "treble_boost": [0, 0, 0, 0, 0, 0, 2, 2, 3, 4],
    "soft": [-5, -4, -2, 0, 2, 3, 0, -2, -3, -5],
    "dynamic": [6, 6, 4, 2, 2, 3, 4, 5, 6, 7],
    "clear": [3, 2, 2, 2, 3, 5, 3, 3, 4, 5],
    "relaxed": [2, 1, 0, 0, 0, -1, -2, -3, -4, -5],
    "vocal": [-3, -2, 0, 2, 3, 5, 3, 2, 0, -1],
}


def eq_band_payload(band: int, gain: int) -> bytes:
    bid, freq, q = EQ_BANDS[band]
    g = int(round(gain * EQ_GAIN_FACTOR)) & 0xFFFF
    return (bytes([bid, 0xFF, 0x98]) + freq.to_bytes(2, "big") + g.to_bytes(2, "big")
            + q.to_bytes(2, "big"))


class Equalizer(Codec):
    """Value: a preset name or ten integers -10..10 (slider units of 0.6 dB)."""
    kind = "eq"

    def parse(self, s):
        if isinstance(s, dict):
            s = s.get("gains")
        if isinstance(s, (list, tuple)):
            gains = list(s)
        else:
            t = str(s).strip().lower()
            if t.replace("-", "_") in EQ_PRESETS:
                t = t.replace("-", "_")
                return {"preset": t, "gains": EQ_PRESETS[t]}
            gains = [x for x in t.replace(",", " ").split()]
        try:
            gains = [int(g) for g in gains]
        except ValueError:
            raise ValueError("expected a preset (%s) or 10 integers -10..10"
                             % ", ".join(EQ_PRESETS)) from None
        if len(gains) != 10 or any(not -10 <= g <= 10 for g in gains):
            raise ValueError("expected 10 integers -10..10")
        preset = next((k for k, v in EQ_PRESETS.items() if v == gains), None)
        return {"preset": preset, "gains": gains}

    def frames(self, v) -> list[bytes]:
        gains = self.parse(v)["gains"]
        return [encode(C_V3["set_equalizer_band"], eq_band_payload(i, g), VENDOR_V3)
                for i, g in enumerate(gains)]

    def describe(self):
        return "preset (%s) or 10 ints -10..10" % "|".join(EQ_PRESETS)


# --------------------------------------------------------------------------- gestures
# GB/prefs/Interactions.java + GB/EarFunPacketEncoder.java encodeSetGesture
# + GB/EarFunResponseHandler.java handleTouchActionInfo + GB/res/values/arrays.xml
# earfun_air_pro_4_tap_action_{names,values}.

GESTURE_TYPES = {"single": 0x01, "double": 0x02, "triple": 0x03, "long": 0x11}
GESTURE_ORDER = [  # order of the eight u16 in the 830B answer
    ("single", "left"), ("single", "right"), ("double", "left"), ("double", "right"),
    ("triple", "left"), ("triple", "right"), ("long", "left"), ("long", "right"),
]
GESTURE_ACTIONS = Enum({
    16: "none", 2: "volume_up", 3: "volume_down", 5: "next", 4: "previous",
    1: "play_pause", 7: "game_mode", 6: "voice_assistant", 8: "noise_control_all",
    9: "noise_control_normal_wind", 10: "noise_control_normal_ambient",
    11: "noise_control_wind_ambient", 13: "redial",
})


def decode_touch_actions(value: bytes) -> dict:
    """LIVE (fw v0.4.1): the answer carries 32 bytes, (type, action) pairs:
    01 01 01 01 02 05 02 05 03 10 03 10 11 09 11 09 | 04 00 04 00 05 00 05 00 06 06 06 06 13 04 13 04.
    The first 16 match GB's eight u16 (high byte = gesture type 01/02/03/11); the
    last 16 carry types 04/05/06/13 that GB does not know -> gesture_extra_raw."""
    out = {}
    if len(value) > 16:
        out["gesture_extra_raw"] = value[16:].hex()
    for i, (t, side) in enumerate(GESTURE_ORDER):
        chunk = value[2 * i:2 * i + 2]
        if len(chunk) == 2:
            out["gesture_%s_%s" % (t, side)] = GESTURE_ACTIONS.decode(chunk[1:])  # low byte only
    return out


def gesture_payload(gtype: str, side: str, action) -> bytes:
    a = GESTURE_ACTIONS.encode(action)[0]
    t = GESTURE_TYPES[gtype]
    return bytes([t, a, 0, 0]) if side == "left" else bytes([0, 0, t, a])


# --------------------------------------------------------------------------- setting table

@dataclass
class Setting:
    key: str
    title: str
    codec: Codec
    get: int | None = None            # GET command (vendor 000A); answer = get | 0x8000
    set: int | None = None            # SET command
    vendor: int = VENDOR
    kind: str = "setting"             # setting | readonly | action | event
    verified_get: bool = False        # LIVE-verified read on real buds
    verified_set: bool = False        # LIVE-verified write on real buds
    source: str = ""                  # where the encoding comes from
    on_connect: bool = False          # read when the channel opens
    poll: bool = False                # re-read every poll interval
    frames_for: Callable | None = None  # custom SET encoder: value -> list[bytes]
    note: str = ""
    extra: dict = field(default_factory=dict)

    def set_frames(self, value) -> list[bytes]:
        if self.frames_for:
            return self.frames_for(value)
        if self.set is None:
            raise ValueError("%s is read-only" % self.key)
        return [encode(self.set, self.codec.encode(value), self.vendor)]

    @property
    def settable(self) -> bool:
        return self.set is not None or self.frames_for is not None

    def provenance(self) -> str:
        g = "live" if self.verified_get else ("source" if self.get is not None else "-")
        s = "live" if self.verified_set else ("source" if self.settable else "-")
        return "get:%s set:%s" % (g, s)

    def info(self) -> dict:
        return {"key": self.key, "title": self.title, "kind": self.kind,
                "values": self.codec.describe(),
                "get": "%04X" % self.get if self.get is not None else None,
                "set": "%04X" % self.set if self.set is not None else None,
                "settable": self.settable, "verified_get": self.verified_get,
                "verified_set": self.verified_set, "source": self.source,
                "note": self.note}


GB_PKT = "GB/EarFunPacket.java"
GB_PROTO = "GB/EarFunProtocol.java"
GB_RESP = "GB/EarFunResponseHandler.java"
GB_ENC = "GB/EarFunPacketEncoder.java"
GB_ARR = "GB/res/values/arrays.xml"

MODE = Enum({0: "off", 1: "anc", 2: "ambient"})
MODE_CYCLE = ["off", "anc", "ambient"]

_S: list[Setting] = [
    # ---- noise control
    Setting("mode", "Noise control", MODE, C["ambient_sound"], C["set_ambient_sound"],
            verified_get=True, verified_set=True, on_connect=True, poll=True,
            source="LIVE; %s SET/REQUEST_RESPONSE_AMBIENT_SOUND, %s earfun_ambient_sound_control_values" % (GB_PKT, GB_ARR),
            note="SET has no reply; the new value reads back ~1-2.5 s later"),
    Setting("anc_style", "ANC style", Enum({2: "strong", 3: "balanced", 4: "ai_environment_adaptive",
                                             0: "ai_ear_adaptive", 1: "wind"}),
            C["anc_mode"], C["set_anc_mode"], verified_get=True, on_connect=True,
            source="%s SET/REQUEST_RESPONSE_ANC_MODE, %s earfun_anc_mode_values" % (GB_PKT, GB_ARR)),
    Setting("transparency_style", "Transparency style", Enum({0: "default", 1: "natural"}),
            C["transparency_mode"], C["set_transparency_mode"], verified_get=True, on_connect=True,
            source="%s SET/REQUEST_RESPONSE_TRANSPARENCY_MODE, %s earfun_transparency_mode_values" % (GB_PKT, GB_ARR)),
    Setting("game_mode", "Game (low latency) mode", Bool(1), C["game_mode"], C["set_game_mode"],
            on_connect=True, source="%s handleGameModeInfo, %s PREF_EARFUN_GAME_MODE" % (GB_RESP, GB_PROTO)),
    # ---- battery / info (read-only)
    Setting("battery_left", "Battery left", Battery(), C["battery_left"], kind="readonly",
            verified_get=True, on_connect=True, poll=True, source="LIVE; %s handleBatteryInfo" % GB_RESP),
    Setting("battery_right", "Battery right", Battery(), C["battery_right"], kind="readonly",
            verified_get=True, on_connect=True, poll=True, source="LIVE; %s handleBatteryInfo" % GB_RESP),
    Setting("battery_case", "Battery case", Battery(), C["battery_case"], kind="readonly",
            verified_get=True, on_connect=True, poll=True, source="LIVE; %s handleBatteryInfo" % GB_RESP,
            note="0xFF (null) when the case cannot report"),
    Setting("firmware", "Firmware", Text(255), C["firmware_version"], kind="readonly",
            verified_get=True, on_connect=True, source="LIVE; %s handleFirmwareVersionInfo" % GB_RESP),
    Setting("gaia_api", "GAIA API version", Version(), C["gaia_api_version"], kind="readonly",
            verified_get=True, on_connect=True, source="LIVE; %s comment '03 03 01 = GAIA v3, API v3.1'" % GB_PKT),
    Setting("app_version", "Application version", Version(), C["application_version"], kind="readonly",
            source="COMMENT %s '02 00 = APP v2.0'" % GB_PKT),
    Setting("device_color", "Device colour", Enum({0: "black"}), C["device_color"], kind="readonly",
            source="COMMENT %s '00 = black'" % GB_PKT),
    Setting("phone_call_state", "Phone call state", Codec(), C["phone_call_state"], kind="readonly",
            source="COMMENT %s (no encoding documented; raw hex)" % GB_PKT),
    Setting("connected_devices", "Connected devices", Codec(), C["connected_devices"], kind="readonly",
            source="COMMENT %s 'names of paired devices + something else' (raw hex)" % GB_PKT),
    # ---- touch / wear
    Setting("touch", "Touch controls", Enum({0: "both", 1: "none", 2: "right", 3: "left"}),
            C["touch_mode"], C["set_touch_mode"], on_connect=True,
            source="%s handleTouchModeInfo + %s comment '00 both, 01 none, 02 right, 03 left'" % (GB_RESP, GB_PKT),
            note="GB UI only uses both/none"),
    Setting("in_ear_detection", "In-ear detection", Bool(0), C["disable_in_ear_detection"],
            C["set_disable_in_ear_detection"], on_connect=True,
            source="%s handleInEarDetectionModeInfo (wire byte 00 = enabled)" % GB_RESP),
    # ---- audio / connectivity
    Setting("audio_codec", "Audio codec", Enum({0: "stable", 1: "aptx", 3: "aptx_adaptive",
                                                19: "aptx_lossless", 8: "ldac"}),
            C["audio_codec"], C["set_audio_codec"], on_connect=True, verified_get=True, verified_set=True,
            source="LIVE (aptx_lossless -> ldac, read back ldac); "
                   "%s SET/REQUEST_RESPONSE_AUDIO_CODEC, %s earfun_audio_codec_values" % (GB_PKT, GB_ARR)),
    Setting("advanced_audio", "Advanced audio (LE Audio / Fast Pair)", Enum({0: "fast_pair", 1: "le_audio"}),
            C["advanced_audio_mode"], C["set_advanced_audio_mode"], on_connect=True,
            verified_get=True, verified_set=True,
            source="LIVE (le_audio -> fast_pair, read back fast_pair); "
                   "%s handleAdvancedAudioModeInfo, %s earfun_advanced_audio_mode_values" % (GB_RESP, GB_ARR)),
    Setting("dual_connection", "Dual device connection", Bool(1), C["connect_two_devices"],
            C["set_connect_two_devices"], on_connect=True,
            frames_for=lambda v: [encode(C["set_connect_two_devices"], Bool(1).encode(v)),
                                  encode(C["reboot"])],
            source="%s PREF_EARFUN_CONNECT_TWO_DEVICES_MODE (SET then REBOOT)" % GB_PROTO,
            note="the buds reboot after this set"),
    Setting("mic_mode", "Microphone", Enum({0: "auto", 1: "left", 2: "right"}),
            C["microphone_mode"], C["set_microphone_mode"], on_connect=True,
            source="%s SET/REQUEST_RESPONSE_MICROPHONE_MODE, %s earfun_microphone_mode_values" % (GB_PKT, GB_ARR)),
    Setting("voice_prompt_volume", "Voice prompt volume", Int(0, 4, lambda v: 4 - v, lambda b: max(0, 4 - b)),
            C["voice_prompt_volume"], C["set_voice_prompt_volume"], on_connect=True,
            source="%s handleVoicePromptVolumeInfo (wire 00 = max, 04 = min/off; user 4 = loudest)" % GB_RESP),
    Setting("voice_protect", "Hearing protection limit", Enum({1: "90db", 2: "80db", 3: "70db",
                                                               4: "60db", 5: "50db"}),
            C["voice_protect"], C["set_voice_protect"],
            source="COMMENT %s SET_VOICE_PROTECT '01 = 90 dB ... 05 = 50 dB'" % GB_PKT,
            note="not in GB's Air Pro 4 UI; may be unsupported"),
    Setting("balance", "Left/right balance", Int(0, 100), C["leftright_balance"], C["set_leftright_balance"],
            source="COMMENT %s SET_LEFTRIGHT_BALANCE '50 = default, 0 = left only, 100 = right only'" % GB_PKT,
            note="not in GB's Air Pro 4 UI; may be unsupported"),
    Setting("find_device", "Find buds (loud sound)", Enum({0: "off", 1: "left", 2: "right", 3: "both"}),
            C["find_device"], C["set_find_device"], on_connect=True,
            source="%s handleFindDeviceInfo, %s earfun_find_device_values" % (GB_RESP, GB_ARR),
            note="plays a LOUD sound; never send while worn"),
    Setting("eq", "Equaliser (10 band)", Equalizer(), vendor=VENDOR_V3,
            frames_for=lambda v: Equalizer().frames(v),
            source="%s encodeSetEqualizerBand + GB/prefs/Equalizer.java TenBandEqualizer/TenBandPreset" % GB_ENC,
            note="write-only (GB never reads 0E02); state shows the last value set via this daemon"),
    Setting("device_name", "Bluetooth name", Text(32), set=C["set_device_name"],
            source="%s PREF_EARFUN_DEVICE_NAME (UTF-8)" % GB_PROTO,
            note="write-only; applies after case close + re-pair (GB strings.xml); 32-byte cap is ours"),
    # ---- actions (write-only, fire and forget)
    Setting("reboot", "Reboot buds", Action(), set=C["reboot"], kind="action",
            source="%s COMMAND_REBOOT, used by %s" % (GB_PKT, GB_PROTO)),
    Setting("factory_reset", "Factory reset", Action(), set=C["factory_reset"], kind="action",
            source="COMMENT %s FACTORY_RESET (no payload documented)" % GB_PKT),
    Setting("trigger_pairing", "Enter pairing mode", Action(), set=C["trigger_pairing"], kind="action",
            source="COMMENT %s TRIGGER_PAIRING (no payload documented)" % GB_PKT),
    Setting("connect_device", "Enable paired device slot", Action({"first": b"\x00", "second": b"\x01"}),
            set=C["connect_device"], kind="action",
            source="COMMENT %s CONNECT_DEVICE '00 = first, 01 = second'" % GB_PKT),
    Setting("disconnect_device", "Disable paired device slot", Action({"first": b"\x00", "second": b"\x01"}),
            set=C["disconnect_device"], kind="action",
            source="COMMENT %s DISCONNECT_DEVICE '00 = first, 01 = second'" % GB_PKT),
    Setting("power_off", "Turn buds off", Action({"now": b"\x01"}), set=C["control_play"], kind="action",
            source="COMMENT %s SET_CONTROL_PLAY '01 = turn off device'" % GB_PKT),
    # ---- unsolicited (the buds send these on their own)
    Setting("playing", "Playing", Bool(2), kind="event", verified_get=True,
            source="LIVE unsolicited 0350 00 01; COMMENT %s '01: not playing, 02: playing'" % GB_PKT),
    Setting("audio_mode_raw", "Audio mode (raw)", Int(0, 255), kind="event", verified_get=True,
            source="LIVE unsolicited 034D 00 03; COMMENT %s meaning unclear" % GB_PKT),
    Setting("phone_list_raw", "Play phone list (raw)", Codec(), kind="event", verified_get=True,
            source="LIVE unsolicited 0358 (two frames: 00 5c3b4d01 / 00 334ee500); undecoded"),
    Setting("gesture_extra_raw", "Touch action bytes 16-31 (raw)", Codec(), kind="event", verified_get=True,
            source="LIVE 830B answer is 32 value bytes; GB decodes only the first 16; undecoded"),
]

# gestures: eight keys sharing GET 030B / SET 030A
for _t, _side in GESTURE_ORDER:
    _S.append(Setting(
        "gesture_%s_%s" % (_t, _side), "%s tap %s" % (_t.capitalize(), _side), GESTURE_ACTIONS,
        C["touch_action"], C["set_touch_action"], on_connect=(_t, _side) == ("single", "left"),
        frames_for=(lambda t, s: lambda v: [encode(C["set_touch_action"], gesture_payload(t, s, v))])(_t, _side),
        source="%s encodeSetGesture + %s handleTouchActionInfo + %s earfun_air_pro_4_tap_action_values"
               % (GB_ENC, GB_RESP, GB_ARR)))

SETTINGS: dict[str, Setting] = {s.key: s for s in _S}


def decode_frame(frame: Frame) -> dict:
    """State updates (key -> value) carried by a frame from the buds."""
    if frame.vendor != VENDOR:
        return {}
    cmd, v = frame.base, frame.value
    if cmd == C["touch_action"]:
        return decode_touch_actions(v)
    if not frame.ack:   # unsolicited
        if cmd == C["play_state"]:
            return {"playing": {1: False, 2: True}.get(v[0]) if v else None}
        if cmd == C["audio_mode"]:
            return {"audio_mode_raw": v[0] if v else None}
        if cmd == C["play_phone_list"]:
            return {"phone_list_raw": v.hex()}
    out = {}
    for s in SETTINGS.values():
        if s.get == cmd and s.kind != "event":
            out[s.key] = s.codec.decode(bytes(v))
    return out


def on_connect_gets() -> list[int]:
    seen, out = set(), []
    for s in SETTINGS.values():
        if s.on_connect and s.get is not None and s.get not in seen:
            seen.add(s.get)
            out.append(s.get)
    return out


def poll_gets() -> list[int]:
    return [s.get for s in SETTINGS.values() if s.poll]


def parse_value(key: str, value):
    return SETTINGS[key].codec.parse(value)


def setting_meta(s: Setting) -> dict:
    """Static part of a settings entry in the state (widget contract, see README)."""
    c = s.codec
    meta = {"type": c.kind, "options": None,
            # true only when every direction this key supports was measured on the real buds
            "live_verified": bool(s.verified_get or s.get is None)
                             and bool(s.verified_set or not s.settable)
                             and (s.get is not None or s.settable or s.kind == "event"),
            "settable": s.settable, "readable": s.get is not None or s.kind == "event",
            "verified_get": s.verified_get, "verified_set": s.verified_set, "kind": s.kind}
    if isinstance(c, Enum):
        meta["options"] = list(c.values)
    elif isinstance(c, Action):
        meta["options"] = list(c.names)
    elif isinstance(c, Equalizer):
        meta["options"] = list(EQ_PRESETS)
    elif isinstance(c, Int):
        meta["min"], meta["max"] = c.lo, c.hi
    return meta


def iter_table() -> Iterable[Setting]:
    return SETTINGS.values()


# --------------------------------------------------------------------------- Fast Pair stream
# Frame: group u8 | code u8 | length u16 BE | payload  (Google Fast Pair Message Stream spec).
FP_DEVICE_INFO = 3
FP_MODEL_ID, FP_BLE_ADDRESS, FP_BATTERY = 1, 2, 3


@dataclass
class FpFrame:
    group: int
    code: int
    payload: bytes


class FpSplitter:
    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes) -> list[FpFrame]:
        self.buf += data
        out = []
        while len(self.buf) >= 4:
            n = int.from_bytes(self.buf[2:4], "big")
            if len(self.buf) < 4 + n:
                break
            out.append(FpFrame(self.buf[0], self.buf[1], self.buf[4:4 + n]))
            self.buf = self.buf[4 + n:]
        return out


def encode_fp(group: int, code: int, payload: bytes = b"") -> bytes:
    return bytes([group, code]) + len(payload).to_bytes(2, "big") + payload


def fp_battery_byte(b: int):
    """(percent | None, charging | None).  High bit = charging; low 7 bits 0x7F = no reading
    (LIVE: case 0x7F while no bud had docked)."""
    level = b & 0x7F
    if level == 0x7F or level > 100:
        return None, None
    return level, bool(b & 0x80)


def decode_fp(f: FpFrame) -> dict:
    """Fast Pair frame -> {"left","right","case": pct|None, "charging": {...}} for battery, else {}."""
    if f.group != FP_DEVICE_INFO or f.code != FP_BATTERY or len(f.payload) != 3:
        return {}
    out, chg = {}, {}
    for part, b in zip(("left", "right", "case"), f.payload):
        out[part], chg[part] = fp_battery_byte(b)
    out["charging"] = chg
    return out
