"""行事曆事件資料模型（不依賴 Google 套件，方便測試）。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, time, timedelta

PRIMARY = "primary"
TW_HOLIDAY_CALENDAR = "zh-tw.taiwan#holiday@group.v.calendar.google.com"
MAX_REMINDER_OVERRIDES = 5  # Google 每個活動最多 5 個自訂提醒


def local_now() -> datetime:
    return datetime.now().astimezone()


def local_tz():
    return local_now().tzinfo


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start: datetime  # 一律是 aware datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    description: str = ""
    hangout_link: str = ""
    html_link: str = ""
    color_id: str = ""
    recurring_event_id: str = ""            # 重複活動的某一次：指向主活動
    reminder_minutes: tuple[int, ...] | None = None  # None = 使用預設提醒；() = 不提醒
    calendar_id: str = PRIMARY
    read_only: bool = False                 # 國定假日等唯讀活動

    @property
    def meeting_url(self) -> str:
        if self.hangout_link:
            return self.hangout_link
        loc = self.location.strip()
        return loc if loc.startswith(("http://", "https://")) else ""

    @property
    def is_recurring(self) -> bool:
        return bool(self.recurring_event_id)

    @property
    def last_day(self) -> date:
        """活動涵蓋的最後一天（全天活動的 end 是隔天 00:00，不算）。"""
        if self.all_day or self.end.time() == time(0) and self.end > self.start:
            return (self.end - timedelta(seconds=1)).date()
        return self.end.date()

    @property
    def spans_days(self) -> bool:
        return self.all_day or self.last_day > self.start.date()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        if self.reminder_minutes is not None:
            d["reminder_minutes"] = list(self.reminder_minutes)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CalendarEvent":
        known = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in known}  # 舊版快取沒有新欄位、新版快取在舊版也讀得懂
        d["start"] = datetime.fromisoformat(d["start"])
        d["end"] = datetime.fromisoformat(d["end"])
        if d.get("reminder_minutes") is not None:
            d["reminder_minutes"] = tuple(d["reminder_minutes"])
        return cls(**d)

    @classmethod
    def from_google(cls, item: dict, calendar_id: str = PRIMARY, read_only: bool = False) -> "CalendarEvent":
        start_raw, end_raw = item.get("start", {}), item.get("end", {})
        all_day = "date" in start_raw and "dateTime" not in start_raw
        if all_day:
            tz = local_tz()
            start = datetime.combine(date.fromisoformat(start_raw["date"]), time(), tz)
            end = datetime.combine(date.fromisoformat(end_raw.get("date", start_raw["date"])), time(), tz)
        else:
            start = datetime.fromisoformat(start_raw["dateTime"]).astimezone()
            end = datetime.fromisoformat(end_raw.get("dateTime", start_raw["dateTime"])).astimezone()
        reminders = item.get("reminders") or {}
        if reminders.get("useDefault", True):
            minutes = None
        else:
            minutes = tuple(sorted({int(o.get("minutes", 0)) for o in reminders.get("overrides", [])}, reverse=True))
        return cls(
            id=item["id"],
            title=item.get("summary") or "（無標題）",
            start=start,
            end=end,
            all_day=all_day,
            location=item.get("location", ""),
            description=item.get("description", ""),
            hangout_link=item.get("hangoutLink", ""),
            html_link=item.get("htmlLink", ""),
            color_id=str(item.get("colorId", "")),
            recurring_event_id=item.get("recurringEventId", ""),
            reminder_minutes=minutes,
            calendar_id=calendar_id,
            read_only=read_only,
        )


@dataclass
class EventDraft:
    """設定器送出的新增 / 修改內容。"""

    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    description: str = ""
    color_id: str = ""
    recurrence: list[str] | None = None     # None = 不更動；[] = 取消重複
    reminder_minutes: tuple[int, ...] | None = None  # None = 使用預設提醒
    tz_name: str = ""                       # IANA 時區（重複活動必填）

    def to_google_body(self, for_patch: bool = False) -> dict:
        """for_patch=True 時會把另一種時間欄位設成 null，讓全天 / 非全天可以互換。"""
        body: dict = {"summary": self.title, "location": self.location, "description": self.description}
        if self.all_day:
            start_d = self.start.date()
            end_d = max(self.end.date(), start_d) + timedelta(days=1)  # Google 的全天結束日不含當天
            body["start"] = {"date": start_d.isoformat()}
            body["end"] = {"date": end_d.isoformat()}
            if for_patch:
                body["start"].update(dateTime=None, timeZone=None)
                body["end"].update(dateTime=None, timeZone=None)
        else:
            body["start"] = {"dateTime": self.start.astimezone().isoformat()}
            body["end"] = {"dateTime": self.end.astimezone().isoformat()}
            if self.tz_name:
                body["start"]["timeZone"] = self.tz_name
                body["end"]["timeZone"] = self.tz_name
            if for_patch:
                body["start"]["date"] = None
                body["end"]["date"] = None
        if self.color_id:
            body["colorId"] = self.color_id
        elif for_patch:
            body["colorId"] = None
        if self.reminder_minutes is None:
            body["reminders"] = {"useDefault": True, "overrides": []}
        else:
            minutes = sorted(set(self.reminder_minutes), reverse=True)[:MAX_REMINDER_OVERRIDES]
            body["reminders"] = {"useDefault": False,
                                 "overrides": [{"method": "popup", "minutes": m} for m in minutes]}
        if self.recurrence is not None:
            body["recurrence"] = list(self.recurrence)
        return body

    @classmethod
    def from_event(cls, ev: CalendarEvent) -> "EventDraft":
        """把既有活動轉成草稿（全天活動的結束日轉回「包含當天」）。"""
        end = ev.end - timedelta(days=1) if ev.all_day else ev.end
        return cls(title=ev.title, start=ev.start, end=max(end, ev.start), all_day=ev.all_day,
                   location=ev.location, description=ev.description, color_id=ev.color_id,
                   reminder_minutes=ev.reminder_minutes)
