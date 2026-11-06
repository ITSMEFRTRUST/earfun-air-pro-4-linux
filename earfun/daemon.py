"""earfun daemon: the single owner of the buds' SPP channel.

Event loop: stdlib `selectors` + timers in the main thread.  The real-buds link
(BluezLink) runs dbus-python + GLib in a helper thread and only posts events to
the core; `--fake` (FakeLink) needs neither D-Bus nor GLib.

Clients talk JSON lines over $XDG_RUNTIME_DIR/earfun.sock (mode 0600); see
README "JSON interface".
"""

from __future__ import annotations

import collections
import heapq
import itertools
import json
import logging
import os
import selectors
import signal
import socket
import threading
import time
from dataclasses import dataclass

from . import protocol as P
from .connect import Connector, heal_busy, pick_buds

log = logging.getLogger("earfun")

KEEP_ON_DISCONNECT = ("firmware", "gaia_api", "app_version", "eq", "device_name")


def default_state_path() -> str:
    env = os.environ.get("EARFUN_STATE")
    if env:
        return env
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "earfun", "state.json")


def default_socket_path() -> str:
    env = os.environ.get("EARFUN_SOCK")
    if env:
        return env
    rt = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(rt, "earfun.sock")


@dataclass
class Timing:
    poll: float = 10.0            # battery + mode re-read
    tx_gap: float = 0.08          # spacing between frames we send
    recheck: float = 1.0          # after a set: re-read every ...
    recheck_tries: int = 6        # ... this many times (LIVE: mode applies in ~1-2.5 s)
    get_timeout: float = 3.0      # client "get" waits this long for the answer
    first_answer: float = 8.0     # no frame at all after opening -> reopen
    stale: float = 45.0           # no frame for this long while open -> reopen
    connect_delay: float = 1.5    # after BlueZ reports Connected, wait before ConnectProfile ...
    a2dp_wait: float = 6.0        # ... and until A2DP is up (MediaTransport1) or this long passed
    connect_backoff: tuple = (3.0, 6.0, 12.0, 24.0)  # ConnectProfile failed (br-connection-busy)
    reconnect: float = 3.0        # channel lost while the device is still connected
    reconnect_cycle: float = 30.0  # after the backoff ran out
    fp_delay: float = 2.0         # SPP open -> open the Fast Pair stream this much later
    fp_retry: float = 15.0        # Fast Pair stream lost while connected
    state_write: float = 300.0    # steady case level: advance case_seen (+ state.json) this often


# --------------------------------------------------------------------------- loop

class Loop:
    def __init__(self):
        self.sel = selectors.DefaultSelector()
        self.timers: list = []
        self.seq = itertools.count()
        self.posted = collections.deque()
        self.rfd, self.wfd = os.pipe()
        os.set_blocking(self.rfd, False)
        os.set_blocking(self.wfd, False)
        self.sel.register(self.rfd, selectors.EVENT_READ, self._drain_wake)
        self.running = False
        self.after = None                 # hook run after every iteration

    def call_later(self, delay, fn, *args):
        h = [time.monotonic() + delay, next(self.seq), fn, args, False]
        heapq.heappush(self.timers, h)
        return h

    @staticmethod
    def cancel(h):
        if h:
            h[4] = True

    def post(self, fn, *args):
        """Thread-safe: run fn(*args) on the loop thread."""
        self.posted.append((fn, args))
        self.wake()

    def wake(self):
        try:
            os.write(self.wfd, b"x")
        except (BlockingIOError, OSError):
            pass

    def _drain_wake(self, _mask):
        try:
            while os.read(self.rfd, 512):
                pass
        except BlockingIOError:
            pass

    def add(self, fileobj, events, cb):
        self.sel.register(fileobj, events, cb)

    def modify(self, fileobj, events, cb):
        self.sel.modify(fileobj, events, cb)

    def remove(self, fileobj):
        try:
            self.sel.unregister(fileobj)
        except (KeyError, ValueError):
            pass

    def stop(self):
        self.running = False
        self.wake()

    def run(self):
        self.running = True
        while self.running:
            timeout = None
            if self.timers:
                timeout = max(0.0, self.timers[0][0] - time.monotonic())
            if self.posted:
                timeout = 0
            for key, mask in self.sel.select(timeout):
                try:
                    key.data(mask)
                except Exception:
                    log.exception("handler failed")
            now = time.monotonic()
            while self.timers and self.timers[0][0] <= now:
                h = heapq.heappop(self.timers)
                if not h[4]:
                    try:
                        h[2](*h[3])
                    except Exception:
                        log.exception("timer failed")
            while self.posted:
                fn, args = self.posted.popleft()
                try:
                    fn(*args)
                except Exception:
                    log.exception("posted call failed")
            if self.after:
                self.after()

    def close(self):
        self.sel.close()
        os.close(self.rfd)
        os.close(self.wfd)


