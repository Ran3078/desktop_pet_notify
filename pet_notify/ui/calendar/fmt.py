"""行事曆畫面用的中文日期 / 時間文字。"""
from __future__ import annotations

from datetime import date, timedelta

from ...cal.models import CalendarEvent

WEEKDAYS = "一二三四五六日"


def day_text(d: date, with_year: bool = False) -> str:
    year = f"{d.year} 年 " if with_year else ""
    return f"{year}{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


def when_text(ev: CalendarEvent) -> str:
    first, last = ev.start.date(), ev.last_day
    if ev.all_day:
        if first == last:
            return f"{day_text(first)}・全天"
        return f"{day_text(first)} – {day_text(last)}・全天"
    if ev.spans_days:
        return f"{day_text(first)} {ev.start:%H:%M} – {day_text(ev.end.date())} {ev.end:%H:%M}"
    return f"{day_text(first)}・{ev.start:%H:%M} – {ev.end:%H:%M}"


def minutes_text(m: int) -> str:
    if m == 0:
        return "活動開始時"
    if m % 1440 == 0:
        return f"{m // 1440} 天前"
    if m % 60 == 0:
        return f"{m // 60} 小時前"
    return f"{m} 分鐘前"


def reminders_text(ev: CalendarEvent, default: list[int]) -> str:
    if ev.reminder_minutes is None:
        return "預設（" + "、".join(minutes_text(m) for m in sorted(default, reverse=True)) + "）"
    if not ev.reminder_minutes:
        return "不提醒"
    return "、".join(minutes_text(m) for m in sorted(ev.reminder_minutes, reverse=True))


def range_title(view: str, anchor: date, days: list[date]) -> str:
    if view == "month":
        return f"{anchor.year} 年 {anchor.month} 月"
    if view == "day":
        return day_text(anchor, with_year=True)
    first, last = days[0], days[-1]
    if first.month == last.month:
        return f"{first.year} 年 {first.month} 月 {first.day} – {last.day} 日"
    if first.year == last.year:
        return f"{first.year} 年 {first.month} 月 {first.day} 日 – {last.month} 月 {last.day} 日"
    return f"{first:%Y/%m/%d} – {last:%Y/%m/%d}"


def relative_day(d: date, today: date) -> str:
    delta = (d - today).days
    return {0: "今天", 1: "明天", -1: "昨天", 2: "後天"}.get(delta, "")


def end_inclusive(ev: CalendarEvent) -> date:
    return ev.last_day if ev.all_day else (ev.end - timedelta(seconds=1)).date()
