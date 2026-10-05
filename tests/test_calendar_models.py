import unittest
from datetime import date, datetime, timedelta, timezone

from pet_notify.cal import lunar
from pet_notify.cal.colors import DEFAULT_COLOR, HOLIDAY_COLOR, color_hex
from pet_notify.cal.models import CalendarEvent, EventDraft
from pet_notify.cal.recurrence import RecurrenceRule, preset

TZ = timezone(timedelta(hours=8))


@unittest.skipUnless(lunar.available(), "系統沒有 ICU，跳過農曆測試")
class LunarTest(unittest.TestCase):
    def test_known_dates(self):
        cases = {
            date(2026, 2, 17): (1, 1, False),    # 2026 春節
            date(2026, 2, 16): (12, 29, False),  # 2026 除夕（臘月廿九）
            date(2025, 10, 6): (8, 15, False),   # 2025 中秋
            date(2025, 7, 25): (6, 1, True),     # 2025 閏六月初一
            date(2023, 3, 22): (2, 1, True),     # 2023 閏二月初一
        }
        for d, (m, day, leap) in cases.items():
            ld = lunar.lunar_date(d)
            self.assertEqual((ld.month, ld.day, ld.leap), (m, day, leap), d)

    def test_labels(self):
        self.assertEqual(lunar.short_label(date(2026, 2, 17)), "春節")
        self.assertEqual(lunar.short_label(date(2026, 2, 16)), "除夕")
        self.assertEqual(lunar.short_label(date(2025, 10, 6)), "中秋")
        self.assertEqual(lunar.short_label(date(2025, 7, 25)), "閏六月")   # 初一顯示月份
        self.assertEqual(lunar.short_label(date(2026, 10, 5)), "廿五")
        self.assertEqual(lunar.full_label(date(2025, 10, 6)), "農曆八月十五 中秋")

    def test_day_names(self):
        names = [lunar.LunarDate(1, d).day_name for d in (1, 10, 11, 20, 21, 29, 30)]
        self.assertEqual(names, ["初一", "初十", "十一", "二十", "廿一", "廿九", "三十"])


class RecurrenceTest(unittest.TestCase):
    def test_roundtrip_weekly(self):
        rule = RecurrenceRule("WEEKLY", interval=2, byday=("WE", "MO"), count=10)
        text = rule.to_rrule()
        self.assertEqual(text, "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=10")
        self.assertEqual(RecurrenceRule.parse(text), RecurrenceRule("WEEKLY", 2, ("MO", "WE"), count=10))

    def test_until_all_day_and_timed(self):
        rule = RecurrenceRule("DAILY", until=date(2026, 12, 31))
        self.assertEqual(rule.to_rrule(all_day=True), "RRULE:FREQ=DAILY;UNTIL=20261231")
        self.assertEqual(rule.to_rrule(tz=TZ), "RRULE:FREQ=DAILY;UNTIL=20261231T155959Z")
        self.assertEqual(RecurrenceRule.parse("RRULE:FREQ=DAILY;UNTIL=20261231T155959Z").until, date(2026, 12, 31))

    def test_unknown_parts_preserved(self):
        text = "RRULE:FREQ=MONTHLY;BYDAY=2TU;BYSETPOS=1"
        rule = RecurrenceRule.parse(text)
        self.assertEqual(rule.to_rrule(), "RRULE:FREQ=MONTHLY;BYDAY=2TU;BYSETPOS=1")

    def test_from_recurrence_skips_exdate(self):
        rule = RecurrenceRule.from_recurrence(["EXDATE;VALUE=DATE:20261010", "RRULE:FREQ=YEARLY"])
        self.assertEqual(rule.freq, "YEARLY")
        self.assertIsNone(RecurrenceRule.from_recurrence(None))

    def test_describe(self):
        start = date(2026, 10, 5)  # 週一
        self.assertEqual(RecurrenceRule("DAILY").describe(start), "每天")
        self.assertEqual(RecurrenceRule("DAILY", 3).describe(start), "每 3 天")
        self.assertEqual(RecurrenceRule("WEEKLY", byday=("WE", "MO")).describe(start), "每週一、三")
        self.assertEqual(RecurrenceRule("WEEKLY").describe(start), "每週一")
        self.assertEqual(RecurrenceRule("MONTHLY", count=6).describe(start), "每月 5 日，共 6 次")
        self.assertEqual(RecurrenceRule("YEARLY", until=date(2030, 1, 1)).describe(start),
                         "每年 10 月 5 日，到 2030/01/01")

    def test_preset(self):
        self.assertEqual(preset("weekly", date(2026, 10, 7)).byday, ("WE",))
        self.assertIsNone(preset("none", date(2026, 10, 7)))


