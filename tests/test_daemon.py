import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from earfun import protocol as P  # noqa: E402
from earfun.client import DaemonDown, request, watch  # noqa: E402
from earfun.daemon import Core, FakeLink, Timing  # noqa: E402
from earfun.fake import FakeBuds, FakeFastPair  # noqa: E402

FAST = Timing(poll=0.5, tx_gap=0.005, recheck=0.1, recheck_tries=8, get_timeout=1.0,
              first_answer=2.0, stale=30, connect_delay=0.1, reconnect=0.2, fp_delay=0.1,
              fp_retry=0.3, connect_backoff=(0.1, 0.2, 0.4), reconnect_cycle=0.5)
BIN = os.path.join(ROOT, "bin", "earfun")


def wait_for(fn, timeout=4.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("condition not met in %.1f s" % timeout)


class LiveLikeLink(FakeLink):
    """Fake buds, but the core treats them as real (unverified sets refused)."""
    source = "live"


class DaemonCase(unittest.TestCase):
    link_cls = FakeLink
    fp = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = os.path.join(self.tmp.name, "earfun.sock")
        self.state_path = os.path.join(self.tmp.name, "state", "state.json")
        self.lock = os.path.join(self.tmp.name, "earfun-heal.lock")
        self.buds = FakeBuds(mode_delay=0.3, unsolicited_every=0.3, chunked=True, seed=1)
        self.fpbuds = FakeFastPair() if self.fp else None
        self.start_core()
        wait_for(lambda: self.status()["settings"]["gesture_single_left"]["value"] == "play_pause")

    def start_core(self, prepare=None):
        self.link = self.link_cls(self.buds, fp=self.fpbuds, heal_lock=self.lock)
        if prepare:
            prepare(self.link)
        self.core = Core(self.link, self.sock, timing=FAST, state_path=self.state_path)
        self.thread = threading.Thread(target=self.core.run, daemon=True)
        self.thread.start()
        wait_for(lambda: os.path.exists(self.sock))

    def stop_core(self):
        self.core.loop.post(self.core.stop)
        self.thread.join(5)

    def tearDown(self):
        self.stop_core()
        self.tmp.cleanup()

    def req(self, **kw):
        return request(kw, self.sock, timeout=5)

    def status(self):
        return self.req(cmd="status")["state"]

    def on_loop(self, fn, *a):
        done = threading.Event()
        self.core.loop.post(lambda: (fn(*a), done.set()))
        done.wait(2)


class FakeDaemon(DaemonCase):
    def test_status_shape(self):
        st = self.status()
        for k in ("daemon", "connected", "name", "mode", "pending_mode", "battery",
                  "anc_style", "transparency_style", "firmware", "settings"):
            self.assertIn(k, st)
        self.assertIs(st["daemon"], True)
        self.assertIs(st["connected"], True)
        self.assertEqual(st["mode"], "off")
        self.assertEqual(st["anc_style"], "strong")
        self.assertEqual(st["firmware"], "TW600-3091_20250919_v0.4.1")
        b = st["battery"]
        self.assertEqual((b["left"], b["right"], b["case"], b["case_last"]), (80, 85, 60, 60))
        self.assertIsInstance(b["case_seen"], int)
        s = st["settings"]["mode"]
        self.assertEqual((s["value"], s["type"], s["options"], s["live_verified"]),
                         ("off", "enum", ["off", "anc", "ambient"], True))
        self.assertEqual(st["settings"]["game_mode"]["type"], "bool")
        self.assertEqual(st["settings"]["eq"]["type"], "eq")
        self.assertEqual(st["settings"]["gesture_single_left"]["value"], "play_pause")

    def test_socket_mode_0600(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.sock).st_mode), 0o600)

    def test_second_daemon_refused(self):
        other = Core(FakeLink(FakeBuds()), self.sock, timing=FAST)
        with self.assertRaises(SystemExit):
            other.serve()

    def test_set_mode_delayed_apply_and_pending(self):
        r = self.req(cmd="set", key="mode", value="anc")
        self.assertEqual((r["ok"], r["value"], r["pending"]), (True, "anc", True))
        st = self.status()
        self.assertEqual((st["mode"], st["pending_mode"]), ("off", "anc"))
        wait_for(lambda: self.status()["mode"] == "anc")
        self.assertIsNone(self.status()["pending_mode"])

    def test_set_wait_and_cycle(self):
        r = self.req(cmd="set", key="mode", value="ambient", wait=True)
        self.assertTrue(r["confirmed"])
        r = self.req(cmd="set", key="mode", value="cycle", wait=True)
        self.assertEqual((r["value"], r["confirmed"]), ("off", True))
        r = self.req(cmd="set", key="mode", value="cycle", wait=True)
        self.assertEqual(r["value"], "anc")

    def test_other_sets_on_fake(self):
        self.assertTrue(self.req(cmd="set", key="anc_style", value="balanced", wait=True)["confirmed"])
        self.assertTrue(self.req(cmd="set", key="gesture_long_right", value="next", wait=True)["confirmed"])
        self.assertEqual(self.status()["settings"]["gesture_long_left"]["value"], "noise_control_all")
        r = self.req(cmd="set", key="eq", value="vocal")
        self.assertEqual((r["ok"], r["pending"]), (True, False))
        self.assertEqual(self.status()["settings"]["eq"]["value"]["preset"], "vocal")
        wait_for(lambda: len([f for f in self.buds.received if f.base == 0x0E01]) == 10)
        self.assertTrue(self.req(cmd="set", key="voice_prompt_volume", value="4", wait=True)["confirmed"])
        self.assertEqual(self.buds.value(0x0339), b"\x00")

    def test_bad_values(self):
        for key, value in (("mode", "loud"), ("anc_style", "x"), ("nope", 1), ("firmware", "x")):
            r = self.req(cmd="set", key=key, value=value)
            self.assertFalse(r["ok"], key)
            self.assertTrue(r["error"])
        self.assertFalse(self.req(cmd="bogus")["ok"])

    def test_get_refresh(self):
        self.buds.set_battery(left=42)
        r = self.req(cmd="get", key="battery_left")
        self.assertEqual(r["value"], 42)
        self.buds.set_battery(case=0xFF)
        self.assertIsNone(self.req(cmd="get", key="battery_case")["value"])
        self.assertTrue(self.req(cmd="get", key="eq")["cached"])
        r = self.req(cmd="get", key="find_device")      # answered without ack bit
        self.assertEqual(r["value"], "off")
        self.assertNotIn("timeout", r)

    def test_poll_picks_up_external_change(self):
        self.buds.set_mode_on_buds("ambient")
        self.buds.set_battery(right=50)
        wait_for(lambda: self.status()["mode"] == "ambient" and self.status()["battery"]["right"] == 50)

    def test_unsolicited_tolerated(self):
        wait_for(lambda: self.status()["playing"] is False)
        wait_for(lambda: self.status()["settings"]["audio_mode_raw"]["value"] == 3)

    def test_watch_stream(self):
        seen = []
        stop = threading.Event()

        def run():
            try:
                for st in watch(self.sock):
                    seen.append(st)
                    if stop.is_set():
                        return
            except DaemonDown:
                pass
        t = threading.Thread(target=run, daemon=True)
        t.start()
        wait_for(lambda: seen)
        self.assertEqual(seen[0]["mode"], "off")
        self.req(cmd="set", key="mode", value="anc")
        wait_for(lambda: any(s["pending_mode"] == "anc" for s in seen))
        wait_for(lambda: seen[-1]["mode"] == "anc" and seen[-1]["pending_mode"] is None)
        # once the unsolicited frames have each been seen, polls with no change emit nothing
        wait_for(lambda: seen[-1]["playing"] is not None
                 and seen[-1]["settings"]["audio_mode_raw"]["value"] is not None
                 and len(seen[-1]["settings"]["phone_list_raw"]["value"] or []) == 2)
        n = len(seen)
        time.sleep(1.2)
        self.assertEqual(len(seen) - n, 0)
        stop.set()

    def test_channel_drop_reconnects(self):
        self.buds.detach()
        wait_for(lambda: self.status()["channel"] != "connected")
        wait_for(lambda: self.status()["connected"] and self.status()["mode"] == "off")

    def test_device_disconnect_and_back(self):
        self.on_loop(self.link.set_present, False)
        st = wait_for(lambda: (lambda s: s if s["channel"] == "disconnected" else None)(self.status()))
        self.assertFalse(st["connected"])
        self.assertIsNone(st["mode"])
        b = st["battery"]
        self.assertEqual((b["left"], b["right"], b["case"]), (None, None, None))
        self.assertEqual(b["case_last"], 60)        # the last real level outlives the connection
        self.assertEqual(st["firmware"], "TW600-3091_20250919_v0.4.1")
        r = self.req(cmd="set", key="mode", value="anc")
        self.assertFalse(r["ok"])
        self.on_loop(self.link.set_present, True)
        wait_for(lambda: self.status()["connected"] and self.status()["battery"]["left"] == 80)


