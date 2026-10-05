"""每日晨報與定時今日行程：列出今天的行程。"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from ..cal.models import CalendarEvent

BRIEF_FROM_HOUR = 7


def should_show(now: datetime, last_brief_date: str, enabled: bool) -> bool:
    return enabled and now.hour >= BRIEF_FROM_HOUR and last_brief_date != now.date().isoformat()


AGENDA_GRACE_MINUTES = 60  # 錯過時間點（睡眠、關機）後，多久內開機仍會補發


def todays_events(events: list[CalendarEvent], now: datetime, include_finished: bool = False) -> list[CalendarEvent]:
    """今天的活動：全天活動在前，其餘依開始時間排序。跨午夜的活動也算。"""
    today = now.date()
    day_start = datetime.combine(today, time(), now.tzinfo)
    day_end = day_start + timedelta(days=1)
    out = []
    for ev in events:
        if ev.all_day:
            if ev.start.date() <= today < ev.end.date():
                out.append(ev)
        elif ev.start < day_end and ev.end > day_start and (include_finished or ev.end > now):
            out.append(ev)
    return sorted(out, key=lambda e: (not e.all_day, e.start))


def compose(events: list[CalendarEvent], now: datetime, limit: int = 6) -> str:
    items = todays_events(events, now)
    if not items:
        return "今天沒有排行程，好好享受一天吧～"
    lines = [f"今天有 {len(items)} 個行程："]
    for ev in items[:limit]:
        when = "全天" if ev.all_day else ev.start.strftime("%H:%M")
        lines.append(f"・{when}  {ev.title}")
    if len(items) > limit:
        lines.append(f"…還有 {len(items) - limit} 個")
    return "\n".join(lines)


# ---- 定時列出今日行程 ----
def due_agenda_times(now: datetime, times: list[str], fired: dict[str, str],
                     grace_minutes: int = AGENDA_GRACE_MINUTES) -> list[str]:
    """回傳現在應該發出的時間點（HH:MM）。每個時間點每天最多一次；錯過超過 grace_minutes 就略過。"""
    today = now.date().isoformat()
    due = []
    for hhmm in times:
        try:
            h, m = (int(x) for x in hhmm.split(":"))
            at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            continue
        if fired.get(hhmm) == today:
            continue
        if at <= now < at + timedelta(minutes=grace_minutes):
            due.append(hhmm)
    return sorted(due)


def _status(ev: CalendarEvent, now: datetime) -> str:
    if ev.all_day:
        return ""
    if ev.end <= now:
        return "（已結束）"
    if ev.start <= now:
        return "（進行中）"
    return ""


def compose_agenda(events: list[CalendarEvent], now: datetime) -> str:
    """完整列出今天所有活動（含已結束），並標示狀態。"""
    items = todays_events(events, now, include_finished=True)
    if not items:
        return "今天沒有排行程，好好享受一天吧～"
    remaining = sum(1 for e in items if e.all_day or e.end > now)
    lines = [f"今天共 {len(items)} 個行程，還有 {remaining} 個沒結束："]
    for ev in items:
        if ev.all_day:
            when = "全天"
        else:
            start = ev.start.strftime("%H:%M") if ev.start.date() == now.date() else "昨天"
            when = f"{start}–{ev.end:%H:%M}" if ev.end.date() == now.date() else f"{start}–明天"
        mark = "✓" if not ev.all_day and ev.end <= now else "・"
        lines.append(f"{mark} {when}  {ev.title}{_status(ev, now)}")
    return "\n".join(lines)
