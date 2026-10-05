"""月曆與時間軸的版面計算（純函式，不依賴 Qt，方便單元測試）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ...cal.models import CalendarEvent

SNAP_MINUTES = 15


# ---- 日期範圍 ----
def first_weekday(week_start: str) -> int:
    """設定值 sun / mon → Python 的 weekday()（週一=0、週日=6）。"""
    return 0 if week_start == "mon" else 6


def week_start_of(d: date, week_start: str) -> date:
    offset = (d.weekday() - first_weekday(week_start)) % 7
    return d - timedelta(days=offset)


def month_grid(year: int, month: int, week_start: str) -> list[date]:
    """月曆的 6 週 × 7 天 = 42 個日期（包含前後月份補位）。"""
    start = week_start_of(date(year, month, 1), week_start)
    return [start + timedelta(days=i) for i in range(42)]


def week_dates(d: date, week_start: str) -> list[date]:
    start = week_start_of(d, week_start)
    return [start + timedelta(days=i) for i in range(7)]


def weekday_labels(week_start: str) -> list[str]:
    names = "一二三四五六日"
    first = first_weekday(week_start)
    return [names[(first + i) % 7] for i in range(7)]


def view_range(view: str, anchor: date, week_start: str) -> tuple[date, date]:
    """每種檢視要讀取的日期範圍 [start, end)。"""
    if view == "month":
        grid = month_grid(anchor.year, anchor.month, week_start)
        return grid[0], grid[-1] + timedelta(days=1)
    if view == "week":
        days = week_dates(anchor, week_start)
        return days[0], days[-1] + timedelta(days=1)
    return anchor, anchor + timedelta(days=1)


def shift_anchor(view: str, anchor: date, step: int) -> date:
    """上一段 / 下一段：月檢視移一個月，週檢視移 7 天，日檢視移 1 天。"""
    if view == "month":
        month_index = anchor.year * 12 + anchor.month - 1 + step
        return date(month_index // 12, month_index % 12 + 1, 1)
    return anchor + timedelta(days=7 * step if view == "week" else step)


# ---- 活動與日期 ----
def event_days(ev: CalendarEvent) -> tuple[date, date]:
    """活動涵蓋的第一天與最後一天（含）。"""
    return ev.start.date(), max(ev.start.date(), ev.last_day)


def events_on(events: list[CalendarEvent], d: date) -> list[CalendarEvent]:
    """某一天的活動：全天 / 跨日在前，再依開始時間排序。"""
    out = [ev for ev in events if event_days(ev)[0] <= d <= event_days(ev)[1]]
    return sorted(out, key=lambda e: (not e.spans_days, e.start, e.title))


def is_bar(ev: CalendarEvent) -> bool:
    """月曆上用色條（而不是「色點 + 時間」）呈現的活動。"""
    return ev.all_day or ev.spans_days


# ---- 月曆：每週的分軌 ----
@dataclass(frozen=True)
class Placed:
    event: CalendarEvent
    col_start: int          # 第幾欄（0 起算）
    col_end: int            # 到第幾欄（含）
    lane: int
    cont_left: bool = False   # 從上一週延續過來
    cont_right: bool = False  # 延續到下一週


def layout_week(events: list[CalendarEvent], week: list[date]) -> list[Placed]:
    """把一段連續日期（月曆的一週，或日檢視的 1 天）內的活動分配到不同「軌道」，跨日活動連成一條，不互相重疊。"""
    first, last = week[0], week[-1]
    items = []
    for ev in events:
        d0, d1 = event_days(ev)
        if d1 < first or d0 > last:
            continue
        items.append((ev, d0, d1))
    # 色條（跨日、全天）先放，越長越前面；再放當天的計時活動
    items.sort(key=lambda t: (not is_bar(t[0]), -(t[2] - t[1]).days if is_bar(t[0]) else 0, t[0].start, t[0].title))
    occupied: list[set[int]] = []
    placed = []
    for ev, d0, d1 in items:
        c0 = max(0, (d0 - first).days)
        c1 = min(len(week) - 1, (d1 - first).days)
        cols = set(range(c0, c1 + 1))
        lane = 0
        while lane < len(occupied) and occupied[lane] & cols:
            lane += 1
        if lane == len(occupied):
            occupied.append(set())
        occupied[lane] |= cols
        placed.append(Placed(ev, c0, c1, lane, cont_left=d0 < first, cont_right=d1 > last))
    return placed


def visible_and_hidden(placed: list[Placed], max_lanes: int) -> tuple[list[Placed], dict[int, int]]:
    """格子只放得下 max_lanes 列時：回傳要畫的項目，以及每一欄被藏起來的數量（顯示「+N 則」）。

    某一欄只要有東西被藏，就把最後一列讓給「+N 則」。
    """
    if max_lanes <= 0:
        hidden = {}
        for p in placed:
            for c in range(p.col_start, p.col_end + 1):
                hidden[c] = hidden.get(c, 0) + 1
        return [], hidden
    per_col: dict[int, int] = {}
    for p in placed:
        for c in range(p.col_start, p.col_end + 1):
            per_col[c] = max(per_col.get(c, 0), p.lane + 1)
    overflow_cols = {c for c, n in per_col.items() if n > max_lanes}
    visible, hidden = [], {}
    for p in placed:
        cols = range(p.col_start, p.col_end + 1)
        limit = max_lanes - 1 if any(c in overflow_cols for c in cols) else max_lanes
        if p.lane < limit:
            visible.append(p)
        else:
            for c in cols:
                hidden[c] = hidden.get(c, 0) + 1
    return visible, hidden


# ---- 時間軸：重疊活動並排 ----
@dataclass(frozen=True)
class TimeBlock:
    event: CalendarEvent
    top_min: int     # 當天 0:00 起算的分鐘
    bottom_min: int
    col: int
    ncols: int


def layout_day(events: list[CalendarEvent], d: date) -> list[TimeBlock]:
    """某一天時間軸上的計時活動：截到當天範圍內，重疊的活動分欄並排。"""
    spans = []
    for ev in events:
        if ev.all_day:
            continue
        day_start = datetime.combine(d, time(), ev.start.tzinfo)
        day_end = day_start + timedelta(days=1)
        if ev.end <= day_start or ev.start >= day_end:
            continue
        top = int((max(ev.start, day_start) - day_start).total_seconds() // 60)
        bottom = int((min(ev.end, day_end) - day_start).total_seconds() // 60)
        spans.append((ev, top, max(bottom, top + 15)))  # 太短的活動至少顯示 15 分鐘高
    spans.sort(key=lambda t: (t[1], -(t[2] - t[1]), t[0].title))

    # 互相有重疊（直接或間接）的活動組成一群，同一群內用最少的欄數排開
    blocks: list[TimeBlock] = []
    cluster: list[tuple[CalendarEvent, int, int, int]] = []
    col_ends: list[int] = []
    cluster_end = 0

    def flush():
        blocks.extend(TimeBlock(ev, top, bottom, col, len(col_ends)) for ev, top, bottom, col in cluster)

    for ev, top, bottom in spans:
        if cluster and top >= cluster_end:
            flush()
            cluster, col_ends, cluster_end = [], [], 0
        col = next((i for i, end in enumerate(col_ends) if end <= top), len(col_ends))
        if col == len(col_ends):
            col_ends.append(bottom)
        else:
            col_ends[col] = bottom
        cluster.append((ev, top, bottom, col))
        cluster_end = max(cluster_end, bottom)
    if cluster:
        flush()
    return blocks


# ---- 拖曳換算 ----
def snap(minutes: float, step: int = SNAP_MINUTES) -> int:
    return int(round(minutes / step) * step)


def moved_by_days(ev: CalendarEvent, days: int) -> tuple[datetime, datetime]:
    """月曆上拖到別天：日期平移，時刻不變。"""
    delta = timedelta(days=days)
    return ev.start + delta, ev.end + delta


def moved_in_time(ev: CalendarEvent, new_day: date, start_min: int) -> tuple[datetime, datetime]:
    """時間軸上拖曳：換到 new_day 的 start_min 分，長度不變。"""
    duration = ev.end - ev.start
    start = datetime.combine(new_day, time(), ev.start.tzinfo) + timedelta(minutes=start_min)
    return start, start + duration


def resized(ev: CalendarEvent, end_min: int) -> tuple[datetime, datetime]:
    """拖曳下緣改結束時間（以活動開始那天的 0:00 起算），至少 15 分鐘。"""
    day_start = datetime.combine(ev.start.date(), time(), ev.start.tzinfo)
    end = day_start + timedelta(minutes=end_min)
    return ev.start, max(end, ev.start + timedelta(minutes=SNAP_MINUTES))


def overlaps(events: list[CalendarEvent], start: datetime, end: datetime,
             exclude_id: str = "") -> list[CalendarEvent]:
    """和 [start, end) 時間重疊的計時活動（衝突提示用）。"""
    return [ev for ev in events
            if not ev.all_day and not ev.read_only and ev.id != exclude_id and ev.start < end and ev.end > start]
