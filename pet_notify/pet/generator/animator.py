"""把一張去背後的角色圖做成各狀態的動畫影格（縮放、位移、旋轉、色調）。

影格是 FRAME×FRAME 的透明圖，角色腳底對齊影格底部中央，上方保留跳躍空間。
愛心、zzz、驚嘆號等特效由桌寵程式另外疊加，不畫進影格。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

FRAME = 200
MAX_W = 170        # 角色在影格內的最大寬度
MAX_H = 150        # 最大高度（上方留 ~50px 給跳躍）
BOTTOM_MARGIN = 4


@dataclass(frozen=True)
class Pose:
    sx: float = 1.0
    sy: float = 1.0
    dx: float = 0.0
    dy: float = 0.0       # 負值＝往上
    rot: float = 0.0      # 度
    tint: str = ""        # 疊色（例如生氣的紅色）
    tint_alpha: int = 0


def _wave(i: int, n: int) -> float:
    return math.sin(2 * math.pi * i / n)


def _hop(i: int, n: int) -> float:
    return abs(math.sin(math.pi * i / n))


# 狀態 → (fps, 每一格的 Pose)
def _states() -> dict[str, tuple[float, list[Pose]]]:
    def frames(n, fn):
        return [fn(i, n) for i in range(n)]

    return {
        "idle": (4, frames(4, lambda i, n: Pose(sx=1 - 0.015 * _wave(i, n), sy=1 + 0.025 * _wave(i, n)))),
        "walk": (8, frames(6, lambda i, n: Pose(dy=-6 * _hop(i, n / 2), rot=6 * _wave(i, n)))),
        "sit": (1, [Pose(sx=1.06, sy=0.9)]),
        "stretch": (5, frames(4, lambda i, n: Pose(sx=1 - 0.05 * _hop(i, n), sy=1 + 0.1 * _hop(i, n)))),
        "yawn": (3, frames(4, lambda i, n: Pose(rot=4 * _wave(i, n), sy=1 - 0.02 * _hop(i, n)))),
        "drag": (6, frames(4, lambda i, n: Pose(sx=0.95, sy=1.08, rot=8 * _wave(i, n)))),
        "happy": (8, frames(4, lambda i, n: Pose(dy=-14 * _hop(i, n), sy=1 + 0.03 * _hop(i, n)))),
        "angry": (12, frames(4, lambda i, n: Pose(dx=4 * _wave(i, n), sx=1.04, sy=0.97,
                                                   tint="#FF3B30", tint_alpha=70))),
        "alert": (10, frames(4, lambda i, n: Pose(dy=-26 * _hop(i, n), sx=1 - 0.04 * _hop(i, n),
                                                   sy=1 + 0.06 * _hop(i, n)))),
        "sleep": (1, frames(2, lambda i, n: Pose(sx=1.05, sy=0.92 - 0.02 * i, rot=-5,
                                                  tint="#1A2340", tint_alpha=55))),
        "pomodoro": (2, frames(2, lambda i, n: Pose(sy=1 + 0.015 * _wave(i, n)))),
        "celebrate": (8, frames(6, lambda i, n: Pose(dy=-30 * _hop(i, n), rot=360 * i / n))),
        "greet": (6, frames(4, lambda i, n: Pose(rot=10 * _wave(i, n)))),
    }


STATES = _states()


def fit_size(img: QImage) -> tuple[float, float]:
    """角色縮放後在影格內的寬高（等比例）。"""
    scale = min(MAX_W / img.width(), MAX_H / img.height())
    return img.width() * scale, img.height() * scale


def _tinted(img: QImage, color: str, alpha: int) -> QImage:
    out = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceAtop)  # 只染在角色上，不影響透明區
    c = QColor(color)
    c.setAlpha(alpha)
    p.fillRect(out.rect(), c)
    p.end()
    return out


def render_frame(img: QImage, pose: Pose) -> QImage:
    frame = QImage(FRAME, FRAME, QImage.Format_ARGB32_Premultiplied)
    frame.fill(Qt.transparent)
    source = _tinted(img, pose.tint, pose.tint_alpha) if pose.tint else img
    w, h = fit_size(img)
    p = QPainter(frame)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.Antialiasing)
    # 以「腳底中心」為原點縮放 / 旋轉，壓扁時腳不會離地
    p.translate(QPointF(FRAME / 2 + pose.dx, FRAME - BOTTOM_MARGIN + pose.dy))
    if pose.rot:
        # 旋轉中心改到身體中間，看起來比較自然
        p.translate(0, -h / 2)
        p.rotate(pose.rot)
        p.translate(0, h / 2)
    p.scale(pose.sx, pose.sy)
    p.drawImage(QRectF(-w / 2, -h, w, h), source)
    p.end()
    return frame


def animate(img: QImage) -> dict[str, tuple[float, list[QImage]]]:
    """回傳 {狀態: (fps, [影格...])}。"""
    return {state: (fps, [render_frame(img, pose) for pose in poses]) for state, (fps, poses) in STATES.items()}
