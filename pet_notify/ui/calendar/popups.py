"""行事曆的小視窗：活動卡片、快速新增、重複活動範圍詢問。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ...cal.colors import color_hex
from ...cal.gcal import INSTANCE, SERIES
from ...cal.models import CalendarEvent
from . import fmt

POPUP_STYLE = """
QFrame#popup { background: #FFFFFF; border: 1px solid #F0C9D5; border-radius: 12px; }
QLabel { color: #4A3B3F; background: transparent; }
QLabel#title { font-size: 12pt; font-weight: bold; }
QLabel#meta { color: #7A6A70; font-size: 9pt; }
QPushButton { background: #FFE4EC; color: #7A3550; border: 1px solid #F3B2C6; border-radius: 8px; padding: 4px 10px; }
QPushButton:hover { background: #FFD3E0; }
QPushButton#flat { background: transparent; border: none; color: #A0506B; }
QLineEdit { border: none; border-bottom: 2px solid #E8789A; font-size: 11pt; padding: 4px 2px; background: #FFFFFF; }
"""


def _place(widget: QWidget, anchor: QPoint) -> None:
    """把小視窗放在 anchor 旁邊，並保持在螢幕內。"""
    widget.adjustSize()
    screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    x = anchor.x() + 8
    if x + widget.width() > avail.right():
        x = anchor.x() - widget.width() - 8
    y = min(max(avail.top(), anchor.y() - 20), avail.bottom() - widget.height())
    widget.move(max(avail.left(), x), y)


class _Popup(QFrame):
    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(POPUP_STYLE)
        self.body = QFrame(self)
        self.body.setObjectName("popup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.body)


class EventCard(_Popup):
    edit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, default_stages):
        super().__init__()
        self._default_stages = default_stages
        self.event: CalendarEvent | None = None
        self.setFixedWidth(340)

    def show_for(self, ev: CalendarEvent, anchor: QPoint, recurrence_text: str = "") -> None:
        self.event = ev
        old = self.body.layout()
        if old is not None:
            QWidget().setLayout(old)  # 丟掉舊內容
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        head = QHBoxLayout()
        swatch = QLabel()
        swatch.setFixedSize(14, 14)
        swatch.setStyleSheet(f"background: {color_hex(ev.color_id, holiday=ev.read_only)}; border-radius: 4px;")
        title = QLabel(ev.title)
        title.setObjectName("title")
        title.setWordWrap(True)
        close = QPushButton("✕")
        close.setObjectName("flat")
        close.setFixedWidth(28)
        close.clicked.connect(self.close)
        head.addWidget(swatch, 0, Qt.AlignTop)
        head.addWidget(title, 1)
        head.addWidget(close, 0, Qt.AlignTop)
        lay.addLayout(head)

        def meta(text: str) -> None:
            label = QLabel(text)
            label.setObjectName("meta")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(label)

        meta(fmt.when_text(ev))
        if ev.read_only:
            meta("🇹🇼 國定假日（唯讀）")
        else:
            if ev.is_recurring:
                meta("🔁 " + (recurrence_text or "重複活動"))
            if not ev.all_day:
                meta("🔔 " + fmt.reminders_text(ev, self._default_stages))
        if ev.location and not ev.meeting_url:
            meta("📍 " + ev.location)
        if ev.description:
            desc = ev.description if len(ev.description) < 300 else ev.description[:300] + "…"
            meta("📝 " + desc)

        buttons = QHBoxLayout()
        if ev.meeting_url:
            join = QPushButton("🎥 加入會議")
            join.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(ev.meeting_url)), self.close()))
            buttons.addWidget(join)
        if ev.html_link:
            web = QPushButton("在 Google 開啟")
            web.setObjectName("flat")
            web.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(ev.html_link)), self.close()))
            buttons.addWidget(web)
        buttons.addStretch(1)
        if not ev.read_only:
            edit = QPushButton("✏️ 編輯")
            edit.clicked.connect(lambda: (self.close(), self.edit_requested.emit(ev)))
            delete = QPushButton("🗑 刪除")
            delete.clicked.connect(lambda: (self.close(), self.delete_requested.emit(ev)))
            buttons.addWidget(edit)
            buttons.addWidget(delete)
        lay.addLayout(buttons)
        _place(self, anchor)
        self.show()


class QuickAdd(_Popup):
    submitted = Signal(str)
    more = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(300)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        self.when = QLabel()
        self.when.setObjectName("meta")
        self.title = QLineEdit()
        self.title.setPlaceholderText("新增標題")
        self.title.returnPressed.connect(self._submit)
        more = QPushButton("更多選項")
        more.setObjectName("flat")
        more.clicked.connect(lambda: (self.close(), self.more.emit(self.title.text().strip())))
        save = QPushButton("儲存")
        save.clicked.connect(self._submit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(more)
        row.addWidget(save)
        lay.addWidget(self.title)
        lay.addWidget(self.when)
        lay.addLayout(row)

    def open_at(self, anchor: QPoint, when_text: str) -> None:
        self.when.setText("🕒 " + when_text)
        self.title.clear()
        _place(self, anchor)
        self.show()
        self.title.setFocus()

    def _submit(self) -> None:
        text = self.title.text().strip()
        if text:
            self.close()
            self.submitted.emit(text)


def ask_scope(parent, verb: str) -> str | None:
    """重複活動要改 / 刪哪個範圍？回傳 INSTANCE、SERIES 或 None（取消）。"""
    box = QMessageBox(parent)
    box.setWindowTitle(f"{verb}重複活動")
    box.setText(f"要{verb}哪些活動？")
    only = box.addButton("只有這一次", QMessageBox.AcceptRole)
    series = box.addButton("整個系列", QMessageBox.AcceptRole)
    box.addButton("取消", QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is only:
        return INSTANCE
    if clicked is series:
        return SERIES
    return None


class SearchResults(QWidget):
    event_chosen = Signal(object)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget

        self.header = QLabel()
        self.header.setStyleSheet("font-weight: bold; color: #A0506B;")
        close = QPushButton("✕ 關閉搜尋")
        close.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        close.clicked.connect(self.closed)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._chosen)
        top = QHBoxLayout()
        top.addWidget(self.header, 1)
        top.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(top)
        lay.addWidget(self.list, 1)

    def show_results(self, q: str, events: list[CalendarEvent]) -> None:
        from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
        from PySide6.QtWidgets import QListWidgetItem

        def dot(hex_: str) -> QIcon:
            pm = QPixmap(12, 12)
            pm.fill(Qt.transparent)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(hex_))
            painter.drawEllipse(1, 1, 10, 10)
            painter.end()
            return QIcon(pm)

        self.header.setText(f"🔍 「{q}」：{len(events)} 筆")
        self.list.clear()
        if not events:
            item = QListWidgetItem("找不到符合的活動（搜尋範圍：前後各一年）")
            item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
            return
        current = None
        for ev in sorted(events, key=lambda e: e.start):
            d = ev.start.date()
            if d != current:
                current = d
                head = QListWidgetItem(fmt.day_text(d, with_year=True))
                f = QFont()
                f.setBold(True)
                head.setFont(f)
                head.setForeground(QColor("#A0506B"))
                head.setFlags(Qt.NoItemFlags)
                self.list.addItem(head)
            when = "全天" if ev.all_day else ev.start.strftime("%H:%M")
            item = QListWidgetItem(dot(color_hex(ev.color_id)), f"{when}　{ev.title}")
            item.setData(Qt.UserRole, ev)
            self.list.addItem(item)

    def _chosen(self, item) -> None:
        ev = item.data(Qt.UserRole)
        if ev is not None:
            self.event_chosen.emit(ev)