class FastPairBattery(DaemonCase):
    fp = True

    def test_fp_fills_gaps_and_case_persists(self):
        # GAIA: case 0xFF (lid shut); the Fast Pair stream knows 34 % charging
        self.buds.set_battery(case=0xFF)
        self.fpbuds.set_battery(case=0xA2)
        st = wait_for(lambda: (lambda s: s if s["battery"]["case"] == 34 else None)(self.status()))
        self.assertTrue(st["battery"]["charging"]["case"])
        self.assertEqual(st["battery"]["left"], 80)          # GAIA wins when it has a value
        self.assertEqual(st["battery"]["case_last"], 34)
        with open(self.state_path) as f:
            self.assertEqual(json.load(f)["case_last"], 34)
        # case stops reporting on both: live null, last value kept
        self.fpbuds.set_battery(case=0x7F)
        st = wait_for(lambda: (lambda s: s if s["battery"]["case"] is None else None)(self.status()))
        self.assertEqual(st["battery"]["case_last"], 34)
        seen = st["battery"]["case_seen"]
        self.assertLessEqual(abs(seen - time.time()), 5)
        # daemon restart with the buds away: case_last/case_seen come back from state.json
        self.stop_core()
        self.start_core(prepare=lambda link: setattr(link, "present", False))
        st = self.status()
        self.assertEqual((st["battery"]["case"], st["battery"]["case_last"]), (None, 34))
        self.assertEqual(st["battery"]["case_seen"], seen)

    def test_fp_only_when_spp_open_and_reopened(self):
        wait_for(lambda: self.core.fp_sock is not None)
        uuids = [u for u, _ in self.link.connector.attempts]
        self.assertEqual(uuids[:2], [P.SPP_UUID, P.FP_UUID])
        self.fpbuds.detach()
        wait_for(lambda: self.core.fp_sock is None)
        wait_for(lambda: self.core.fp_sock is not None)