# --------------------------------------------------------------------------- core

class Client:
    def __init__(self, sock):
        self.sock = sock
        self.inbuf = b""
        self.out = b""
        self.watch = False
        self.closed = False


class Core:
    def __init__(self, link, socket_path=None, timing=None, allow_unverified=False, state_path=None):
        self.link = link
        self.source = link.source
        self.socket_path = socket_path or default_socket_path()
        self.t = timing or Timing()
        # fake buds cannot be hurt; on the real buds only verified sets go out unless asked
        self.allow_unverified = allow_unverified or link.source == "fake"
        self.loop = Loop()
        self.loop.after = self._broadcast
        self.server = None
        self.clients: list[Client] = []
        # device / channel
        self.address = None
        self.name = None
        self.device_connected = False
        self.channel = "disconnected"
        self.sock = None
        self.split = P.FrameSplitter()
        self.txq = collections.deque()
        self.tx_timer = None
        self.opened_at = 0.0
        self.last_rx = 0.0
        self.error = None
        # values
        self.values: dict = {}
        self.pending: dict = {}           # key -> {"value", "tries", "timer", "waiters"}
        self.get_waiters: dict = {}       # get cmd -> [(client, rid, key, timer)]
        self.poll_timer = None
        self.last_sent = None
        # Fast Pair Message Stream (battery pushed by the buds)
        self.fp_sock = None
        self.fp_split = P.FpSplitter()
        self.fp: dict = {}
        # last real case level (survives disconnects and, with state_path, restarts)
        self.state_path = state_path
        self.case_last = None
        self.case_seen = None
        self.case_live_at = 0.0
        self._load_state()

    # ---- lifecycle --------------------------------------------------------------
    def serve(self):
        path = self.socket_path
        if os.path.exists(path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(path)
            except OSError:
                os.unlink(path)          # stale socket from a dead daemon
            else:
                probe.close()
                raise SystemExit("earfun daemon already running on %s" % path)
            finally:
                probe.close()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            srv.bind(path)
        finally:
            os.umask(old)
        os.chmod(path, 0o600)
        srv.listen(16)
        srv.setblocking(False)
        self.server = srv
        self.loop.add(srv, selectors.EVENT_READ, self._accept)
        log.info("listening on %s (%s)", path, self.source)

    def run(self):
        self.serve()
        self.link.start(self)
        try:
            self.loop.run()
        finally:
            self.shutdown()

    def stop(self):
        self.loop.stop()

    def shutdown(self):
        try:
            self.link.stop()
        except Exception:
            log.exception("link stop")
        self._close_channel("daemon stopping", notify_link=False)
        self._close_fp("daemon stopping", notify_link=False)
        self._save_state()
        for c in list(self.clients):
            self._drop(c)
        if self.server:
            self.loop.remove(self.server)
            self.server.close()
            self.server = None
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

    # ---- events from the link (on the loop thread) ------------------------------
    def device_changed(self, address, name, connected):
        self.address, self.name = address, name
        was = self.device_connected
        self.device_connected = bool(connected)
        if was and not connected:
            log.info("device disconnected")
            self._close_channel("device disconnected", notify_link=False)
            self._close_fp("device disconnected", notify_link=False)
        if connected and self.channel == "disconnected":
            self.channel = "connecting"

    def link_error(self, message):
        self.error = message
        if self.channel == "connecting" and not self.sock:
            self.channel = "disconnected"
        log.warning("%s", message)

    def channel_opened(self, sock):
        if self.sock is not None:
            log.info("second channel offered; closing it")
            sock.close()
            return
        sock.setblocking(False)
        self.sock = sock
        self.split = P.FrameSplitter()
        self.channel = "connected"
        self.device_connected = True
        self.error = None
        self.opened_at = time.monotonic()
        self.last_rx = 0.0
        self.loop.add(sock, selectors.EVENT_READ, self._on_spp)
        log.info("channel open")
        for cmd in P.on_connect_gets():
            self._send(P.encode_get(cmd))
        self._schedule_poll()

    def channel_closed(self, reason):
        self._close_channel(reason)

    def fp_opened(self, sock):
        if self.fp_sock is not None:
            sock.close()
            return
        sock.setblocking(False)
        self.fp_sock = sock
        self.fp_split = P.FpSplitter()
        self.loop.add(sock, selectors.EVENT_READ, self._on_fp)
        log.info("fast pair stream open")

    def fp_closed(self, reason):
        self._close_fp(reason)

    def _close_fp(self, reason, notify_link=True):
        if self.fp_sock is None:
            return
        self.loop.remove(self.fp_sock)
        try:
            self.fp_sock.close()
        except OSError:
            pass
        self.fp_sock = None
        self.fp = {}
        self._note_case()
        log.info("fast pair stream closed: %s", reason)
        if notify_link:
            self.link.fp_lost()

    def _on_fp(self, _mask):
        try:
            data = self.fp_sock.recv(4096)
        except BlockingIOError:
            return
        except OSError as e:
            return self._close_fp("read error: %s" % e)
        if not data:
            return self._close_fp("EOF")
        for f in self.fp_split.feed(data):
            log.debug("FP RX group %d code %d %s", f.group, f.code, f.payload.hex())
            upd = P.decode_fp(f)
            if upd:
                self.fp = upd
                self._note_case()

    # ---- battery: GAIA polls + Fast Pair pushes, last real case level -----------
    def battery(self) -> dict:
        v, fp = self.values, self.fp
        out = {}
        for part in ("left", "right", "case"):
            g = v.get("battery_" + part)
            out[part] = g if g is not None else fp.get(part)
        out["case_last"] = self.case_last
        out["case_seen"] = int(self.case_seen) if self.case_seen is not None else None
        chg = fp.get("charging") or {}
        out["charging"] = {p: chg.get(p) for p in ("left", "right", "case")}
        return out

    def _note_case(self):
        """Track the last real case level.  case_seen moves when the level changes, when the case
        stops reporting (stamped with the last moment it did), and otherwise at most every
        `state_write` s, so a steady level does not make every poll a new watch line."""
        case = self.values.get("battery_case")
        if case is None:
            case = self.fp.get("case")
        now = time.time()
        if case is not None:
            self.case_live_at = now
            if (case != self.case_last or self.case_seen is None
                    or now - self.case_seen >= self.t.state_write):
                self.case_last, self.case_seen = case, now
                self._save_state()
        elif self.case_live_at and self.case_seen is not None and self.case_live_at > self.case_seen:
            self.case_seen = self.case_live_at
            self._save_state()

    def _load_state(self):
        if not self.state_path:
            return
        try:
            with open(self.state_path) as f:
                d = json.load(f)
            c, seen = d.get("case_last"), d.get("case_seen")
            if isinstance(c, int) and 0 <= c <= 100 and isinstance(seen, (int, float)):
                self.case_last, self.case_seen = c, float(seen)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError) as e:
            log.warning("state %s unreadable: %s", self.state_path, e)

    def _save_state(self):
        if not self.state_path or self.case_last is None:
            return
        tmp = self.state_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(tmp, "w") as f:
                json.dump({"address": self.address, "case_last": self.case_last,
                           "case_seen": int(self.case_seen)}, f)
            os.replace(tmp, self.state_path)
        except OSError as e:
            log.warning("cannot write %s: %s", self.state_path, e)

    # ---- channel ----------------------------------------------------------------
    def _close_channel(self, reason, notify_link=True):
        had = self.sock is not None
        if self.sock is not None:
            self.loop.remove(self.sock)
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self.txq.clear()
        self.loop.cancel(self.tx_timer)
        self.tx_timer = None
        self.loop.cancel(self.poll_timer)
        self.poll_timer = None
        for key in list(self.pending):
            self._finish_pending(key, False)
        for cmd in list(self.get_waiters):
            for c, rid, key, tm in self.get_waiters.pop(cmd):
                self.loop.cancel(tm)
                self._reply(c, rid, {"ok": False, "error": "channel closed"})
        self.values = {k: v for k, v in self.values.items() if k in KEEP_ON_DISCONNECT}
        self._note_case()
        self.channel = "connecting" if (self.device_connected and notify_link) else "disconnected"
        if had:
            log.info("channel closed: %s", reason)
            if notify_link:
                self.link.channel_lost()

    def _on_spp(self, _mask):
        try:
            data = self.sock.recv(4096)
        except BlockingIOError:
            return
        except OSError as e:
            return self._close_channel("read error: %s" % e)
        if not data:
            return self._close_channel("EOF")
        self.last_rx = time.monotonic()
        for f in self.split.feed(data):
            log.debug("RX %s", f)
            self._on_frame(f)

    def _send(self, frame: bytes):
        self.txq.append(frame)
        if self.tx_timer is None:
            self.tx_timer = self.loop.call_later(0, self._tx)

    def _tx(self):
        self.tx_timer = None
        if not self.txq or self.sock is None:
            return
        frame = self.txq.popleft()
        try:
            self.sock.sendall(frame)
            log.debug("TX %s", frame.hex(" "))
        except OSError as e:
            return self._close_channel("write error: %s" % e)
        if self.txq:
            self.tx_timer = self.loop.call_later(self.t.tx_gap, self._tx)

    def _schedule_poll(self):
        self.loop.cancel(self.poll_timer)
        self.poll_timer = self.loop.call_later(self.t.poll, self._poll)

    def _poll(self):
        self.poll_timer = None
        if self.sock is None:
            return
        now = time.monotonic()
        if self.last_rx == 0.0 and now - self.opened_at > self.t.first_answer:
            return self._close_channel("no answer from the buds")
        if self.last_rx and now - self.last_rx > self.t.stale:
            return self._close_channel("buds silent for %.0f s" % (now - self.last_rx))
        for cmd in P.poll_gets():
            self._send(P.encode_get(cmd))
        self._schedule_poll()

    def _on_frame(self, f: P.Frame):
        updates = P.decode_frame(f)
        for k, v in updates.items():
            if k == "phone_list_raw":     # the buds alternate two 0358 frames; keep the set
                v = sorted(set(self.values.get(k) or []) | {v})
            self.values[k] = v
            p = self.pending.get(k)
            if p is not None and p["value"] == v:
                self._finish_pending(k, True)
        if "battery_case" in updates:
            self._note_case()
        if f.vendor == P.VENDOR:      # LIVE: the 0333 answer comes without the ack bit
            for c, rid, key, tm in self.get_waiters.pop(f.base, []):
                self.loop.cancel(tm)
                self._reply(c, rid, {"ok": True, "key": key, "value": self.values.get(key)})

    # ---- sets -------------------------------------------------------------------
    def set_value(self, key, value):
        """Returns (parsed value, pending: bool); raises ValueError."""
        s = P.SETTINGS.get(key)
        if s is None:
            raise ValueError("unknown key %r (try: earfun keys)" % key)
        if not s.settable:
            raise ValueError("%s is read-only" % key)
        if key == "mode" and str(value).strip().lower() == "cycle":
            cur = self.pending.get("mode", {}).get("value") or self.values.get("mode") or "ambient"
            value = P.MODE_CYCLE[(P.MODE_CYCLE.index(cur) + 1) % 3] if cur in P.MODE_CYCLE else "anc"
        parsed = s.codec.parse(value)
        if not s.verified_set and not self.allow_unverified:
            raise PermissionError(
                "refused: SET for %s is not verified on the real buds; restart the daemon "
                "with --allow-unverified-sets to send it" % key)
        if self.sock is None:
            raise ConnectionError("buds not connected")
        frames = s.set_frames(parsed)
        for fr in frames:
            self._send(fr)
        self.last_sent = (key, parsed)
        if s.get is None:                 # write-only: remember what we sent
            if s.kind != "action":
                self.values[key] = parsed
            return parsed, False
        old = self.pending.get(key)
        if old:
            self._finish_pending(key, False, superseded=True)
        self.pending[key] = {"value": parsed, "tries": 0, "waiters": [],
                             "timer": self.loop.call_later(self.t.recheck, self._recheck, key)}
        return parsed, True

    def _recheck(self, key):
        p = self.pending.get(key)
        if p is None or self.sock is None:
            return
        if p["tries"] >= self.t.recheck_tries:
            log.warning("%s: buds still report %r, not %r", key, self.values.get(key), p["value"])
            return self._finish_pending(key, False)
        p["tries"] += 1
        self._send(P.encode_get(P.SETTINGS[key].get))
        p["timer"] = self.loop.call_later(self.t.recheck, self._recheck, key)

    def _finish_pending(self, key, confirmed, superseded=False):
        p = self.pending.pop(key, None)
        if p is None:
            return
        self.loop.cancel(p["timer"])
        for c, rid in p["waiters"]:
            msg = {"ok": True, "key": key, "value": p["value"], "confirmed": confirmed}
            if superseded:
                msg["superseded"] = True
            if not confirmed and not superseded:
                msg["reported"] = self.values.get(key)
            self._reply(c, rid, msg)

    # ---- state ------------------------------------------------------------------
    def state(self) -> dict:
        v = self.values
        settings = {}
        for s in P.iter_table():
            e = {"value": v.get(s.key)}
            e.update(P.setting_meta(s))
            if s.key in self.pending:
                e["pending"] = self.pending[s.key]["value"]
            settings[s.key] = e
        return {
            "daemon": True,
            "source": self.source,
            "connected": self.channel == "connected",
            "device_connected": self.device_connected,
            "channel": self.channel,
            "name": self.name,
            "address": self.address,
            "mode": v.get("mode"),
            "pending_mode": self.pending.get("mode", {}).get("value"),
            "battery": self.battery(),
            "anc_style": v.get("anc_style"),
            "transparency_style": v.get("transparency_style"),
            "firmware": v.get("firmware"),
            "playing": v.get("playing"),
            "error": self.error,
            "settings": settings,
        }

    def _broadcast(self):
        watchers = [c for c in self.clients if c.watch]
        if not watchers:
            self._last_state = None
            return
        line = json.dumps(self.state(), sort_keys=True)
        if line == getattr(self, "_last_state", None):
            return
        self._last_state = line
        for c in watchers:
            self._write(c, line + "\n")

    # ---- clients ----------------------------------------------------------------
    def _accept(self, _mask):
        try:
            sock, _ = self.server.accept()
        except (BlockingIOError, InterruptedError):
            return
        sock.setblocking(False)
        c = Client(sock)
        self.clients.append(c)
        self.loop.add(sock, selectors.EVENT_READ, lambda m, c=c: self._client_io(c, m))

    def _client_io(self, c, mask):
        if mask & selectors.EVENT_WRITE:
            self._flush(c)
        if c.closed or not mask & selectors.EVENT_READ:
            return
        try:
            data = c.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            return self._drop(c)
        if not data:
            return self._drop(c)
        c.inbuf += data
        if len(c.inbuf) > 1 << 20:
            return self._drop(c)
        while b"\n" in c.inbuf and not c.closed:
            line, c.inbuf = c.inbuf.split(b"\n", 1)
            if line.strip():
                self._request(c, line)

    def _request(self, c, line):
        rid = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
            rid = req.get("id")
            cmd = req.get("cmd")
            if cmd == "status":
                return self._reply(c, rid, {"ok": True, "state": self.state()})
            if cmd == "watch":
                c.watch = True
                self._write(c, json.dumps(self.state(), sort_keys=True) + "\n")
                return
            if cmd == "keys":
                return self._reply(c, rid, {"ok": True, "keys": [s.info() for s in P.iter_table()]})
            if cmd == "ping":
                return self._reply(c, rid, {"ok": True, "source": self.source})
            if cmd == "get":
                return self._get(c, rid, req.get("key"), req.get("refresh", True))
            if cmd == "set":
                key = req.get("key")
                parsed, pending = self.set_value(key, req.get("value"))
                if pending and req.get("wait"):
                    self.pending[key]["waiters"].append((c, rid))
                    return
                return self._reply(c, rid, {"ok": True, "key": key, "value": parsed,
                                            "pending": pending})
            raise ValueError("unknown cmd %r" % cmd)
        except PermissionError as e:
            self._reply(c, rid, {"ok": False, "error": str(e), "refused": True})
        except (ValueError, ConnectionError, TypeError) as e:
            self._reply(c, rid, {"ok": False, "error": str(e)})

    def _get(self, c, rid, key, refresh):
        s = P.SETTINGS.get(key)
        if s is None:
            raise ValueError("unknown key %r (try: earfun keys)" % key)
        if not refresh or s.get is None or self.sock is None:
            return self._reply(c, rid, {"ok": True, "key": key, "value": self.values.get(key),
                                        "cached": True})
        self._send(P.encode_get(s.get))

        def timeout():
            lst = self.get_waiters.get(s.get, [])
            for w in list(lst):
                if w[0] is c and w[1] == rid:
                    lst.remove(w)
                    self._reply(c, rid, {"ok": True, "key": key, "value": self.values.get(key),
                                         "cached": True, "timeout": True})
        tm = self.loop.call_later(self.t.get_timeout, timeout)
        self.get_waiters.setdefault(s.get, []).append((c, rid, key, tm))

    def _reply(self, c, rid, msg):
        if rid is not None:
            msg["id"] = rid
        self._write(c, json.dumps(msg, sort_keys=True) + "\n")

    def _write(self, c, text):
        if c.closed:
            return
        c.out += text.encode()
        if len(c.out) > 4 << 20:
            return self._drop(c)
        self._flush(c)

    def _flush(self, c):
        try:
            while c.out:
                n = c.sock.send(c.out)
                c.out = c.out[n:]
        except BlockingIOError:
            pass
        except OSError:
            return self._drop(c)
        ev = selectors.EVENT_READ | (selectors.EVENT_WRITE if c.out else 0)
        try:
            self.loop.modify(c.sock, ev, lambda m, c=c: self._client_io(c, m))
        except (KeyError, ValueError):
            pass

    def _drop(self, c):
        if c.closed:
            return
        c.closed = True
        self.loop.remove(c.sock)
        try:
            c.sock.close()
        except OSError:
            pass
        if c in self.clients:
            self.clients.remove(c)


