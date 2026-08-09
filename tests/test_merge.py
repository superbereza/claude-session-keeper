import unittest

from lib.state_engine import merge

REG = {"name": "cc—x/proj", "uuid": "u1", "cwd_registered": "/home/me/dev/proj",
       "effort": "", "rc_desired": True, "pane_id": "%3"}
TUI = {"state": "at-prompt", "rc_footer": "rc", "composer": "empty", "banners": [], "last_gen": None}
STATE = {"status": "idle", "rc_bridge": "present", "pid": 1111,
         "cwd_actual": "/home/me/dev/proj", "session_id": "u1"}


class TestMerge(unittest.TestCase):
    def test_basic_record_shape(self):
        r = merge(REG, True, STATE, TUI)
        self.assertEqual(r["rc_desired"], True)
        self.assertEqual(r["live"], True)
        self.assertEqual(r["status"], "idle")
        self.assertEqual(r["rc_bridge"], "present")
        self.assertEqual(r["dialog"], "none")            # at-prompt → no dialog
        self.assertEqual(r["drift"], False)
        self.assertEqual(r["rc_health"], "unknown")      # filled by derive_health later

    def test_dialog_mapped_from_state(self):
        tui = dict(TUI, state="resume-dialog")
        self.assertEqual(merge(REG, True, STATE, tui)["dialog"], "resume")

    def test_drift_when_cwd_differs(self):
        st = dict(STATE, cwd_actual="/home/me/dev/other")
        self.assertTrue(merge(REG, True, st, TUI)["drift"])

    def test_worktree_cwd_is_not_drift(self):
        st = dict(STATE, cwd_actual="/home/me/dev/proj/.claude/worktrees/x")
        self.assertFalse(merge(REG, True, st, TUI)["drift"])   # worktree cwd is expected, not drift

    def test_tui_busy_overrides_idle_statefile(self):
        tui = dict(TUI, state="busy")                          # pane shows 'esc to interrupt'
        self.assertEqual(merge(REG, True, STATE, tui)["status"], "busy")  # even though state file says idle


if __name__ == "__main__":
    unittest.main()
