import os
import unittest

from lib.state_engine import parse_pane

FX = os.path.join(os.path.dirname(__file__), "fixtures", "panes")


def load(name):
    return open(os.path.join(FX, name), encoding="utf-8").read()


class TestParsePane(unittest.TestCase):
    def test_at_prompt_bare_rc(self):
        r = parse_pane(load("at-prompt-rc.txt"))
        self.assertEqual(r["state"], "at-prompt")
        self.assertEqual(r["rc_footer"], "rc")
        self.assertEqual(r["composer"], "empty")
        self.assertIn("auto-update-failed", r["banners"])
        self.assertEqual(r["last_gen"], "Crunched for 6s")

    def test_nonempty_composer(self):
        r = parse_pane(load("at-prompt-nonempty.txt"))
        self.assertEqual(r["composer"], "nonempty")   # live composer between the rules has text
        self.assertEqual(r["state"], "at-prompt")

    def test_busy_wins_and_footer_wraps(self):
        r = parse_pane(load("busy.txt"))
        self.assertEqual(r["state"], "busy")          # 'esc to interrupt' in the (wrapped) footer
        self.assertEqual(r["rc_footer"], "rc")        # /rc found despite wrapping to its own line

    def test_rc_connecting_from_output_zone_and_echo_is_not_composer(self):
        r = parse_pane(load("rc-connecting.txt"))
        self.assertEqual(r["rc_footer"], "connecting")  # '⎿ /rc connecting…' in the output zone
        self.assertEqual(r["composer"], "empty")        # the ❯ /remote-control echo is NOT the composer

    def test_resume_dialog_detected(self):
        r = parse_pane(load("resume-dialog.txt"))
        self.assertEqual(r["state"], "resume-dialog")


if __name__ == "__main__":
    unittest.main()