# --------------------------------------------------------------------------- links

class FakeLink:
    """In-process fake buds (earfun.fake); no D-Bus, no GLib.  Goes through the same Connector as
    the real link: `busy` = how many ConnectProfile calls fail with br-connection-busy, `a2dp` =
    whether A2DP counts as up, `fp` = FakeFastPair (None = no Fast Pair UUID)."""
    source = "fake"

    def __init__(self, fake=None, address="00:00:00:00:00:00", name="EarFun Air Pro 4 (fake)",
                 fp=None, heal_lock=None):
        from .fake import FakeBuds
        self.fake = fake or FakeBuds()
        self.fp = fp
        self.address, self.name = address, name
        self.core = None
        self.present = True
        self.stopping = False
        self.busy = 0
        self.a2dp = True
        self.heal_lock = heal_lock
        self.connector = None

    def start(self, core):
        self.core = core
        loop = core.loop
        self.connector = Connector(
            core.t, call_later=loop.call_later, cancel=loop.cancel, connect=self._connect,
            a2dp_up=lambda: self.a2dp, has_fp=lambda: self.fp is not None,
            heal_busy=lambda: heal_busy(self.heal_lock) if self.heal_lock else False,
            on_error=core.link_error)
        core.device_changed(self.address, self.name, True)
        self.connector.device_connected()

    def _connect(self, uuid, ok, err):
        if self.stopping or not self.present:
            return self.core.loop.call_later(0.01, err, "Host is down")
        if self.busy > 0:
            self.busy -= 1
            return self.core.loop.call_later(0.01, err, "br-connection-busy")
        ok()
        if uuid == P.SPP_UUID:
            self.connector.spp_opened()
            self.core.channel_opened(self.fake.attach())
        else:
            self.connector.fp_opened()
            self.core.fp_opened(self.fp.attach())

    def channel_lost(self):
        if self.connector:
            self.connector.spp_lost()

    def fp_lost(self):
        if self.connector:
            self.connector.fp_lost()

    def set_present(self, present: bool):
        """Simulate the buds connecting/disconnecting (call on the loop thread)."""
        self.present = present
        if not present:
            self.connector.device_disconnected()
            self.core.device_changed(self.address, self.name, False)
            self.fake.detach()
            if self.fp:
                self.fp.detach()
        else:
            self.core.device_changed(self.address, self.name, True)
            self.connector.device_connected()

    def stop(self):
        self.stopping = True
        if self.connector:
            self.connector.device_disconnected()
        self.fake.detach()
        if self.fp:
            self.fp.detach()


