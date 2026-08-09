import unittest

from lib.state_engine import derive_health, decide


def rec(**kw):
    base = {"live": True, "rc_desired": True, "status": "idle",
            "rc_bridge": "present", "rc_footer": "active", "dialog": "none",
            "drift": False, "logged_in": True}
    base.update(kw)
    return base


class TestDeriveHealth(unittest.TestCase):
    def test_absent_is_down(self):
        self.assertEqual(derive_health(rec(rc_bridge="absent")), "down")

    def test_present_active_is_up(self):
        self.assertEqual(derive_health(rec(rc_bridge="present", rc_footer="active")), "up")

    def test_present_bare_rc_is_unknown_until_experiment(self):
        self.assertEqual(derive_health(rec(rc_bridge="present", rc_footer="rc")), "unknown")

    def test_present_connecting_is_unknown(self):
        self.assertEqual(derive_health(rec(rc_bridge="present", rc_footer="connecting")), "unknown")


class TestDecide(unittest.TestCase):
    def test_busy_never_touched(self):
        self.assertEqual(decide(rec(status="busy", rc_bridge="absent")), "none")

    def test_not_subscribed_never_healed(self):
        self.assertEqual(decide(rec(rc_desired=False, rc_bridge="absent")), "none")

    def test_live_channel_never_reissued(self):
        self.assertEqual(decide(rec(rc_bridge="present", rc_footer="active")), "none")

    def test_dead_session_relaunched(self):
        self.assertEqual(decide(rec(live=False)), "relaunch")

    def test_live_drift_is_flag_only_not_migrate(self):
        # migrating a live session would copy a transcript it's still writing → later restore
        # resumes the stale copy and loses work. So live drift is surfaced, never auto-acted.
        self.assertEqual(decide(rec(drift=True, rc_bridge="present", rc_footer="active")), "none")

    def test_stuck_dialog_tidied(self):
        self.assertEqual(decide(rec(dialog="resume")), "tidy")

    def test_absent_bridge_idle_reissues(self):
        self.assertEqual(decide(rec(rc_bridge="absent", status="idle")), "reissue-rc")

    def test_absent_bridge_but_logged_out_no_reissue(self):
        self.assertEqual(decide(rec(rc_bridge="absent", logged_in=False)), "none")


if __name__ == "__main__":
    unittest.main()
