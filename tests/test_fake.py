import os
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earfun import protocol as P  # noqa: E402
from earfun.fake import FakeBuds  # noqa: E402


class Fake(unittest.TestCase):
    def setUp(self):
        self.buds = FakeBuds(mode_delay=0.3, unsolicited_every=0)
        self.s = self.buds.attach()
        self.s.settimeout(0.05)
        self.sp = P.FrameSplitter()

    def tearDown(self):
        self.buds.detach()
        self.s.close()

    def frames(self, wait=0.3):
        out, end = [], time.monotonic() + wait
        while time.monotonic() < end:
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            out += self.sp.feed(d)
        return out

    def ask_mode(self):
        self.s.sendall(P.encode_get(0x0315))
        return [P.decode_frame(f).get("mode") for f in self.frames(0.15) if f.base == 0x0315]

    def test_get_answer_shape(self):
        self.s.sendall(P.encode_get(0x0315))
        f = self.frames()[0]
        self.assertEqual(f.encode(), bytes.fromhex("ff 03 00 02 00 0a 83 15 00 00"))

    def test_mode_set_no_reply_then_delayed(self):
        self.s.sendall(P.SETTINGS["mode"].set_frames("anc")[0])
        self.assertEqual(self.frames(0.1), [])            # no reply to the set
        self.assertEqual(self.ask_mode(), ["off"])         # old value until applied
        time.sleep(0.35)
        self.assertEqual(self.ask_mode(), ["anc"])

    def test_concatenated_gets(self):
        self.s.sendall(P.encode_get(0x0306) + P.encode_get(0x0307) + P.encode_get(0x0317))
        fs = self.frames()
        self.assertEqual([f.base for f in fs], [0x0306, 0x0307, 0x0317])

    def test_unknown_get_ignored(self):
        self.s.sendall(P.encode_get(0x03EE))
        self.assertEqual(self.frames(0.15), [])

    def test_unsolicited_and_chunked(self):
        self.buds.detach()
        self.s.close()
        self.buds = FakeBuds(unsolicited_every=0.1, chunked=True, seed=3)
        self.s = self.buds.attach()
        self.s.settimeout(0.05)
        fs = self.frames(0.8)
        self.assertTrue(fs)
        self.assertTrue(all(not f.ack for f in fs))
        self.assertTrue({f.base for f in fs} <= {0x0358, 0x0350, 0x034D})

    def test_eq_band_answered(self):
        self.s.sendall(P.SETTINGS["eq"].set_frames("default")[0])
        fs = self.frames()
        self.assertEqual([(f.vendor, f.command, f.payload) for f in fs], [(0x001D, 0x0F81, b"\x01")])

    def test_detach_gives_eof(self):
        self.buds.detach()
        self.assertEqual(self.s.recv(10), b"")


if __name__ == "__main__":
    unittest.main()