class BluezLink:
    """Real buds through BlueZ: Profile1 clients for SPP and the Fast Pair Message Stream +
    Device1.ConnectProfile, timed by connect.Connector.

    All D-Bus work happens in a GLib thread; results are posted to the core."""
    source = "live"
    PROFILE_PATH = "/org/earfun_linux/daemon"
    FP_PROFILE_PATH = "/org/earfun_linux/fastpair"

    def __init__(self, address=None):
        self.want_address = address.upper() if address else None
        self.core = None
        self.thread = None
        self.ready = threading.Event()
        self.gloop = None
        self.device_path = None
        self.connected = False
        self.registered = False
        self.fp_registered = False
        self.connector = None

    # called on the core thread
    def start(self, core):
        self.core = core
        self.thread = threading.Thread(target=self._thread, name="bluez", daemon=True)
        self.thread.start()
        self.ready.wait(10)

    def channel_lost(self):
        self._idle(lambda: self.connector.spp_lost())

    def fp_lost(self):
        self._idle(lambda: self.connector.fp_lost())

    def stop(self):
        if self.gloop is None:
            return
        done = threading.Event()

        def bye():
            self._unregister()
            self.gloop.quit()
            done.set()
            return False
        self._idle(bye)
        done.wait(5)
        self.thread.join(5)

    def _idle(self, fn, *a):
        from gi.repository import GLib
        GLib.idle_add(lambda: (fn(*a), False)[1])

    # ---- GLib thread ------------------------------------------------------------
    def _thread(self):
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib
        self.dbus, self.GLib = dbus, GLib
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        link = self
        core = self.core

        class Profile(dbus.service.Object):
            @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}")
            def NewConnection(self, dev, fd, props):
                sock = socket.socket(fileno=fd.take())
                link.connector.spp_opened()
                core.loop.post(core.channel_opened, sock)

            @dbus.service.method("org.bluez.Profile1", in_signature="o")
            def RequestDisconnection(self, dev):
                core.loop.post(core.channel_closed, "BlueZ requested disconnection")

            @dbus.service.method("org.bluez.Profile1")
            def Release(self):
                link.registered = False

        class FpProfile(dbus.service.Object):
            @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}")
            def NewConnection(self, dev, fd, props):
                sock = socket.socket(fileno=fd.take())
                link.connector.fp_opened()
                core.loop.post(core.fp_opened, sock)

            @dbus.service.method("org.bluez.Profile1", in_signature="o")
            def RequestDisconnection(self, dev):
                core.loop.post(core.fp_closed, "BlueZ requested disconnection")

            @dbus.service.method("org.bluez.Profile1")
            def Release(self):
                link.fp_registered = False

        def later(delay, fn):
            return GLib.timeout_add(max(0, int(delay * 1000)), lambda: (fn(), False)[1])

        def cancel(src):
            try:
                GLib.source_remove(src)
            except Exception:
                pass

        self.connector = Connector(core.t, call_later=later, cancel=cancel, connect=self._connect,
                                   a2dp_up=self._a2dp_up, has_fp=self._has_fp,
                                   on_error=lambda m: core.loop.post(core.link_error, m))
        self.profile = Profile(self.bus, self.PROFILE_PATH)
        self.fp_profile = FpProfile(self.bus, self.FP_PROFILE_PATH)
        self.bus.add_signal_receiver(self._props_changed, signal_name="PropertiesChanged",
                                     dbus_interface="org.freedesktop.DBus.Properties",
                                     bus_name="org.bluez", path_keyword="path")
        self.bus.add_signal_receiver(self._owner_changed, signal_name="NameOwnerChanged",
                                     dbus_interface="org.freedesktop.DBus", arg0="org.bluez")
        self.gloop = GLib.MainLoop()
        GLib.idle_add(lambda: (self._setup(), False)[1])
        self.ready.set()
        self.gloop.run()

    def _setup(self):
        dbus = self.dbus
        try:
            self._register()
            path, props = self._find_device()
        except dbus.DBusException as e:
            self.core.loop.post(self.core.link_error, "BlueZ: %s" % e.get_dbus_message())
            self.GLib.timeout_add_seconds(10, lambda: (self._setup(), False)[1])
            return
        if not path:
            self.core.loop.post(self.core.link_error,
                                "no paired EarFun device%s" % (" " + self.want_address
                                                               if self.want_address else ""))
            self.GLib.timeout_add_seconds(30, lambda: (self._setup(), False)[1])
            return
        self.device_path = path
        self._publish(props)
        if self.connected:
            self.connector.device_connected()

    def _manager(self):
        return self.dbus.Interface(self.bus.get_object("org.bluez", "/org/bluez"),
                                   "org.bluez.ProfileManager1")

    def _opts(self, name):
        B = self.dbus.Boolean
        return {"Name": name, "Role": "client", "RequireAuthentication": B(False),
                "RequireAuthorization": B(False), "AutoConnect": B(False)}

    def _register(self):
        if not self.registered:
            self._manager().RegisterProfile(self.PROFILE_PATH, P.SPP_UUID,
                                            self._opts("earfun-daemon"), timeout=10)
            self.registered = True
        if not self.fp_registered:
            try:
                self._manager().RegisterProfile(self.FP_PROFILE_PATH, P.FP_UUID,
                                                self._opts("earfun-fastpair"), timeout=10)
                self.fp_registered = True
            except self.dbus.DBusException as e:
                if "AlreadyExists" in (e.get_dbus_name() or ""):
                    self.fp_registered = True
                else:
                    log.warning("RegisterProfile Fast Pair: %s", e.get_dbus_message())

    def _unregister(self):
        if self.connector:
            self.connector.device_disconnected()
        for flag, path in (("registered", self.PROFILE_PATH), ("fp_registered", self.FP_PROFILE_PATH)):
            if getattr(self, flag):
                try:
                    self._manager().UnregisterProfile(path, timeout=5)
                except self.dbus.DBusException:
                    pass
                setattr(self, flag, False)

    def _find_device(self):
        om = self.dbus.Interface(self.bus.get_object("org.bluez", "/"),
                                 "org.freedesktop.DBus.ObjectManager")
        return pick_buds(om.GetManagedObjects(), self.want_address)

    def _a2dp_up(self):
        """A MediaTransport1 exists for the buds (A2DP connected, playing or idle)."""
        try:
            om = self.dbus.Interface(self.bus.get_object("org.bluez", "/"),
                                     "org.freedesktop.DBus.ObjectManager")
            for path, ifaces in om.GetManagedObjects().items():
                t = ifaces.get("org.bluez.MediaTransport1")
                if t and str(t.get("Device", "")) == self.device_path:
                    return True
        except self.dbus.DBusException as e:
            log.debug("GetManagedObjects: %s", e.get_dbus_message())
        return False

    def _has_fp(self):
        try:
            props = self.dbus.Interface(self.bus.get_object("org.bluez", self.device_path),
                                        "org.freedesktop.DBus.Properties")
            uuids = [str(u).lower() for u in props.Get("org.bluez.Device1", "UUIDs")]
        except self.dbus.DBusException:
            return False
        return self.fp_registered and P.FP_UUID in uuids

    def _connect(self, uuid, ok, err):
        try:
            self._register()
        except self.dbus.DBusException as e:
            log.warning("RegisterProfile: %s", e.get_dbus_message())
        dev = self.dbus.Interface(self.bus.get_object("org.bluez", self.device_path),
                                  "org.bluez.Device1")
        dev.ConnectProfile(uuid, reply_handler=ok, timeout=30, error_handler=lambda e: err(
            e.get_dbus_message() if hasattr(e, "get_dbus_message") else str(e)))

    def _publish(self, props):
        self.connected = bool(props.get("Connected", False))
        self.core.loop.post(self.core.device_changed, str(props.get("Address", "")),
                            str(props.get("Alias", props.get("Name", ""))), self.connected)

    def _props_changed(self, iface, changed, invalidated, path=None):
        if iface != "org.bluez.Device1" or path != self.device_path or "Connected" not in changed:
            return
        was, self.connected = self.connected, bool(changed["Connected"])
        dev = self.bus.get_object("org.bluez", self.device_path)
        props = self.dbus.Interface(dev, "org.freedesktop.DBus.Properties").GetAll("org.bluez.Device1")
        self._publish(props)
        if self.connected and not was:
            self.connector.device_connected()
        elif not self.connected:
            self.connector.device_disconnected()

    def _owner_changed(self, name, old, new):
        self.registered = self.fp_registered = False
        self.connector.device_disconnected()
        if new:                     # bluetoothd (re)started
            self.GLib.timeout_add_seconds(2, lambda: (self._setup(), False)[1])
        else:
            self.core.loop.post(self.core.device_changed, None, None, False)


