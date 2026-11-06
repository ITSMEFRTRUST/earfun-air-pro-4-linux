import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Units(unittest.TestCase):
    def test_units_do_not_depend_on_the_clone_location(self):
        for unit, binary in (("earfun.service", "earfun"), ("earfun-audio-heal.service", "earfun-audio-heal")):
            with open(os.path.join(ROOT, "systemd", unit)) as f:
                text = f.read()
            self.assertIn("%%h/.local/bin/%s" % binary, text)
            self.assertNotIn("earfun-app", text)


class Symlinks(unittest.TestCase):
    def test_bin_works_through_a_symlink_from_elsewhere(self):
        with tempfile.TemporaryDirectory() as d:
            link = os.path.join(d, "earfun")
            os.symlink(os.path.join(ROOT, "bin", "earfun"), link)
            r = subprocess.run([sys.executable, "-I", link, "keys", "--json"], cwd=d, capture_output=True,
                               text=True, timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr)        # keys needs no daemon


class Tools(unittest.TestCase):
    def test_tools_need_an_address(self):
        for tool in ("probe.py", "modetest.py"):
            for args in ([], ["not-an-address"]):
                r = subprocess.run([sys.executable, os.path.join(ROOT, tool)] + args, capture_output=True,
                                   text=True, timeout=10)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("Usage", r.stderr)
                self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
