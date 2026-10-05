"""移動：在目前高度左右散步，並把桌寵限制在螢幕可用範圍內。座標為 Qt 邏輯座標（視窗左上角）。

沒有重力：拖到哪裡就停在哪裡。
"""
from __future__ import annotations

from dataclasses import dataclass

WALK_SPEED = 42.0  # px/s


@dataclass
class Bounds:
    left: float     # 視窗左上角 x 的最小值（已扣掉畫布兩側透明留白，身體會剛好貼齊螢幕邊緣）
    right: float    # 視窗左上角 x 的最大值
    top: float      # 視窗左上角 y 的最小值
    bottom: float   # 視窗左上角 y 的最大值（腳底貼齊工作列上緣）


def clamp(x: float, y: float, b: Bounds) -> tuple[float, float]:
    return max(b.left, min(x, b.right)), max(b.top, min(y, b.bottom))


def step(x: float, y: float, dt: float, b: Bounds, walk_dir: int = 0) -> tuple[float, float, int]:
    """回傳 (新 x, 新 y, 新的行走方向)。走到螢幕邊緣會轉向。"""
    x, y = clamp(x, y, b)
    if walk_dir:
        x += walk_dir * WALK_SPEED * dt
        if x <= b.left:
            x, walk_dir = b.left, 1
        elif x >= b.right:
            x, walk_dir = b.right, -1
    return x, y, walk_dir