class ReconnectPolicy(DaemonCase):
    def reconnect_with(self, prepare):
        self.on_loop(self.link.set_present, False)
        wait_for(lambda: self.status()["channel"] == "disconnected")
        prepare()
        self.on_loop(self.link.set_present, True)

    def test_busy_backs_off_then_connects(self):
        def prep():
            self.link.busy = 3
        self.reconnect_with(prep)
        wait_for(lambda: self.status()["connected"], timeout=5)
        times = [t for u, t in self.link.connector.attempts][-4:]
        gaps = [b - a for a, b in zip(times, times[1:])]
        for got, want in zip(gaps, (0.1, 0.2, 0.4)):
            self.assertGreaterEqual(got, want)

    def test_waits_while_heal_reconnects(self):
        def prep():
            open(self.lock, "w").close()
        n = len(self.link.connector.attempts)
        self.reconnect_with(prep)
        time.sleep(0.8)
        self.assertEqual(len(self.link.connector.attempts), n)
        self.assertNotEqual(self.status()["channel"], "connected")
        os.unlink(self.lock)
        wait_for(lambda: self.status()["connected"], timeout=5)

    def test_waits_for_a2dp(self):
        def prep():
            self.link.a2dp = False
        n = len(self.link.connector.attempts)
        self.reconnect_with(prep)
        time.sleep(0.6)
        self.assertEqual(len(self.link.connector.attempts), n)
        self.link.a2dp = True
        wait_for(lambda: self.status()["connected"], timeout=5)


class LiveGate(DaemonCase):
    link_cls = LiveLikeLink

    def test_only_verified_sets_go_out(self):
        before = len(self.buds.received)
        for key, value in (("anc_style", "balanced"), ("eq", "vocal"), ("find_device", "both"),
                           ("device_name", "x"), ("reboot", "now"), ("dual_connection", "off")):
            r = self.req(cmd="set", key=key, value=value)
            self.assertFalse(r["ok"], key)
            self.assertTrue(r.get("refused"), key)
        time.sleep(0.1)
        sent = [f for f in self.buds.received[before:] if f.payload or f.base not in P.on_connect_gets()]
        self.assertEqual(sent, [])
        self.assertTrue(self.req(cmd="set", key="mode", value="anc", wait=True)["confirmed"])


class Cli(DaemonCase):
    def cli(self, *args, timeout=10):
        return subprocess.run([sys.executable, "-I", BIN, "--socket", self.sock] + list(args),
                              capture_output=True, text=True, timeout=timeout)

    def test_cli(self):
        r = self.cli("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = json.loads(r.stdout)
        self.assertEqual(st["battery"]["left"], 80)
        r = self.cli("mode", "anc", "--wait")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("confirmed", r.stdout)
        self.assertEqual(self.cli("get", "mode").stdout.strip(), "anc")
        r = self.cli("set", "anc_style", "nonsense")
        self.assertEqual(r.returncode, 1)
        self.assertIn("expected one of", r.stderr)
        self.assertEqual(self.cli("set", "game_mode", "on").returncode, 0)
        r = self.cli("status")
        self.assertIn("battery:  L 80%", r.stdout)

    def test_cli_daemon_down(self):
        sock = os.path.join(self.tmp.name, "none.sock")
        r = subprocess.run([sys.executable, "-I", BIN, "--socket", sock, "status", "--json"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout), {"daemon": False})
        r = subprocess.run([sys.executable, "-I", BIN, "--socket", sock, "mode", "anc"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not running", r.stderr)
        p = subprocess.Popen([sys.executable, "-I", BIN, "--socket", sock, "watch"],
                             stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(json.loads(p.stdout.readline()), {"daemon": False})
        finally:
            p.kill()
            p.wait()
            p.stdout.close()

    def test_cli_watch_lines(self):
        p = subprocess.Popen([sys.executable, "-I", BIN, "--socket", self.sock, "watch"],
                             stdout=subprocess.PIPE, text=True)
        try:
            first = json.loads(p.stdout.readline())
            self.assertIs(first["daemon"], True)
            self.req(cmd="set", key="mode", value="ambient")
            while True:
                st = json.loads(p.stdout.readline())
                if st["mode"] == "ambient":
                    break
        finally:
            p.kill()
            p.wait()
            p.stdout.close()


if __name__ == "__main__":
    unittest.main()
