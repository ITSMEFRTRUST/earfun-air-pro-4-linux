import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from earfun import heal  # noqa: E402
from earfun.connect import pick_buds  # noqa: E402
from earfun.heal import Healer, classify  # noqa: E402
from earfun.protocol import SPP_UUID  # noqa: E402

MAC = "AA:BB:CC:DD:EE:FF"
# real journal lines, with the address replaced
BUSY = ("src/service.c:btd_service_connect() a2dp-sink profile connect failed for "
        "AA:BB:CC:DD:EE:FF: Device or resource busy")
FAIL = "spa.bluez5: Failure in Bluetooth audio transport /org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF/sep8/fd0"
ACQ = ("spa.bluez5: Acquire /org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF/fd0 returned error: "
       "org.freedesktop.DBus.Error.NoReply")


class Classify(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(classify(BUSY, MAC), "a2dp_busy")
        self.assertEqual(classify(FAIL, MAC), "transport")
        self.assertEqual(classify(ACQ, MAC), "acquire")
        self.assertEqual(classify(ACQ.replace("NoReply", "NotAuthorized"), MAC), "acquire")
        self.assertIsNone(classify(FAIL.replace("EE_FF", "EE_00"), MAC))
        self.assertIsNone(classify("plugins/policy.c:reconnect_timeout() Reconnecting services "
                                   "failed: Device or resource busy (16)", MAC))


class HealerTest(unittest.TestCase):
    def test_swap_reacts_within_2s(self):
        # drop at 1.38, buds back 40 ms later, busy at 2.94 and 3.94
        h = Healer()
        self.assertTrue(h.trigger("a2dp_busy", 2.94))
        self.assertAlmostEqual(h.due(), 3.94)            # settle 1 s, buds back > 1 s already
        h.trigger("a2dp_busy", 3.94)
        act, msg = h.check(3.94, True, 1.42, False)
        self.assertEqual(act, "reconnect")
        h.reconnected(10.0)
        self.assertFalse(h.trigger("transport", 11.0))      # echo of our own reconnect

    def test_waits_for_the_buds_own_reconnect(self):
        h = Healer()
        h.trigger("transport", 0.0)
        self.assertEqual(h.check(1.0, False, 0, False)[0], "wait")
        self.assertEqual(h.check(1.5, True, 1.5, False)[0], "wait")   # connected only now
        self.assertAlmostEqual(h.due(), 2.5)
        self.assertEqual(h.check(2.5, True, 1.5, False)[0], "reconnect")

    def test_busy_dropped_when_a2dp_came_up(self):
        h = Healer()
        h.trigger("a2dp_busy", 0.0)
        self.assertEqual(h.check(1.0, True, -10, True)[0], "drop")
        h.trigger("acquire", 5.0)
        self.assertEqual(h.check(6.0, True, -10, True)[0], "reconnect")   # transport exists but broken

    def test_buds_gone(self):
        h = Healer()
        h.trigger("transport", 0.0)
        self.assertEqual(h.check(13.0, False, 0, False)[0], "drop")

    def test_per_incident_cap_and_new_incident(self):
        h = Healer()
        t = 0.0
        for _ in range(3):
            h.trigger("transport", t)
            self.assertEqual(h.check(t + 1, True, -100, False)[0], "reconnect")
            h.reconnected(t + 8)
            t += 20
        h.trigger("transport", t)
        act, msg = h.check(t + 1, True, -100, False)
        self.assertEqual(act, "drop")
        self.assertIn("this incident", msg)
        # a later swap (> 60 s quiet) is a new incident
        t += 120
        h.trigger("a2dp_busy", t)
        self.assertEqual(h.check(t + 1, True, -100, False)[0], "reconnect")

    def test_global_guard(self):
        h = Healer()
        t = 0.0
        for i in range(6):
            h.trigger("transport", t)
            self.assertEqual(h.check(t + 1, True, -100, False)[0], "reconnect", i)
            h.reconnected(t + 8)
            t += 70                                          # each its own incident
        h.trigger("transport", t)
        self.assertEqual(h.check(t + 1, True, -100, False)[0], "drop")
        t = 700.0
        h.trigger("transport", t)
        self.assertEqual(h.check(t + 1, True, -100, False)[0], "reconnect")


class BluezState(unittest.TestCase):
    def test_state_with_stub_dbus(self):
        import types
        from earfun import heal
        dev = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        objs = {dev: {"org.bluez.Device1": {"Address": MAC, "Connected": True}},
                dev + "/sep8/fd0": {"org.bluez.MediaTransport1": {"Device": dev}}}

        class Iface:
            def __init__(self, obj, name):
                pass

            def GetManagedObjects(self):
                return objs

            def Get(self, iface, prop):
                return objs[dev]["org.bluez.Device1"][prop]
        stub = types.SimpleNamespace(SystemBus=lambda: types.SimpleNamespace(get_object=lambda *a: None),
                                     Interface=Iface, DBusException=Exception)
        old = sys.modules.get("dbus")
        sys.modules["dbus"] = stub
        try:
            b = heal.Bluez(MAC)
            self.assertEqual(b.state(False), (True, True))     # no path yet -> full scan
            self.assertEqual(b.state(False), (True, False))    # cheap property read
            objs[dev]["org.bluez.Device1"]["Connected"] = False
            self.assertEqual(b.state(True), (False, True))
        finally:
            if old is None:
                del sys.modules["dbus"]
            else:
                sys.modules["dbus"] = old


def device(addr, alias="EarFun Air Pro 4", paired=True, connected=False, uuids=(SPP_UUID,)):
    return {"org.bluez.Device1": {"Address": addr, "Alias": alias, "Paired": paired,
                                  "Connected": connected, "UUIDs": list(uuids)}}


class FindBuds(unittest.TestCase):
    A, B = "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"

    def test_pick_rules(self):
        self.assertEqual(pick_buds({}), (None, None))
        objs = {"/a": device(self.A, alias="Some Speaker"), "/b": device(self.A, paired=False),
                "/c": device(self.A, uuids=()), "/d": {"org.bluez.Adapter1": {}}}
        self.assertEqual(pick_buds(objs), (None, None))
        self.assertEqual(pick_buds(objs, self.A.lower())[0], "/a")     # an explicit address wins

    def test_pick_prefers_connected(self):
        objs = {"/a": device(self.A), "/b": device(self.B, connected=True)}
        self.assertEqual(pick_buds(objs)[1]["Address"], self.B)

    def test_env_wins_and_never_asks_bluez(self):
        def boom():
            raise AssertionError("asked BlueZ")
        self.assertEqual(heal.find_mac({"EARFUN_MAC": "aa:bb:cc:dd:ee:ff"}, boom), (MAC, None))

    def test_bad_env(self):
        mac, why = heal.find_mac({"EARFUN_MAC": "nonsense"}, lambda: {})
        self.assertIsNone(mac)
        self.assertIn("EARFUN_MAC", why)

    def test_auto_detect(self):
        self.assertEqual(heal.find_mac({}, lambda: {"/a": device(self.A)}), (self.A, None))

    def test_nothing_found(self):
        mac, why = heal.find_mac({}, lambda: {})
        self.assertIsNone(mac)
        self.assertIn("no paired EarFun", why)

    def test_bluez_unreachable(self):
        for exc in (ImportError("dbus"), RuntimeError("no bus")):
            def fail():
                raise exc
            mac, why = heal.find_mac({}, fail)
            self.assertIsNone(mac)
            self.assertTrue(why)

    def test_wait_logs_changes_only_then_returns(self):
        answers = iter([(None, "x"), (None, "y"), (None, "y"), (self.A, None)])
        lines, naps = [], []
        old, heal.log = heal.log, lines.append
        try:
            self.assertEqual(heal.wait_for_mac("x", lambda: next(answers), naps.append, 7), self.A)
        finally:
            heal.log = old
        self.assertEqual(naps, [7] * 4)
        self.assertEqual(lines, ["still no buds: y", "found the buds: " + self.A])

    def test_stdin_mode_without_buds_exits_cleanly(self):
        lines = []
        old_log, old_find = heal.log, heal.find_mac
        heal.log, heal.find_mac = lines.append, lambda: (None, "nothing here")
        try:
            self.assertEqual(heal.run(["--stdin"]), 0)
        finally:
            heal.log, heal.find_mac = old_log, old_find
        self.assertIn("nothing here", lines[0])
        self.assertIn("Doing nothing", lines[0])


class DryRun(unittest.TestCase):
    def test_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, DRY_RUN="1", EARFUN_MAC=MAC,
                       EARFUN_HEAL_LOCK=os.path.join(d, "lock"))
            r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "earfun-audio-heal"),
                                "--stdin"], input="noise\n%s\n%s\n" % (BUSY, FAIL), env=env,
                               capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("would run: bluetoothctl disconnect " + MAC, r.stdout)
            self.assertEqual(r.stdout.count("would run: bluetoothctl connect"), 1)
            self.assertFalse(os.path.exists(os.path.join(d, "lock")))

    def test_entry_point_with_a_bad_address_logs_and_exits_zero(self):
        env = dict(os.environ, DRY_RUN="1", EARFUN_MAC="nonsense")
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "earfun-audio-heal"), "--stdin"],
                           input="", env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Doing nothing", r.stdout)


if __name__ == "__main__":
    unittest.main()
