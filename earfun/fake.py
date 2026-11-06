"""Fake EarFun Air Pro 4: answers on one end of a socketpair like the real buds.

Behaviour copied from the live captures (real buds, and omarchy-headphones
PR #30 docs/captures/earfun-air-pro-4.txt):
  * GET -> answer version 03, command | 0x8000, payload 00 <value>, in ~20-50 ms;
  * SET 0314 (mode) -> no reply; the new value is applied after `mode_delay` s, and a
    GET before then still answers the old value;
  * other SETs -> no reply, applied at once (unknown on the real buds); the EQ band
    set answers 0F81 01 like GB/EarFunProtocol.java expects;
  * unsolicited frames 0358 x2, 0350, 034D, often several in one write;
  * `chunked=True` splits writes at random points to exercise frame reassembly.
Unknown GETs get no answer.  Stdlib only.
"""

from __future__ import annotations

import random
import socket
import threading
import time

from . import protocol as P
from .protocol import C, C_V3

FIRMWARE = b"TW600-3091_20250919_v0.4.1"


class FakeBuds:
    def __init__(self, mode_delay=1.5, unsolicited_every=7.0, chunked=False, seed=None,
                 battery=(80, 85, 60)):
        self.mode_delay = mode_delay
        self.unsolicited_every = unsolicited_every
        self.chunked = chunked
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        L, R, K = battery
        # wire values (what the buds would send after the 00 status byte)
        self.regs: dict[int, bytes] = {
            C["ambient_sound"]: b"\x00", C["anc_mode"]: b"\x02", C["transparency_mode"]: b"\x00",
            C["game_mode"]: b"\x00", C["battery_left"]: bytes([L]), C["battery_right"]: bytes([R]),
            C["battery_case"]: bytes([K]), C["firmware_version"]: FIRMWARE,
            C["gaia_api_version"]: b"\x03\x03\x01", C["application_version"]: b"\x02\x00",
            C["device_color"]: b"\x00", C["touch_mode"]: b"\x00",
            C["disable_in_ear_detection"]: b"\x00", C["audio_codec"]: b"\x13",
            C["advanced_audio_mode"]: b"\x00", C["connect_two_devices"]: b"\x01",
            C["microphone_mode"]: b"\x00", C["voice_prompt_volume"]: b"\x01",
            C["find_device"]: b"\x00", C["voice_protect"]: b"\x01", C["leftright_balance"]: b"\x32",
            C["phone_call_state"]: b"\x00",
            # LIVE layout: 16 (type, action) pairs in GESTURE_ORDER, then 16 bytes GB doesn't know
            C["touch_action"]: bytes.fromhex("0101 0101 0205 0204 0303 0302 1108 1108"
                                             "0400 0400 0500 0500 0606 0606 1304 1304"),
        }
        self.set_map = {s.set: s.get for s in P.SETTINGS.values()
                        if s.set is not None and s.get is not None}
        self.received: list[P.Frame] = []     # every frame the host sent (for tests)
        self.name = "EarFun Air Pro 4"
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.timers: list[threading.Timer] = []
        self.stop_evt = threading.Event()

    # ---- connection -------------------------------------------------------------
    def attach(self) -> socket.socket:
        """New channel: returns the host end of a fresh socketpair."""
        self.detach()
        host, buds = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock = buds
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(buds, self.stop_evt),
                                       name="fake-buds", daemon=True)
        self.thread.start()
        return host

    def detach(self):
        """Drop the channel (the host sees EOF/HUP), like the buds going into the case."""
        self.stop_evt.set()
        for t in self.timers:
            t.cancel()
        self.timers = []
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            self.sock = None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(1)
        self.thread = None

    # ---- test helpers -----------------------------------------------------------
    def set_battery(self, left=None, right=None, case=None):
        with self.lock:
            for cmd, v in ((C["battery_left"], left), (C["battery_right"], right),
                           (C["battery_case"], case)):
                if v is not None:
                    self.regs[cmd] = bytes([v])

    def set_mode_on_buds(self, mode: str):
        """Mode changed on the buds themselves (no notification, like the real ones)."""
        with self.lock:
            self.regs[C["ambient_sound"]] = P.MODE.encode(mode)

    def value(self, get_cmd: int) -> bytes:
        with self.lock:
            return self.regs.get(get_cmd, b"")

    def sets_received(self) -> list[P.Frame]:
        return [f for f in self.received if f.payload or f.base in (C["reboot"],)
                and f.base not in P.on_connect_gets()]

    # ---- wire -------------------------------------------------------------------
    def _send(self, data: bytes):
        s = self.sock
        if s is None:
            return
        try:
            if self.chunked and len(data) > 2:
                cut = self.rng.randrange(1, len(data))
                s.sendall(data[:cut])
                time.sleep(0.002)
                s.sendall(data[cut:])
            else:
                s.sendall(data)
        except OSError:
            pass

    @staticmethod
    def _frame(cmd, value=b"", ack=True, vendor=P.VENDOR, status=0):
        return P.encode(cmd | (P.ACK if ack else 0), bytes([status]) + value, vendor, version=0x03)

    def unsolicited(self) -> bytes:
        return (self._frame(C["play_phone_list"], bytes.fromhex("5c3b4d01"), ack=False)
                + self._frame(C["play_phone_list"], bytes.fromhex("334ee500"), ack=False)
                + self._frame(C["play_state"], b"\x01", ack=False))

    def _run(self, sock, stop):
        split = P.FrameSplitter()
        sock.settimeout(0.05)
        next_unsol = time.monotonic() + min(0.4, self.unsolicited_every)
        while not stop.is_set():
            if self.unsolicited_every and time.monotonic() >= next_unsol:
                self._send(self.unsolicited() if self.rng.random() < 0.5
                           else self._frame(C["audio_mode"], b"\x03", ack=False))
                next_unsol = time.monotonic() + self.unsolicited_every
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            for f in self._split_host(split, data):
                self._handle(f)

    @staticmethod
    def _split_host(split, data):
        return split.feed(data)

    def _handle(self, f: P.Frame):
        self.received.append(f)
        if f.vendor == P.VENDOR_V3:
            if f.base == C_V3["set_equalizer_band"]:
                self._send(P.encode(C_V3["response_equalizer_band"] | 0, b"\x01", P.VENDOR_V3, 0x03))
            return
        cmd = f.base
        if cmd == C["set_ambient_sound"]:
            if f.payload[:1] in (b"\x00", b"\x01", b"\x02"):
                t = threading.Timer(self.mode_delay, self._apply, (C["ambient_sound"], f.payload[:1]))
                t.daemon = True
                self.timers.append(t)
                t.start()
            return                                   # LIVE: no reply to the set
        if cmd == C["set_touch_action"] and len(f.payload) == 4:
            self._apply_gesture(f.payload)
            return
        if cmd in self.set_map:
            self._apply(self.set_map[cmd], f.payload[:1])
            return
        if cmd == C["set_device_name"]:
            self.name = f.payload.decode("utf-8", "replace")
            return
        if not f.payload:                            # a GET
            with self.lock:
                v = self.regs.get(cmd)
            if v is not None:
                # LIVE: the find-device answer has no ack bit
                self._send(self._frame(cmd, v, ack=cmd != C["find_device"]))

    def _apply(self, get_cmd, value: bytes):
        with self.lock:
            self.regs[get_cmd] = value

    def _apply_gesture(self, payload: bytes):
        t, a = (payload[0], payload[1]) if payload[0] else (payload[2], payload[3])
        left = bool(payload[0])
        gtype = {v: k for k, v in P.GESTURE_TYPES.items()}.get(t)
        if gtype is None:
            return
        idx = P.GESTURE_ORDER.index((gtype, "left" if left else "right"))
        with self.lock:
            r = bytearray(self.regs[C["touch_action"]])
            r[2 * idx + 1] = a
            self.regs[C["touch_action"]] = bytes(r)


