import unittest
from datetime import date, datetime, time, timedelta, timezone

from pet_notify.cal.models import CalendarEvent
from pet_notify.reminders.daily_brief import compose_agenda, due_agenda_times, todays_events

TZ = timezone(timedelta(hours=8))


def at(h, m=0, day=5):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def timed(id_, title, start, end):
    return CalendarEvent(id_, title, start, end)


def all_day(id_, title, d0, d1):
    return CalendarEvent(id_, title, datetime.combine(d0, time(), TZ), datetime.combine(d1, time(), TZ), all_day=True)


class DueAgendaTest(unittest.TestCase):
    def test_fires_at_time(self):
        self.assertEqual(due_agenda_times(at(9, 0), ["09:00", "13:30"], {}), ["09:00"])

    def test_not_before_time(self):
        self.assertEqual(due_agenda_times(at(8, 59), ["09:00"], {}), [])

    def test_once_per_day(self):
        fired = {"09:00": "2026-10-05"}
        self.assertEqual(due_agenda_times(at(9, 5), ["09:00"], fired), [])
        # 隔天又會再發
        self.assertEqual(due_agenda_times(at(9, 5, day=6), ["09:00"], fired), ["09:00"])

    def test_catch_up_within_grace(self):
        self.assertEqual(due_agenda_times(at(9, 59), ["09:00"], {}), ["09:00"])

    def test_skip_after_grace(self):
        # 下午才開機，早上的時間點不補發
        self.assertEqual(due_agenda_times(at(10, 0), ["09:00"], {}), [])

    def test_multiple_due_sorted(self):
        self.assertEqual(due_agenda_times(at(9, 40), ["09:30", "09:00"], {}), ["09:00", "09:30"])

    def test_bad_value_ignored(self):
        self.assertEqual(due_agenda_times(at(9, 0), ["xx", "25:00", "09:00"], {}), ["09:00"])


class ComposeAgendaTest(unittest.TestCase):
    def setUp(self):
        self.now = at(12, 0)
        self.events = [
            timed("a", "晨會", at(9), at(10)),                     # 已結束
            timed("b", "午餐會議", at(11, 30), at(13)),            # 進行中
            timed("c", "看牙醫", at(16, 30), at(17, 30)),          # 還沒開始
            all_day("d", "家人生日", date(2026, 10, 5), date(2026, 10, 6)),
            timed("e", "明天的事", at(9, day=6), at(10, day=6)),   # 不是今天
            timed("f", "通宵部署", at(23, day=4), at(1)),           # 從昨天跨到今天，已結束
        ]

    def test_includes_finished_events(self):
        ids = [e.id for e in todays_events(self.events, self.now, include_finished=True)]
        self.assertEqual(ids, ["d", "f", "a", "b", "c"])
        # 晨報（預設）只列沒結束的
        self.assertEqual([e.id for e in todays_events(self.events, self.now)], ["d", "b", "c"])

    def test_text(self):
        text = compose_agenda(self.events, self.now)
        lines = text.splitlines()
        self.assertEqual(lines[0], "今天共 5 個行程，還有 3 個沒結束：")
        self.assertEqual(lines[1], "・ 全天  家人生日")
        self.assertEqual(lines[2], "✓ 昨天–01:00  通宵部署（已結束）")
        self.assertEqual(lines[3], "✓ 09:00–10:00  晨會（已結束）")
        self.assertEqual(lines[4], "・ 11:30–13:00  午餐會議（進行中）")
        self.assertEqual(lines[5], "・ 16:30–17:30  看牙醫")
        self.assertNotIn("明天的事", text)

    def test_empty(self):
        self.assertIn("沒有排行程", compose_agenda([], self.now))


if __name__ == "__main__":
    unittest.main()
