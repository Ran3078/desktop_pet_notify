"""桌寵行為狀態機。

優先順序：拖曳 > 反應（開心 / 生氣 / 慶祝 / 打招呼）> 提醒 > 睡覺 > 番茄鐘 > 日常閒晃。
"""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass

from .skins.base import (
    ALERT, ANGRY, CELEBRATE, DRAG, GREET, HAPPY, IDLE, POMODORO, SIT, SLEEP, STRETCH, WALK, YAWN,
)

REACTIONS = {HAPPY, ANGRY, CELEBRATE, GREET}
AMBIENT = {IDLE, WALK, SIT, STRETCH, YAWN}
FAST_STATES = {WALK, DRAG, HAPPY, ANGRY, ALERT, CELEBRATE, GREET, STRETCH, YAWN}

ANGRY_CLICKS = 5
ANGRY_WINDOW = 2.0
ALERT_ANIM_MAX = 30.0  # 提醒動畫最長秒數（之後安靜等待，節省 CPU）


@dataclass
class BehaviorInput:
    dragging: bool = False
    walk_enabled: bool = True
    sleepy: bool = False
    pomodoro_focus: bool = False


class PetBehavior:
    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self.state = IDLE
        self.state_time = 0.0
        self.facing = 1
        self.urgency = 0.0
        self._reaction_left = 0.0
        self._ambient_left = self._rng.uniform(2, 5)
        self._alert_active = False
        self._alert_time = 0.0
        self._clicks: deque[float] = deque()

    # ---- 外部事件 ----
    def on_click(self) -> str:
        now = time.monotonic()
        self._clicks.append(now)
        while self._clicks and now - self._clicks[0] > ANGRY_WINDOW:
            self._clicks.popleft()
        if len(self._clicks) >= ANGRY_CLICKS:
            self._clicks.clear()
            self.react(ANGRY, 3.0)
            return ANGRY
        if self.state != ANGRY:
            self.react(HAPPY, 1.6)
        return self.state

    def react(self, state: str, seconds: float) -> None:
        self._reaction_left = seconds
        self._set(state)

    def start_alert(self, urgency: float) -> None:
        self._alert_active = True
        self._alert_time = 0.0
        self.urgency = max(0.0, min(1.0, urgency))

    def stop_alert(self) -> None:
        self._alert_active = False

    @property
    def is_fast(self) -> bool:
        return self.state in FAST_STATES

    # ---- 每幀更新 ----
    def update(self, dt: float, inp: BehaviorInput) -> None:
        self.state_time += dt
        if self._alert_active:
            self._alert_time += dt

        if inp.dragging:
            self._set(DRAG)
            return
        if self._reaction_left > 0:
            self._reaction_left -= dt
            if self._reaction_left > 0:
                return
        if self._alert_active and self._alert_time < ALERT_ANIM_MAX:
            self._set(ALERT)
            return
        if inp.sleepy:
            self._set(SLEEP)
            return
        if inp.pomodoro_focus:
            self._set(POMODORO)
            return
        self._ambient(dt, inp)

    def _ambient(self, dt: float, inp: BehaviorInput) -> None:
        if self.state not in AMBIENT:
            self._set(IDLE)
            self._ambient_left = self._rng.uniform(1.5, 4)
            return
        if self.state == WALK and not inp.walk_enabled:
            self._set(IDLE)
        self._ambient_left -= dt
        if self._ambient_left > 0:
            return
        choices = [(IDLE, 30), (SIT, 15), (STRETCH, 10), (YAWN, 10)]
        if inp.walk_enabled:
            choices.append((WALK, 35))
        states, weights = zip(*choices)
        nxt = self._rng.choices(states, weights=weights)[0]
        durations = {IDLE: (3, 8), WALK: (2, 5), SIT: (5, 10), STRETCH: (2, 2), YAWN: (2, 2)}
        lo, hi = durations[nxt]
        self._ambient_left = self._rng.uniform(lo, hi)
        if nxt == WALK:
            self.facing = self._rng.choice((-1, 1))
        self._set(nxt, force=True)

    def _set(self, state: str, force: bool = False) -> None:
        if state != self.state or force:
            self.state = state
            self.state_time = 0.0