class FakeFastPair:
    """Fake Google Fast Pair Message Stream: like the real buds (LIVE) it pushes model id,
    BLE address and battery right after the channel opens, then battery again on every change
    (`set_battery`).  Bytes: percent | 0x80 when charging, 0x7F = no reading.  Ignores what it gets."""

    def __init__(self, left=0x50, right=0x64, case=0x7F):
        self.levels = [left, right, case]
        self.sock = None
        self.lock = threading.Lock()

    def attach(self) -> socket.socket:
        self.detach()
        host, buds = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock = buds
        self._push(P.encode_fp(3, 1, bytes.fromhex("f3d9b4")) +
                   P.encode_fp(3, 2, bytes.fromhex("5b66778899aa")) + self._battery())
        return host

    def detach(self):
        with self.lock:
            if self.sock is not None:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.sock.close()
                self.sock = None

    def set_battery(self, left=None, right=None, case=None):
        """Raw bytes (e.g. case=0xA2 = 34 % charging, 0x7F = unknown); pushed at once."""
        for i, v in enumerate((left, right, case)):
            if v is not None:
                self.levels[i] = v
        self._push(self._battery())

    def _battery(self):
        return P.encode_fp(3, 3, bytes(self.levels))

    def _push(self, data):
        with self.lock:
            if self.sock is not None:
                try:
                    self.sock.sendall(data)
                except OSError:
                    pass
