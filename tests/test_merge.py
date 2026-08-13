import unittest

from lib.state_engine import merge, encode_cwd, infer_target_cwd

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

    def test_drift_is_passthrough_from_caller(self):
        # drift is I/O-derived (gather checks the transcript location) and passed in via reg;
        # a wandering live cwd must NOT by itself mark drift.
        self.assertTrue(merge(dict(REG, drift=True), True, STATE, TUI)["drift"])
        self.assertFalse(merge(dict(REG, drift=False), True, STATE, TUI)["drift"])

    def test_wandering_live_cwd_is_not_drift(self):
        st = dict(STATE, cwd_actual="/home/me/dev/proj/.claude/worktrees/x")
        self.assertFalse(merge(REG, True, st, TUI)["drift"])   # no drift flag from caller → not drift

    def test_tui_busy_overrides_idle_statefile(self):
        tui = dict(TUI, state="busy")                          # pane shows 'esc to interrupt'
        self.assertEqual(merge(REG, True, STATE, tui)["status"], "busy")  # even though state file says idle


class TestEncodeCwd(unittest.TestCase):
    def test_every_nonalnum_becomes_dash(self):
        self.assertEqual(encode_cwd("/home/me/dev/ai-auth-lib"), "-home-me-dev-ai-auth-lib")

    def test_worktree_path_encoding(self):
        self.assertEqual(encode_cwd("/home/me/dev/proj/.claude/worktrees/x"),
                         "-home-me-dev-proj--claude-worktrees-x")   # '.' → '-', so '/.claude' → '--claude'


class TestInferTargetCwd(unittest.TestCase):
    OLD = "/home/me/dev/mass-server-infrastructure"   # renamed away — no longer exists
    NEW = "/home/me/dev/massonde"                      # exists

    def exists(self, only):
        return lambda p: p in only

    def test_renamed_folder_infers_new_dominant_cwd(self):
        recent = [self.OLD] * 4 + [self.NEW] * 20        # session moved; NEW dominates recent
        self.assertEqual(infer_target_cwd(recent, self.OLD, self.exists({self.NEW})), self.NEW)

    def test_transient_mount_same_missing_path_returns_none(self):
        recent = [self.OLD] * 20                          # cwd unchanged, just not mounted
        self.assertIsNone(infer_target_cwd(recent, self.OLD, self.exists(set())))

    def test_one_off_cd_below_threshold_returns_none(self):
        recent = [self.OLD] * 20 + [self.NEW] * 2         # a stray cd, not a move
        self.assertIsNone(infer_target_cwd(recent, self.OLD, self.exists({self.NEW})))

    def test_target_must_exist(self):
        recent = [self.NEW] * 20                          # dominant but the dir doesn't exist
        self.assertIsNone(infer_target_cwd(recent, self.OLD, self.exists(set())))


if __name__ == "__main__":
    unittest.main()
