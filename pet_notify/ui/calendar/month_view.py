"""月檢視：6 週 × 7 天的日期格子，全部自己畫（跨日色條、hover、拖曳改期）。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...cal import lunar
from ...cal.models import CalendarEvent
from . import layout as L
from . import theme as T

HEADER_H = 26
DATE_H = 26
LANE_H = 18
LANE_GAP = 2
DRAG_THRESHOLD = 6


def item_label(ev: CalendarEvent) -> str:
    if ev.all_day:
        return ev.title
    return f"{ev.start:%H:%M} {ev.title}"


class MonthView(QWidget):
    date_selected = Signal(object)            # date
    date_activated = Signal(object, object)   # date, QPoint（全域座標）→ 快速新增
    event_clicked = Signal(object, object)    # CalendarEvent, QPoint
    event_moved = Signal(object, int)         # CalendarEvent, 位移天數
    wheel_step = Signal(int)                  # -1 上個月、1 下個月

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(560, 420)
        self.year, self.month = date.today().year, date.today().month
        self.week_start = "sun"
        self.show_lunar = True
        self.events: list[CalendarEvent] = []
        self.holidays_on: Callable[[date], list[CalendarEvent]] = lambda d: []
        self.selected: date | None = date.today()
        self.selected_event_id = ""
        self._grid: list[date] = L.month_grid(self.year, self.month, self.week_start)
        self._items: list[tuple[QRectF, CalendarEvent, date]] = []  # 可點擊的活動：(範圍, 活動, 所在日期)
        self._more: list[tuple[QRectF, date]] = []
        self._hover_date: date | None = None
        self._hover_event_id = ""
        self._press: tuple[QPointF, CalendarEvent | None, date | None] | None = None
        self._drag_target: date | None = None

    # ---- 資料 ----
    def set_month(self, year: int, month: int, week_start: str, show_lunar: bool) -> None:
        self.year, self.month, self.week_start, self.show_lunar = year, month, week_start, show_lunar
        self._grid = L.month_grid(year, month, week_start)
        self.update()

    def set_events(self, events: list[CalendarEvent]) -> None:
        self.events = events
        self.update()

    def set_selected(self, d: date | None) -> None:
        self.selected = d
        self.update()

    # ---- 幾何 ----
    def _cell_size(self) -> tuple[float, float]:
        return self.width() / 7, (self.height() - HEADER_H) / 6

    def _cell_rect(self, index: int) -> QRectF:
        w, h = self._cell_size()
        return QRectF((index % 7) * w, HEADER_H + (index // 7) * h, w, h)

    def date_at(self, pos: QPointF) -> date | None:
        w, h = self._cell_size()
        if pos.y() < HEADER_H or pos.x() < 0 or pos.x() >= self.width():
            return None
        col, row = int(pos.x() // w), int((pos.y() - HEADER_H) // h)
        if 0 <= row < 6 and 0 <= col < 7:
            return self._grid[row * 7 + col]
        return None

    def _item_at(self, pos: QPointF) -> tuple[CalendarEvent, date] | None:
        for rect, ev, d in reversed(self._items):
            if rect.contains(pos):
                return ev, d
        return None

    def _max_lanes(self) -> int:
        _, h = self._cell_size()
        return max(0, int((h - DATE_H - 2) // (LANE_H + LANE_GAP)))

    # ---- 繪圖 ----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), T.BACKGROUND)
        w, h = self._cell_size()
        today = date.today()

        # 星期標題
        p.setFont(T.font(9))
        p.setPen(T.HEADER_TEXT)
        for i, label in enumerate(L.weekday_labels(self.week_start)):
            p.drawText(QRectF(i * w, 0, w, HEADER_H), Qt.AlignCenter, label)

        self._items, self._more = [], []
        for index, d in enumerate(self._grid):
            self._paint_cell(p, index, d, today)

        # 格線
        p.setPen(QPen(T.GRID_LINE, 1))
        for r in range(7):
            y = HEADER_H + r * h
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
        for c in range(1, 7):
            p.drawLine(QPointF(c * w, HEADER_H), QPointF(c * w, self.height()))

        # 活動
        p.setFont(T.font(8.5))
        max_lanes = self._max_lanes()
        for row in range(6):
            week = self._grid[row * 7:row * 7 + 7]
            week_events = [ev for ev in self.events if self._in_week(ev, week)]
            for d in week:
                week_events.extend(hd for hd in self.holidays_on(d) if hd not in week_events)
            placed = L.layout_week(week_events, week)
            visible, hidden = L.visible_and_hidden(placed, max_lanes)
            for pl in visible:
                self._paint_item(p, row, pl, w, h)
            for col, count in hidden.items():
                slot = max(0, max_lanes - 1)
                rect = QRectF(col * w + 3, HEADER_H + row * h + DATE_H + slot * (LANE_H + LANE_GAP), w - 6, LANE_H)
                hovered = self._hover_date == week[col] and rect.contains(self.mapFromGlobal(self.cursor().pos()))
                p.setPen(T.TODAY if hovered else T.HEADER_TEXT)
                p.drawText(rect.adjusted(6, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, f"+{count} 則")
                self._more.append((rect, week[col]))

        if self._drag_target and self._press and self._press[1]:
            self._paint_drag(p, self._press[1], w, h)

    @staticmethod
    def _in_week(ev: CalendarEvent, week: list[date]) -> bool:
        d0, d1 = L.event_days(ev)
        return d0 <= week[-1] and d1 >= week[0]

    def _paint_cell(self, p: QPainter, index: int, d: date, today: date) -> None:
        rect = self._cell_rect(index)
        in_month = d.month == self.month
        if d == self.selected:
            p.fillRect(rect, T.SELECTED_BG)
        elif d == self._hover_date:
            p.fillRect(rect, T.HOVER_BG)
        elif d.weekday() >= 5:
            p.fillRect(rect, T.WEEKEND_BG)
        if self._drag_target == d:
            p.setPen(QPen(T.TODAY, 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(rect.adjusted(1, 1, -1, -1))

        holiday = bool(self.holidays_on(d))
        label = f"{d.month}月{d.day}日" if d.day == 1 else str(d.day)
        p.setFont(T.font(9.5, bold=d == today or d.day == 1))
        num_rect = QRectF(rect.left() + 6, rect.top() + 3, 60, DATE_H - 6)
        if d == today:
            text_w = p.fontMetrics().horizontalAdvance(label)
            circle_w = max(20.0, text_w + 10)
            p.setPen(Qt.NoPen)
            p.setBrush(T.TODAY)
            p.drawRoundedRect(QRectF(rect.left() + 3, rect.top() + 3, circle_w, 20), 10, 10)
            p.setPen(T.BACKGROUND)
            p.drawText(QRectF(rect.left() + 3, rect.top() + 3, circle_w, 20), Qt.AlignCenter, label)
        else:
            color = T.HOLIDAY_TEXT if holiday else (T.TEXT if in_month else T.MUTED)
            if d < today and in_month and not holiday:
                color = T.HEADER_TEXT
            p.setPen(color)
            p.drawText(num_rect, Qt.AlignVCenter | Qt.AlignLeft, label)

        if self.show_lunar:
            text = lunar.short_label(d)
            if text:
                p.setFont(T.font(7.5))
                festival = bool(lunar.festival(d))
                p.setPen(T.HOLIDAY_TEXT if festival and in_month else T.MUTED)
                p.drawText(QRectF(rect.right() - 60, rect.top() + 3, 55, DATE_H - 6),
                           Qt.AlignVCenter | Qt.AlignRight, text)

    def _paint_item(self, p: QPainter, row: int, pl: L.Placed, w: float, h: float) -> None:
        ev = pl.event
        top = HEADER_H + row * h + DATE_H + pl.lane * (LANE_H + LANE_GAP)
        left = pl.col_start * w + (1 if pl.cont_left else 3)
        right = (pl.col_end + 1) * w - (1 if pl.cont_right else 3)
        rect = QRectF(left, top, right - left, LANE_H)
        week_first = self._grid[row * 7]
        first_day = week_first + timedelta(days=pl.col_start)
        faded = L.event_days(ev)[1] < date.today()
        highlight = ev.id in (self._hover_event_id, self.selected_event_id)
        if L.is_bar(ev):
            T.draw_bar(p, rect, ev, item_label(ev), cont_left=pl.cont_left, cont_right=pl.cont_right,
                       faded=faded, highlight=highlight)
        else:
            T.draw_dot_item(p, rect, ev, item_label(ev), faded=faded, highlight=highlight)
        self._items.append((rect, ev, first_day))

    def _paint_drag(self, p: QPainter, ev: CalendarEvent, w: float, h: float) -> None:
        index = self._grid.index(self._drag_target)
        cell = self._cell_rect(index)
        span = (L.event_days(ev)[1] - L.event_days(ev)[0]).days
        cols = min(span, 6 - index % 7)
        rect = QRectF(cell.left() + 3, cell.top() + DATE_H, w * (cols + 1) - 6, LANE_H)
        p.setFont(T.font(8.5))
        T.draw_ghost(p, rect, ev, item_label(ev))

    # ---- 滑鼠 ----
    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        hit = self._item_at(pos)
        self._press = (pos, hit[0] if hit else None, self.date_at(pos))

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._press and self._press[1] and (event.buttons() & Qt.LeftButton):
            ev = self._press[1]
            if not ev.read_only and (pos - self._press[0]).manhattanLength() > DRAG_THRESHOLD:
                self._drag_target = self.date_at(pos)
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
            return
        hit = self._item_at(pos)
        hover_date = self.date_at(pos)
        hover_event = hit[0].id if hit else ""
        self.setCursor(Qt.PointingHandCursor if hit or any(r.contains(pos) for r, _ in self._more)
                       else Qt.ArrowCursor)
        if (hover_date, hover_event) != (self._hover_date, self._hover_event_id):
            self._hover_date, self._hover_event_id = hover_date, hover_event
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._press:
            return
        press_pos, ev, press_date = self._press
        target = self._drag_target
        self._press, self._drag_target = None, None
        self.unsetCursor()
        pos = event.position()
        if target is not None and ev is not None:
            delta = (target - press_date).days if press_date else 0
            if delta:
                self.event_moved.emit(ev, delta)
            self.update()
            return
        if ev is not None:
            self.event_clicked.emit(ev, event.globalPosition().toPoint())
            return
        for rect, d in self._more:
            if rect.contains(pos):
                self.date_selected.emit(d)
                return
        d = self.date_at(pos)
        if d:
            self.date_selected.emit(d)

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position()
        if event.button() != Qt.LeftButton or self._item_at(pos):
            return
        d = self.date_at(pos)
        if d:
            self.date_activated.emit(d, event.globalPosition().toPoint())

    def leaveEvent(self, _event) -> None:
        self._hover_date, self._hover_event_id = None, ""
        self.update()

    def wheelEvent(self, event) -> None:
        dy = event.angleDelta().y()
        if dy:
            self.wheel_step.emit(-1 if dy > 0 else 1)

    def cell_global_pos(self, d: date) -> QPoint:
        if d in self._grid:
            rect = self._cell_rect(self._grid.index(d))
            return self.mapToGlobal(rect.topRight().toPoint())
        return self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
