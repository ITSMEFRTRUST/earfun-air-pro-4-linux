import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earfun import protocol as P  # noqa: E402

H = bytes.fromhex


class Frames(unittest.TestCase):
    def test_get_bytes_match_capture(self):
        self.assertEqual(P.encode_get(0x0315), H("ff 04 00 00 00 0a 03 15"))
        self.assertEqual(P.SETTINGS["mode"].set_frames("anc"), [H("ff 04 00 01 00 0a 03 14 01")])
        self.assertEqual(P.SETTINGS["mode"].set_frames("off"), [H("ff 04 00 01 00 0a 03 14 00")])

    def test_decode_answer(self):
        f = P.decode(H("ff 03 00 02 00 0a 83 15 00 01"))
        self.assertTrue(f.ack)
        self.assertEqual((f.base, f.status, f.value), (0x0315, 0, b"\x01"))
        self.assertEqual(P.decode_frame(f), {"mode": "anc"})

    def test_firmware_and_gaia(self):
        f = P.decode(H("ff 03 00 1b 00 0a 83 09 00") + b"TW600-3091_20250919_v0.4.1")
        self.assertEqual(P.decode_frame(f), {"firmware": "TW600-3091_20250919_v0.4.1"})
        f = P.decode(H("ff 03 00 04 00 0a 83 00 00 03 03 01"))
        self.assertEqual(P.decode_frame(f), {"gaia_api": "3.3.1"})

    def test_battery_unavailable(self):
        f = P.decode(H("ff 03 00 02 00 0a 83 17 00 ff"))
        self.assertEqual(P.decode_frame(f), {"battery_case": None})
        f = P.decode(H("ff 03 00 02 00 0a 83 06 00 64"))
        self.assertEqual(P.decode_frame(f), {"battery_left": 100})

    def test_splitter_concatenated(self):
        # one read from the capture, three frames from the buds
        data = H("ff 03 00 05 00 0a 03 58 00 5c 3b 4d 01 ff 03 00 05 00 0a 03 58 00 33 4e e5 00 "
                 "ff 03 00 02 00 0a 03 4d 00 03")
        frames = P.FrameSplitter().feed(data)
        self.assertEqual([f.base for f in frames], [0x0358, 0x0358, 0x034D])
        self.assertFalse(any(f.ack for f in frames))
        self.assertEqual(P.decode_frame(frames[2]), {"audio_mode_raw": 3})

    def test_splitter_partial_byte_by_byte(self):
        data = H("ff 03 00 02 00 0a 83 15 00 02 ff 03 00 02 00 0a 03 50 00 01")
        sp = P.FrameSplitter()
        out = []
        for b in data:
            out += sp.feed(bytes([b]))
        self.assertEqual([(f.base, f.value) for f in out], [(0x0315, b"\x02"), (0x0350, b"\x01")])
        self.assertEqual(P.decode_frame(out[1]), {"playing": False})

    def test_splitter_garbage(self):
        sp = P.FrameSplitter()
        out = sp.feed(H("00 ff ff 07 12 ff 03 00 02 00 0a 83 07 00 55 aa"))
        self.assertEqual([(f.base, f.value) for f in out], [(0x0307, b"\x55")])
        self.assertGreater(sp.dropped, 0)

    def test_decode_rejects_not_one_frame(self):
        with self.assertRaises(ValueError):
            P.decode(H("ff 03 00 02 00 0a 83 15 00"))