# --------------------------------------------------------------------------- entry

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="earfun daemon")
    ap.add_argument("--fake", action="store_true", help="run against in-process fake buds")
    ap.add_argument("--address", help="buds address (default: first paired EarFun with SPP)")
    ap.add_argument("--socket", help="socket path (default $XDG_RUNTIME_DIR/earfun.sock)")
    ap.add_argument("--allow-unverified-sets", action="store_true",
                    help="also send SETs not verified on the real buds (live only)")
    ap.add_argument("--state", help="state file (default $XDG_STATE_HOME/earfun/state.json; "
                    "none under --fake)")
    ap.add_argument("--fake-mode-delay", type=float, default=1.5)
    ap.add_argument("-v", "--verbose", action="count", default=0)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s earfun %(levelname)s %(message)s")
    if a.fake:
        from .fake import FakeBuds, FakeFastPair
        link = FakeLink(FakeBuds(mode_delay=a.fake_mode_delay), fp=FakeFastPair())
    else:
        link = BluezLink(a.address)
    core = Core(link, a.socket, allow_unverified=a.allow_unverified_sets,
                state_path=a.state or (None if a.fake else default_state_path()))
    signal.signal(signal.SIGTERM, lambda *_: core.stop())
    signal.signal(signal.SIGINT, lambda *_: core.stop())
    core.run()
    return 0
