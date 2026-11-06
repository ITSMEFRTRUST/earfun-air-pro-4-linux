"""When to call Device1.ConnectProfile, shared by BluezLink (GLib timers) and FakeLink (core loop).

LIVE (bud swap, btmon): the buds reconnect by themselves ~40 ms after dropping, bluetoothd's
A2DP reconnect collides with them (a2dp-sink: Device or resource busy), earfun-audio-heal reconnects,
and our SPP ConnectProfile right after that reconnect (br-connection-busy) knocked the buds off again.
So: after a (re)connect wait for A2DP (a MediaTransport1 for the device) or `a2dp_wait` seconds, never
connect while earfun-audio-heal holds its lock file, open SPP first and Fast Pair after it, one
ConnectProfile in flight at a time, and back off 3 / 6 / 12 / 24 s on failure, then every 30 s.
"""

from __future__ import annotations

import logging
import os
import time

from . import protocol as P

log = logging.getLogger("earfun")

HEAL_LOCK_MAX_AGE = 45.0      # a lock older than this is a leftover of a killed heal


def heal_lock_path() -> str:
    env = os.environ.get("EARFUN_HEAL_LOCK")
    if env:
        return env
    rt = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(rt, "earfun-heal.lock")


def heal_busy(path: str | None = None, now: float | None = None) -> bool:
    """earfun-audio-heal is reconnecting the buds (lock file younger than HEAL_LOCK_MAX_AGE)."""
    try:
        mtime = os.stat(path or heal_lock_path()).st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - mtime < HEAL_LOCK_MAX_AGE


def pick_buds(objects, want_address=None):
    """Choose the buds from BlueZ's GetManagedObjects(): (path, Device1 props) or (None, None).

    With want_address, that device.  Otherwise the paired devices named EarFun that offer SPP,
    a connected one first.  Shared by the daemon and earfun-audio-heal."""
    want = want_address.upper() if want_address else None
    found = []
    for path, ifaces in objects.items():
        d = ifaces.get("org.bluez.Device1")
        if not d:
            continue
        addr = str(d.get("Address", "")).upper()
        name = str(d.get("Alias", d.get("Name", "")))
        uuids = [str(u).lower() for u in d.get("UUIDs", [])]
        if want:
            ok = addr == want
        else:
            ok = bool(d.get("Paired")) and "earfun" in name.lower() and P.SPP_UUID in uuids
        if ok:
            found.append((not bool(d.get("Connected")), str(path), d))
    if not found:
        return None, None
    found.sort(key=lambda x: (x[0], x[1]))
    return found[0][1], found[0][2]


class Connector:
    """Decides when to open SPP, then the Fast Pair stream.

    call_later(delay, fn) -> handle; cancel(handle); connect(uuid, ok_cb, err_cb(msg)) starts an async
    ConnectProfile; a2dp_up() -> bool; has_fp() -> bool (FP UUID listed by the device);
    on_error(msg) reports a persistent failure to the core."""

    def __init__(self, timing, call_later, cancel, connect, a2dp_up, has_fp=lambda: False,
                 heal_busy=heal_busy, on_error=lambda msg: None, clock=time.monotonic):
        self.t = timing
        self.call_later, self.cancel, self.connect = call_later, cancel, connect
        self.a2dp_up, self.has_fp, self.heal_busy = a2dp_up, has_fp, heal_busy
        self.on_error, self.clock = on_error, clock
        self.connected = False
        self.connected_at = 0.0
        self.spp = False
        self.fp = False
        self.in_flight = None
        self.failures = {P.SPP_UUID: 0, P.FP_UUID: 0}
        self.timer = None
        self.gen = 0
        self.waiting = None          # what the last deferral was for (log once)
        self.attempts = []           # (uuid, clock) of every ConnectProfile, for tests/logs

    # ---- events -----------------------------------------------------------------
    def device_connected(self):
        self.connected = True
        self.connected_at = self.clock()
        self.spp = self.fp = False
        self.in_flight = None
        self.failures = dict.fromkeys(self.failures, 0)
        self._schedule(self.t.connect_delay)

    def device_disconnected(self):
        self.connected = False
        self.spp = self.fp = False
        self.in_flight = None
        self.gen += 1
        self._cancel()

    def spp_opened(self):
        self.spp = True
        self.failures[P.SPP_UUID] = 0
        if self.in_flight == P.SPP_UUID:
            self.in_flight = None
        self._schedule(self.t.fp_delay)

    def spp_lost(self):
        self.spp = False
        if self.connected:
            self._schedule(self.t.reconnect)

    def fp_opened(self):
        self.fp = True
        self.failures[P.FP_UUID] = 0
        if self.in_flight == P.FP_UUID:
            self.in_flight = None

    def fp_lost(self):
        self.fp = False
        if self.connected and self.spp:
            self._schedule(self.t.fp_retry)

    # ---- scheduling -------------------------------------------------------------
    def _cancel(self):
        if self.timer is not None:
            self.cancel(self.timer)
            self.timer = None

    def _schedule(self, delay):
        self._cancel()
        gen = self.gen
        self.timer = self.call_later(delay, lambda: self._step(gen))

    def _want(self):
        if not self.spp:
            return P.SPP_UUID
        if not self.fp and self.has_fp():
            return P.FP_UUID
        return None

    def _defer(self, why, delay):
        if self.waiting != why:
            log.info("ConnectProfile deferred: %s", why)
            self.waiting = why
        self._schedule(delay)

    def _step(self, gen):
        self.timer = None
        if gen != self.gen or not self.connected or self.in_flight:
            return
        uuid = self._want()
        if uuid is None:
            return
        if self.heal_busy():
            return self._defer("earfun-audio-heal is reconnecting", 1.0)
        if self.clock() - self.connected_at < self.t.a2dp_wait and not self.a2dp_up():
            return self._defer("waiting for A2DP", 0.5)
        self.waiting = None
        self.in_flight = uuid
        self.attempts.append((uuid, self.clock()))
        name = "SPP" if uuid == P.SPP_UUID else "Fast Pair"
        log.info("ConnectProfile %s attempt %d", name, self.failures[uuid] + 1)
        self.connect(uuid, lambda: self._ok(gen, uuid), lambda msg: self._failed(gen, uuid, msg))

    def _ok(self, gen, uuid):
        if gen == self.gen and self.in_flight == uuid:
            self.in_flight = None

    def _failed(self, gen, uuid, msg):
        if gen != self.gen:
            return
        if self.in_flight == uuid:
            self.in_flight = None
        if (uuid == P.SPP_UUID and self.spp) or (uuid == P.FP_UUID and self.fp):
            return                      # opened anyway (NewConnection won the race)
        n = self.failures[uuid] = self.failures[uuid] + 1
        backoff = self.t.connect_backoff
        delay = backoff[n - 1] if n <= len(backoff) else self.t.reconnect_cycle
        name = "SPP" if uuid == P.SPP_UUID else "Fast Pair"
        log.info("ConnectProfile %s attempt %d failed: %s; next in %.0f s", name, n, msg, delay)
        if n == len(backoff) and uuid == P.SPP_UUID:
            self.on_error("cannot open the channel: %s" % msg)
        self._schedule(delay)
