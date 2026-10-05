"""圖片皮膚：讀取 skin.json + sprite sheet。

skin.json 範例：
{
  "name": "我的桌寵",
  "frame_size": [128, 128],
  "sheet": "sheet.png",
  "flip_when_left": true,
  "states": {
    "idle":  {"row": 0, "frames": 4, "fps": 6},
    "walk":  {"row": 1, "frames": 4, "fps": 8},
    "happy": {"row": 2, "frames": 4, "fps": 8}
  }
}
每個狀態佔 sheet 的一列（row），從左到右依序是各影格。沒定義的狀態會退回相近的狀態，最後退回 idle。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage, QPainter, QTransform

from . import overlays
from .base import CANVAS_W, FEET_Y, RenderContext, Skin

log = logging.getLogger(__name__)

FALLBACK = {
    "celebrate": "happy",
    "greet": "happy",
    "drag": "alert",
    "pomodoro": "sit",
    "stretch": "idle",
    "yawn": "sleep",
}

HEAD_ROOM = 34  # 畫布上方保留給倒數小牌與特效的空間


class SpriteSkin(Skin):
    supports_customization = False

    def __init__(self, folder: Path):
        manifest = json.loads((folder / "skin.json").read_text(encoding="utf-8"))
        self.id = f"dir:{folder.name}"
        self.name = manifest.get("name", folder.name)
        self._flip = bool(manifest.get("flip_when_left", True))
        fw, fh = manifest["frame_size"]
        sheet = QImage(str(folder / manifest["sheet"]))
        if sheet.isNull():
            raise ValueError(f"無法讀取 sprite sheet：{folder / manifest['sheet']}")
        sheet = sheet.convertToFormat(QImage.Format_ARGB32_Premultiplied)

        self._frames: dict[str, tuple[list[QImage], float]] = {}
        for state, spec in manifest["states"].items():
            row, count, fps = int(spec["row"]), int(spec["frames"]), float(spec.get("fps", 6))
            frames = [sheet.copy(QRect(i * fw, row * fh, fw, fh)) for i in range(count)]
            self._frames[state] = (frames, fps)
        if "idle" not in self._frames:
            raise ValueError("skin.json 必須定義 idle 狀態")

        # 依畫布可用空間等比例縮放，腳底對齊 FEET_Y
        scale = min(CANVAS_W / fw, (FEET_Y + 4 - HEAD_ROOM) / fh)
        w, h = fw * scale, fh * scale
        self._target = QRectF(CANVAS_W / 2 - w / 2, FEET_Y + 4 - h, w, h)
        self.edge_inset = self._target.left()
        log.info("載入圖片皮膚：%s（%d 個狀態）", self.name, len(self._frames))

    def _resolve(self, state: str) -> str:
        seen = set()
        while state not in self._frames and state not in seen:
            seen.add(state)
            state = FALLBACK.get(state, "idle")
        return state if state in self._frames else "idle"

    def _frame(self, ctx: RenderContext) -> QImage:
        frames, fps = self._frames[self._resolve(ctx.state)]
        idx = int(ctx.state_time * fps) % len(frames)
        img = frames[idx]
        if ctx.facing < 0 and self._flip:
            img = img.transformed(QTransform().scale(-1, 1))
        return img

    def draw(self, p: QPainter, ctx: RenderContext) -> None:
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(self._target, self._frame(ctx))
        head_top = self._target.top() + 6
        overlays.draw_effects(p, ctx, head_top)
        overlays.draw_badge(p, ctx, head_top)

    def hit_test(self, pt: QPointF, ctx: RenderContext) -> bool:
        if not self._target.contains(pt):
            return False
        img = self._frame(ctx)
        x = int((pt.x() - self._target.left()) / self._target.width() * img.width())
        y = int((pt.y() - self._target.top()) / self._target.height() * img.height())
        if not (0 <= x < img.width() and 0 <= y < img.height()):
            return False
        return img.pixelColor(x, y).alpha() > 40

