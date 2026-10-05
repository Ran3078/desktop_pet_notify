import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pet_notify.cal.models import CalendarEvent, EventDraft
from pet_notify.reminders import daily_brief
from pet_notify.state import StateManager, level_for, newly_unlocked

TZ = timezone(timedelta(hours=8))


class AffectionTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(level_for(0), 1)
        self.assertEqual(level_for(99), 1)
        self.assertEqual(level_for(100), 2)
        self.assertEqual(level_for(450), 5)

    def test_unlocks(self):
        self.assertEqual(newly_unlocked(1, 2), ["櫻花粉", "蝴蝶結"])
        self.assertEqual(newly_unlocked(4, 5), ["圍巾"])
        self.assertEqual(newly_unlocked(5, 5), [])

    def test_level_up_signal_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            mgr = StateManager(path)
            ups = []
            mgr.level_up.connect(lambda lvl, items: ups.append((lvl, items)))
            mgr.add_affection(99, "test")
            self.assertEqual(ups, [])
            mgr.add_affection(1, "test")
            self.assertEqual(ups, [(2, ["櫻花粉", "蝴蝶結"])])
            self.assertEqual(StateManager(path).state.affection, 100)


class ModelTest(unittest.TestCase):
    def test_from_google_timed(self):
        ev = CalendarEvent.from_google({
            "id": "x", "summary": "開會",
            "start": {"dateTime": "2026-10-05T14:00:00+08:00"},
            "end": {"dateTime": "2026-10-05T15:00:00+08:00"},
            "hangoutLink": "https://meet.google.com/abc",
        })
        self.assertFalse(ev.all_day)
        self.assertEqual(ev.start.astimezone(TZ).hour, 14)
        self.assertEqual(ev.meeting_url, "https://meet.google.com/abc")

    def test_from_google_all_day_and_roundtrip(self):
        ev = CalendarEvent.from_google({
            "id": "y", "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"},
        })
        self.assertTrue(ev.all_day)
        self.assertEqual(ev.title, "（無標題）")
        self.assertEqual(CalendarEvent.from_dict(ev.to_dict()), ev)

    def test_location_url_as_meeting(self):
        start = datetime(2026, 10, 5, 9, tzinfo=TZ)
        ev = CalendarEvent("z", "t", start, start, location="https://zoom.us/j/1")
        self.assertEqual(ev.meeting_url, "https://zoom.us/j/1")

    def test_draft_all_day_body(self):
        start = datetime(2026, 10, 5, 0, tzinfo=TZ)
        body = EventDraft("休假", start, start, all_day=True).to_google_body(for_patch=True)
        self.assertEqual(body["start"], {"date": "2026-10-05", "dateTime": None, "timeZone": None})
        self.assertEqual(body["end"]["date"], "2026-10-06")

    def test_draft_timed_body(self):
        start = datetime(2026, 10, 5, 9, tzinfo=TZ)
        body = EventDraft("開會", start, start + timedelta(hours=1)).to_google_body()
        self.assertIn("dateTime", body["start"])
        self.assertNotIn("date", body["start"])


class DailyBriefTest(unittest.TestCase):
    def test_should_show(self):
        now = datetime(2026, 10, 5, 8, tzinfo=TZ)
        self.assertTrue(daily_brief.should_show(now, "", True))
        self.assertFalse(daily_brief.should_show(now, "2026-10-05", True))
        self.assertFalse(daily_brief.should_show(now.replace(hour=6), "", True))
        self.assertFalse(daily_brief.should_show(now, "", False))

    def test_compose(self):
        now = datetime(2026, 10, 5, 8, tzinfo=TZ)
        events = [
            CalendarEvent("a", "開會", now + timedelta(hours=2), now + timedelta(hours=3)),
            CalendarEvent("b", "明天的事", now + timedelta(days=1), now + timedelta(days=1, hours=1)),
            CalendarEvent("c", "生日", datetime.combine(date(2026, 10, 5), datetime.min.time(), TZ),
                          datetime.combine(date(2026, 10, 6), datetime.min.time(), TZ), all_day=True),
        ]
        text = daily_brief.compose(events, now)
        self.assertIn("今天有 2 個行程", text)
        self.assertLess(text.index("生日"), text.index("開會"))
        self.assertNotIn("明天的事", text)
        self.assertIn("沒有排行程", daily_brief.compose([], now))



class NextUnlockTest(unittest.TestCase):
    def test_next_unlock(self):
        from pet_notify.state import next_unlock

        self.assertEqual(next_unlock(1), (2, ["櫻花粉", "蝴蝶結"]))
        self.assertEqual(next_unlock(3), (4, ["奶茶"]))
        self.assertEqual(next_unlock(4), (5, ["圍巾"]))
        self.assertIsNone(next_unlock(5))


if __name__ == "__main__":
    unittest.main()
