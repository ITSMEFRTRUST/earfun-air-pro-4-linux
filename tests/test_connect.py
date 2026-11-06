import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earfun import protocol as P  # noqa: E402
from earfun.connect import Connector, heal_busy  # noqa: E402
from earfun.daemon import Timing  # noqa: E402


class Sim:
    """Virtual clock + timer queue + scripted ConnectProfile results."""

    def __init__(self, **kw):
        self.now = 100.0
        self.timers = []
        self.a2dp = False
        self.heal = False
        self.fp = True
        self.results = []          # per call: None = ok, str = error
        self.calls = []
        self.errors = []
        self.c = Connector(Timing(**kw), call_later=self.later, cancel=self.cancel,
                           connect=self.connect, a2dp_up=lambda: self.a2dp, has_fp=lambda: self.fp,
                           heal_busy=lambda: self.heal, on_error=self.errors.append,
                           clock=lambda: self.now)

    def later(self, d, fn):
        h = [self.now + d, fn]
        self.timers.append(h)
        return h

    def cancel(self, h):
        if h in self.timers:
            self.timers.remove(h)

    def connect(self, uuid, ok, err):
        self.calls.append((uuid, round(self.now - 100.0, 2)))
        r = self.results.pop(0) if self.results else None
        if r is None:
            ok()
            (self.c.spp_opened if uuid == P.SPP_UUID else self.c.fp_opened)()
        else:
            self.later(0.05, lambda: err(r))

    def run(self, until):
        while self.timers:
            self.timers.sort(key=lambda h: h[0])
            if self.timers[0][0] > 100.0 + until:
                break
            t, fn = self.timers.pop(0)
            self.now = t
            fn()
        self.now = 100.0 + until


class ConnectorTest(unittest.TestCase):
    def test_waits_for_a2dp_then_spp_then_fp(self):
        s = Sim()
        s.c.device_connected()
        s.run(3.0)
        self.assertEqual(s.calls, [])              # A2DP not up yet, < 6 s
        s.a2dp = True
        s.run(10.0)
        self.assertEqual([u for u, _ in s.calls], [P.SPP_UUID, P.FP_UUID])
        self.assertGreaterEqual(s.calls[0][1], 3.0)
        self.assertGreaterEqual(s.calls[1][1] - s.calls[0][1], 2.0)   # fp_delay after SPP

    def test_gives_up_waiting_for_a2dp_after_6s(self):
        s = Sim()
        s.c.device_connected()
        s.run(20.0)
        self.assertEqual(s.calls[0][0], P.SPP_UUID)
        self.assertGreaterEqual(s.calls[0][1], 6.0)
        self.assertLess(s.calls[0][1], 7.0)

    def test_busy_backs_off(self):
        s = Sim()
        s.a2dp = True
        s.results = ["br-connection-busy"] * 5
        s.c.device_connected()
        s.run(120.0)
        spp = [t for u, t in s.calls if u == P.SPP_UUID]
        gaps = [b - a for a, b in zip(spp, spp[1:])]
        self.assertEqual(len(gaps), 5)
        for got, want in zip(gaps, [3, 6, 12, 24, 30]):
            self.assertAlmostEqual(got, want, delta=0.11)
        self.assertEqual(len(s.errors), 1)
        self.assertIn(P.FP_UUID, [u for u, _ in s.calls])

    def test_never_while_heal_holds_the_lock(self):
        s = Sim()
        s.a2dp = True
        s.heal = True
        s.c.device_connected()
        s.run(30.0)
        self.assertEqual(s.calls, [])
        s.heal = False
        s.run(32.0)
        self.assertEqual(s.calls[0][0], P.SPP_UUID)

    def test_no_fp_without_uuid_and_disconnect_cancels(self):
        s = Sim()
        s.a2dp = True
        s.fp = False
        s.c.device_connected()
        s.run(10.0)
        self.assertEqual([u for u, _ in s.calls], [P.SPP_UUID])
        s.c.spp_lost()
        s.c.device_disconnected()
        s.run(60.0)
        self.assertEqual(len(s.calls), 1)

    def test_one_in_flight(self):
        s = Sim()
        s.a2dp = True
        pending = []
        s.c.connect = lambda uuid, ok, err: pending.append(uuid)
        s.c.device_connected()
        s.run(2.0)
        s.c.spp_lost()                # would reschedule, but a call is still in flight
        s.run(20.0)
        self.assertEqual(pending, [P.SPP_UUID])


class HealLock(unittest.TestCase):
    def test_lock_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "earfun-heal.lock")
            self.assertFalse(heal_busy(p))
            open(p, "w").close()
            self.assertTrue(heal_busy(p))
            self.assertFalse(heal_busy(p, now=time.time() + 60))   # stale leftover


if __name__ == "__main__":
    unittest.main()
