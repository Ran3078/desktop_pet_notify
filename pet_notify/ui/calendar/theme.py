"""行事曆畫面共用的配色、字型與活動色塊繪製。"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from ...cal.colors import color_hex
from ...cal.models import CalendarEvent

FONT_FAMILY = "Microsoft JhengHei UI"

GRID_LINE = QColor("#F0D9E0")
HEADER_TEXT = QColor("#8A6A75")
TEXT = QColor("#4A3B3F")
MUTED = QColor("#C9B8BE")
TODAY = QColor("#E8789A")
SELECTED_BG = QColor("#FFEFF4")
HOVER_BG = QColor("#FFF6F9")
WEEKEND_BG = QColor("#FFFBFC")
HOLIDAY_TEXT = QColor("#D93025")
NOW_LINE = QColor("#EA4335")
BACKGROUND = QColor("#FFFFFF")


def font(pt: float, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


def event_color(ev: CalendarEvent) -> QColor:
    return QColor(color_hex(ev.color_id, holiday=ev.read_only))


def text_on(bg: QColor) -> QColor:
    """在 bg 上要用白字還是深色字。"""
    luminance = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return QColor("#3B2F33") if luminance > 170 else QColor("#FFFFFF")


def elide(p: QPainter, text: str, width: float) -> str:
    return QFontMetrics(p.font()).elidedText(text, Qt.ElideRight, max(0, int(width)))


def draw_bar(p: QPainter, rect: QRectF, ev: CalendarEvent, label: str, *, cont_left=False, cont_right=False,
             faded=False, highlight=False) -> None:
    """實心色條（全天 / 跨日活動、時間軸上的活動區塊）。"""
    color = event_color(ev)
    if faded:
        color = QColor(color)
        color.setAlpha(150)
    if highlight:
        color = color.darker(112)
    radius = 4
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(rect, radius, radius)
    # 延續到上 / 下一週的那一側畫成方角
    if cont_left:
        p.drawRect(QRectF(rect.left(), rect.top(), radius, rect.height()))
    if cont_right:
        p.drawRect(QRectF(rect.right() - radius, rect.top(), radius, rect.height()))
    p.setPen(text_on(color))
    inner = rect.adjusted(6, 0, -4, 0)
    p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, elide(p, label, inner.width()))


def draw_dot_item(p: QPainter, rect: QRectF, ev: CalendarEvent, label: str, *, faded=False,
                  highlight=False) -> None:
    """月曆格子裡的計時活動：色點 + 時間 + 標題（Google 日曆樣式）。"""
    if highlight:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 18))
        p.drawRoundedRect(rect, 4, 4)
    color = event_color(ev)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    r = 3.5
    p.drawEllipse(rect.left() + 6, rect.center().y() - r, r * 2, r * 2)
    p.setPen(MUTED if faded else TEXT)
    inner = rect.adjusted(16, 0, -2, 0)
    p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, elide(p, label, inner.width()))


def draw_ghost(p: QPainter, rect: QRectF, ev: CalendarEvent, label: str) -> None:
    """拖曳中的半透明預覽。"""
    color = event_color(ev)
    color.setAlpha(190)
    p.setPen(QPen(color.darker(120), 1.2))
    p.setBrush(color)
    p.drawRoundedRect(rect, 4, 4)
    p.setPen(text_on(color))
    p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, elide(p, label, rect.width() - 10))
