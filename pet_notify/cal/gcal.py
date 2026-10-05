"""Google Calendar API 包裝（主日曆、雙向同步）。所有方法都是阻塞呼叫，請在背景執行緒使用。"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta

from .. import app_paths
from .models import PRIMARY, TW_HOLIDAY_CALENDAR, CalendarEvent, EventDraft, local_now
from .recurrence import WEEKDAY_CODES, RecurrenceRule
from .oauth_local import run_cancellable_flow

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
INSTANCE = "instance"  # 只有這一次（或一般活動）
SERIES = "series"      # 整個重複系列


class CredentialsMissing(Exception):
    """找不到 credentials.json。"""


class AuthRequired(Exception):
    """需要使用者到瀏覽器授權。"""


class GoogleCalendarClient:
    def __init__(self):
        self._lock = threading.Lock()  # httplib2 不是 thread-safe，所有呼叫串行化
        self._creds = None
        self._service = None
        self._cancel_sign_in = threading.Event()
        self._calendar_tz = ""  # 從 events.list 回應取得的日曆時區

    # ---- 授權 ----
    @staticmethod
    def has_credentials_file() -> bool:
        return app_paths.CREDENTIALS_FILE.exists()

    @staticmethod
    def has_token() -> bool:
        return app_paths.TOKEN_FILE.exists()

    def authorize(self, interactive: bool) -> None:
        """取得有效憑證。interactive=True 時若沒有可用 token 會開瀏覽器讓使用者授權（可用 cancel_sign_in 取消）。"""
        with self._lock:
            creds = self._load_saved_creds()
            if creds is not None:
                self._store(creds)
                return
        if not interactive:
            raise AuthRequired()
        if not app_paths.CREDENTIALS_FILE.exists():
            raise CredentialsMissing(str(app_paths.CREDENTIALS_FILE))

        # 等瀏覽器的期間不持有鎖，避免卡住其他同步動作
        from google_auth_oauthlib.flow import InstalledAppFlow

        self._cancel_sign_in.clear()
        flow = InstalledAppFlow.from_client_secrets_file(str(app_paths.CREDENTIALS_FILE), SCOPES)
        creds = run_cancellable_flow(flow, self._cancel_sign_in)
        log.info("Google 授權完成")
        with self._lock:
            self._store(creds)

    def cancel_sign_in(self) -> None:
        self._cancel_sign_in.set()

    def _load_saved_creds(self):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not app_paths.TOKEN_FILE.exists():
            return None
        try:
            creds = Credentials.from_authorized_user_file(str(app_paths.TOKEN_FILE), SCOPES)
        except Exception:
            log.exception("token.json 格式錯誤，將重新授權")
            return None
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log.info("Google token 已更新")
                return creds
            except RefreshError:
                log.warning("Google token 更新失敗，刪除 token.json 並需要重新授權", exc_info=True)
                app_paths.TOKEN_FILE.unlink(missing_ok=True)
        return None

    def _store(self, creds) -> None:
        app_paths.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        if creds is not self._creds:
            self._creds = creds
            self._service = None

    def sign_out(self) -> None:
        with self._lock:
            app_paths.TOKEN_FILE.unlink(missing_ok=True)
            self._creds = None
            self._service = None
            log.info("已登出 Google（刪除 token.json）")

    def _svc(self):
        if self._creds is None:
            raise AuthRequired()
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("calendar", "v3", credentials=self._creds, cache_discovery=False)
        return self._service

    # ---- 讀取 ----
    def _list(self, time_min: datetime, time_max: datetime, calendar_id: str = PRIMARY,
              q: str | None = None, read_only: bool = False, limit: int = 2500) -> list[CalendarEvent]:
        self.authorize(interactive=False)
        events: list[CalendarEvent] = []
        with self._lock:
            page_token = None
            while len(events) < limit:
                params = dict(calendarId=calendar_id, timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
                              singleEvents=True, orderBy="startTime", maxResults=250, pageToken=page_token)
                if q:
                    params["q"] = q
                resp = self._svc().events().list(**params).execute()
                if calendar_id == PRIMARY and resp.get("timeZone"):
                    self._calendar_tz = resp["timeZone"]
                for item in resp.get("items", []):
                    if item.get("status") == "cancelled":
                        continue
                    try:
                        events.append(CalendarEvent.from_google(item, calendar_id, read_only))
                    except Exception:
                        log.exception("無法解析事件：%s", item.get("id"))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        return events[:limit]

    def list_upcoming(self, days: int = 30) -> list[CalendarEvent]:
        now = local_now()
        # 往前抓一天，才能顯示今天已開始的活動
        events = self._list(now - timedelta(days=1), now + timedelta(days=days))
        log.info("同步完成，共 %d 個活動", len(events))
        return events

    def list_range(self, start: date, end: date) -> list[CalendarEvent]:
        """[start, end) 這段日期內的活動（月曆畫面用）。"""
        tz = local_now().tzinfo
        events = self._list(datetime.combine(start, time(), tz), datetime.combine(end, time(), tz))
        log.info("讀取 %s ~ %s 的活動，共 %d 個", start, end, len(events))
        return events

    def list_holidays(self, year: int) -> list[CalendarEvent]:
        tz = local_now().tzinfo
        events = self._list(datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz),
                            calendar_id=TW_HOLIDAY_CALENDAR, read_only=True)
        log.info("讀取 %d 年國定假日，共 %d 個", year, len(events))
        return events

    def search(self, q: str, days_back: int = 365, days_ahead: int = 365) -> list[CalendarEvent]:
        now = local_now()
        events = self._list(now - timedelta(days=days_back), now + timedelta(days=days_ahead), q=q, limit=200)
        log.info("搜尋「%s」，找到 %d 個活動", q, len(events))
        return events

    def get_event(self, event_id: str) -> dict:
        self.authorize(interactive=False)
        with self._lock:
            return self._svc().events().get(calendarId=PRIMARY, eventId=event_id).execute()

    def tz_name(self) -> str:
        return self._calendar_tz or local_iana_tz()

    # ---- 寫入 ----
    def create_event(self, draft: EventDraft) -> CalendarEvent:
        self.authorize(interactive=False)
        if not draft.tz_name:
            draft.tz_name = self.tz_name()
        with self._lock:
            item = self._svc().events().insert(calendarId=PRIMARY, body=draft.to_google_body()).execute()
        log.info("已新增活動：%s (%s)", draft.title, item.get("id"))
        return CalendarEvent.from_google(item)

    def update_event(self, event: CalendarEvent, draft: EventDraft, scope: str = INSTANCE) -> CalendarEvent:
        """scope=instance：只改這一次（或一般活動）；scope=series：改整個重複系列。"""
        self.authorize(interactive=False)
        if not draft.tz_name:
            draft.tz_name = self.tz_name()
        target_id = event.id
        if scope == SERIES and event.recurring_event_id:
            target_id = event.recurring_event_id
            draft = self._series_draft(event, draft)
        elif event.recurring_event_id:
            draft.recurrence = None  # 單一次的例外不能帶重複規則
        with self._lock:
            item = (self._svc().events()
                    .patch(calendarId=PRIMARY, eventId=target_id, body=draft.to_google_body(for_patch=True))
                    .execute())
        log.info("已修改活動：%s (%s，範圍=%s)", draft.title, target_id, scope)
        return CalendarEvent.from_google(item)

    def _series_draft(self, event: CalendarEvent, draft: EventDraft) -> EventDraft:
        """把「這一次」的修改換算到主活動。"""
        master_item = self.get_event(event.recurring_event_id)
        master = CalendarEvent.from_google(master_item)
        return series_draft(event, draft, master, master_item.get("recurrence", []))

    def delete_event(self, event: CalendarEvent, scope: str = INSTANCE) -> EventDraft:
        """刪除活動，回傳可用來「復原」的草稿。"""
        self.authorize(interactive=False)
        if scope == SERIES and event.recurring_event_id:
            master_item = self.get_event(event.recurring_event_id)
            restore = EventDraft.from_event(CalendarEvent.from_google(master_item))
            restore.recurrence = master_item.get("recurrence", [])
            target_id = event.recurring_event_id
        else:
            restore = EventDraft.from_event(event)
            target_id = event.id
        restore.tz_name = self.tz_name()
        with self._lock:
            self._svc().events().delete(calendarId=PRIMARY, eventId=target_id).execute()
        log.info("已刪除活動：%s（%s，範圍=%s）", event.title, target_id, scope)
        return restore


def series_draft(event: CalendarEvent, draft: EventDraft, master: CalendarEvent,
                 master_recurrence: list[str]) -> EventDraft:
    """「整個系列」的修改：把這一次的日期位移量與新時刻，套用到主活動原本的開始日。

    每週規則若整體位移了幾天，BYDAY 也跟著位移；對話框若重新設定了重複規則則以新規則為準。
    """
    day_shift = (draft.start.date() - event.start.date()).days
    duration = draft.end - draft.start
    new_start = datetime.combine(master.start.date() + timedelta(days=day_shift), draft.start.timetz())
    recurrence = draft.recurrence
    if recurrence is None:
        recurrence = list(master_recurrence)
        if day_shift:
            recurrence = [shift_byday(line, day_shift) for line in recurrence]
    return EventDraft(title=draft.title, start=new_start, end=new_start + duration, all_day=draft.all_day,
                      location=draft.location, description=draft.description, color_id=draft.color_id,
                      recurrence=recurrence, reminder_minutes=draft.reminder_minutes, tz_name=draft.tz_name)


def shift_byday(rrule_line: str, days: int) -> str:
    """整個系列往後移 days 天時，每週規則的 BYDAY 也要跟著移。"""
    if not rrule_line.upper().startswith("RRULE:"):
        return rrule_line
    rule = RecurrenceRule.parse(rrule_line)
    if rule is None or rule.freq != "WEEKLY" or not rule.byday or not all(c in WEEKDAY_CODES for c in rule.byday):
        return rrule_line
    shifted = sorted({WEEKDAY_CODES[(WEEKDAY_CODES.index(c) + days) % 7] for c in rule.byday},
                     key=WEEKDAY_CODES.index)
    parts = rrule_line.split(":", 1)[1].split(";")
    parts = [f"BYDAY={','.join(shifted)}" if part.upper().startswith("BYDAY=") else part for part in parts]
    return "RRULE:" + ";".join(parts)


_WINDOWS_TZ = {
    "Taipei Standard Time": "Asia/Taipei",
    "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Eastern Standard Time": "America/New_York",
    "Pacific Standard Time": "America/Los_Angeles",
    "UTC": "UTC",
}


def local_iana_tz() -> str:
    """Windows 時區名稱 → IANA 名稱（Google 的重複活動需要）。對應不到就用 UTC。"""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as key:
            name = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
        return _WINDOWS_TZ.get(name, "UTC")
    except (ImportError, OSError):
        return "UTC"
