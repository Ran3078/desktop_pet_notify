import unittest
from datetime import date, datetime, timedelta, timezone

from pet_notify.cal.models import CalendarEvent
from pet_notify.ui.calendar import layout as L

TZ = timezone(timedelta(hours=8))


def dt(day, h=0, m=0, month=10):
    return datetime(2026, month, day, h, m, tzinfo=TZ)


def timed(id_, day, h0, h1, m0=0, m1=0):
    return CalendarEvent(id_, id_, dt(day, h0, m0), dt(day, h1, m1))


def allday(id_, d0, d1_exclusive):
    return CalendarEvent(id_, id_, dt(d0), dt(d1_exclusive), all_day=True)


class RangeTest(unittest.TestCase):
    def test_month_grid_sunday_start(self):
        grid = L.month_grid(2026, 10, "sun")  # 2026/10/1 是週四
        self.assertEqual(len(grid), 42)
        self.assertEqual(grid[0], date(2026, 9, 27))
        self.assertEqual(grid[0].weekday(), 6)
        self.assertIn(date(2026, 10, 31), grid)

    def test_month_grid_monday_start(self):
        grid = L.month_grid(2026, 10, "mon")
        self.assertEqual(grid[0], date(2026, 9, 28))
        self.assertEqual(L.weekday_labels("mon")[0], "一")
        self.assertEqual(L.weekday_labels("sun")[0], "日")

    def test_view_range_and_shift(self):
        self.assertEqual(L.view_range("week", date(2026, 10, 7), "sun"), (date(2026, 10, 4), date(2026, 10, 11)))
        self.assertEqual(L.view_range("day", date(2026, 10, 7), "sun"), (date(2026, 10, 7), date(2026, 10, 8)))
        self.assertEqual(L.shift_anchor("month", date(2026, 12, 15), 1), date(2027, 1, 1))
        self.assertEqual(L.shift_anchor("month", date(2026, 1, 31), -1), date(2025, 12, 1))
        self.assertEqual(L.shift_anchor("week", date(2026, 10, 7), -1), date(2026, 9, 30))


class WeekLanesTest(unittest.TestCase):
    def setUp(self):
        self.week = L.week_dates(date(2026, 10, 5), "sun")  # 10/4(日) ~ 10/10(六)

    def test_multi_day_bar_continues(self):
        trip = allday("trip", 2, 7)  # 10/2 ~ 10/6，從上週延續過來
        (p,) = L.layout_week([trip], self.week)
        self.assertEqual((p.col_start, p.col_end, p.cont_left, p.cont_right), (0, 2, True, False))

    def test_lanes_do_not_overlap(self):
        evs = [allday("a", 5, 8), timed("b", 6, 9, 10), timed("c", 6, 11, 12), timed("d", 9, 9, 10)]
        placed = {p.event.id: p for p in L.layout_week(evs, self.week)}
        self.assertEqual(placed["a"].lane, 0)            # 色條優先放第一軌
        self.assertEqual({placed["b"].lane, placed["c"].lane}, {1, 2})
        self.assertEqual(placed["d"].lane, 0)            # 10/9 沒被色條佔用

    def test_overflow(self):
        evs = [timed(f"e{i}", 6, 8 + i, 9 + i) for i in range(5)]
        visible, hidden = L.visible_and_hidden(L.layout_week(evs, self.week), max_lanes=3)
        self.assertEqual(len(visible), 2)   # 最後一列讓給「+N 則」
        self.assertEqual(hidden, {2: 3})

    def test_no_overflow_when_fits(self):
        evs = [timed(f"e{i}", 6, 8 + i, 9 + i) for i in range(3)]
        visible, hidden = L.visible_and_hidden(L.layout_week(evs, self.week), max_lanes=3)
        self.assertEqual((len(visible), hidden), (3, {}))

    def test_events_on_order(self):
        evs = [timed("late", 6, 15, 16), allday("all", 6, 7), timed("early", 6, 9, 10)]
        self.assertEqual([e.id for e in L.events_on(evs, date(2026, 10, 6))], ["all", "early", "late"])


class DayLayoutTest(unittest.TestCase):
    def test_overlap_columns(self):
        evs = [timed("a", 5, 9, 11), timed("b", 5, 10, 12), timed("c", 5, 11, 13), timed("d", 5, 14, 15)]
        blocks = {b.event.id: b for b in L.layout_day(evs, date(2026, 10, 5))}
        self.assertEqual((blocks["a"].col, blocks["b"].col, blocks["c"].col), (0, 1, 0))
        self.assertEqual({blocks[k].ncols for k in "abc"}, {2})
        self.assertEqual((blocks["d"].col, blocks["d"].ncols), (0, 1))
        self.assertEqual((blocks["a"].top_min, blocks["a"].bottom_min), (540, 660))

    def test_clip_overnight(self):
        ev = CalendarEvent("n", "n", dt(5, 22), dt(6, 2))
        (b5,) = L.layout_day([ev], date(2026, 10, 5))
        (b6,) = L.layout_day([ev], date(2026, 10, 6))
        self.assertEqual((b5.top_min, b5.bottom_min), (1320, 1440))
        self.assertEqual((b6.top_min, b6.bottom_min), (0, 120))

    def test_short_event_min_height(self):
        (b,) = L.layout_day([timed("s", 5, 9, 9, 0, 5)], date(2026, 10, 5))
        self.assertEqual(b.bottom_min - b.top_min, 15)


class DragTest(unittest.TestCase):
    def test_snap(self):
        self.assertEqual(L.snap(547), 540)
        self.assertEqual(L.snap(553), 555)

    def test_moves(self):
        ev = timed("a", 5, 9, 10, 0, 30)  # 9:00~10:30
        self.assertEqual(L.moved_by_days(ev, 2), (dt(7, 9), dt(7, 10, 30)))
        self.assertEqual(L.moved_in_time(ev, date(2026, 10, 6), 14 * 60), (dt(6, 14), dt(6, 15, 30)))
        self.assertEqual(L.resized(ev, 12 * 60), (dt(5, 9), dt(5, 12)))
        self.assertEqual(L.resized(ev, 8 * 60), (dt(5, 9), dt(5, 9, 15)))  # 不能小於 15 分鐘

    def test_overlaps(self):
        evs = [timed("a", 5, 9, 10), timed("b", 5, 10, 11), allday("c", 5, 6)]
        self.assertEqual([e.id for e in L.overlaps(evs, dt(5, 9, 30), dt(5, 10, 30))], ["a", "b"])
        self.assertEqual([e.id for e in L.overlaps(evs, dt(5, 9, 30), dt(5, 10, 30), exclude_id="a")], ["b"])
        self.assertEqual(L.overlaps(evs, dt(5, 11), dt(5, 12)), [])


if __name__ == "__main__":
    unittest.main()
