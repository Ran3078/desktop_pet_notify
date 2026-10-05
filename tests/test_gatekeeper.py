import unittest
from datetime import datetime

from pet_notify.config import Settings
from pet_notify.reminders.gatekeeper import Environment, Route, decide, in_quiet_period


def at(h, m=0):
    return datetime(2026, 10, 5, h, m)


class QuietPeriodTest(unittest.TestCase):
    def test_simple_range(self):
        periods = [["12:00", "13:00"]]
        self.assertTrue(in_quiet_period(at(12, 30), periods))
        self.assertFalse(in_quiet_period(at(13, 0), periods))
        self.assertFalse(in_quiet_period(at(11, 59), periods))

    def test_overnight_range(self):
        periods = [["22:00", "07:00"]]
        self.assertTrue(in_quiet_period(at(23), periods))
        self.assertTrue(in_quiet_period(at(3), periods))
        self.assertFalse(in_quiet_period(at(7), periods))
        self.assertFalse(in_quiet_period(at(12), periods))

    def test_bad_values_ignored(self):
        self.assertFalse(in_quiet_period(at(12), [["xx", "13:00"], ["12:00"]]))


class DecideTest(unittest.TestCase):
    def env(self, fullscreen=False, idle=0.0, now=None):
        return Environment(now=now or at(15), fullscreen=fullscreen, idle_seconds=idle)

    def test_normal_show(self):
        self.assertEqual(decide(Settings(), self.env()), Route.SHOW)

    def test_fullscreen(self):
        self.assertEqual(decide(Settings(), self.env(fullscreen=True)), Route.FULLSCREEN)

    def test_fullscreen_detection_disabled(self):
        self.assertEqual(decide(Settings(dnd_fullscreen=False), self.env(fullscreen=True)), Route.SHOW)

    def test_idle_defers(self):
        self.assertEqual(decide(Settings(idle_defer_min=5), self.env(idle=301)), Route.DEFER)
        self.assertEqual(decide(Settings(idle_defer_min=5), self.env(idle=200)), Route.SHOW)

    def test_idle_defer_off(self):
        self.assertEqual(decide(Settings(idle_defer_min=0), self.env(idle=99999)), Route.SHOW)

    def test_quiet_has_priority(self):
        s = Settings(quiet_periods=[["14:00", "16:00"]])
        self.assertEqual(decide(s, self.env(fullscreen=True, idle=9999)), Route.QUIET)


if __name__ == "__main__":
    unittest.main()
