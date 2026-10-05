"""通知中心：所有提醒都經過這裡，依照不打擾規則決定要顯示、延後或只發系統匣通知。"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from ..cal.models import local_now
from .gatekeeper import Environment, Route, decide

log = logging.getLogger(__name__)


@dataclass
class Notification:
    kind: str                     # event / health / pomodoro / brief / level
    title: str
    text: str
    buttons: list[tuple[str, Callable[[], None]]] = field(default_factory=list)
    sound: bool = True
    urgency: float = 0.0          # 0~1，越高桌寵越急
    expires_at: datetime | None = None
    timeout_s: int = 20           # 泡泡自動消失秒數，0 = 等使用者按
    toast: bool = False           # 顯示泡泡時是否同時發系統匣通知
    on_dismiss: Callable[[], None] | None = None
    toast_sent: bool = False


class NotificationCenter(QObject):
    present = Signal(object)      # Notification → 桌寵泡泡
    toast = Signal(str, str)      # 標題, 內容 → 系統匣通知

    def __init__(self, config, probe, sound, pet_visible: Callable[[], bool]):
        super().__init__()
        self._config = config
        self._probe = probe
        self._sound = sound
        self._pet_visible = pet_visible
        self._queue: list[Notification] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._process_queue)
        self._timer.start(3000)

    def environment(self) -> Environment:
        return Environment(
            now=local_now(),
            fullscreen=self._probe.foreground_is_fullscreen(),
            idle_seconds=self._probe.idle_seconds(),
        )

    def current_route(self) -> Route:
        return decide(self._config.settings, self.environment())

    def submit(self, n: Notification) -> None:
        route = self.current_route()
        log.info("通知 [%s] %s → %s", n.kind, n.title, route.value)
        self._route(n, route)

    def _route(self, n: Notification, route: Route) -> bool:
        """處理一則通知；回傳 True 表示已處理完、不需留在佇列。"""
        if route == Route.SHOW:
            self._show(n)
            return True
        if route == Route.QUIET:
            self.toast.emit(n.title, n.text)
            return True
        if route == Route.FULLSCREEN:
            if not n.toast_sent:
                self.toast.emit(n.title, n.text)
                n.toast_sent = True
        if n not in self._queue:
            self._queue.append(n)
        return False

    def _show(self, n: Notification) -> None:
        visible = self._pet_visible()
        if n.sound and not n.toast_sent:
            self._sound.play()
        if visible:
            self.present.emit(n)
        if (n.toast or not visible) and not n.toast_sent:
            self.toast.emit(n.title, n.text)

    def _process_queue(self) -> None:
        if not self._queue:
            return
        now = local_now()
        self._queue = [n for n in self._queue if n.expires_at is None or n.expires_at > now]
        if not self._queue:
            return
        route = self.current_route()
        remaining = []
        for n in self._queue:
            if not self._route_from_queue(n, route):
                remaining.append(n)
        self._queue = remaining

    def _route_from_queue(self, n: Notification, route: Route) -> bool:
        if route in (Route.SHOW, Route.QUIET):
            log.info("補發延後的通知 [%s] %s → %s", n.kind, n.title, route.value)
        if route == Route.SHOW:
            self._show(n)
            return True
        if route == Route.QUIET:
            if not n.toast_sent:
                self.toast.emit(n.title, n.text)
            return True
        if route == Route.FULLSCREEN and not n.toast_sent:
            self.toast.emit(n.title, n.text)
            n.toast_sent = True
        return False
