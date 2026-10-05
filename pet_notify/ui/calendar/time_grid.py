"""週檢視 / 日檢視的時間格（也用在月檢視右側的日程面板）。

上方是全天活動列，下方是可捲動的 0~24 小時格；重疊的活動並排，今天有「現在」紅線。
支援：拖曳活動改時間（15 分鐘為單位，可拖到別天）、拖曳下緣改結束時間、在空白處拖曳選取時段快速新增。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from ...cal import lunar
from ...cal.models import CalendarEvent, local_now
from . import layout as L
from . import theme as T

HOUR_H = 44
GUTTER = 52
LANE_H = 18
LANE_GAP = 2
RESIZE_EDGE = 6
DRAG_THRESHOLD = 5
WEEKDAYS = "一二三四五六日"


def time_text(ev: CalendarEvent) -> str:
    return f"{ev.start:%H:%M}–{ev.end:%H:%M}"


class _Base(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.days: list[date] = [date.today()]
        self.events: list[CalendarEvent] = []
        self.holidays_on: Callable[[date], list[CalendarEvent]] = lambda d: []
        self.selected_event_id = ""
        self.setMouseTracking(True)

    def col_width(self) -> float:
        return (self.width() - GUTTER) / max(1, len(self.days))

    def col_at(self, x: float) -> int | None:
        if x < GUTTER:
            return None
        col = int((x - GUTTER) // self.col_width())
        return col if 0 <= col < len(self.days) else None


class AllDayHeader(_Base):
    date_clicked = Signal(object)          # date
    event_clicked = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.label_h = 40          # 日期標題列高度；右側日程面板已有標題，設為 0 隱藏
        self.show_lunar = True
        self._items: list[tuple[QRectF, CalendarEvent]] = []
        self._hover_id = ""

    def _all_day_events(self) -> list[CalendarEvent]:
        out = [ev for ev in self.events if L.is_bar(ev)]
        for d in self.days:
            out.extend(h for h in self.holidays_on(d) if h not in out)
        return out

    def refresh_height(self) -> None:
        placed = L.layout_week(self._all_day_events(), self.days)
        lanes = max([p.lane + 1 for p in placed], default=0)
        self.setFixedHeight(self.label_h + max(1, lanes) * (LANE_H + LANE_GAP) + 6)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), T.BACKGROUND)
        w = self.col_width()
        today = date.today()
        for i, d in enumerate(self.days if self.label_h >= 30 else []):  # 精簡模式不畫日期標題
            x = GUTTER + i * w
            p.setFont(T.font(8.5))
            holiday = bool(self.holidays_on(d))
            p.setPen(T.HOLIDAY_TEXT if holiday else T.HEADER_TEXT)
            sub = f"週{WEEKDAYS[d.weekday()]}"
            if self.show_lunar and lunar.short_label(d):
                sub += f" · {lunar.short_label(d)}"
            p.drawText(QRectF(x, 2, w, 16), Qt.AlignCenter, sub)
            p.setFont(T.font(12, bold=d == today))
            num_rect = QRectF(x + w / 2 - 14, 18, 28, 22)
            if d == today:
                p.setPen(Qt.NoPen)
                p.setBrush(T.TODAY)
                p.drawEllipse(num_rect.center(), 12, 12)
                p.setPen(T.BACKGROUND)
            else:
                p.setPen(T.HOLIDAY_TEXT if holiday else T.TEXT)
            p.drawText(num_rect, Qt.AlignCenter, str(d.day))

        p.setFont(T.font(8))
        p.setPen(T.HEADER_TEXT)
        p.drawText(QRectF(0, self.label_h, GUTTER - 6, LANE_H), Qt.AlignVCenter | Qt.AlignRight, "全天")

        self._items = []
        p.setFont(T.font(8.5))
        for pl in L.layout_week(self._all_day_events(), self.days):
            top = self.label_h + pl.lane * (LANE_H + LANE_GAP)
            rect = QRectF(GUTTER + pl.col_start * w + 2, top, (pl.col_end - pl.col_start + 1) * w - 4, LANE_H)
            T.draw_bar(p, rect, pl.event, pl.event.title, cont_left=pl.cont_left, cont_right=pl.cont_right,
                       highlight=pl.event.id in (self._hover_id, self.selected_event_id))
            self._items.append((rect, pl.event))

        p.setPen(QPen(T.GRID_LINE, 1))
        p.drawLine(QPointF(0, self.height() - 1), QPointF(self.width(), self.height() - 1))

    def mouseMoveEvent(self, event) -> None:
        hit = next((ev.id for r, ev in self._items if r.contains(event.position())), "")
        if hit != self._hover_id:
            self._hover_id = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        for rect, ev in self._items:
            if rect.contains(pos):
                self.event_clicked.emit(ev, event.globalPosition().toPoint())
                return
        col = self.col_at(pos.x())
        if col is not None and pos.y() < self.label_h:
            self.date_clicked.emit(self.days[col])


class HoursCanvas(_Base):
    event_clicked = Signal(object, object)
    event_retimed = Signal(object, object, object)       # 活動, 新開始, 新結束
    range_selected = Signal(object, int, int, object)    # 日期, 開始分鐘, 結束分鐘, QPoint
    date_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24 * HOUR_H + 1)
        self._blocks: list[tuple[QRectF, CalendarEvent]] = []
        self._hover_id = ""
        self._drag: dict | None = None
        self._ghost: tuple[int, int, int] | None = None     # (欄, 開始分鐘, 結束分鐘)

    # ---- 換算 ----
    @staticmethod
    def minutes_at(y: float) -> float:
        return max(0.0, min(24 * 60.0, y / HOUR_H * 60))

    @staticmethod
    def y_of(minutes: float) -> float:
        return minutes / 60 * HOUR_H

    def _block_at(self, pos: QPointF) -> tuple[QRectF, CalendarEvent] | None:
        for rect, ev in reversed(self._blocks):
            if rect.contains(pos):
                return rect, ev
        return None

    # ---- 繪圖 ----
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), T.BACKGROUND)
        w = self.col_width()
        today = date.today()
        for i, d in enumerate(self.days):
            if d.weekday() >= 5:
                p.fillRect(QRectF(GUTTER + i * w, 0, w, self.height()), T.WEEKEND_BG)

        p.setFont(T.font(8))
        for h in range(24):
            y = self.y_of(h * 60)
            p.setPen(QPen(T.GRID_LINE, 1))
            p.drawLine(QPointF(GUTTER - 4, y), QPointF(self.width(), y))
            p.setPen(QPen(T.GRID_LINE, 1, Qt.DotLine))
            p.drawLine(QPointF(GUTTER, y + HOUR_H / 2), QPointF(self.width(), y + HOUR_H / 2))
            if h:
                p.setPen(T.HEADER_TEXT)
                p.drawText(QRectF(0, y - 8, GUTTER - 8, 16), Qt.AlignVCenter | Qt.AlignRight, f"{h:02d}:00")
        p.setPen(QPen(T.GRID_LINE, 1))
        for i in range(len(self.days) + 1):
            x = GUTTER + i * w
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))

        self._blocks = []
        dragging_id = self._drag["event"].id if self._drag and self._drag.get("active") and self._drag.get(
            "event") else ""
        for i, d in enumerate(self.days):
            for b in L.layout_day(self.events, d):
                bw = w / b.ncols
                rect = QRectF(GUTTER + i * w + b.col * bw + 1, self.y_of(b.top_min) + 1,
                              bw - 3, self.y_of(b.bottom_min) - self.y_of(b.top_min) - 2)
                self._paint_block(p, rect, b.event, faded=b.event.id == dragging_id or b.event.end < local_now())
                self._blocks.append((rect, b.event))

        if self._ghost:
            col, s, e = self._ghost
            rect = QRectF(GUTTER + col * w + 1, self.y_of(s) + 1, w - 3, self.y_of(e) - self.y_of(s) - 2)
            ev = self._drag.get("event") if self._drag else None
            if ev is not None:
                T.draw_ghost(p, rect, ev, f"{s // 60:02d}:{s % 60:02d} {ev.title}")
            else:
                p.setPen(QPen(T.TODAY, 1.2))
                c = T.TODAY.lighter(150)
                c.setAlpha(120)
                p.setBrush(c)
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(T.TEXT)
                p.setFont(T.font(8.5))
                p.drawText(rect.adjusted(6, 2, -4, 0), Qt.AlignTop | Qt.AlignLeft,
                           f"{s // 60:02d}:{s % 60:02d} – {e // 60:02d}:{e % 60:02d}")

        if today in self.days:
            now = local_now()
            col = self.days.index(today)
            y = self.y_of(now.hour * 60 + now.minute)
            p.setPen(QPen(T.NOW_LINE, 2))
            p.drawLine(QPointF(GUTTER + col * w, y), QPointF(GUTTER + (col + 1) * w, y))
            p.setPen(Qt.NoPen)
            p.setBrush(T.NOW_LINE)
            p.drawEllipse(QPointF(GUTTER + col * w, y), 5, 5)

    def _paint_block(self, p: QPainter, rect: QRectF, ev: CalendarEvent, faded: bool) -> None:
        color = T.event_color(ev)
        if faded:
            color.setAlpha(140)
        if ev.id in (self._hover_id, self.selected_event_id):
            color = color.darker(112)
        p.setPen(QPen(T.BACKGROUND, 1))
        p.setBrush(color)
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(T.text_on(color))
        inner = rect.adjusted(5, 2, -3, -2)
        if rect.height() < 30:
            p.setFont(T.font(8))
            p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft,
                       T.elide(p, f"{ev.title}，{ev.start:%H:%M}", inner.width()))
            return
        p.setFont(T.font(8.5, bold=True))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                   T.elide(p, ev.title, inner.width()))
        p.setFont(T.font(8))
        p.drawText(QRectF(inner.left(), inner.top() + 16, inner.width(), 14), Qt.AlignLeft | Qt.AlignVCenter,
                   T.elide(p, time_text(ev), inner.width()))
        if ev.location and rect.height() > 48:
            p.drawText(QRectF(inner.left(), inner.top() + 30, inner.width(), 14), Qt.AlignLeft | Qt.AlignVCenter,
                       T.elide(p, ev.location, inner.width()))

    # ---- 滑鼠 ----
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        col = self.col_at(pos.x())
        hit = self._block_at(pos)
        if hit:
            rect, ev = hit
            mode = "resize" if pos.y() > rect.bottom() - RESIZE_EDGE and not ev.spans_days else "move"
            grab = self.minutes_at(pos.y()) - (ev.start.hour * 60 + ev.start.minute)
            self._drag = {"event": ev, "mode": mode, "press": pos, "grab": grab, "active": False}
        elif col is not None:
            start = L.snap(self.minutes_at(pos.y()) - 7)
            self._drag = {"event": None, "mode": "select", "press": pos, "col": col, "start": start,
                          "active": False}

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        d = self._drag
        if d and (event.buttons() & Qt.LeftButton):
            if not d["active"] and (pos - d["press"]).manhattanLength() > DRAG_THRESHOLD:
                ev = d["event"]
                if ev is not None and ev.read_only:
                    return
                d["active"] = True
            if d["active"]:
                self._update_ghost(pos)
            return
        hit = self._block_at(pos)
        hover = hit[1].id if hit else ""
        if hit and pos.y() > hit[0].bottom() - RESIZE_EDGE and not hit[1].read_only:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        if hover != self._hover_id:
            self._hover_id = hover
            self.update()

    def _update_ghost(self, pos: QPointF) -> None:
        d = self._drag
        col = self.col_at(pos.x())
        minutes = self.minutes_at(pos.y())
        if d["mode"] == "select":
            end = max(d["start"] + 15, L.snap(minutes))
            start = min(d["start"], L.snap(minutes))
            self._ghost = (d["col"], start, max(end, start + 15))
        elif d["mode"] == "resize":
            ev = d["event"]
            col = self.days.index(ev.start.date()) if ev.start.date() in self.days else 0
            start = ev.start.hour * 60 + ev.start.minute
            self._ghost = (col, start, max(start + 15, L.snap(minutes)))
        else:
            ev = d["event"]
            if col is None:
                return
            duration = int((ev.end - ev.start).total_seconds() // 60)
            start = max(0, min(24 * 60 - 15, L.snap(minutes - d["grab"])))
            self._ghost = (col, start, min(24 * 60, start + duration))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._drag:
            return
        d, ghost = self._drag, self._ghost
        self._drag, self._ghost = None, None
        self.update()
        gpos = event.globalPosition().toPoint()
        if not d["active"]:
            if d["event"] is not None:
                self.event_clicked.emit(d["event"], gpos)
            else:
                self.date_clicked.emit(self.days[d["col"]])
            return
        if ghost is None:
            return
        col, s, e = ghost
        if d["mode"] == "select":
            self.range_selected.emit(self.days[col], s, e, gpos)
        elif d["mode"] == "resize":
            start, end = L.resized(d["event"], e)
            if end != d["event"].end:
                self.event_retimed.emit(d["event"], start, end)
        else:
            start, end = L.moved_in_time(d["event"], self.days[col], s)
            if start != d["event"].start:
                self.event_retimed.emit(d["event"], start, end)

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position()
        col = self.col_at(pos.x())
        if event.button() == Qt.LeftButton and col is not None and not self._block_at(pos):
            start = (int(self.minutes_at(pos.y())) // 60) * 60
            self.range_selected.emit(self.days[col], start, min(24 * 60, start + 60),
                                     event.globalPosition().toPoint())

    def leaveEvent(self, _event) -> None:
        if self._hover_id:
            self._hover_id = ""
            self.update()


class TimeGridView(QWidget):
    """全天列 + 可捲動的小時格。"""

    event_clicked = Signal(object, object)
    event_retimed = Signal(object, object, object)
    range_selected = Signal(object, int, int, object)
    date_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.header = AllDayHeader()
        self.canvas = HoursCanvas()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.scroll, 1)

        for src in (self.header, self.canvas):
            src.event_clicked.connect(self.event_clicked)
            src.date_clicked.connect(self.date_clicked)
        self.canvas.event_retimed.connect(self.event_retimed)
        self.canvas.range_selected.connect(self.range_selected)

        self._scrolled = False
        # 每分鐘重畫一次，讓「現在」紅線往下移
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.canvas.update)
        self._tick.start(60_000)

    def set_data(self, days: list[date], events: list[CalendarEvent], holidays_on, show_lunar: bool,
                 selected_event_id: str = "") -> None:
        for w in (self.header, self.canvas):
            w.days, w.events, w.holidays_on, w.selected_event_id = days, events, holidays_on, selected_event_id
        self.header.show_lunar = show_lunar
        self.header.refresh_height()
        self.header.update()
        self.canvas.update()

    def scroll_to_hour(self, hour: int) -> None:
        self.scroll.verticalScrollBar().setValue(max(0, int(hour * HOUR_H) - 12))  # 留點空間，時刻標籤才不會被切掉

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._scrolled:
            self._scrolled = True
            QTimer.singleShot(0, lambda: self.scroll_to_hour(max(0, min(local_now().hour - 1, 8))))

    def global_pos_for(self, d: date, minutes: int) -> QPoint:
        if d not in self.canvas.days:
            return self.mapToGlobal(QPoint(self.width() // 2, 60))
        x = GUTTER + (self.canvas.days.index(d) + 1) * self.canvas.col_width()
        return self.canvas.mapToGlobal(QPoint(int(x), int(HoursCanvas.y_of(minutes))))


def combine(d: date, minutes: int, tz) -> datetime:
    return datetime.combine(d, datetime.min.time(), tz) + timedelta(minutes=minutes)
