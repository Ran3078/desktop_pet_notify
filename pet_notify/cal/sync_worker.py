"""在背景執行緒呼叫 Google API，結果用 signal 回到 UI 執行緒。"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from enum import Enum

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from .cache import load_cache, save_cache
from .gcal import INSTANCE, AuthRequired, CredentialsMissing, GoogleCalendarClient
from .models import CalendarEvent, EventDraft
from .oauth_local import AuthCancelled, AuthDenied, AuthTimeout

log = logging.getLogger(__name__)


class AuthState(Enum):
    NO_CREDENTIALS = "no_credentials"  # 沒有 credentials.json
    SIGNED_OUT = "signed_out"          # 有 credentials，但還沒授權
    SIGNED_IN = "signed_in"
    ERROR = "error"                    # 網路或 API 錯誤（仍使用快取）


class _Task(QRunnable):
    def __init__(self, fn: Callable, done: Callable, fail: Callable, emitter: "CalendarController"):
        super().__init__()
        self._fn, self._done, self._fail, self._emitter = fn, done, fail, emitter

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - 錯誤一律回報到 UI 執行緒處理
            self._emitter._dispatch.emit(self._fail, exc)
        else:
            self._emitter._dispatch.emit(self._done, result)


def describe_error(exc: Exception) -> str:
    if isinstance(exc, CredentialsMissing):
        return "找不到 credentials.json，請依 README 的說明下載後放到程式資料夾。"
    if isinstance(exc, AuthRequired):
        return "尚未登入 Google，請在設定器按「登入 Google」。"
    if isinstance(exc, AuthCancelled):
        return "已取消登入。"
    if isinstance(exc, AuthDenied):
        return "你在 Google 授權頁面拒絕了存取，需要允許日曆權限才能同步。"
    if isinstance(exc, AuthTimeout):
        return "等候授權逾時（3 分鐘），請重新按「登入 Google」。"
    try:
        from googleapiclient.errors import HttpError

        if isinstance(exc, HttpError):
            return f"Google API 錯誤（HTTP {exc.resp.status}）：{exc.reason}"
    except ImportError:
        pass
    if isinstance(exc, (OSError, TimeoutError)):
        return f"網路連線失敗：{exc}"
    return f"{type(exc).__name__}: {exc}"


class CalendarController(QObject):
    events_changed = Signal(list)           # list[CalendarEvent]
    auth_state_changed = Signal(object, str)  # AuthState, 說明文字
    busy_changed = Signal(bool)
    signing_in_changed = Signal(bool)
    operation_failed = Signal(str)
    operation_succeeded = Signal(str)
    range_loaded = Signal(object, object, list)   # start, end, list[CalendarEvent]
    holidays_loaded = Signal()
    search_results = Signal(str, list)            # 關鍵字, list[CalendarEvent]
    deleted = Signal(str, object)                 # 標題, 復原用的 EventDraft

    _dispatch = Signal(object, object)  # (callback, result)，跨執行緒用

    RANGE_FRESH_SECONDS = 60  # 同一段範圍在這段時間內不重複向 Google 讀取

    def __init__(self, config, client: GoogleCalendarClient | None = None):
        super().__init__()
        self._config = config
        self._client = client or GoogleCalendarClient()
        # 月曆畫面用的範圍資料：(start, end) → (讀取時間, 活動)
        self._range_cache: dict[tuple[date, date], tuple[float, list[CalendarEvent]]] = {}
        self.current_range: tuple[date, date] | None = None
        self.holidays: dict[int, list[CalendarEvent]] = {}
        self._holiday_years_loading: set[int] = set()
        self.holidays_available = True
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        # 登入要等瀏覽器，獨立一條執行緒，才不會卡住同步與其他操作
        self._auth_pool = QThreadPool(self)
        self._auth_pool.setMaxThreadCount(1)
        self.signing_in = False
        self._dispatch.connect(self._on_dispatch)
        self._pending = 0
        self.events: list[CalendarEvent] = load_cache()
        self.auth_state = AuthState.SIGNED_OUT
        self.loaded_once = bool(self.events)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.sync)
        self._apply_interval()
        config.changed.connect(lambda keys: "sync_interval_min" in keys and self._apply_interval())

    def _apply_interval(self) -> None:
        minutes = max(1, int(self._config.settings.sync_interval_min))
        self._timer.start(minutes * 60_000)

    @Slot(object, object)
    def _on_dispatch(self, callback, result) -> None:
        self._pending -= 1
        if self._pending == 0:
            self.busy_changed.emit(False)
        callback(result)

    def _run(self, fn, done, fail=None, pool=None) -> None:
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)
        (pool or self._pool).start(_Task(fn, done, fail or self._on_error, self))

    def _set_auth(self, state: AuthState, message: str = "") -> None:
        self.auth_state = state
        self.auth_state_changed.emit(state, message)

    # ---- 公開方法 ----
    def start(self) -> None:
        if self.events:
            self.events_changed.emit(self.events)
        if not self._client.has_credentials_file() and not self._client.has_token():
            log.warning("找不到 credentials.json，Google 日曆功能停用（仍可使用快取與其他功能）")
            self._set_auth(AuthState.NO_CREDENTIALS, describe_error(CredentialsMissing()))
            return
        self.sync()

    def sync(self) -> None:
        if self.signing_in:
            return  # 登入完成後會自動抓一次活動
        if self.auth_state == AuthState.NO_CREDENTIALS and not self._client.has_credentials_file():
            return
        self._run(lambda: self._client.list_upcoming(30), self._on_events)
        if self.current_range:
            self.fetch_range(*self.current_range, force=True)

    @property
    def can_fetch(self) -> bool:
        return not self.signing_in and self.auth_state in (AuthState.SIGNED_IN, AuthState.ERROR)

    # ---- 月曆範圍 ----
    def cached_range(self, start: date, end: date) -> list[CalendarEvent] | None:
        hit = self._range_cache.get((start, end))
        return hit[1] if hit else None

    def fetch_range(self, start: date, end: date, force: bool = False) -> None:
        """讀取 [start, end) 的活動；有快取就先送出快取，再視需要背景更新。"""
        self.current_range = (start, end)
        hit = self._range_cache.get((start, end))
        if hit:
            self.range_loaded.emit(start, end, hit[1])
            if not force and time.monotonic() - hit[0] < self.RANGE_FRESH_SECONDS:
                return
        if self._config.settings.show_holidays:
            for year in range(start.year, end.year + 1):
                self.fetch_holidays(year)
        if not self.can_fetch:
            return

        def done(events):
            self._range_cache[(start, end)] = (time.monotonic(), events)
            self.range_loaded.emit(start, end, events)

        self._run(lambda: self._client.list_range(start, end), done, self._on_range_error)

    def _on_range_error(self, exc: Exception) -> None:
        log.warning("讀取月曆範圍失敗：%s", describe_error(exc))
        self.operation_failed.emit(describe_error(exc))

    def fetch_holidays(self, year: int) -> None:
        if (not self.holidays_available or year in self.holidays or year in self._holiday_years_loading
                or not self.can_fetch):
            return
        self._holiday_years_loading.add(year)

        def done(events):
            self._holiday_years_loading.discard(year)
            self.holidays[year] = events
            self.holidays_loaded.emit()

        def fail(exc):
            self._holiday_years_loading.discard(year)
            self.holidays_available = False
            log.warning("無法讀取國定假日日曆，將不顯示假日：%s", describe_error(exc))

        self._run(lambda: self._client.list_holidays(year), done, fail)

    def holidays_on(self, d: date) -> list[CalendarEvent]:
        return [h for h in self.holidays.get(d.year, []) if h.start.date() <= d <= h.last_day]

    def fetch_master(self, event_id: str, done: Callable[[dict], None]) -> None:
        """讀取重複活動的主活動（含 recurrence），讀完在 UI 執行緒呼叫 done(item)。"""
        self._run(lambda: self._client.get_event(event_id), done, self._on_range_error)

    # ---- 搜尋 ----
    def search(self, q: str) -> None:
        q = q.strip()
        if not q or not self.can_fetch:
            return
        self._run(lambda: self._client.search(q), lambda events: self.search_results.emit(q, events))

    def sign_in(self) -> None:
        if self.signing_in:
            return

        def work():
            self._client.authorize(interactive=True)
            return self._client.list_upcoming(30)

        def finished(callback):
            def wrapper(result):
                self._set_signing_in(False)
                callback(result)
            return wrapper

        self._set_signing_in(True)
        self._run(work, finished(self._on_events), finished(self._on_error), pool=self._auth_pool)

    def cancel_sign_in(self) -> None:
        if self.signing_in:
            log.info("使用者取消 Google 登入")
            self._client.cancel_sign_in()

    def shutdown(self) -> None:
        """結束程式前呼叫：取消等待中的登入，並等背景工作收尾。"""
        self._timer.stop()
        self._client.cancel_sign_in()
        for pool in (self._auth_pool, self._pool):
            if not pool.waitForDone(3000):
                log.warning("背景工作未在 3 秒內結束")

    def _set_signing_in(self, value: bool) -> None:
        self.signing_in = value
        self.signing_in_changed.emit(value)

    def sign_out(self) -> None:
        self._client.sign_out()
        self._set_auth(AuthState.SIGNED_OUT, "已登出 Google")

    # ---- 新增 / 修改 / 刪除 ----
    def create(self, draft: EventDraft, message: str = "") -> None:
        self._run(lambda: self._client.create_event(draft),
                  lambda ev: self._after_change(message or f"已新增「{ev.title}」"))

    def update(self, event: CalendarEvent, draft: EventDraft, scope: str = INSTANCE) -> None:
        self._run(lambda: self._client.update_event(event, draft, scope),
                  lambda ev: self._after_change(f"已修改「{ev.title}」"))

    def move(self, event: CalendarEvent, new_start: datetime, new_end: datetime, scope: str = INSTANCE) -> None:
        """拖曳改期：只改時間，其他內容不變。new_end 對全天活動來說是「不含」的結束日 00:00。"""
        draft = EventDraft.from_event(event)
        draft.start = new_start
        # EventDraft 的全天結束日是「包含」的那天
        draft.end = max(new_start, new_end - timedelta(days=1)) if event.all_day else new_end
        self.update(event, draft, scope)

    def delete(self, event: CalendarEvent, scope: str = INSTANCE) -> None:
        def done(restore: EventDraft):
            self.deleted.emit(event.title, restore)
            self._after_change(f"已刪除「{event.title}」")

        self._run(lambda: self._client.delete_event(event, scope), done)

    def restore(self, draft: EventDraft) -> None:
        self.create(draft, message=f"已復原「{draft.title}」")

    # ---- 回呼 ----
    def _after_change(self, message: str) -> None:
        self.operation_succeeded.emit(message)
        self._range_cache.clear()
        self.sync()

    def _on_events(self, events: list[CalendarEvent]) -> None:
        was_signed_in = self.auth_state == AuthState.SIGNED_IN
        self.events = events
        self.loaded_once = True
        save_cache(events)
        self._set_auth(AuthState.SIGNED_IN, "已連線 Google 日曆")
        self.events_changed.emit(events)
        if not was_signed_in and self.current_range:
            self.fetch_range(*self.current_range, force=True)  # 剛登入或恢復連線，補抓月曆

    def _on_error(self, exc: Exception) -> None:
        message = describe_error(exc)
        if isinstance(exc, (AuthCancelled, AuthDenied, AuthTimeout)):
            log.warning("Google 登入未完成：%s", message)
            state = AuthState.SIGNED_OUT
        elif isinstance(exc, AuthRequired):
            log.warning("需要 Google 授權")
            state = AuthState.SIGNED_OUT
        elif isinstance(exc, CredentialsMissing):
            log.warning("找不到 credentials.json")
            state = AuthState.NO_CREDENTIALS
        else:
            log.error("Google 日曆操作失敗：%s", message, exc_info=exc)
            state = AuthState.ERROR
        self._set_auth(state, message)
        self.operation_failed.emit(message)
