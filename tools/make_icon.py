r"""產生 assets/icon.ico（打包 exe 用的圖示）。執行：.venv\Scripts\python tools\make_icon.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet_notify.tray import render_icon  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)  # noqa: F841
    pixmap = render_icon("cream").pixmap(QSize(256, 256))
    out = ROOT / "assets" / "icon.ico"
    if not pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(out), "ICO"):
        raise SystemExit("圖示儲存失敗")
    print(f"已產生 {out}")


if __name__ == "__main__":
    main()
