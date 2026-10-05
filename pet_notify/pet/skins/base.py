"""皮膚介面與繪製時的上下文。

座標系：畫布邏輯尺寸 CANVAS_W × CANVAS_H（縮放前）；腳底在 (CANVAS_W/2, FEET_Y)。
pet_window 會先用 painter.scale(s, s) 再呼叫 skin.draw()，所以 skin 只需處理基準尺寸。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter

CANVAS_W = 160
CANVAS_H = 172
FEET_Y = 166


# 行為狀態
IDLE = "idle"
WALK = "walk"
SIT = "sit"
STRETCH = "stretch"
YAWN = "yawn"
DRAG = "drag"
HAPPY = "happy"
ANGRY = "angry"
ALERT = "alert"
SLEEP = "sleep"
POMODORO = "pomodoro"
CELEBRATE = "celebrate"
GREET = "greet"

ALL_STATES = [IDLE, WALK, SIT, STRETCH, YAWN, DRAG, HAPPY, ANGRY, ALERT, SLEEP, POMODORO, CELEBRATE, GREET]


@dataclass
class RenderContext:
    state: str = IDLE
    state_time: float = 0.0      # 進入此狀態後經過秒數
    clock: float = 0.0           # 全域時間（秒）
    look: tuple[float, float] = (0.0, 0.0)  # 視線方向，-1~1
    facing: int = 1              # 1 朝右、-1 朝左
    blink: bool = False
    lifted: bool = False         # 被拎起來（不畫腳下影子）
    urgency: float = 0.0         # 0~1，提醒急迫程度
    color: str = "cream"
    accessory: str = "none"
    badge: str | None = None     # 頭上小牌文字（倒數 / 番茄鐘）
    badge_kind: str = "event"    # event / pomodoro


class Skin(ABC):
    id: str = ""
    name: str = ""
    supports_customization: bool = False  # 是否支援配色與配件
    edge_inset: float = 0.0  # 畫布兩側透明留白的寬度，讓身體可以貼齊螢幕邊緣

    @abstractmethod
    def draw(self, p: QPainter, ctx: RenderContext) -> None: ...

    @abstractmethod
    def hit_test(self, pt: QPointF, ctx: RenderContext) -> bool:
        """pt 為畫布座標（縮放前）。只有回傳 True 的位置可以拖曳或點擊。"""
