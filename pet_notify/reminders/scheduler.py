"""多段提醒判斷（純函式）+ QTimer 驅動的排程器。"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from ..cal.models import CalendarEvent, local_now

log = logging.getLogger(__name__)

START_GRACE_SECONDS = 60   # 「現在開始」提醒最多晚 60 秒還會發
TICK_MS = 15_000
SLEEP_GAP_SECONDS = 120    # 兩次 tick 間隔超過這個值，就視為剛從睡眠喚醒


def reminder_key(event: CalendarEvent, stage: int) -> str:
    return f"{event.id}|{event.start.isoformat()}|{stage}"


@dataclass(frozen=True)
class Reminder:
    event: CalendarEvent
    stage: int                          # 觸發的提醒點（分鐘），-1 代表稍後提醒（snooze）
    mark_keys: tuple[str, ...] = field(default=())
    first_stage: bool = False           # 是不是最早的那一段（用來算好感度加分）

    def remaining_seconds(self, now: datetime) -> float:
        return (self.event.start - now).total_seconds()


def stages_for(event: CalendarEvent, default: list[int]) -> list[int]:
    """這個活動的提醒時間點（分鐘，由小到大）：有自訂提醒就用自訂的，否則用全域設定。"""
    source = default if event.reminder_minutes is None else event.reminder_minutes
    return sorted({max(0, int(s)) for s in source})


def due_reminders(
    events: Iterable[CalendarEvent],
    now: datetime,
    stages: list[int],
    is_notified: Callable[[str], bool],
) -> list[Reminder]:
    """回傳現在應該發出的提醒。stages 是全域預設，活動有自訂提醒時以活動為準。

    同一個活動如果同時有多段到期（例如睡眠醒來），只發最緊急的那一段，
    並把所有已到期的段落一起標記為已提醒，避免連續轟炸。
    """
    out = []
    for ev in events:
        if ev.all_day or ev.read_only:
            continue
        ev_stages = stages_for(ev, stages)
        if not ev_stages:
            continue  # 這個活動設定為不提醒
        first = max(ev_stages)
        remaining = (ev.start - now).total_seconds()
        if remaining < -START_GRACE_SECONDS:
            continue
        due = [s for s in ev_stages if remaining <= s * 60]
        if not due:
            continue
        most_urgent = min(due)
        key = reminder_key(ev, most_urgent)
        if is_notified(key):
            continue
        out.append(
            Reminder(
                event=ev,
                stage=most_urgent,
                mark_keys=tuple(reminder_key(ev, s) for s in due),
                first_stage=most_urgent == first,
            )
        )
    out.sort(key=lambda r: r.event.start)
    return out


def describe_remaining(seconds: float) -> str:
    if seconds > 90:
        return f"{round(seconds / 60)} 分鐘後"
    if seconds > 0:
        return "馬上就要開始了"
    return "現在開始！"


class ReminderScheduler(QObject):
    reminder = Signal(object)   # Reminder
    woke_up = Signal()          # 偵測到系統剛從睡眠喚醒
    tick = Signal(object)       # 每次檢查時送出 now，給其他元件順便使用

    def __init__(self, config, state_mgr, events_provider: Callable[[], list[CalendarEvent]]):
        super().__init__()
        self._config = config
        self._state = state_mgr
        self._events = events_provider
        self._snoozed: list[tuple[datetime, CalendarEvent]] = []
        self._last_tick: datetime | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)

    def start(self) -> None:
        self._timer.start(TICK_MS)
        self.check()

    def snooze(self, event: CalendarEvent, minutes: int = 5) -> None:
        fire_at = local_now() + timedelta(minutes=minutes)
        self._snoozed.append((fire_at, event))
        log.info("「%s」將於 %s 再次提醒", event.title, fire_at.strftime("%H:%M"))

    def check(self) -> None:
        now = local_now()
        if self._last_tick and (now - self._last_tick).total_seconds() > SLEEP_GAP_SECONDS:
            log.info("偵測到系統喚醒（距上次檢查 %.0f 秒）", (now - self._last_tick).total_seconds())
            self.woke_up.emit()
        self._last_tick = now

        try:
            for r in due_reminders(self._events(), now, self._config.settings.stages_sorted, self._state.is_notified):
                self._state.mark_notified(list(r.mark_keys), r.event.start)
                log.info("提醒：%s（%s 分鐘段）", r.event.title, r.stage)
                self.reminder.emit(r)

            still = []
            for fire_at, ev in self._snoozed:
                if now >= fire_at:
                    if (ev.start - now).total_seconds() > -START_GRACE_SECONDS * 5:
                        self.reminder.emit(Reminder(event=ev, stage=-1))
                else:
                    still.append((fire_at, ev))
            self._snoozed = still
        except Exception:
            log.exception("提醒檢查失敗")

        self.tick.emit(now)
