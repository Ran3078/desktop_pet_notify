"""系統匣圖示與選單。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .pet.skins.base import CANVAS_H, CANVAS_W, RenderContext
from .pet.skins.painter_skin import PainterSkin


def render_icon(color: str = "cream", size: int = 64) -> QIcon:
    img = QImage(CANVAS_W, CANVAS_H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    PainterSkin().draw(p, RenderContext(color=color, lifted=True))
    p.end()
    cropped = img.copy(QRect(18, 50, 124, 124))
    icon = QIcon()
    for s in (16, 24, 32, 48, size, 256):
        icon.addPixmap(QPixmap.fromImage(cropped.scaled(QSize(s, s), Qt.KeepAspectRatio, Qt.SmoothTransformation)))
    return icon


class Tray(QSystemTrayIcon):
    settings_requested = Signal()
    toggle_pet_requested = Signal()
    sync_requested = Signal()
    pomodoro_toggle_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, pet_visible, pomodoro_running):
        super().__init__(icon)
        self.setToolTip("桌寵小提醒")
        self._pet_visible = pet_visible
        self._pomodoro_running = pomodoro_running

        self._menu = QMenu()
        self._menu.addAction("開啟設定器", self.settings_requested.emit)
        self._toggle = QAction(self._menu)
        self._toggle.triggered.connect(self.toggle_pet_requested.emit)
        self._menu.addAction(self._toggle)
        self._menu.addAction("立即同步行事曆", self.sync_requested.emit)
        self._pomodoro = QAction(self._menu)
        self._pomodoro.triggered.connect(self.pomodoro_toggle_requested.emit)
        self._menu.addAction(self._pomodoro)
        self._menu.addSeparator()
        self._menu.addAction("結束", self.quit_requested.emit)
        self._menu.aboutToShow.connect(self._refresh)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._refresh()

    def _refresh(self) -> None:
        self._toggle.setText("隱藏桌寵" if self._pet_visible() else "顯示桌寵")
        self._pomodoro.setText("停止番茄鐘" if self._pomodoro_running() else "開始番茄鐘")

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.settings_requested.emit()

    def toast(self, title: str, text: str) -> None:
        self.showMessage(title, text, self.icon(), 8000)
