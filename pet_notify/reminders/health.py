"""健康提醒：喝水、起來伸展。"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

AWAY_RESET_SECONDS = 5 * 60  # 使用者離開超過 5 分鐘，回來後重新計時

MESSAGES = {
    "water": ("喝水時間", "喝口水吧！補充水分精神更好～"),
    "stretch": ("伸展一下", "坐好久了，站起來伸伸懶腰吧！"),
}


class HealthReminder(QObject):
    remind = Signal(str)  # kind

    def __init__(self, config, probe, is_sleeping):
        super().__init__()
        self._config = config
        self._probe = probe
        self._is_sleeping = is_sleeping
        now = time.monotonic()
        self._last = {"water": now, "stretch": now}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        config.changed.connect(self._on_config)

    def start(self) -> None:
        self._timer.start(30_000)

    def _on_config(self, keys: set) -> None:
        now = time.monotonic()
        for kind in ("water", "stretch"):
            if {f"{kind}_enabled", f"{kind}_interval"} & keys:
                self._last[kind] = now

    def _tick(self) -> None:
        now = time.monotonic()
        if self._probe.idle_seconds() >= AWAY_RESET_SECONDS:
            self._last = {k: now for k in self._last}
            return
        if self._is_sleeping():
            return
        s = self._config.settings
        for kind, enabled, interval in (
            ("water", s.water_enabled, s.water_interval),
            ("stretch", s.stretch_enabled, s.stretch_interval),
        ):
            if enabled and now - self._last[kind] >= max(1, int(interval)) * 60:
                self._last[kind] = now
                log.info("健康提醒：%s", kind)
                self.remind.emit(kind)
