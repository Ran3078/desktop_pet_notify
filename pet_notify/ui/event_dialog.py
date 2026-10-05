"""新增 / 編輯活動對話框：標題、時間、重複、顏色、提醒、地點、備註，並即時提示時間衝突。"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from ..cal.colors import DEFAULT_COLOR, EVENT_COLORS
from ..cal.models import CalendarEvent, EventDraft, local_now
from ..cal.recurrence import UNIT, WEEKDAY_CODES, WEEKDAY_NAMES, RecurrenceRule, preset
from .calendar import fmt
from .calendar.layout import overlaps

PRESETS = ["none", "daily", "weekly", "monthly", "yearly", "custom"]
REMINDER_UNITS = [("分鐘", 1), ("小時", 60), ("天", 1440)]


def _to_qdt(dt: datetime) -> QDateTime:
    return QDateTime.fromSecsSinceEpoch(int(dt.timestamp()))


def _from_qdt(qdt: QDateTime) -> datetime:
    return datetime.fromtimestamp(qdt.toSecsSinceEpoch()).astimezone()


def _row(*widgets, stretch=True) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


class EventDialog(QDialog):
    """
    event：要編輯的活動（None 表示新增）
    draft：新增時預先帶入的內容（快速新增的「更多選項」）
    allow_recurrence：可不可以設定重複（只改重複活動的「這一次」時不行）
    recurrence：編輯整個系列時，主活動目前的 recurrence
    events：用來檢查時間衝突的活動
    """

    def __init__(self, parent=None, event: CalendarEvent | None = None, draft: EventDraft | None = None,
                 allow_recurrence: bool = True, recurrence: list[str] | None = None,
                 events: list[CalendarEvent] | None = None, default_stages: list[int] | None = None):
        super().__init__(parent)
        self.setWindowTitle("編輯活動" if event else "新增活動")
        self.setMinimumWidth(460)
        self._event = event
        self._events = events or []
        self._allow_recurrence = allow_recurrence
        self._editing_series = event is not None and event.is_recurring and allow_recurrence
        self._original_recurrence = recurrence

        self.title = QLineEdit()
        self.title.setPlaceholderText("要做什麼事？")
        self.all_day = QCheckBox("全天活動")
        self.start = QDateTimeEdit()
        self.end = QDateTimeEdit()
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
        self.conflict = QLabel()
        self.conflict.setWordWrap(True)
        self.conflict.setStyleSheet("color: #B26A00;")
        self.location = QLineEdit()
        self.location.setPlaceholderText("地點或會議連結（選填）")
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("備註（選填）")
        self.description.setFixedHeight(70)

        form = QFormLayout(self)
        form.addRow("標題", self.title)
        form.addRow("", self.all_day)
        form.addRow("開始", self.start)
        form.addRow("結束", self.end)
        form.addRow("", self.conflict)
        self._build_recurrence(form)
        self._build_colors(form)
        self._build_reminders(form, default_stages or [10, 1, 0])
        form.addRow("地點", self.location)
        form.addRow("備註", self.description)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("儲存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        source = EventDraft.from_event(event) if event else draft
        if source is None:
            start = (local_now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            source = EventDraft("", start, start + timedelta(hours=1))
        self._load(source)

        self._last_start = self.start.dateTime()
        self.start.dateTimeChanged.connect(self._shift_end)
        self.end.dateTimeChanged.connect(lambda _: self._check_conflict())
        self.all_day.toggled.connect(self._apply_format)
        self._apply_format()
        self._update_recurrence_labels()
        self._check_conflict()
        self.title.setFocus()

    # ---- 重複 ----
    def _build_recurrence(self, form: QFormLayout) -> None:
        self.repeat = QComboBox()
        for key in PRESETS:
            self.repeat.addItem("", key)
        self.repeat.currentIndexChanged.connect(self._on_repeat_changed)

        self.custom = QWidget()
        c = QVBoxLayout(self.custom)
        c.setContentsMargins(0, 0, 0, 0)
        self.interval = QSpinBox()
        self.interval.setRange(1, 99)
        self.freq = QComboBox()
        for code in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            self.freq.addItem(UNIT[code], code)
        self.freq.currentIndexChanged.connect(self._on_freq_changed)
        c.addWidget(_row(QLabel("每"), self.interval, self.freq))
        self.weekday_boxes: dict[str, QCheckBox] = {}
        days = QWidget()
        d = QHBoxLayout(days)
        d.setContentsMargins(0, 0, 0, 0)
        for code in WEEKDAY_CODES:
            box = QCheckBox(WEEKDAY_NAMES[code])
            self.weekday_boxes[code] = box
            d.addWidget(box)
        d.addStretch(1)
        self.weekday_row = days
        c.addWidget(days)
        self.end_never = QRadioButton("永不結束")
        self.end_until = QRadioButton("結束於")
        self.end_count = QRadioButton("共")
        group = QButtonGroup(self)
        for b in (self.end_never, self.end_until, self.end_count):
            group.addButton(b)
        self.until_date = QDateEdit()
        self.until_date.setCalendarPopup(True)
        self.until_date.setDisplayFormat("yyyy/MM/dd")
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setValue(10)
        self.end_never.setChecked(True)
        c.addWidget(_row(self.end_never, self.end_until, self.until_date, self.end_count, self.count, QLabel("次")))
        self.custom.setVisible(False)

        if self._allow_recurrence:
            form.addRow("重複", self.repeat)
            form.addRow("", self.custom)
        else:
            hint = QLabel("只修改這一次，不能變更重複規則")
            hint.setStyleSheet("color: #8A7A80;")
            form.addRow("重複", hint)

    def _update_recurrence_labels(self) -> None:
        d = _from_qdt(self.start.dateTime()).date()
        labels = {
            "none": "不重複",
            "daily": "每天",
            "weekly": f"每週{fmt.WEEKDAYS[d.weekday()]}",
            "monthly": f"每月 {d.day} 日",
            "yearly": f"每年 {d.month} 月 {d.day} 日",
            "custom": "自訂…",
        }
        for i, key in enumerate(PRESETS):
            self.repeat.setItemText(i, labels[key])

    def _on_repeat_changed(self) -> None:
        custom = self.repeat.currentData() == "custom"
        self.custom.setVisible(custom)
        if custom and not any(b.isChecked() for b in self.weekday_boxes.values()):
            d = _from_qdt(self.start.dateTime()).date()
            self.weekday_boxes[WEEKDAY_CODES[d.weekday()]].setChecked(True)
        self._on_freq_changed()
        self.adjustSize()

    def _on_freq_changed(self) -> None:
        self.weekday_row.setVisible(self.freq.currentData() == "WEEKLY")

    def _load_rule(self, rule: RecurrenceRule | None) -> None:
        start = _from_qdt(self.start.dateTime()).date()
        self.until_date.setDate(QDate(start.year, start.month, start.day).addMonths(3))
        if rule is None:
            self.repeat.setCurrentIndex(PRESETS.index("none"))
            return
        for key in ("daily", "weekly", "monthly", "yearly"):
            if rule == preset(key, start):
                self.repeat.setCurrentIndex(PRESETS.index(key))
                return
        self.repeat.setCurrentIndex(PRESETS.index("custom"))
        self.interval.setValue(rule.interval)
        self.freq.setCurrentIndex(max(0, self.freq.findData(rule.freq)))
        for code, box in self.weekday_boxes.items():
            box.setChecked(code in rule.byday)
        if rule.count:
            self.end_count.setChecked(True)
            self.count.setValue(rule.count)
        elif rule.until:
            self.end_until.setChecked(True)
            self.until_date.setDate(QDate(rule.until.year, rule.until.month, rule.until.day))
        self._extra = rule.extra

    def rule(self) -> RecurrenceRule | None:
        key = self.repeat.currentData()
        start = _from_qdt(self.start.dateTime()).date()
        if key != "custom":
            return preset(key, start)
        freq = self.freq.currentData()
        byday = tuple(c for c, b in self.weekday_boxes.items() if b.isChecked()) if freq == "WEEKLY" else ()
        until = self.until_date.date().toPython() if self.end_until.isChecked() else None
        count = self.count.value() if self.end_count.isChecked() else None
        extra = getattr(self, "_extra", ()) if freq == "MONTHLY" else ()
        return RecurrenceRule(freq, self.interval.value(), byday, until, count, extra)

    # ---- 顏色 ----
    def _build_colors(self, form: QFormLayout) -> None:
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        for cid, (name, hex_) in [("", ("預設", DEFAULT_COLOR))] + list(EVENT_COLORS.items()):
            b = QToolButton()
            b.setCheckable(True)
            b.setToolTip(name)
            b.setFixedSize(22, 22)
            b.setProperty("color_id", cid)
            b.setStyleSheet(
                f"QToolButton {{ background: {hex_}; border-radius: 11px; border: 2px solid white; }}"
                f"QToolButton:checked {{ border: 3px solid #4A3B3F; }}")
            self.color_group.addButton(b)
            lay.addWidget(b)
        lay.addStretch(1)
        form.addRow("顏色", row)

    def color_id(self) -> str:
        b = self.color_group.checkedButton()
        return b.property("color_id") if b else ""

    # ---- 提醒 ----
    def _build_reminders(self, form: QFormLayout, default_stages: list[int]) -> None:
        self.reminder_mode = QComboBox()
        default_text = "、".join(fmt.minutes_text(m) for m in sorted(default_stages, reverse=True))
        self.reminder_mode.addItem(f"使用預設（{default_text}）", "default")
        self.reminder_mode.addItem("自訂提醒時間", "custom")
        self.reminder_mode.addItem("不提醒", "none")
        self.reminder_mode.currentIndexChanged.connect(self._on_reminder_mode)
        self.reminder_list = QListWidget()
        self.reminder_list.setMaximumHeight(70)
        self.reminder_amount = QSpinBox()
        self.reminder_amount.setRange(0, 999)
        self.reminder_amount.setValue(30)
        self.reminder_unit = QComboBox()
        for label, factor in REMINDER_UNITS:
            self.reminder_unit.addItem(label, factor)
        add = QPushButton("＋ 加入")
        add.clicked.connect(self._add_reminder)
        remove = QPushButton("移除")
        remove.clicked.connect(lambda: [self.reminder_list.takeItem(self.reminder_list.row(i))
                                        for i in self.reminder_list.selectedItems()])
        self.reminder_custom = QWidget()
        c = QVBoxLayout(self.reminder_custom)
        c.setContentsMargins(0, 0, 0, 0)
        c.addWidget(self.reminder_list)
        c.addWidget(_row(self.reminder_amount, self.reminder_unit, QLabel("前"), add, remove))
        self.reminder_custom.setVisible(False)
        form.addRow("提醒", self.reminder_mode)
        form.addRow("", self.reminder_custom)

    def _on_reminder_mode(self) -> None:
        self.reminder_custom.setVisible(self.reminder_mode.currentData() == "custom")
        self.adjustSize()

    def _set_reminders(self, minutes) -> None:
        self.reminder_list.clear()
        for m in sorted(set(minutes), reverse=True):
            item = QListWidgetItem(fmt.minutes_text(m))
            item.setData(Qt.UserRole, m)
            self.reminder_list.addItem(item)

    def _add_reminder(self) -> None:
        m = self.reminder_amount.value() * self.reminder_unit.currentData()
        current = [self.reminder_list.item(i).data(Qt.UserRole) for i in range(self.reminder_list.count())]
        if m in current:
            return
        if len(current) >= 5:
            QMessageBox.information(self, "提醒太多", "每個活動最多 5 個提醒。")
            return
        self._set_reminders(current + [m])

    def reminder_minutes(self) -> tuple[int, ...] | None:
        mode = self.reminder_mode.currentData()
        if mode == "default":
            return None
        if mode == "none":
            return ()
        return tuple(self.reminder_list.item(i).data(Qt.UserRole) for i in range(self.reminder_list.count()))

    # ---- 載入 / 欄位行為 ----
    def _load(self, d: EventDraft) -> None:
        self.title.setText(d.title)
        self.all_day.setChecked(d.all_day)
        self.start.setDateTime(_to_qdt(d.start))
        self.end.setDateTime(_to_qdt(max(d.end, d.start)))
        self.location.setText(d.location)
        self.description.setPlainText(d.description)
        for b in self.color_group.buttons():
            b.setChecked(b.property("color_id") == d.color_id)
        if d.reminder_minutes is None:
            self.reminder_mode.setCurrentIndex(0)
        elif not d.reminder_minutes:
            self.reminder_mode.setCurrentIndex(2)
        else:
            self.reminder_mode.setCurrentIndex(1)
            self._set_reminders(d.reminder_minutes)
        rule = RecurrenceRule.from_recurrence(self._original_recurrence if self._editing_series else d.recurrence)
        self._load_rule(rule)

    def _apply_format(self) -> None:
        fmt_ = "yyyy/MM/dd" if self.all_day.isChecked() else "yyyy/MM/dd HH:mm"
        self.start.setDisplayFormat(fmt_)
        self.end.setDisplayFormat(fmt_)
        self.reminder_mode.setEnabled(not self.all_day.isChecked())
        self._check_conflict()

    def _shift_end(self, new_start: QDateTime) -> None:
        """移動開始時間時，結束時間跟著平移，保持原本的長度。"""
        delta = self._last_start.secsTo(new_start)
        self.end.setDateTime(self.end.dateTime().addSecs(delta))
        self._last_start = new_start
        self._update_recurrence_labels()
        self._check_conflict()

    def _check_conflict(self) -> None:
        if self.all_day.isChecked():
            self.conflict.setVisible(False)
            return
        start, end = _from_qdt(self.start.dateTime()), _from_qdt(self.end.dateTime())
        hits = overlaps(self._events, start, end, exclude_id=self._event.id if self._event else "")
        if not hits:
            self.conflict.setVisible(False)
            return
        names = "、".join(f"「{e.title}」{e.start:%H:%M}–{e.end:%H:%M}" for e in hits[:3])
        more = f" 等 {len(hits)} 個活動" if len(hits) > 3 else ""
        self.conflict.setText(f"⚠️ 與{names}{more}時間重疊")
        self.conflict.setVisible(True)

    def _accept(self) -> None:
        if not self.title.text().strip():
            QMessageBox.warning(self, "缺少標題", "請輸入活動標題。")
            return
        start, end = _from_qdt(self.start.dateTime()), _from_qdt(self.end.dateTime())
        if self.all_day.isChecked():
            if end.date() < start.date():
                QMessageBox.warning(self, "時間錯誤", "結束日期不能早於開始日期。")
                return
        elif end <= start:
            QMessageBox.warning(self, "時間錯誤", "結束時間必須晚於開始時間。")
            return
        rule = self.rule() if self._allow_recurrence else None
        if rule and rule.freq == "WEEKLY" and self.repeat.currentData() == "custom" and not rule.byday:
            QMessageBox.warning(self, "重複設定", "每週重複請至少勾選一天。")
            return
        self.accept()

    def draft(self) -> EventDraft:
        recurrence = None
        if self._allow_recurrence:
            rule = self.rule()
            if rule:
                recurrence = [rule.to_rrule(all_day=self.all_day.isChecked())]
            elif self._editing_series or (self._event and not self._event.is_recurring):
                recurrence = []  # 取消重複
        return EventDraft(
            title=self.title.text().strip(),
            start=_from_qdt(self.start.dateTime()),
            end=_from_qdt(self.end.dateTime()),
            all_day=self.all_day.isChecked(),
            location=self.location.text().strip(),
            description=self.description.toPlainText().strip(),
            color_id=self.color_id(),
            recurrence=recurrence,
            reminder_minutes=self.reminder_minutes(),
        )