class Encodings(unittest.TestCase):
    def test_gesture_payloads(self):
        # GB EarFunPacketEncoderTest: SINGLE, LEFT, action 1 -> 01 01 00 00
        self.assertEqual(P.SETTINGS["gesture_single_left"].set_frames("play_pause"),
                         [P.encode(0x030A, b"\x01\x01\x00\x00")])
        self.assertEqual(P.SETTINGS["gesture_long_right"].set_frames("next"),
                         [P.encode(0x030A, b"\x00\x00\x11\x05")])

    def test_touch_action_answer(self):
        v = bytes([0, 1, 0, 1, 0, 5, 0, 4, 0, 3, 0, 2, 0x12, 8, 0, 16])
        d = P.decode_touch_actions(v)
        self.assertEqual(d["gesture_single_left"], "play_pause")
        self.assertEqual(d["gesture_double_right"], "previous")
        self.assertEqual(d["gesture_long_left"], "noise_control_all")   # high byte ignored (GB)
        self.assertEqual(d["gesture_long_right"], "none")
        self.assertNotIn("gesture_extra_raw", d)

    def test_touch_action_live_answer(self):
        f = P.decode(H("ff 03 00 21 00 0a 83 0b 00 01 01 01 01 02 05 02 05 03 10 03 10 11 09 11 09 "
                       "04 00 04 00 05 00 05 00 06 06 06 06 13 04 13 04"))
        d = P.decode_frame(f)
        self.assertEqual([d["gesture_%s_left" % t] for t in ("single", "double", "triple", "long")],
                         ["play_pause", "next", "none", "noise_control_normal_wind"])
        self.assertEqual(d["gesture_extra_raw"], "04000400050005000606060613041304")

    def test_find_device_answer_without_ack(self):
        f = P.decode(H("ff 03 00 02 00 0a 03 33 00 00"))      # LIVE: no ack bit
        self.assertEqual(P.decode_frame(f), {"find_device": "off"})

    def test_eq(self):
        frames = P.SETTINGS["eq"].set_frames("bass_boost")
        self.assertEqual(len(frames), 10)
        self.assertEqual(sum(map(len, frames)), 170)   # GB EarFunPacketEncoderTest
        self.assertEqual(frames[0], H("ff 04 00 09 00 1d 0e 01 a1 ff 98 00 5e 01 20 0b 33"))
        neg = P.SETTINGS["eq"].set_frames(",".join(["-5"] * 10))[9]
        self.assertEqual(neg[8:], H("aa ff 98 bb 80 ff 4c 0b 33"))
        self.assertEqual(P.SETTINGS["eq"].codec.parse("8 6 4 2 0 0 0 0 0 0")["preset"], "bass_boost")
        with self.assertRaises(ValueError):
            P.SETTINGS["eq"].codec.parse("11,0,0,0,0,0,0,0,0,0")

    def test_inversions(self):
        s = P.SETTINGS["voice_prompt_volume"]
        self.assertEqual(s.set_frames(4), [P.encode(0x0338, b"\x00")])     # loudest = wire 00
        self.assertEqual(s.codec.decode(b"\x01"), 3)
        s = P.SETTINGS["in_ear_detection"]
        self.assertEqual(s.set_frames("on"), [P.encode(0x0349, b"\x00")])  # 'disable' = 0
        self.assertTrue(s.codec.decode(b"\x00"))

    def test_dual_connection_reboots(self):
        fr = P.SETTINGS["dual_connection"].set_frames("on")
        self.assertEqual(fr, [P.encode(0x0327, b"\x01"), P.encode(0x0308)])

    def test_every_settable_key_encodes(self):
        samples = {"enum": None, "bool": "on", "int": None, "text": "Buds", "eq": "default",
                   "action": None}
        for s in P.iter_table():
            if not s.settable:
                continue
            c = s.codec
            v = samples.get(c.kind)
            if v is None:
                v = (list(c.values)[0] if isinstance(c, P.Enum) else
                     list(c.names)[0] if isinstance(c, P.Action) else c.lo)
            frames = s.set_frames(c.parse(v))
            self.assertTrue(frames, s.key)
            for f in frames:
                self.assertEqual(f[0], 0xFF)
                self.assertEqual(f[3], len(f) - 8)

    def test_live_verified_sets(self):
        self.assertEqual(sorted(s.key for s in P.iter_table() if s.verified_set),
                         ["advanced_audio", "audio_codec", "mode"])
        meta = {s.key: P.setting_meta(s) for s in P.iter_table()}
        self.assertTrue(meta["mode"]["live_verified"])
        self.assertTrue(meta["battery_left"]["live_verified"])
        self.assertFalse(meta["anc_style"]["live_verified"])
        self.assertEqual(meta["mode"]["options"], ["off", "anc", "ambient"])
        self.assertEqual(meta["voice_prompt_volume"]["type"], "int")

    def test_every_command_named(self):
        for s in P.iter_table():
            for c in (s.get, s.set):
                if c is not None:
                    self.assertIn((s.vendor if s.key != "eq" else P.VENDOR_V3, c), P.COMMAND_NAMES)


class FastPair(unittest.TestCase):
    def test_split_and_battery(self):
        # LIVE frames: model id f3d9b4, battery 50 64 7f
        data = P.encode_fp(3, 1, bytes.fromhex("f3d9b4")) + P.encode_fp(3, 3, bytes.fromhex("50647f"))
        sp = P.FpSplitter()
        frames = sp.feed(data[:5]) + sp.feed(data[5:9]) + sp.feed(data[9:])
        self.assertEqual([(f.group, f.code) for f in frames], [(3, 1), (3, 3)])
        self.assertEqual(P.decode_fp(frames[0]), {})
        b = P.decode_fp(frames[1])
        self.assertEqual((b["left"], b["right"], b["case"]), (80, 100, None))
        self.assertEqual(b["charging"], {"left": False, "right": False, "case": None})

    def test_charging_bit(self):
        b = P.decode_fp(P.FpFrame(3, 3, bytes([0x7F, 0x0A, 0xA2])))
        self.assertEqual((b["left"], b["right"], b["case"]), (None, 10, 34))
        self.assertTrue(b["charging"]["case"])
        self.assertIsNone(P.decode_fp(P.FpFrame(3, 3, bytes([0xFF, 1, 2])))["left"])


if __name__ == "__main__":
    unittest.main()
