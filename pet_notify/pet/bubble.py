"""對話泡泡：獨立的透明置頂視窗，尾巴指向桌寵。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

TAIL_H = 8
RADIUS = 10
MAX_TEXT_W = 190
MIN_TEXT_W = 70
FONT_FAMILY = "Microsoft JhengHei UI"
TITLE_PT = 9
TEXT_PT = 8
BUTTON_PT = 8
MARGIN_L, MARGIN_T, MARGIN_R, MARGIN_B = 10, 6, 6, 7

BUTTON_STYLE = """
QPushButton {
    background: #FFE4EC; color: #8A3B55; border: 1px solid #F3B2C6;
    border-radius: 8px; padding: 1px 7px; font-size: 8pt;
}
QPushButton:hover { background: #FFD3E0; }
QPushButton:pressed { background: #F9BCD0; }
"""


class Bubble(QWidget):
    closed = Signal(object)  # Notification

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.notification = None
        self._tail_x = 40.0

        self._title = QLabel()
        title_font = QFont(FONT_FAMILY, TITLE_PT)
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setStyleSheet("color: #5B3A44;")
        self._title.setWordWrap(True)

        self._text = QLabel()
        self._text.setFont(QFont(FONT_FAMILY, TEXT_PT))
        self._text.setStyleSheet("color: #4A3B3F;")
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.NoTextInteraction)

        self._close_btn = QToolButton()
        self._close_btn.setText("×")
        self._close_btn.setAutoRaise(True)
        self._close_btn.setStyleSheet("QToolButton { color: #B08A95; border: none; font-size: 10pt; padding: 0; }"
                                      "QToolButton:hover { color: #6B4450; }")
        self._close_btn.setFixedSize(16, 16)
        self._close_btn.clicked.connect(lambda: self.dismiss())

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._title, 1)
        header.addWidget(self._close_btn, 0, Qt.AlignTop)

        self._buttons = QHBoxLayout()
        self._buttons.setContentsMargins(0, 3, 0, 0)
        self._buttons.setSpacing(4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_L, MARGIN_T, MARGIN_R, MARGIN_B + TAIL_H)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addWidget(self._text)
        layout.addLayout(self._buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.dismiss())

    # ---- 內容 ----
    def show_notification(self, n, anchor: QPoint) -> None:
        self.notification = n
        self._title.setText(n.title)
        self._title.setVisible(bool(n.title))
        # 沒有標題的閒聊泡泡點一下就會關閉，不需要 ×，也省下標題列的高度
        self._close_btn.setVisible(bool(n.title) or bool(n.buttons))
        self._text.setText(n.text)
        self._text.setVisible(bool(n.text))

        while self._buttons.count():
            item = self._buttons.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for label, callback in n.buttons:
            btn = QPushButton(label)
            btn.setStyleSheet(BUTTON_STYLE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(22)
            btn.clicked.connect(lambda _=False, cb=callback: self._on_button(cb))
            self._buttons.addWidget(btn)
        if n.buttons:
            self._buttons.addStretch(1)

        self._fit_width(n)
        self.reposition(anchor)
        self.show()
        self.raise_()
        if n.timeout_s > 0:
            self._timer.start(n.timeout_s * 1000)
        else:
            self._timer.stop()

    def _fit_width(self, n) -> None:
        fm = QFontMetrics(self._text.font())
        tm = QFontMetrics(self._title.font())
        lines = (n.text or "").splitlines() or [""]
        need = max([fm.horizontalAdvance(line) for line in lines] + [tm.horizontalAdvance(n.title or "") + 20])
        bm = QFontMetrics(QFont(FONT_FAMILY, BUTTON_PT))
        btn_need = sum(bm.horizontalAdvance(lbl) + 20 for lbl, _ in n.buttons)
        text_w = max(MIN_TEXT_W, min(MAX_TEXT_W, max(need + 4, btn_need)))
        self.setFixedWidth(text_w + MARGIN_L + MARGIN_R)
        self._fit_height()

    def _fit_height(self) -> None:
        # 新建的按鈕要先套用樣式（padding），量出來的高度才正確
        for child in self.findChildren(QWidget):
            child.ensurePolished()
        lay = self.layout()
        lay.invalidate()
        lay.activate()
        h = lay.heightForWidth(self.width())
        if h <= 0:
            h = self.sizeHint().height()
        h = max(h, lay.totalMinimumSize().height())
        self.setFixedHeight(h)

    def _on_button(self, callback) -> None:
        try:
            callback()
        except Exception:
            log.exception("泡泡按鈕處理失敗")
        self.dismiss()

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        self._timer.stop()
        self.hide()
        n, self.notification = self.notification, None
        if n is not None:
            if n.on_dismiss:
                try:
                    n.on_dismiss()
                except Exception:
                    log.exception("泡泡關閉回呼失敗")
            self.closed.emit(n)

    # ---- 位置 ----
    def reposition(self, anchor: QPoint) -> None:
        """anchor：桌寵頭頂的全域座標，泡泡尾巴會指向這裡。"""
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        avail: QRect = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = max(avail.left(), min(anchor.x() - w // 2, avail.right() + 1 - w))
        y = max(avail.top(), anchor.y() - h)
        self._tail_x = float(max(RADIUS + 8, min(anchor.x() - x, w - RADIUS - 8)))
        self.move(x, y)
        self.update()

    # ---- 繪圖 ----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(1, 1, self.width() - 2, self.height() - TAIL_H - 2)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)
        tail = QPainterPath(QPointF(self._tail_x - 6, body.bottom() - 1))
        tail.lineTo(self._tail_x, body.bottom() + TAIL_H - 1)
        tail.lineTo(self._tail_x + 6, body.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)
        p.setPen(QPen(QColor("#F0B5C6"), 1.3))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawPath(path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.notification is not None and not self.notification.buttons:
            self.dismiss()
