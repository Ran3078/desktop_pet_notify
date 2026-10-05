"""番茄鐘狀態機。"""
from __future__ import annotations

import logging
import time
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)


class Phase(Enum):
    IDLE = "idle"
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


PHASE_LABEL = {
    Phase.IDLE: "",
    Phase.FOCUS: "專注",
    Phase.SHORT_BREAK: "休息",
    Phase.LONG_BREAK: "長休息",
}


class Pomodoro(QObject):
    phase_changed = Signal(object)           # Phase
    phase_finished = Signal(object, object)  # 結束的 Phase, 下一個 Phase

    def __init__(self, config):
        super().__init__()
        self._config = config
        self.phase = Phase.IDLE
        self.round = 0
        self._ends_at = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        return self.phase != Phase.IDLE

    def remaining_seconds(self) -> int:
        return max(0, int(round(self._ends_at - time.monotonic()))) if self.running else 0

    def _duration(self, phase: Phase) -> int:
        s = self._config.settings
        minutes = {
            Phase.FOCUS: s.pomodoro_focus,
            Phase.SHORT_BREAK: s.pomodoro_short_break,
            Phase.LONG_BREAK: s.pomodoro_long_break,
        }[phase]
        return max(1, int(minutes)) * 60

    def start(self) -> None:
        self.round = 0
        self._enter(Phase.FOCUS)
        log.info("番茄鐘開始")

    def stop(self) -> None:
        self._timer.stop()
        self.phase = Phase.IDLE
        self.phase_changed.emit(self.phase)
        log.info("番茄鐘停止")

    def skip(self) -> None:
        if self.running:
            self._finish()

    def _enter(self, phase: Phase) -> None:
        self.phase = phase
        self._ends_at = time.monotonic() + self._duration(phase)
        self._timer.start(1000)
        self.phase_changed.emit(phase)

    def _tick(self) -> None:
        if self.remaining_seconds() <= 0:
            self._finish()

    def _finish(self) -> None:
        done = self.phase
        if done == Phase.FOCUS:
            self.round += 1
            rounds = max(1, int(self._config.settings.pomodoro_rounds))
            nxt = Phase.LONG_BREAK if self.round % rounds == 0 else Phase.SHORT_BREAK
        else:
            nxt = Phase.FOCUS
        log.info("番茄鐘：%s 結束 → %s（第 %d 輪）", done.value, nxt.value, self.round)
        self._enter(nxt)
        self.phase_finished.emit(done, nxt)
