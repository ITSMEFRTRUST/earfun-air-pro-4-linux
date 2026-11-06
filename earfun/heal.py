"""earfun-audio-heal: reconnect the buds when their A2DP stream breaks while they stay connected.

Which buds: $EARFUN_MAC, else the paired EarFun device BlueZ knows (connect.pick_buds, the daemon's
own rule).  With neither it logs why and does nothing: the service keeps checking every 30 s, in case
the buds get paired later, and --stdin / DRY_RUN=1 exit 0.

Triggers:
  * wireplumber (user journal): "Failure in Bluetooth audio transport /org/bluez/hciN/dev_X/..."
    and "Acquire /org/bluez/hciN/dev_X/... returned error: ..." (NoReply, NotAuthorized, ...);
  * bluetoothd (system journal, so the user must be able to read it): "a2dp-sink profile connect failed for X: Device or
    resource busy" -- LIVE bud swap: the buds reconnect on their own ~40 ms after dropping,
    bluetoothd's own A2DP reconnect collides with them and nothing plays.

Action: full `bluetoothctl disconnect` + `connect` (re-selecting the profile or reconnecting only A2DP
did not help), holding $XDG_RUNTIME_DIR/earfun-heal.lock so the earfun daemon keeps its
ConnectProfile calls out of the way.  Timing: act ~1 s after the trigger and >= 1 s after the buds'
own reconnect; a busy-only trigger is dropped when A2DP came up anyway (a MediaTransport1 exists).
Caps: 3 reconnects per incident (an incident ends after 60 s without triggers) and 6 per 10 min.

Usage: earfun-audio-heal [--stdin]   (--stdin reads log lines from stdin; DRY_RUN=1 only prints)
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time

from .connect import heal_lock_path, pick_buds

MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
FIND_RETRY = 30.0


def log(msg):
    print(msg, flush=True)


def bluez_objects():
    """BlueZ's GetManagedObjects(); raises ImportError / DBusException when it cannot be asked."""
    import dbus
    om = dbus.Interface(dbus.SystemBus().get_object("org.bluez", "/"),
                        "org.freedesktop.DBus.ObjectManager")
    return om.GetManagedObjects()


def find_mac(env=None, objects=bluez_objects):
    """(address, None), or (None, why not)."""
    raw = (os.environ if env is None else env).get("EARFUN_MAC", "").strip()
    if raw:
        mac = raw.upper()
        if MAC_RE.match(mac):
            return mac, None
        return None, "EARFUN_MAC=%r is not a Bluetooth address" % raw
    try:
        objs = objects()
    except ImportError:
        return None, "python-dbus is not installed, so BlueZ cannot be asked"
    except Exception as e:      # dbus.DBusException, but dbus may be stubbed or missing
        return None, "cannot ask BlueZ (%s)" % e
    _, props = pick_buds(objs)
    if props is None:
        return None, "BlueZ knows no paired EarFun device offering SPP"
    return str(props["Address"]).upper(), None


def wait_for_mac(why, find=find_mac, sleep=time.sleep, retry=FIND_RETRY):
    """Idle until the buds can be found; repeats the reason only when it changes."""
    while True:
        sleep(retry)
        mac, now = find()
        if mac:
            log("found the buds: " + mac)
            return mac
        if now != why:
            log("still no buds: " + now)
            why = now


def classify(line: str, mac: str):
    mac = mac.upper()
    dev = "dev_" + mac.replace(":", "_")
    if "a2dp-sink profile connect failed for " + mac in line and "busy" in line:
        return "a2dp_busy"
    if re.search(r"Failure in Bluetooth audio transport /org/bluez/hci\d+/%s/" % dev, line):
        return "transport"
    if re.search(r"Acquire /org/bluez/hci\d+/%s/\S* returned error" % dev, line):
        return "acquire"
    return None


