"""行事曆分頁：Google 日曆風格的月 / 週 / 日檢視，右側日程面板，搜尋、快速新增、拖曳改期、復原刪除。

快捷鍵：T 今天、← / → 上下一段、M / W / D 切換檢視、N 新增、/ 搜尋、Delete 刪除選取的活動。
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ...cal import lunar
from ...cal.gcal import INSTANCE, SERIES
from ...cal.models import CalendarEvent, EventDraft, local_now
from ...cal.recurrence import RecurrenceRule
from ...cal.sync_worker import AuthState
from ..event_dialog import EventDialog
from . import fmt
from . import layout as L
from .month_view import MonthView
from .popups import EventCard, QuickAdd, SearchResults, ask_scope
from .time_grid import TimeGridView

log = logging.getLogger(__name__)

TAB_STYLE = """
QPushButton#nav { min-width: 30px; padding: 4px 8px; }
QPushButton#seg { border-radius: 0; padding: 5px 14px; background: #FFFFFF; }
QPushButton#seg:checked { background: #FFD3E0; font-weight: bold; }
QPushButton#segL { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#segR { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QLabel#rangeTitle { font-size: 14pt; font-weight: bold; color: #4A3B3F; }
QLabel#panelTitle { font-size: 12pt; font-weight: bold; color: #4A3B3F; }
QLabel#panelSub { color: #8A7A80; }
QFrame#snack { background: #4A3B3F; border-radius: 8px; }
QFrame#snack QLabel { color: #FFFFFF; }
QFrame#snack QPushButton { background: transparent; border: none; color: #FFB3C7; font-weight: bold; }
QFrame#panel { background: #FFFFFF; border-left: 1px solid #F0D9E0; }
"""


class DayPanel(QFrame):
    """月檢視右側：選取日期的全天活動與時間軸。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        self.sub = QLabel()
        self.sub.setObjectName("panelSub")
        self.sub.setWordWrap(True)
        self.add_btn = QPushButton("＋")
        self.add_btn.setToolTip("在這天新增活動")
        self.add_btn.setFixedWidth(34)
        self.grid = TimeGridView()
        self.grid.header.label_h = 4
        head = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(self.title)
        text.addWidget(self.sub)
        head.addLayout(text, 1)
        head.addWidget(self.add_btn, 0, Qt.AlignTop)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 6, 6)
        lay.addLayout(head)
        lay.addWidget(self.grid, 1)

    def show_day(self, d: date, events, holidays_on, show_lunar: bool, selected_event_id: str) -> None:
        rel = fmt.relative_day(d, date.today())
        self.title.setText(fmt.day_text(d) + (f"・{rel}" if rel else ""))
        parts = []
        if show_lunar and lunar.full_label(d):
            parts.append(lunar.full_label(d))
        parts.extend(f"🇹🇼 {h.title}" for h in holidays_on(d))
        day_events = [e for e in L.events_on(events, d) if not e.read_only]
        parts.append(f"{len(day_events)} 個活動" if day_events else "沒有活動，雙擊時間軸可以新增")
        self.sub.setText("　".join(parts))
        self.grid.set_data([d], events, holidays_on, show_lunar=False, selected_event_id=selected_event_id)


