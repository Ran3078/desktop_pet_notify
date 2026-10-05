"""所有皮膚共用的頭上特效：倒數小牌、驚嘆號、愛心、zzz、生氣符號、慶祝彩帶。"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from .base import ALERT, ANGRY, CANVAS_W, CELEBRATE, HAPPY, SLEEP, RenderContext

UI_FONT = "Microsoft JhengHei UI"


def heart_path(cx: float, cy: float, size: float) -> QPainterPath:
    s = size
    path = QPainterPath(QPointF(cx, cy + s * 0.35))
    path.cubicTo(cx - s * 0.9, cy - s * 0.25, cx - s * 0.45, cy - s * 0.95, cx, cy - s * 0.4)
    path.cubicTo(cx + s * 0.45, cy - s * 0.95, cx + s * 0.9, cy - s * 0.25, cx, cy + s * 0.35)
    return path


def draw_badge(p: QPainter, ctx: RenderContext, head_top: float) -> None:
    if not ctx.badge:
        return
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    p.setFont(font)
    text_w = p.fontMetrics().horizontalAdvance(ctx.badge)
    icon_w = 14
    w = text_w + icon_w + 16
    rect = QRectF(CANVAS_W / 2 - w / 2, max(2.0, head_top - 30), w, 20)
    if ctx.badge_kind == "pomodoro":
        bg, fg = QColor("#FFEDEB"), QColor("#D9443B")
    else:
        bg, fg = QColor("#FFF8E1"), QColor("#B26A00")
        if ctx.urgency > 0.8:
            bg, fg = QColor("#FFE3E3"), QColor("#C62828")
    p.setPen(QPen(fg.lighter(150), 1.2))
    p.setBrush(bg)
    p.drawRoundedRect(rect, 10, 10)

    # 小圖示：番茄或時鐘
    ix, iy = rect.left() + 12, rect.center().y()
    if ctx.badge_kind == "pomodoro":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E5533D"))
        p.drawEllipse(QPointF(ix, iy + 1), 5.2, 4.8)
        p.setBrush(QColor("#4CAF50"))
        p.drawEllipse(QPointF(ix, iy - 3.6), 2.6, 1.4)
    else:
        p.setPen(QPen(fg, 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(ix, iy), 5, 5)
        p.drawLine(QPointF(ix, iy), QPointF(ix, iy - 3))
        p.drawLine(QPointF(ix, iy), QPointF(ix + 2.4, iy))

    p.setPen(fg)
    p.drawText(QRectF(rect.left() + icon_w + 8, rect.top(), text_w + 4, rect.height()),
               Qt.AlignVCenter | Qt.AlignLeft, ctx.badge)


def draw_effects(p: QPainter, ctx: RenderContext, head_top: float) -> None:
    """head_top：頭頂在畫布上的 y 座標。"""
    cx = CANVAS_W / 2
    t = ctx.state_time

    if ctx.state == ALERT:
        bounce = abs(math.sin(t * (6 + ctx.urgency * 6))) * 4
        center = QPointF(cx + 46, head_top - 4 - bounce)
        p.setPen(QPen(QColor("#E0A100"), 1.5))
        p.setBrush(QColor("#FFD54F"))
        p.drawEllipse(center, 10, 10)
        font = QFont("Segoe UI", 12)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#5D4037"))
        p.drawText(QRectF(center.x() - 10, center.y() - 11, 20, 22), Qt.AlignCenter, "!")

    if ctx.state in (HAPPY, CELEBRATE):
        p.setPen(Qt.NoPen)
        for i, (dx, delay) in enumerate(((-22, 0.0), (8, 0.25), (28, 0.5))):
            k = ((t - delay) % 1.4) / 1.4 if t >= delay else -1
            if k < 0:
                continue
            alpha = int(255 * (1 - k))
            color = QColor("#FF6B8B") if i != 1 else QColor("#FF9EB5")
            color.setAlpha(alpha)
            p.setBrush(color)
            y = head_top - 4 - k * 46
            x = cx + dx + math.sin(k * 6 + i) * 4
            p.drawPath(heart_path(x, y, 8 + i))

    if ctx.state == CELEBRATE:
        colors = ["#FF6B8B", "#FFD54F", "#4FC3F7", "#81C784", "#BA68C8"]
        for i in range(14):
            angle = i * (2 * math.pi / 14) + t * 1.5
            r = 30 + (t * 40) % 50
            x = cx + math.cos(angle) * r
            y = head_top + 20 + math.sin(angle) * r * 0.7
            c = QColor(colors[i % len(colors)])
            c.setAlpha(max(0, 230 - int((r - 30) * 4)))
            p.setBrush(c)
            p.save()
            p.translate(x, y)
            p.rotate(angle * 57 + t * 200)
            p.drawRect(QRectF(-2.5, -1.2, 5, 2.4))
            p.restore()

    if ctx.state == SLEEP:
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        for i in range(3):
            k = ((t * 0.5 + i / 3) % 1.0)
            c = QColor("#7E8CC9")
            c.setAlpha(int(255 * (1 - k)))
            p.setPen(c)
            font.setPointSizeF(7 + k * 6)
            p.setFont(font)
            p.drawText(QPointF(cx + 30 + k * 18, head_top + 6 - k * 34), "Z")

    if ctx.state == ANGRY:
        x, y = cx + 38, head_top + 6
        p.setPen(QPen(QColor("#E53935"), 2.6, Qt.SolidLine, Qt.RoundCap))
        pulse = 1 + 0.12 * math.sin(t * 14)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            a = QPointF(x + sx * 2.5 * pulse, y + sy * 2.5 * pulse)
            b = QPointF(x + sx * 7 * pulse, y + sy * 2.5 * pulse)
            c = QPointF(x + sx * 2.5 * pulse, y + sy * 7 * pulse)
            path = QPainterPath(b)
            path.quadTo(a, c)
            p.drawPath(path)
