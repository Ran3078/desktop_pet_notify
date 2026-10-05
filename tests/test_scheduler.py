import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from pet_notify.cal.models import CalendarEvent
from pet_notify.reminders.scheduler import describe_remaining, due_reminders, reminder_key

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 5, 14, 0, 0, tzinfo=TZ)
STAGES = [10, 1, 0]


def ev(minutes_from_now: float, id_="e1", all_day=False) -> CalendarEvent:
    start = NOW + timedelta(minutes=minutes_from_now)
    return CalendarEvent(id=id_, title="開會", start=start, end=start + timedelta(hours=1), all_day=all_day)


class DueRemindersTest(unittest.TestCase):
    def run_due(self, events, now=NOW, notified=()):
        notified = set(notified)
        return due_reminders(events, now, STAGES, notified.__contains__)

    def test_not_due_before_first_stage(self):
        self.assertEqual(self.run_due([ev(10.5)]), [])

    def test_first_stage_at_ten_minutes(self):
        (r,) = self.run_due([ev(10)])
        self.assertEqual(r.stage, 10)
        self.assertTrue(r.first_stage)
        self.assertEqual(r.mark_keys, (reminder_key(r.event, 10),))

    def test_not_repeated_after_marked(self):
        e = ev(8)
        self.assertEqual(self.run_due([e], notified={reminder_key(e, 10)}), [])

    def test_one_minute_stage_after_ten(self):
        e = ev(0.9)
        (r,) = self.run_due([e], notified={reminder_key(e, 10)})
        self.assertEqual(r.stage, 1)
        self.assertFalse(r.first_stage)

    def test_start_stage_within_grace(self):
        e = ev(-0.5)
        (r,) = self.run_due([e], notified={reminder_key(e, 10), reminder_key(e, 1)})
        self.assertEqual(r.stage, 0)

    def test_past_event_ignored(self):
        self.assertEqual(self.run_due([ev(-2)]), [])

    def test_all_day_skipped(self):
        self.assertEqual(self.run_due([ev(5, all_day=True)]), [])

    def test_catch_up_after_sleep_only_most_urgent(self):
        # 睡眠醒來時已經剩 30 秒：只發「1 分鐘」那段，但 10 分鐘那段也要一起標記
        e = ev(0.5)
        (r,) = self.run_due([e])
        self.assertEqual(r.stage, 1)
        self.assertEqual(set(r.mark_keys), {reminder_key(e, 10), reminder_key(e, 1)})

    def test_rescheduled_event_reminds_again(self):
        old = ev(5)
        moved = CalendarEvent(id=old.id, title=old.title, start=old.start + timedelta(minutes=2),
                              end=old.end + timedelta(minutes=2))
        (r,) = self.run_due([moved], notified={reminder_key(old, 10)})
        self.assertEqual(r.stage, 10)

    def test_sorted_by_start(self):
        rs = self.run_due([ev(9, "b"), ev(3, "a")])
        self.assertEqual([r.event.id for r in rs], ["a", "b"])

    def test_custom_stages(self):
        rs = due_reminders([ev(29)], NOW, [30, 5], lambda k: False)
        self.assertEqual(rs[0].stage, 30)


class DescribeTest(unittest.TestCase):
    def test_texts(self):
        self.assertEqual(describe_remaining(600), "10 分鐘後")
        self.assertEqual(describe_remaining(30), "馬上就要開始了")
        self.assertEqual(describe_remaining(-5), "現在開始！")



class PerEventStagesTest(unittest.TestCase):
    def test_custom_reminders_override_default(self):
        e = replace(ev(29), reminder_minutes=(30,))
        (r,) = due_reminders([e], NOW, STAGES, lambda k: False)
        self.assertEqual(r.stage, 30)
        self.assertTrue(r.first_stage)
        # 自訂只有 30 分鐘：剩 9 分鐘時不會再出現預設的 10 分鐘提醒
        e2 = replace(ev(9), reminder_minutes=(30,))
        self.assertEqual(due_reminders([e2], NOW, STAGES, lambda k: k.endswith("|30")), [])

    def test_no_reminders(self):
        self.assertEqual(due_reminders([replace(ev(5), reminder_minutes=())], NOW, STAGES, lambda k: False), [])

    def test_read_only_skipped(self):
        self.assertEqual(due_reminders([replace(ev(5), read_only=True)], NOW, STAGES, lambda k: False), [])


if __name__ == "__main__":
    unittest.main()
