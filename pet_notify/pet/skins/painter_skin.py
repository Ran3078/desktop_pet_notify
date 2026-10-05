"""內建皮膚：用 QPainter 畫一隻圓滾滾的小動物（麻糬貓）。"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from . import overlays
from .base import (
    ALERT, ANGRY, CANVAS_W, CELEBRATE, DRAG, FEET_Y, GREET, HAPPY, POMODORO, SIT, SLEEP, STRETCH, WALK, YAWN,
    RenderContext, Skin,
)

# 配色：身體、外框、肚子、耳朵內側
PALETTES = {
    "cream": ("#FFF3DC", "#D9A866", "#FFFBF2", "#FFC9C9"),
    "pink": ("#FFD9E4", "#E58AA8", "#FFF2F6", "#FFA9C2"),
    "mint": ("#D2F5E8", "#5FB894", "#F2FFFA", "#FFC2CF"),
    "milktea": ("#EBD5BC", "#A57D57", "#F8EEE2", "#F0B7A4"),
}

BODY_RX, BODY_RY = 52.0, 44.0
BODY_CY = -46.0  # 相對腳底


class PainterSkin(Skin):
    id = "builtin"
    name = "麻糬貓（內建）"
    supports_customization = True
    edge_inset = 24.0  # 身體（含手）左右各留約 24px 透明邊

    # ---- 動作參數 ----
    @staticmethod
    def _pose(ctx: RenderContext) -> tuple[float, float, float]:
        """回傳 (y 位移, x 位移, 額外 squash)。"""
        t, st = ctx.clock, ctx.state_time
        dy = dx = 0.0
        squash = 0.0
        if ctx.state == WALK:
            dy = -abs(math.sin(t * 9)) * 3
        elif ctx.state == ALERT:
            freq = 7 + ctx.urgency * 6
            dy = -abs(math.sin(st * freq)) * (6 + ctx.urgency * 10)
        elif ctx.state == HAPPY:
            dy = -abs(math.sin(st * 9)) * 6
        elif ctx.state == CELEBRATE:
            dy = -abs(math.sin(st * 6)) * 16
        elif ctx.state == ANGRY:
            dx = math.sin(st * 45) * 1.8
        elif ctx.state == STRETCH:
            squash = -0.14 * math.sin(min(1.0, st / 2.0) * math.pi)
        elif ctx.state == DRAG:
            squash = -0.08
        elif ctx.state == SIT:
            squash = 0.06
        elif ctx.state == SLEEP:
            squash = 0.05 + 0.025 * math.sin(t * 1.6)
        else:
            squash = 0.02 * math.sin(t * 2.4)  # 呼吸
        return dy, dx, squash

    def head_top(self, ctx: RenderContext) -> float:
        dy, _, sq = self._pose(ctx)
        return FEET_Y + dy + (BODY_CY - BODY_RY - 10) * (1 - sq)

    # ---- 繪圖 ----
    def draw(self, p: QPainter, ctx: RenderContext) -> None:
        body_c, line_c, belly_c, ear_c = (QColor(c) for c in PALETTES.get(ctx.color, PALETTES["cream"]))
        dy, dx, extra_sq = self._pose(ctx)
        sq = max(-0.3, min(0.35, extra_sq))

        p.setRenderHint(QPainter.Antialiasing)

        # 影子（在地面上才畫）
        if not ctx.lifted:
            shade = QColor(0, 0, 0, 38 if dy > -4 else 22)
            p.setPen(Qt.NoPen)
            p.setBrush(shade)
            w = 46 * (1 + sq * 0.6) * (1 + dy / 60)
            p.drawEllipse(QPointF(CANVAS_W / 2, FEET_Y + 1), w, 4.5)

        p.save()
        p.translate(CANVAS_W / 2 + dx, FEET_Y + dy)
        p.scale(1 + sq * 0.8, 1 - sq)
        if ctx.facing < 0:
            p.scale(-1, 1)

        outline = QPen(line_c, 2.4)
        outline.setJoinStyle(Qt.RoundJoin)
        rx = BODY_RX + (4 if ctx.state == ANGRY else 0)

        self._draw_feet(p, ctx, body_c, outline)
        self._draw_ears(p, ctx, body_c, ear_c, outline)

        # 身體
        p.setPen(outline)
        p.setBrush(body_c)
        p.drawEllipse(QPointF(0, BODY_CY), rx, BODY_RY)
        p.setPen(Qt.NoPen)
        p.setBrush(belly_c)
        p.drawEllipse(QPointF(0, -30), 30, 20)

        if ctx.accessory == "scarf":
            self._draw_scarf(p)

        self._draw_face(p, ctx)
        self._draw_paws(p, ctx, body_c, outline)

        if ctx.accessory == "bow":
            self._draw_bow(p)
        elif ctx.accessory == "hat":
            self._draw_hat(p)
        p.restore()

        head_top = self.head_top(ctx)
        overlays.draw_effects(p, ctx, head_top)
        overlays.draw_badge(p, ctx, head_top)

    def _draw_feet(self, p, ctx, body_c, outline):
        p.setPen(outline)
        p.setBrush(body_c)
        lift_l = lift_r = 0.0
        if ctx.state == WALK:
            phase = ctx.clock * 9
            lift_l, lift_r = max(0, math.sin(phase)) * 4, max(0, -math.sin(phase)) * 4
        elif ctx.state == DRAG:
            lift_l = lift_r = -3  # 懸空時腳往下垂
        spread = 26 if ctx.state == SIT else 21
        p.drawEllipse(QPointF(-spread, -5 - lift_l), 12, 7)
        p.drawEllipse(QPointF(spread, -5 - lift_r), 12, 7)

    def _draw_ears(self, p, ctx, body_c, ear_c, outline):
        droop = 6 if ctx.state in (SLEEP, ANGRY) else 0
        wiggle = math.sin(ctx.clock * 3) * 1.5 if ctx.state in (HAPPY, CELEBRATE, ALERT) else 0
        for side in (-1, 1):
            p.save()
            p.translate(side * 31, -78 + droop)
            p.rotate(side * (22 + droop * 2) + wiggle * side)
            ear = QPainterPath(QPointF(-13, 8))
            ear.quadTo(QPointF(-10, -18), QPointF(0, -20))
            ear.quadTo(QPointF(10, -18), QPointF(13, 8))
            ear.closeSubpath()
            p.setPen(outline)
            p.setBrush(body_c)
            p.drawPath(ear)
            inner = QPainterPath(QPointF(-6, 4))
            inner.quadTo(QPointF(-5, -11), QPointF(0, -12))
            inner.quadTo(QPointF(5, -11), QPointF(6, 4))
            inner.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(ear_c)
            p.drawPath(inner)
            p.restore()

    def _draw_face(self, p: QPainter, ctx: RenderContext) -> None:
        dark = QColor("#3E2C2C")
        eye_y, eye_x = -54.0, 18.0
        lx, ly = ctx.look
        if ctx.facing < 0:
            lx = -lx  # 已經整體鏡像，視線要反向修正
        st = ctx.state
        pen = QPen(dark, 2.8, Qt.SolidLine, Qt.RoundCap)

        # 腮紅
        blush = QColor("#FF8FA8")
        blush.setAlpha(200 if st in (ANGRY, HAPPY, CELEBRATE) else 130)
        p.setPen(Qt.NoPen)
        p.setBrush(blush)
        for side in (-1, 1):
            p.drawEllipse(QPointF(side * 33, -40), 9 if st == ANGRY else 8, 5)

        closed = ctx.blink or st == SLEEP or (st == YAWN and 0.3 < ctx.state_time < 1.6)
        for side in (-1, 1):
            cx = side * eye_x
            if st in (HAPPY, CELEBRATE, GREET):
                path = QPainterPath(QPointF(cx - 5.5, eye_y + 2))
                path.quadTo(QPointF(cx, eye_y - 7), QPointF(cx + 5.5, eye_y + 2))
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            elif st == ANGRY:
                # > < 眼睛
                p.setPen(pen)
                p.drawLine(QPointF(cx - side * 5, eye_y - 4), QPointF(cx + side * 3, eye_y))
                p.drawLine(QPointF(cx + side * 3, eye_y), QPointF(cx - side * 5, eye_y + 4))
            elif closed:
                path = QPainterPath(QPointF(cx - 5, eye_y))
                path.quadTo(QPointF(cx, eye_y + 4.5), QPointF(cx + 5, eye_y))
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            else:
                big = st in (ALERT, DRAG)
                rx, ry = (5.6, 7.4) if big else (4.6, 6.2)
                ex, ey = cx + lx * 3.2, eye_y + ly * 2.4
                p.setPen(Qt.NoPen)
                p.setBrush(dark)
                p.drawEllipse(QPointF(ex, ey), rx, ry)
                p.setBrush(QColor("white"))
                p.drawEllipse(QPointF(ex - 1.6, ey - 2.6), 1.9, 1.9)
                if big:
                    p.drawEllipse(QPointF(ex + 1.8, ey + 2.4), 1.0, 1.0)

        # 嘴巴
        p.setBrush(Qt.NoBrush)
        mouth_pen = QPen(dark, 2.0, Qt.SolidLine, Qt.RoundCap)
        if st == YAWN and 0.3 < ctx.state_time < 1.6:
            open_k = math.sin((ctx.state_time - 0.3) / 1.3 * math.pi)
            p.setPen(QPen(dark, 1.8))
            p.setBrush(QColor("#C75B6B"))
            p.drawEllipse(QPointF(0, -40), 5 + 2 * open_k, 3 + 6 * open_k)
        elif st in (ALERT, DRAG):
            p.setPen(mouth_pen)
            p.drawEllipse(QPointF(0, -41), 3.2, 3.8)
        elif st == ANGRY:
            p.setPen(mouth_pen)
            path = QPainterPath(QPointF(-5, -38))
            path.quadTo(QPointF(0, -44), QPointF(5, -38))
            p.drawPath(path)
        else:
            # ω
            p.setPen(mouth_pen)
            path = QPainterPath(QPointF(-6, -44))
            path.quadTo(QPointF(-3, -39), QPointF(0, -43))
            path.quadTo(QPointF(3, -39), QPointF(6, -44))
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F28AA0"))
            p.drawEllipse(QPointF(0, -47), 2.4, 1.6)  # 小鼻子

    def _draw_paws(self, p, ctx, body_c, outline):
        st = ctx.state
        p.setPen(outline)
        p.setBrush(body_c)
        if st == POMODORO:
            # 抱著番茄
            p.setPen(QPen(QColor("#B83A2E"), 2))
            p.setBrush(QColor("#E5533D"))
            p.drawEllipse(QPointF(0, -24), 14, 12.5)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4CAF50"))
            for a in (-40, 0, 40):
                p.save()
                p.translate(0, -36)
                p.rotate(a)
                p.drawEllipse(QPointF(0, -2), 2.4, 5)
                p.restore()
            p.setPen(outline)
            p.setBrush(body_c)
            p.drawEllipse(QPointF(-14, -26), 7, 6)
            p.drawEllipse(QPointF(14, -26), 7, 6)
            return
        if st in (STRETCH, DRAG, CELEBRATE):
            raise_k = 1.0 if st != STRETCH else math.sin(min(1.0, ctx.state_time / 2.0) * math.pi)
            for side in (-1, 1):
                p.drawEllipse(QPointF(side * (50 + 4 * raise_k), -40 - 26 * raise_k), 8, 7)
            return
        if st == GREET:
            wave = math.sin(ctx.state_time * 12) * 18
            p.drawEllipse(QPointF(-48, -30), 8, 7)
            p.save()
            p.translate(50, -48)
            p.rotate(-30 + wave)
            p.drawEllipse(QPointF(0, -14), 8, 7)
            p.restore()
            return
        p.drawEllipse(QPointF(-47, -30), 8, 7)
        p.drawEllipse(QPointF(47, -30), 8, 7)

    # ---- 配件 ----
    @staticmethod
    def _draw_bow(p: QPainter) -> None:
        p.save()
        p.translate(30, -84)
        p.rotate(18)
        p.setPen(QPen(QColor("#C2185B"), 1.6))
        p.setBrush(QColor("#FF5C8A"))
        for side in (-1, 1):
            wing = QPainterPath(QPointF(0, 0))
            wing.lineTo(side * 13, -8)
            wing.quadTo(QPointF(side * 16, 0), QPointF(side * 13, 8))
            wing.closeSubpath()
            p.drawPath(wing)
        p.drawEllipse(QPointF(0, 0), 3.6, 3.6)
        p.restore()

    @staticmethod
    def _draw_hat(p: QPainter) -> None:
        p.save()
        p.translate(0, -88)
        p.setPen(QPen(QColor("#3949AB"), 1.6))
        p.setBrush(QColor("#5C6BC0"))
        hat = QPainterPath(QPointF(-15, 0))
        hat.lineTo(0, -28)
        hat.lineTo(15, 0)
        hat.closeSubpath()
        p.drawPath(hat)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFD54F"))
        for y, half in ((-8, 9.6), (-17, 5.6)):
            p.drawRect(QRectF(-half, y - 1.5, half * 2, 3))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(0, -29), 4, 4)
        p.restore()

    @staticmethod
    def _draw_scarf(p: QPainter) -> None:
        p.setPen(QPen(QColor("#B71C1C"), 1.4))
        p.setBrush(QColor("#E53935"))
        band = QPainterPath(QPointF(-40, -24))
        band.quadTo(QPointF(0, -10), QPointF(40, -24))
        band.lineTo(QPointF(38, -16))
        band.quadTo(QPointF(0, -2), QPointF(-38, -16))
        band.closeSubpath()
        p.drawPath(band)
        p.drawRoundedRect(QRectF(16, -18, 9, 18), 3, 3)
        p.setPen(QPen(QColor("#FFCDD2"), 1.4))
        for x in (-20, 0, 20):
            p.drawLine(QPointF(x, -20 + abs(x) * 0.18), QPointF(x + 4, -12 + abs(x) * 0.18))

    # ---- 點擊判定 ----
    def hit_test(self, pt: QPointF, ctx: RenderContext) -> bool:
        cx, cy = CANVAS_W / 2, FEET_Y + BODY_CY
        nx = (pt.x() - cx) / (BODY_RX + 8)
        ny = (pt.y() - cy) / (BODY_RY + 14)
        return nx * nx + ny * ny <= 1.0
