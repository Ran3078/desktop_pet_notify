"""桌寵主視窗：無邊框、置頂、透明背景；處理拖曳、點擊、動畫、移動與泡泡。

沒有重力：拖到哪裡就停在哪裡（只限制不超出螢幕）。

點擊穿透：視窗是 Windows 分層視窗（WA_TranslucentBackground），完全透明的像素本來就不會攔截滑鼠，
所以周圍空白處可以直接點到下面的視窗；不透明但不屬於身體的區域（特效、小牌）會忽略點擊。
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QMenu, QWidget

from ..reminders.notifier import Notification
from .behavior import BehaviorInput, PetBehavior
from .bubble import Bubble
from . import physics
from .physics import Bounds
from .skins.base import ANGRY, CANVAS_H, CANVAS_W, CELEBRATE, FEET_Y, GREET, WALK, RenderContext, Skin
from .skins.registry import load_skin

log = logging.getLogger(__name__)

FAST_INTERVAL_MS = 33   # ~30 fps
SLOW_INTERVAL_MS = 100  # ~10 fps
DRAG_THRESHOLD = 4
EYE_Y = FEET_Y - 54



def _priority(n: Notification) -> int:
    """泡泡優先度：活動提醒 > 其他通知 > 閒聊。"""
    return {"event": 2, "chat": 0}.get(n.kind, 1)


class PetWindow(QWidget):
    settings_requested = Signal()
    sync_requested = Signal()
    pomodoro_toggle_requested = Signal()
    upcoming_requested = Signal()
    hide_requested = Signal()
    quit_requested = Signal()
    petted = Signal()

    def __init__(self, config, badge_provider: Callable[[], tuple[str, str, float] | None],
                 pomodoro_focus: Callable[[], bool], pomodoro_running: Callable[[], bool]):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Desktop Pet")

        self._config = config
        self._badge_provider = badge_provider
        self._pomodoro_focus = pomodoro_focus
        self._pomodoro_running = pomodoro_running

        self.skin: Skin = load_skin(config.settings.skin)
        self.behavior = PetBehavior()
        self._ctx = RenderContext()
        self._scale = config.settings.pet_scale
        self._x = 0.0
        self._y = 0.0
        self._last_frame = time.monotonic()
        self._clock = 0.0
        self._next_blink = self._clock + random.uniform(2, 5)
        self._blink_until = 0.0
        self._sleepy_cache: tuple[float, bool] = (0.0, False)

        # 拖曳
        self._press_pos: QPoint | None = None
        self._press_offset = QPointF()
        self._dragging = False

        # 泡泡
        self.bubble = Bubble()
        self.bubble.closed.connect(self._on_bubble_closed)
        self._bubble_queue: list[Notification] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._frame)

        self._apply_size()
        self._restore_position()
        config.changed.connect(self._on_config)

    # ---- 尺寸與位置 ----
    def _apply_size(self) -> None:
        self._scale = self._config.settings.pet_scale
        self.setFixedSize(round(CANVAS_W * self._scale), round(CANVAS_H * self._scale))

    def _restore_position(self) -> None:
        s = self._config.settings
        if s.pos_x is not None and s.pos_y is not None and QGuiApplication.screenAt(QPoint(s.pos_x + self.width() // 2, s.pos_y + self.height() // 2)):
            self._x, self._y = float(s.pos_x), float(s.pos_y)
        else:
            avail = QGuiApplication.primaryScreen().availableGeometry()
            self._x = float(avail.right() - self.width() - 80)
            self._y = float(avail.bottom() + 1 - self.height())  # 預設站在工作列上
        self._x, self._y = physics.clamp(self._x, self._y, self._bounds())
        self.move(round(self._x), round(self._y))

    def save_position(self) -> None:
        self._config.update(pos_x=round(self._x), pos_y=round(self._y))

    def _bounds(self, at: QPoint | None = None) -> Bounds:
        """桌寵可以移動的範圍：at（預設為桌寵中心）所在螢幕的可用區域，不含工作列。"""
        center = at or QPoint(round(self._x + self.width() / 2), round(self._y + self.height() / 2))
        screen = QGuiApplication.screenAt(center) or self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = self.width(), self.height()
        inset = self.skin.edge_inset * self._scale  # 畫布兩側的透明留白可以超出螢幕
        return Bounds(left=avail.left() - inset, right=avail.right() + 1 - w + inset,
                      top=avail.top(), bottom=avail.bottom() + 1 - h)

    def head_anchor(self) -> QPoint:
        """泡泡尾巴要指向的全域座標（頭頂上方）。"""
        head_y = FEET_Y - 100
        return QPoint(round(self._x + CANVAS_W / 2 * self._scale), round(self._y + head_y * self._scale))

    # ---- 設定 ----
    def _on_config(self, keys: set) -> None:
        if "pet_size" in keys:
            old_h = self.height()
            self._apply_size()
            self._y += old_h - self.height()  # 保持腳底位置
            self.move(round(self._x), round(self._y))
        if "skin" in keys:
            self.skin = load_skin(self._config.settings.skin)
        if keys & {"pet_size", "skin", "color", "accessory"}:
            self.update()

    # ---- 顯示 / 隱藏 ----
    def showEvent(self, event) -> None:
        self._last_frame = time.monotonic()
        self._timer.start(FAST_INTERVAL_MS)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        self.bubble.hide()
        super().hideEvent(event)

    # ---- 每幀 ----
    def _is_sleepy(self) -> bool:
        now = time.monotonic()
        if now - self._sleepy_cache[0] > 30:
            hour = datetime.now().hour
            sleepy = self._config.settings.night_sleep and (hour >= 23 or hour < 6)
            self._sleepy_cache = (now, sleepy)
        return self._sleepy_cache[1]

    def _frame(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self._last_frame)
        self._last_frame = now
        self._clock += dt

        b = self.behavior
        b.update(dt, BehaviorInput(
            dragging=self._dragging,
            walk_enabled=self._config.settings.walk_enabled,
            sleepy=self._is_sleepy(),
            pomodoro_focus=self._pomodoro_focus(),
        ))

        if not self._dragging:
            walk = b.facing if b.state == WALK else 0
            nx, ny, new_dir = physics.step(self._x, self._y, dt, self._bounds(), walk)
            if walk and new_dir != walk:
                b.facing = new_dir
            if (nx, ny) != (self._x, self._y):
                self._x, self._y = nx, ny
                self.move(round(nx), round(ny))
                if self.bubble.isVisible():
                    self.bubble.reposition(self.head_anchor())

        if self._clock >= self._next_blink:
            self._blink_until = self._clock + 0.14
            self._next_blink = self._clock + random.uniform(2.5, 6)

        self._update_ctx()
        self.update()

        interval = FAST_INTERVAL_MS if b.is_fast else SLOW_INTERVAL_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _update_ctx(self) -> None:
        s = self._config.settings
        c = self._ctx
        c.state = self.behavior.state
        c.state_time = self.behavior.state_time
        c.clock = self._clock
        c.facing = self.behavior.facing
        c.blink = self._clock < self._blink_until
        c.lifted = self._dragging  # 拎起來時不畫腳下的影子
        c.urgency = self.behavior.urgency
        c.color = s.color
        c.accessory = s.accessory

        cursor = QCursor.pos()
        ex = self._x + CANVAS_W / 2 * self._scale
        ey = self._y + EYE_Y * self._scale
        dx, dy = cursor.x() - ex, cursor.y() - ey
        c.look = (dx / (abs(dx) + 90), dy / (abs(dy) + 90))

        badge = self._badge_provider()
        if badge:
            c.badge, c.badge_kind, urgency = badge
            if c.badge_kind == "event":
                c.urgency = max(c.urgency, urgency)
        else:
            c.badge = None

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self._scale, self._scale)
        try:
            self.skin.draw(p, self._ctx)
        except Exception:
            log.exception("繪製桌寵失敗，改用內建皮膚")
            from .skins.painter_skin import PainterSkin

            self.skin = PainterSkin()

    # ---- 滑鼠 ----
    def _hit(self, pos: QPointF) -> bool:
        return self.skin.hit_test(QPointF(pos.x() / self._scale, pos.y() / self._scale), self._ctx)

    def mousePressEvent(self, event) -> None:
        if not self._hit(event.position()):
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_offset = event.position()
            self._dragging = False
        elif event.button() == Qt.RightButton:
            self._show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            return
        gpos = event.globalPosition()
        if not self._dragging and (gpos.toPoint() - self._press_pos).manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
        if self._dragging:
            # 跟著滑鼠走，但不超出滑鼠所在螢幕的可用範圍
            x, y = gpos.x() - self._press_offset.x(), gpos.y() - self._press_offset.y()
            self._x, self._y = physics.clamp(x, y, self._bounds(at=gpos.toPoint()))
            self.move(round(self._x), round(self._y))
            if self.bubble.isVisible():
                self.bubble.reposition(self.head_anchor())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._press_pos is None:
            return
        self._press_pos = None
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self.save_position()
            log.debug("放開桌寵，位置 (%.0f, %.0f)", self._x, self._y)
        else:
            result = self.behavior.on_click()
            if result == ANGRY:
                self.say("哼！不要一直戳我啦！", 3)
            else:
                self.petted.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._hit(event.position()):
            self.upcoming_requested.emit()

    def _show_menu(self, pos: QPoint) -> None:
        menu = QMenu()
        menu.addAction("開啟設定器", self.settings_requested.emit)
        menu.addAction("看看接下來的行程", self.upcoming_requested.emit)
        menu.addAction("立即同步行事曆", self.sync_requested.emit)
        menu.addSeparator()
        label = "停止番茄鐘" if self._pomodoro_running() else "開始番茄鐘"
        menu.addAction(label, self.pomodoro_toggle_requested.emit)
        menu.addSeparator()
        hide = QAction("隱藏桌寵", menu)
        hide.triggered.connect(self.hide_requested.emit)
        menu.addAction(hide)
        menu.addAction("結束", self.quit_requested.emit)
        menu.exec(pos)

    # ---- 動作 ----
    def greet(self) -> None:
        self.behavior.react(GREET, 2.5)

    def celebrate(self) -> None:
        self.behavior.react(CELEBRATE, 3.5)

    def say(self, text: str, seconds: int = 4, title: str = "") -> None:
        """閒聊泡泡：如果正在顯示重要通知，就直接略過。"""
        if self.bubble.isVisible() and self.bubble.notification and self.bubble.notification.kind != "chat":
            return
        self._show_bubble(Notification(kind="chat", title=title, text=text, sound=False, timeout_s=seconds))

    def show_notification(self, n: Notification) -> None:
        if n.kind == "event":
            self.behavior.start_alert(n.urgency)
        current = self.bubble.notification if self.bubble.isVisible() else None
        if current is None or current.kind == "chat":
            self._show_bubble(n)
        elif _priority(n) > _priority(current):
            # 活動提醒比午餐、喝水等一般通知重要：先顯示，被擠掉的排回佇列最前面
            self._bubble_queue.insert(0, current)
            self._show_bubble(n)
        else:
            # 同優先度依序排隊，但活動提醒排在一般通知前面
            index = next((i for i, q in enumerate(self._bubble_queue) if _priority(q) < _priority(n)),
                         len(self._bubble_queue))
            self._bubble_queue.insert(index, n)

    def _show_bubble(self, n: Notification) -> None:
        if not self.isVisible():
            return
        self.bubble.show_notification(n, self.head_anchor())

    def _on_bubble_closed(self, n: Notification) -> None:
        if self._bubble_queue:
            self._show_bubble(self._bubble_queue.pop(0))
        has_event = any(q.kind == "event" for q in self._bubble_queue) or (
            self.bubble.isVisible() and self.bubble.notification and self.bubble.notification.kind == "event"
        )
        if not has_event:
            self.behavior.stop_alert()

    def dismiss_all(self) -> None:
        self._bubble_queue.clear()
        self.bubble.dismiss()
        self.behavior.stop_alert()

