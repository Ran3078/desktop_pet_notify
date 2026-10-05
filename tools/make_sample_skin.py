"""產生範例圖片皮膚 assets/skins/sample/（sheet.png + skin.json）。

示範 sprite sheet 格式：用內建畫法輸出成圖片，換成你自己的手繪圖時照著同樣的格式排列即可。
執行：.venv\\Scripts\\python tools\\make_sample_skin.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402

from pet_notify.pet.skins import overlays  # noqa: E402
from pet_notify.pet.skins.base import CANVAS_H, CANVAS_W, RenderContext  # noqa: E402
from pet_notify.pet.skins.painter_skin import PainterSkin  # noqa: E402

CROP = QRect(10, 52, 140, 120)  # 只取身體範圍（頭頂特效由程式另外畫）
STATES = {
    # 狀態: (影格數, fps, 每格的 RenderContext 參數)
    "idle": (4, 4, lambda i: dict(clock=i * 0.65, blink=i == 3)),
    "walk": (4, 8, lambda i: dict(clock=i * 0.087)),
    "happy": (4, 8, lambda i: dict(state_time=i * 0.087)),
    "angry": (2, 10, lambda i: dict(state_time=i * 0.035)),
    "alert": (4, 10, lambda i: dict(state_time=i * 0.06, urgency=0.5)),
    "sleep": (2, 1, lambda i: dict(clock=i * 2.0)),
    "sit": (1, 1, lambda i: {}),
    "drag": (1, 1, lambda i: dict(lifted=True)),
    "greet": (4, 8, lambda i: dict(state_time=i * 0.13)),
    "pomodoro": (1, 1, lambda i: {}),
}


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841
    overlays.draw_effects = lambda *a, **k: None  # 特效由執行時疊加，不畫進圖片
    skin = PainterSkin()
    cols = max(n for n, _, _ in STATES.values())
    sheet = QImage(CROP.width() * cols, CROP.height() * len(STATES), QImage.Format_ARGB32_Premultiplied)
    sheet.fill(Qt.transparent)
    manifest = {
        "name": "薄荷帽帽（圖片皮膚範例）",
        "frame_size": [CROP.width(), CROP.height()],
        "sheet": "sheet.png",
        "flip_when_left": True,
        "states": {},
    }
    p = QPainter(sheet)
    for row, (state, (count, fps, params)) in enumerate(STATES.items()):
        for i in range(count):
            frame = QImage(CANVAS_W, CANVAS_H, QImage.Format_ARGB32_Premultiplied)
            frame.fill(Qt.transparent)
            fp = QPainter(frame)
            skin.draw(fp, RenderContext(state=state, color="mint", accessory="hat", **params(i)))
            fp.end()
            p.drawImage(i * CROP.width(), row * CROP.height(), frame.copy(CROP))
        manifest["states"][state] = {"row": row, "frames": count, "fps": fps}
    p.end()

    out = ROOT / "assets" / "skins" / "sample"
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out / "sheet.png"))
    (out / "skin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已產生 {out}")


if __name__ == "__main__":
    main()