class CalendarTab(QWidget):
    def __init__(self, config, calendar, parent=None):
        super().__init__(parent)
        self.setStyleSheet(TAB_STYLE)
        self._config = config
        self._cal = calendar
        today = date.today()
        self.view = config.settings.calendar_view if config.settings.calendar_view in ("month", "week", "day") \
            else "month"
        self.anchor = today
        self.selected = today
        self.events: list[CalendarEvent] = []
        self._range: tuple[date, date] | None = None
        self.selected_event: CalendarEvent | None = None
        self._undo_draft: EventDraft | None = None
        self._searching = False

        self._build_toolbar()
        self._build_body()
        self._build_snackbar()
        self._build_shortcuts()

        self.card = EventCard(config.settings.stages_sorted)
        self.card.edit_requested.connect(self.edit_event)
        self.card.delete_requested.connect(self.delete_event)
        self.quick = QuickAdd()
        self._quick_target: tuple[date, int | None, int | None] | None = None
        self.quick.submitted.connect(self._quick_submit)
        self.quick.more.connect(self._quick_more)

        calendar.range_loaded.connect(self._on_range_loaded)
        calendar.holidays_loaded.connect(self.render)
        calendar.search_results.connect(self._on_search_results)
        calendar.deleted.connect(self._on_deleted)
        calendar.operation_succeeded.connect(self._on_succeeded)
        calendar.operation_failed.connect(self._on_failed)
        calendar.auth_state_changed.connect(self._on_auth)
        calendar.signing_in_changed.connect(self._on_signing_in)
        calendar.busy_changed.connect(lambda busy: self.busy.setVisible(busy))
        config.changed.connect(self._on_config)
        self._on_auth(calendar.auth_state, "")
        self.refresh()

    # ================= 版面 =================
    def _build_toolbar(self) -> None:
        self.today_btn = QPushButton("今天")
        self.today_btn.clicked.connect(self.go_today)
        self.prev_btn = QPushButton("‹")
        self.prev_btn.setObjectName("nav")
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn = QPushButton("›")
        self.next_btn.setObjectName("nav")
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.range_title = QLabel()
        self.range_title.setObjectName("rangeTitle")
        self.busy = QLabel("⏳ 同步中…")
        self.busy.setStyleSheet("color: #8A7A80;")
        self.busy.setVisible(False)

        self.view_group = QButtonGroup(self)
        seg = QWidget()
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(0, 0, 0, 0)
        seg_lay.setSpacing(0)
        self.view_buttons = {}
        for i, (key, label) in enumerate((("month", "月"), ("week", "週"), ("day", "日"))):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            if i == 0:
                b.setStyleSheet("border-top-left-radius: 8px; border-bottom-left-radius: 8px;")
            if i == 2:
                b.setStyleSheet("border-top-right-radius: 8px; border-bottom-right-radius: 8px;")
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            self.view_group.addButton(b)
            self.view_buttons[key] = b
            seg_lay.addWidget(b)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 搜尋活動（Enter）")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.returnPressed.connect(self.run_search)
        self.add_btn = QPushButton("＋ 新增")
        self.add_btn.clicked.connect(lambda: self.new_event())
        self.sync_btn = QPushButton("🔄")
        self.sync_btn.setToolTip("立即同步")
        self.sync_btn.clicked.connect(self._cal.sync)
        self.options = QToolButton()
        self.options.setText("⚙")
        self.options.setPopupMode(QToolButton.InstantPopup)
        self.options.setMenu(self._build_options_menu())

        self.auth_label = QLabel()
        self.auth_label.setStyleSheet("color: #7A6A70;")
        self.login_btn = QPushButton("登入 Google")
        self.login_btn.clicked.connect(self._login_clicked)
        self.logout_btn = QPushButton("登出")
        self.logout_btn.clicked.connect(self._confirm_sign_out)

        bar = QHBoxLayout()
        for w in (self.today_btn, self.prev_btn, self.next_btn):
            bar.addWidget(w)
        bar.addSpacing(8)
        bar.addWidget(self.range_title)
        bar.addSpacing(8)
        bar.addWidget(self.busy)
        bar.addStretch(1)
        bar.addWidget(seg)
        bar.addSpacing(8)
        bar.addWidget(self.search)
        bar.addWidget(self.add_btn)
        bar.addWidget(self.sync_btn)
        bar.addWidget(self.options)
        auth = QHBoxLayout()
        auth.addWidget(self.auth_label, 1)
        auth.addWidget(self.login_btn)
        auth.addWidget(self.logout_btn)
        self._toolbar = QVBoxLayout()
        self._toolbar.addLayout(bar)
        self._toolbar.addLayout(auth)

    def _build_options_menu(self) -> QMenu:
        menu = QMenu(self)
        start_menu = menu.addMenu("一週的第一天")
        group = QActionGroup(menu)
        self.week_actions = {}
        for key, label in (("sun", "星期日"), ("mon", "星期一")):
            a = QAction(label, menu, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self._config.update(week_start=k))
            group.addAction(a)
            start_menu.addAction(a)
            self.week_actions[key] = a
        self.lunar_action = QAction("顯示農曆", menu, checkable=True)
        self.lunar_action.triggered.connect(lambda v: self._config.update(show_lunar=v))
        self.holiday_action = QAction("顯示國定假日", menu, checkable=True)
        self.holiday_action.triggered.connect(lambda v: self._config.update(show_holidays=v))
        menu.addAction(self.lunar_action)
        menu.addAction(self.holiday_action)
        menu.addSeparator()
        menu.addAction("快捷鍵說明", self._show_shortcuts)
        menu.aboutToShow.connect(self._sync_options)
        return menu

    def _sync_options(self) -> None:
        s = self._config.settings
        self.week_actions[s.week_start if s.week_start in self.week_actions else "sun"].setChecked(True)
        self.lunar_action.setChecked(s.show_lunar)
        self.lunar_action.setEnabled(lunar.available())
        self.holiday_action.setChecked(s.show_holidays)

    def _build_body(self) -> None:
        self.month = MonthView()
        self.month.date_selected.connect(self.select_date)
        self.month.date_activated.connect(self._quick_all_day)
        self.month.event_clicked.connect(self.show_card)
        self.month.event_moved.connect(self._on_moved_days)
        self.month.wheel_step.connect(self.step)
        self.grid = TimeGridView()
        self._connect_grid(self.grid)
        self.grid.date_clicked.connect(self._open_day)
        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.month)
        self.main_stack.addWidget(self.grid)

        self.day_panel = DayPanel()
        self._connect_grid(self.day_panel.grid)
        self.day_panel.add_btn.clicked.connect(lambda: self.new_event(self.selected))
        self.results = SearchResults()
        self.results.event_chosen.connect(self._on_search_chosen)
        self.results.closed.connect(self.close_search)
        self.side_stack = QStackedWidget()
        self.side_stack.addWidget(self.day_panel)
        self.side_stack.addWidget(self.results)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.main_stack)
        self.splitter.addWidget(self.side_stack)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([780, 320])
        self.splitter.setChildrenCollapsible(False)

    def _connect_grid(self, grid: TimeGridView) -> None:
        grid.event_clicked.connect(self.show_card)
        grid.event_retimed.connect(self._on_retimed)
        grid.range_selected.connect(self._quick_timed)

    def _build_snackbar(self) -> None:
        self.snack = QFrame()
        self.snack.setObjectName("snack")
        self.snack_label = QLabel()
        self.snack_undo = QPushButton("復原")
        self.snack_undo.clicked.connect(self._undo)
        lay = QHBoxLayout(self.snack)
        lay.setContentsMargins(14, 6, 10, 6)
        lay.addWidget(self.snack_label, 1)
        lay.addWidget(self.snack_undo)
        self.snack.setVisible(False)
        self.snack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._snack_timer = QTimer(self)
        self._snack_timer.setSingleShot(True)
        self._snack_timer.timeout.connect(self._hide_snack)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self._toolbar)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.snack)

    def _build_shortcuts(self) -> None:
        keys = {
            "T": self.go_today,
            "Left": lambda: self.step(-1),
            "Right": lambda: self.step(1),
            "M": lambda: self.set_view("month"),
            "W": lambda: self.set_view("week"),
            "D": lambda: self.set_view("day"),
            "N": lambda: self.new_event(),
            "/": lambda: (self.search.setFocus(), self.search.selectAll()),
            "Delete": lambda: self.selected_event and self.delete_event(self.selected_event),
        }
        for key, fn in keys.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    def _show_shortcuts(self) -> None:
        QMessageBox.information(self, "快捷鍵", "T　回到今天\n← / →　上一段 / 下一段\nM / W / D　月 / 週 / 日檢視\n"
                                "N　新增活動\n/　搜尋\nDelete　刪除選取的活動\n\n"
                                "月檢視：雙擊格子快速新增、拖曳活動改日期、滾輪切換月份\n"
                                "時間軸：拖曳空白處選時段新增、拖曳活動改時間、拖曳下緣改長度")

    # ================= 顯示 =================
    def _holidays_on(self, d: date) -> list[CalendarEvent]:
        return self._cal.holidays_on(d) if self._config.settings.show_holidays else []

    def refresh(self) -> None:
        """依目前檢視與日期重新讀取資料並重畫。"""
        s = self._config.settings
        self._range = L.view_range(self.view, self.anchor, s.week_start)
        cached = self._cal.cached_range(*self._range)
        if cached is not None:
            self.events = cached
        else:
            # 還沒讀到：先用已知的活動（未來 30 天）填，避免畫面整個空白
            start, end = self._range
            self.events = [e for e in self._cal.events if L.event_days(e)[1] >= start and L.event_days(e)[0] < end]
        self.render()
        self._cal.fetch_range(*self._range)

    def render(self) -> None:
        s = self._config.settings
        show_lunar = s.show_lunar and lunar.available()
        for key, b in self.view_buttons.items():
            b.setChecked(key == self.view)
        sel_id = self.selected_event.id if self.selected_event else ""
        if self.view == "month":
            days = L.month_grid(self.anchor.year, self.anchor.month, s.week_start)
            self.month.holidays_on = self._holidays_on
            self.month.selected_event_id = sel_id
            self.month.set_month(self.anchor.year, self.anchor.month, s.week_start, show_lunar)
            self.month.set_selected(self.selected)
            self.month.set_events(self.events)
            self.main_stack.setCurrentWidget(self.month)
        else:
            days = L.week_dates(self.anchor, s.week_start) if self.view == "week" else [self.anchor]
            self.grid.set_data(days, self.events, self._holidays_on, show_lunar, sel_id)
            self.main_stack.setCurrentWidget(self.grid)
        self.range_title.setText(fmt.range_title(self.view, self.anchor, days))
        self.day_panel.show_day(self.selected, self.events, self._holidays_on, show_lunar, sel_id)
        self.side_stack.setVisible(self.view == "month" or self._searching)
        self.side_stack.setCurrentWidget(self.results if self._searching else self.day_panel)

    def _on_range_loaded(self, start: date, end: date, events: list) -> None:
        if (start, end) == self._range:
            self.events = events
            if self.selected_event:
                self.selected_event = next((e for e in events if e.id == self.selected_event.id), None)
            self.render()

    def _on_config(self, keys: set) -> None:
        if keys & {"week_start", "show_lunar", "show_holidays", "reminder_stages"}:
            self.card._default_stages = self._config.settings.stages_sorted
            self.refresh()

    # ================= 導覽 =================
    def set_view(self, view: str) -> None:
        if view == self.view:
            return
        self.view = view
        self.anchor = self.selected
        self._config.update(calendar_view=view)
        self.refresh()

    def step(self, direction: int) -> None:
        self.anchor = L.shift_anchor(self.view, self.anchor, direction)
        if self.view == "month":
            today = date.today()
            in_month = (today.year, today.month) == (self.anchor.year, self.anchor.month)
            self.selected = today if in_month else self.anchor
        else:
            self.selected = self.anchor
        self.refresh()

    def go_today(self) -> None:
        self.anchor = self.selected = date.today()
        self.refresh()

    def select_date(self, d: date) -> None:
        self.selected = d
        self.selected_event = None
        if self.view == "month" and (d.year, d.month) != (self.anchor.year, self.anchor.month):
            self.anchor = d.replace(day=1)  # 點到前後月份的補位格：直接切過去
            self.refresh()
        else:
            self.render()

    def _open_day(self, d: date) -> None:
        """週檢視點日期標題 → 切到那天的日檢視。"""
        self.selected = self.anchor = d
        if self.view == "week":
            self.set_view("day")
        else:
            self.refresh()

    # ================= 活動卡片 =================
    def show_card(self, ev: CalendarEvent, pos: QPoint) -> None:
        self.selected_event = None if ev.read_only else ev
        self.render()
        self.card.show_for(ev, pos)
        if ev.is_recurring and self._cal.can_fetch:
            def fill(item):
                rule = RecurrenceRule.from_recurrence(item.get("recurrence"))
                if rule and self.card.isVisible() and self.card.event is ev:
                    self.card.show_for(ev, self.card.pos() + QPoint(0, 20), rule.describe(ev.start.date()))
            self._cal.fetch_master(ev.recurring_event_id, fill)

    # ================= 新增 =================
    def _require_signed_in(self) -> bool:
        if self._cal.auth_state in (AuthState.SIGNED_IN, AuthState.ERROR):
            return True
        QMessageBox.information(self, "尚未登入", "請先按「登入 Google」連結你的 Google 日曆。")
        return False

    def new_event(self, d: date | None = None, draft: EventDraft | None = None) -> None:
        if not self._require_signed_in():
            return
        if draft is None:
            d = d or self.selected
            now = local_now()
            if d == now.date():
                start = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            else:
                start = datetime.combine(d, time(9), now.tzinfo)
            draft = EventDraft("", start, start + timedelta(hours=1))
        dlg = EventDialog(self, draft=draft, events=self.events, default_stages=self._config.settings.stages_sorted)
        if dlg.exec():
            self._cal.create(dlg.draft())

    def _quick_all_day(self, d: date, pos: QPoint) -> None:
        if not self._require_signed_in():
            return
        self.select_date(d)
        self._quick_target = (d, None, None)
        self.quick.open_at(pos, f"{fmt.day_text(d)}・全天")

    def _quick_timed(self, d: date, start_min: int, end_min: int, pos: QPoint) -> None:
        if not self._require_signed_in():
            return
        self.selected = d
        self._quick_target = (d, start_min, end_min)
        self.quick.open_at(pos, f"{fmt.day_text(d)}・{start_min // 60:02d}:{start_min % 60:02d} – "
                                f"{end_min // 60:02d}:{end_min % 60:02d}")

    def _quick_draft(self, title: str) -> EventDraft | None:
        if not self._quick_target:
            return None
        d, s, e = self._quick_target
        tz = local_now().tzinfo
        if s is None:
            start = datetime.combine(d, time(), tz)
            return EventDraft(title, start, start, all_day=True)
        base = datetime.combine(d, time(), tz)
        return EventDraft(title, base + timedelta(minutes=s), base + timedelta(minutes=e))

    def _quick_submit(self, title: str) -> None:
        draft = self._quick_draft(title)
        if draft:
            self._cal.create(draft)

    def _quick_more(self, title: str) -> None:
        draft = self._quick_draft(title)
        if draft:
            self.new_event(draft=draft)

    # ================= 編輯 / 刪除 / 移動 =================
    def edit_event(self, ev: CalendarEvent) -> None:
        if ev.read_only or not self._require_signed_in():
            return
        scope = INSTANCE
        if ev.is_recurring:
            scope = ask_scope(self, "修改")
            if scope is None:
                return
        if scope == SERIES:
            self._cal.fetch_master(ev.recurring_event_id,
                                   lambda item: self._open_edit(ev, SERIES, item.get("recurrence", [])))
        else:
            self._open_edit(ev, INSTANCE, None)

    def _open_edit(self, ev: CalendarEvent, scope: str, recurrence) -> None:
        dlg = EventDialog(self, event=ev, allow_recurrence=scope == SERIES or not ev.is_recurring,
                          recurrence=recurrence, events=self.events,
                          default_stages=self._config.settings.stages_sorted)
        if dlg.exec():
            self._cal.update(ev, dlg.draft(), scope)

    def delete_event(self, ev: CalendarEvent) -> None:
        if ev.read_only or not self._require_signed_in():
            return
        scope = INSTANCE
        if ev.is_recurring:
            scope = ask_scope(self, "刪除")
            if scope is None:
                return
        # 先從畫面拿掉（樂觀更新），失敗時會重新讀取
        if scope == SERIES:
            self.events = [e for e in self.events if e.recurring_event_id != ev.recurring_event_id]
        else:
            self.events = [e for e in self.events if e.id != ev.id]
        self.selected_event = None
        self.render()
        self._cal.delete(ev, scope)

    def _on_moved_days(self, ev: CalendarEvent, days: int) -> None:
        start, end = L.moved_by_days(ev, days)
        self._move(ev, start, end)

    def _on_retimed(self, ev: CalendarEvent, start: datetime, end: datetime) -> None:
        self._move(ev, start, end)

    def _move(self, ev: CalendarEvent, start: datetime, end: datetime) -> None:
        if ev.read_only or not self._require_signed_in():
            self.render()
            return
        scope = INSTANCE
        if ev.is_recurring:
            scope = ask_scope(self, "移動")
            if scope is None:
                self.render()
                return
        moved = replace(ev, start=start, end=end)
        self.events = [moved if e.id == ev.id else e for e in self.events]
        self.selected = start.date()
        self.render()
        self._cal.move(ev, start, end, scope)

    # ================= 搜尋 =================
    def run_search(self) -> None:
        q = self.search.text().strip()
        if not q:
            self.close_search()
            return
        if not self._require_signed_in():
            return
        self._searching = True
        self.results.show_results(q, [])
        self.results.header.setText(f"🔍 搜尋「{q}」中…")
        self.render()
        self._cal.search(q)

    def _on_search_results(self, q: str, events: list) -> None:
        if self._searching and q == self.search.text().strip():
            self.results.show_results(q, events)

    def _on_search_chosen(self, ev: CalendarEvent) -> None:
        d = ev.start.date()
        self.selected = d
        self.anchor = d.replace(day=1) if self.view == "month" else d
        self.selected_event = ev
        self.refresh()
        self.card.show_for(ev, self.results.mapToGlobal(QPoint(-350, 40)))

    def close_search(self) -> None:
        self._searching = False
        self.search.clear()
        self.render()

    # ================= 提示列 / 復原 =================
    def _show_snack(self, text: str, undo: EventDraft | None = None, seconds: int = 6) -> None:
        self._undo_draft = undo
        self.snack_label.setText(text)
        self.snack_undo.setVisible(undo is not None)
        self.snack.setVisible(True)
        self._snack_timer.start(seconds * 1000)

    def _hide_snack(self) -> None:
        self.snack.setVisible(False)
        self._undo_draft = None

    def _on_deleted(self, title: str, restore: EventDraft) -> None:
        self._show_snack(f"已刪除「{title}」", undo=restore)

    def _undo(self) -> None:
        draft = self._undo_draft
        self._hide_snack()
        if draft:
            self._cal.restore(draft)

    def _on_succeeded(self, message: str) -> None:
        if message.startswith("已刪除") and self._undo_draft is not None:
            return  # 保留有「復原」按鈕的提示
        self._show_snack("✅ " + message, seconds=3)

    def _on_failed(self, message: str) -> None:
        self._show_snack("❌ " + message, seconds=8)
        if self._range:
            self._cal.fetch_range(*self._range, force=True)  # 樂觀更新失敗：還原成 Google 上的實際資料

    # ================= 登入狀態 =================
    def _login_clicked(self) -> None:
        if self._cal.signing_in:
            self._cal.cancel_sign_in()
            self.login_btn.setEnabled(False)
        else:
            self._cal.sign_in()

    def _confirm_sign_out(self) -> None:
        if QMessageBox.question(self, "登出", "確定要登出 Google 嗎？（會刪除 token.json）") == QMessageBox.Yes:
            self._cal.sign_out()

    def _on_signing_in(self, signing_in: bool) -> None:
        self.login_btn.setEnabled(True)
        if signing_in:
            self.login_btn.setText("取消登入")
            self.login_btn.setVisible(True)
            self.logout_btn.setVisible(False)
            self.auth_label.setText("🌐 請在瀏覽器完成 Google 授權（不小心關掉分頁的話，按「取消登入」再重新登入）")
        else:
            self.login_btn.setText("登入 Google")

    def _on_auth(self, state: AuthState, message: str) -> None:
        text = {
            AuthState.NO_CREDENTIALS: "⚠️ 找不到 credentials.json，請參考 README 設定 Google OAuth。",
            AuthState.SIGNED_OUT: "🔒 尚未登入 Google",
            AuthState.SIGNED_IN: "🟢 已連線 Google 日曆（主日曆）",
            AuthState.ERROR: f"🟠 同步失敗，暫用離線資料：{message}",
        }[state]
        if self._cal.signing_in:
            return
        self.auth_label.setText(text)
        signed_in = state in (AuthState.SIGNED_IN, AuthState.ERROR)
        self.login_btn.setVisible(not signed_in)
        self.logout_btn.setVisible(signed_in)
        for b in (self.add_btn, self.day_panel.add_btn):
            b.setEnabled(signed_in)