class Healer:
    """Pure decision logic; the caller feeds triggers and device state with its own clock."""

    def __init__(self, settle=1.0, wait_connect=12.0, quiet=3.0, incident_gap=60.0,
                 per_incident=3, global_max=6, global_window=600.0):
        self.settle, self.wait_connect, self.quiet = settle, wait_connect, quiet
        self.incident_gap, self.per_incident = incident_gap, per_incident
        self.global_max, self.global_window = global_max, global_window
        self.pending = None           # {"kinds", "first", "at"}
        self.quiet_until = 0.0
        self.incident_last = None
        self.incident_count = 0
        self.gave_up = False
        self.history = []

    def trigger(self, kind, now) -> bool:
        """False = ignored (echo of our own reconnect)."""
        if now < self.quiet_until:
            return False
        if self.incident_last is None or now - self.incident_last > self.incident_gap:
            self.incident_count, self.gave_up = 0, False
        self.incident_last = now
        if self.pending is None:
            self.pending = {"kinds": {kind}, "first": now, "at": now + self.settle}
        else:
            self.pending["kinds"].add(kind)
        return True

    def due(self):
        return self.pending["at"] if self.pending else None

    def check(self, now, connected, connected_since, has_transport):
        """-> ("reconnect" | "wait" | "drop", message)."""
        p = self.pending
        if p is None:
            return "drop", None
        if not connected:
            if now - p["first"] > self.wait_connect:
                self.pending = None
                return "drop", "buds stayed disconnected; nothing to heal"
            p["at"] = now + 0.25
            return "wait", None
        if now - connected_since < self.settle:
            p["at"] = connected_since + self.settle
            return "wait", None
        kinds = sorted(p["kinds"])
        if kinds == ["a2dp_busy"] and has_transport:
            self.pending = None
            return "drop", "A2DP busy, but it came up anyway; leaving it"
        self.pending = None
        if self.incident_count >= self.per_incident:
            if self.gave_up:
                return "drop", None
            self.gave_up = True
            return "drop", ("audio still failing after %d reconnects in this incident; "
                            "leaving it alone" % self.per_incident)
        self.history = [t for t in self.history if now - t < self.global_window]
        if len(self.history) >= self.global_max:
            return "drop", ("%d reconnects in %d min; leaving it alone"
                            % (self.global_max, self.global_window // 60))
        self.incident_count += 1
        self.history.append(now)
        return "reconnect", "%s while connected -> reconnecting" % "+".join(kinds)

    def reconnected(self, now):
        self.quiet_until = now + self.quiet


# --------------------------------------------------------------------------- runner

class Bluez:
    def __init__(self, mac):
        import dbus
        self.dbus = dbus
        self.bus = dbus.SystemBus()
        self.mac = mac.upper()
        self.path = None

    def _objects(self):
        om = self.dbus.Interface(self.bus.get_object("org.bluez", "/"),
                                 "org.freedesktop.DBus.ObjectManager")
        return om.GetManagedObjects()

    def state(self, full):
        """(connected, has_transport) for the buds; has_transport only with full=True (one
        GetManagedObjects), else a single property read."""
        try:
            if not full and self.path:
                props = self.dbus.Interface(self.bus.get_object("org.bluez", self.path),
                                            "org.freedesktop.DBus.Properties")
                return bool(props.Get("org.bluez.Device1", "Connected")), False
            objs = self._objects()
        except self.dbus.DBusException:
            self.path = None
            return False, False
        connected = False
        self.path = None
        for p, ifaces in objs.items():
            d = ifaces.get("org.bluez.Device1")
            if d and str(d.get("Address", "")).upper() == self.mac:
                self.path, connected = str(p), bool(d.get("Connected"))
                break
        has_t = self.path is not None and any(
            str(i["org.bluez.MediaTransport1"].get("Device", "")) == self.path
            for i in objs.values() if "org.bluez.MediaTransport1" in i)
        return connected, has_t


def _follow(cmd, q, stop_on_eof=False):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1) if cmd else None
    src = p.stdout if p else sys.stdin
    for line in src:
        q.put(line)
    q.put(None if stop_on_eof else "")


def run(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = os.environ.get("DRY_RUN") == "1"
    mac, why = find_mac()
    if mac is None:
        log("no buds to watch: %s. Set EARFUN_MAC or pair the buds. Doing nothing." % why)
        if dry or "--stdin" in argv:
            return 0
        mac = wait_for_mac(why)
    q = queue.Queue()
    if "--stdin" in argv:
        threading.Thread(target=_follow, args=(None, q, True), daemon=True).start()
    else:
        for cmd in (["journalctl", "--user", "-f", "-n0", "-o", "cat", "-u", "wireplumber"],
                    ["journalctl", "-f", "-n0", "-o", "cat", "-u", "bluetooth"]):
            threading.Thread(target=_follow, args=(cmd, q), daemon=True).start()
    bluez = None if dry else Bluez(mac)
    h = Healer()
    connected, since = (True, 0.0) if dry else (False, 0.0)
    lock = heal_lock_path()

    def sh(*cmd, timeout):
        if dry:
            log("would run: " + " ".join(cmd))
            return True
        try:
            return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=timeout).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def reconnect():
        with open(lock, "w") as f:
            f.write(str(os.getpid()))
        try:
            sh("bluetoothctl", "disconnect", mac, timeout=10)
            time.sleep(0 if dry else 3)
            ok = sh("bluetoothctl", "connect", mac, timeout=20)
            log("reconnected" if ok else "reconnect failed")
            time.sleep(0 if dry else 1)
        finally:
            try:
                os.unlink(lock)
            except FileNotFoundError:
                pass

    eof = False
    while True:
        now = time.monotonic()
        due = h.due()
        if eof and due is None:
            return 0
        timeout = 1.0 if due is None else max(0.0, min(1.0, due - now))
        try:
            line = q.get(timeout=timeout)
        except queue.Empty:
            line = ""
        if line is None:
            eof = True
        now = time.monotonic()
        kind = classify(line, mac) if line else None
        if kind:
            h.trigger(kind, now)
        due = h.due()
        checking = due is not None and now >= due
        c, has_t = bluez.state(full=checking) if bluez is not None else (True, False)
        if c and not connected:
            since = now
        connected = c
        if checking:
            action, msg = h.check(now, connected, since, has_t)
            if msg:
                log(msg)
            if action == "reconnect":
                reconnect()
                h.reconnected(time.monotonic())


def main():
    try:
        return run()
    except KeyboardInterrupt:
        return 0