class ColorTest(unittest.TestCase):
    def test_colors(self):
        self.assertEqual(color_hex("11"), "#D50000")
        self.assertEqual(color_hex(""), DEFAULT_COLOR)
        self.assertEqual(color_hex("7", holiday=True), HOLIDAY_COLOR)


class ModelFieldsTest(unittest.TestCase):
    def test_from_google_new_fields(self):
        ev = CalendarEvent.from_google({
            "id": "x_20261005", "summary": "週會", "colorId": "7", "recurringEventId": "x",
            "start": {"dateTime": "2026-10-05T14:00:00+08:00"}, "end": {"dateTime": "2026-10-05T15:00:00+08:00"},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30},
                                                              {"method": "email", "minutes": 1440}]},
        })
        self.assertEqual((ev.color_id, ev.recurring_event_id, ev.reminder_minutes), ("7", "x", (1440, 30)))
        self.assertTrue(ev.is_recurring)
        self.assertEqual(CalendarEvent.from_dict(ev.to_dict()), ev)

    def test_default_reminders(self):
        ev = CalendarEvent.from_google({"id": "y", "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"},
                                        "reminders": {"useDefault": True}})
        self.assertIsNone(ev.reminder_minutes)
        ev2 = CalendarEvent.from_google({"id": "z", "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"},
                                         "reminders": {"useDefault": False}})
        self.assertEqual(ev2.reminder_minutes, ())

    def test_old_cache_compatible(self):
        old = {"id": "a", "title": "t", "start": "2026-10-05T09:00:00+08:00", "end": "2026-10-05T10:00:00+08:00",
               "all_day": False, "location": "", "description": "", "hangout_link": "", "html_link": ""}
        ev = CalendarEvent.from_dict(old)
        self.assertEqual((ev.color_id, ev.reminder_minutes, ev.calendar_id), ("", None, "primary"))

    def test_span_days(self):
        d = lambda *a: datetime(*a, tzinfo=TZ)  # noqa: E731
        one_day = CalendarEvent("a", "t", d(2026, 10, 5), d(2026, 10, 6), all_day=True)
        self.assertEqual(one_day.last_day, date(2026, 10, 5))
        trip = CalendarEvent("b", "t", d(2026, 10, 5), d(2026, 10, 8), all_day=True)
        self.assertEqual(trip.last_day, date(2026, 10, 7))
        overnight = CalendarEvent("c", "t", d(2026, 10, 5, 22), d(2026, 10, 6, 2))
        self.assertTrue(overnight.spans_days)
        until_midnight = CalendarEvent("e", "t", d(2026, 10, 5, 22), d(2026, 10, 6))
        self.assertFalse(until_midnight.spans_days)
        normal = CalendarEvent("f", "t", d(2026, 10, 5, 9), d(2026, 10, 5, 10))
        self.assertFalse(normal.spans_days)

    def test_draft_body_new_fields(self):
        start = datetime(2026, 10, 5, 9, tzinfo=TZ)
        draft = EventDraft("週會", start, start + timedelta(hours=1), color_id="5",
                           recurrence=["RRULE:FREQ=WEEKLY"], reminder_minutes=(30, 1440, 30), tz_name="Asia/Taipei")
        body = draft.to_google_body()
        self.assertEqual(body["colorId"], "5")
        self.assertEqual(body["recurrence"], ["RRULE:FREQ=WEEKLY"])
        self.assertEqual(body["reminders"]["overrides"], [{"method": "popup", "minutes": 1440},
                                                         {"method": "popup", "minutes": 30}])
        self.assertEqual(body["start"]["timeZone"], "Asia/Taipei")
        patch = EventDraft("x", start, start + timedelta(hours=1)).to_google_body(for_patch=True)
        self.assertIsNone(patch["colorId"])
        self.assertEqual(patch["reminders"], {"useDefault": True, "overrides": []})
        self.assertNotIn("recurrence", patch)

    def test_draft_from_event(self):
        d = lambda *a: datetime(*a, tzinfo=TZ)  # noqa: E731
        ev = CalendarEvent("a", "休假", d(2026, 10, 5), d(2026, 10, 8), all_day=True, color_id="2")
        draft = EventDraft.from_event(ev)
        self.assertEqual((draft.end.date(), draft.color_id), (date(2026, 10, 7), "2"))
        self.assertEqual(draft.to_google_body()["end"]["date"], "2026-10-08")


if __name__ == "__main__":
    unittest.main()
