import os
import unittest

from lib.state_engine import parse_state

FX = os.path.join(os.path.dirname(__file__), "fixtures", "state")


def load(name):
    return open(os.path.join(FX, name), encoding="utf-8").read()


class TestParseState(unittest.TestCase):
    def test_bridge_present_idle(self):
        r = parse_state(load("bridge-present.json"))
        self.assertEqual(r["rc_bridge"], "present")
        self.assertEqual(r["status"], "idle")
        self.assertEqual(r["pid"], 1111)
        self.assertEqual(r["session_id"], "00000000-aaaa-bbbb-cccc-000000000001")

    def test_bridge_absent(self):
        r = parse_state(load("bridge-absent.json"))
        self.assertEqual(r["rc_bridge"], "absent")

    def test_busy(self):
        self.assertEqual(parse_state(load("busy.json"))["status"], "busy")

    def test_garbage_is_unknown(self):
        r = parse_state("not json")
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["rc_bridge"], "absent")
        self.assertIsNone(r["pid"])


if __name__ == "__main__":
    unittest.main()
