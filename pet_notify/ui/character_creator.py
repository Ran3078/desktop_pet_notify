"""從圖片建立角色：選圖 → 去背 → 預覽動畫 → 存成圖片皮膚。"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget,
)

from ..pet.generator import background
from ..pet.generator.generator import GenerateOptions, GeneratedCharacter, available_generators
from ..pet.generator.skin_writer import write_skin

log = logging.getLogger(__name__)

IMAGE_FILTER = "圖片 (*.png *.jpg *.jpeg *.webp *.bmp)"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
STATE_LABELS = {
    "idle": "待機", "walk": "散步", "sit": "坐下", "stretch": "伸懶腰", "yawn": "打哈欠", "drag": "被拎起來",
    "happy": "開心", "angry": "生氣", "alert": "提醒", "sleep": "睡覺", "pomodoro": "專注", "celebrate": "慶祝",
    "greet": "打招呼",
}


def _checker(p: QPainter, rect: QRectF, size: int = 10) -> None:
    p.fillRect(rect, QColor("#FFFFFF"))
    light = QColor("#EFE6EA")
    y = rect.top()
    row = 0
    while y < rect.bottom():
        x = rect.left() + (size if row % 2 else 0)
        while x < rect.right():
            p.fillRect(QRectF(x, y, size, size).intersected(rect), light)
            x += size * 2
        y += size
        row += 1


class ImagePane(QWidget):
    """顯示一張圖（等比例置中），可選擇棋盤格底；點一下回報圖片座標。"""

    clicked = Signal(int, int)

    def __init__(self, title: str, checker: bool = False, clickable: bool = False):
        super().__init__()
        self.title = title
        self.checker = checker
        self.image: QImage | None = None
        self.placeholder = ""
        self.setMinimumSize(220, 240)
        if clickable:
            self.setCursor(Qt.CrossCursor)
        self._clickable = clickable

    def set_image(self, img: QImage | None, placeholder: str = "") -> None:
        self.image, self.placeholder = img, placeholder
        self.update()

    def _target(self) -> QRectF:
        area = QRectF(8, 28, self.width() - 16, self.height() - 36)
        if not self.image or self.image.isNull():
            return area
        scale = min(area.width() / self.image.width(), area.height() / self.image.height(), 3.0)
        w, h = self.image.width() * scale, self.image.height() * scale
        return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#FFFDFD"))
        p.setPen(QColor("#A0506B"))
        p.drawText(QRectF(8, 4, self.width() - 16, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        area = QRectF(8, 28, self.width() - 16, self.height() - 36)
        p.setPen(QPen(QColor("#F0C9D5"), 1))
        p.drawRoundedRect(area, 8, 8)
        if self.image and not self.image.isNull():
            target = self._target()
            if self.checker:
                _checker(p, target)
            p.drawImage(target, self.image)
        else:
            p.setPen(QColor("#B9A9AE"))
            p.drawText(area, Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)

    def mousePressEvent(self, event) -> None:
        if not (self._clickable and self.image) or event.button() != Qt.LeftButton:
            return
        t = self._target()
        pos = event.position()
        if t.contains(pos):
            x = int((pos.x() - t.left()) / t.width() * self.image.width())
            y = int((pos.y() - t.top()) / t.height() * self.image.height())
            self.clicked.emit(x, y)


class AnimationPane(QWidget):
    """播放生成的影格；可以選單一狀態或全部輪播。"""

    def __init__(self):
        super().__init__()
        self.character: GeneratedCharacter | None = None
        self.state = ""          # "" = 全部輪播
        self._tick = 0
        self._cycle_index = 0
        self.combo = QComboBox()
        self.combo.addItem("全部輪播", "")
        for key, label in STATE_LABELS.items():
            self.combo.addItem(label, key)
        self.combo.currentIndexChanged.connect(lambda _: self._set_state(self.combo.currentData()))
        self.canvas = QWidget()
        self.canvas.setMinimumSize(220, 210)
        self.canvas.paintEvent = self._paint
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("動畫預覽")
        title.setStyleSheet("color: #A0506B;")
        lay.addWidget(title)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.combo)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(50)

    def set_character(self, ch: GeneratedCharacter | None) -> None:
        self.character = ch
        self.canvas.update()

    def _set_state(self, state: str) -> None:
        self.state = state
        self._tick = 0
        self.canvas.update()

    def _current(self) -> tuple[str, list[QImage], float] | None:
        if not self.character:
            return None
        states = list(self.character.states)
        state = self.state or states[self._cycle_index % len(states)]
        fps, frames = self.character.states[state]
        return state, frames, fps

    def _advance(self) -> None:
        self._tick += 1
        if not self.state and self._tick >= 40:  # 全部輪播：每個狀態 2 秒
            self._tick = 0
            self._cycle_index += 1
        self.canvas.update()

    def _paint(self, _event) -> None:
        p = QPainter(self.canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.canvas.rect())
        p.fillRect(rect, QColor("#DCE6F0"))
        cur = self._current()
        if not cur:
            p.setPen(QColor("#8A9BB0"))
            p.drawText(rect, Qt.AlignCenter, "選好圖片後會在這裡動起來")
            return
        state, frames, fps = cur
        frame = frames[int(self._tick * 0.05 * fps) % len(frames)]
        side = min(rect.width(), rect.height() - 20)
        p.drawImage(QRectF(rect.center().x() - side / 2, rect.top(), side, side), frame)
        p.setPen(QColor("#4A3B3F"))
        p.drawText(QRectF(rect.left(), rect.bottom() - 20, rect.width(), 20), Qt.AlignCenter,
                   STATE_LABELS.get(state, state))


class CharacterCreator(QDialog):
    """建立成功後 self.skin_id 會是新皮膚的 id（例如 "dir:我的小狗"）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("從圖片建立角色")
        self.setAcceptDrops(True)
        self.resize(820, 560)
        self.skin_id = ""
        self._path = ""
        self._source: QImage | None = None
        self._character: GeneratedCharacter | None = None
        self._picked: list[tuple[int, int, int]] = []

        pick = QPushButton("📂 選擇圖片…")
        pick.clicked.connect(self._choose_file)
        self.path_label = QLabel("也可以直接把圖片拖進這個視窗（PNG、JPG、WEBP、BMP）")
        self.path_label.setStyleSheet("color: #8A7A80;")

        self.original = ImagePane("原圖（點一下：把這個顏色也去掉）", clickable=True)
        self.original.clicked.connect(self._pick_color)
        self.cutout = ImagePane("去背結果", checker=True)
        self.animation = AnimationPane()

        self.generator = QComboBox()
        for g in available_generators():
            self.generator.addItem(g.name, g.id)
        self.mode_auto = QRadioButton("自動去背")
        self.mode_alpha = QRadioButton("只用圖片原本的透明")
        self.mode_none = QRadioButton("不去背")
        self.mode_auto.setChecked(True)
        modes = QButtonGroup(self)
        for b in (self.mode_auto, self.mode_alpha, self.mode_none):
            modes.addButton(b)
            b.toggled.connect(self._schedule)
        self.tolerance = QSlider(Qt.Horizontal)
        self.tolerance.setRange(0, 120)
        self.tolerance.setValue(40)
        self.tolerance.setFixedWidth(160)
        self.tolerance_label = QLabel("40")
        self.tolerance.valueChanged.connect(lambda v: (self.tolerance_label.setText(str(v)), self._schedule()))
        # 從哪些邊開始去背：角色碰到的邊（例如半身圖的下緣）不要勾，不然淺色的臉或身體會被當成背景吃掉
        self.side_boxes: dict[str, QCheckBox] = {}
        for side, label in (("top", "上"), ("bottom", "下"), ("left", "左"), ("right", "右")):
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._schedule)
            self.side_boxes[side] = box
        self.sides_row = QWidget()
        sides_lay = QHBoxLayout(self.sides_row)
        sides_lay.setContentsMargins(0, 0, 0, 0)
        sides_lay.addWidget(QLabel("從這些邊開始去背："))
        for box in self.side_boxes.values():
            sides_lay.addWidget(box)
        hint = QLabel("（角色被圖片邊緣切到的那一邊不要勾；選好圖片時會自動判斷）")
        hint.setStyleSheet("color: #8A7A80;")
        sides_lay.addWidget(hint)
        sides_lay.addStretch(1)
        self.mode_auto.toggled.connect(self.sides_row.setVisible)
        self.picked_label = QLabel()
        self.picked_label.setStyleSheet("color: #8A7A80;")
        clear = QPushButton("清除點選的顏色")
        clear.clicked.connect(self._clear_picked)

        self.name = QLineEdit()
        self.name.setPlaceholderText("角色名稱")
        self.create_btn = QPushButton("✨ 建立並套用")
        self.create_btn.setEnabled(False)
        self.create_btn.clicked.connect(self._create)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(pick)
        top.addWidget(self.path_label, 1)
        top.addWidget(QLabel("生成方式"))
        top.addWidget(self.generator)
        panes = QHBoxLayout()
        panes.addWidget(self.original, 1)
        panes.addWidget(self.cutout, 1)
        panes.addWidget(self.animation, 1)
        opts = QHBoxLayout()
        for w in (self.mode_auto, self.mode_alpha, self.mode_none):
            opts.addWidget(w)
        opts.addSpacing(16)
        opts.addWidget(QLabel("容差"))
        opts.addWidget(self.tolerance)
        opts.addWidget(self.tolerance_label)
        opts.addStretch(1)
        picked = QHBoxLayout()
        picked.addWidget(self.picked_label, 1)
        picked.addWidget(clear)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("名稱"))
        bottom.addWidget(self.name, 1)
        bottom.addSpacing(16)
        bottom.addWidget(cancel)
        bottom.addWidget(self.create_btn)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(panes, 1)
        lay.addLayout(opts)
        lay.addWidget(self.sides_row)
        lay.addLayout(picked)
        lay.addLayout(bottom)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._regenerate)
        self._update_picked_label()
        self.original.set_image(None, "還沒選圖片")
        self.cutout.set_image(None, "")

    # ---- 選圖 ----
    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇角色圖片", "", IMAGE_FILTER)
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        try:
            self._source = background.load_image(path)
        except ValueError as exc:
            log.warning("讀取圖片失敗：%s", exc)
            QMessageBox.warning(self, "無法讀取圖片", str(exc))
            return
        self._path = path
        self._picked.clear()
        self._update_picked_label()
        self.path_label.setText(Path(path).name)
        if not self.name.text().strip():
            self.name.setText(Path(path).stem[:20])
        # 已經是透明背景的 PNG：預設沿用原本的透明
        (self.mode_alpha if background.has_transparency(self._source) else self.mode_auto).setChecked(True)
        auto_sides = background.auto_seed_sides(self._source)
        for side, box in self.side_boxes.items():
            box.blockSignals(True)
            box.setChecked(side in auto_sides)
            box.blockSignals(False)
        self.original.set_image(self._source)
        log.info("載入角色圖片：%s（%dx%d）", path, self._source.width(), self._source.height())
        self._regenerate()

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls and Path(urls[0].toLocalFile()).suffix.lower() in IMAGE_SUFFIXES:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.load(event.mimeData().urls()[0].toLocalFile())

    # ---- 參數 ----
    def _mode(self) -> str:
        if self.mode_none.isChecked():
            return background.NONE
        if self.mode_alpha.isChecked():
            return background.ALPHA_ONLY
        return background.AUTO

    def _pick_color(self, x: int, y: int) -> None:
        if self._source is None:
            return
        rgb = background.color_at(self._source, x, y)
        if rgb not in self._picked:
            self._picked.append(rgb)
        self.mode_auto.setChecked(True)
        self._update_picked_label()
        self._schedule()

    def _clear_picked(self) -> None:
        self._picked.clear()
        self._update_picked_label()
        self._schedule()

    def _update_picked_label(self) -> None:
        if not self._picked:
            self.picked_label.setText("提示：角色中間有沒去掉的背景（例如手臂和身體之間），在原圖上點一下那個顏色")
            return
        chips = " ".join(f"<span style='background:#{r:02x}{g:02x}{b:02x}'>　　</span>" for r, g, b in self._picked)
        self.picked_label.setText(f"額外去掉的顏色：{chips}")

    def options(self) -> GenerateOptions:
        return GenerateOptions(bg_mode=self._mode(), tolerance=self.tolerance.value(),
                               extra_colors=list(self._picked),
                               seed_sides={side for side, box in self.side_boxes.items() if box.isChecked()})

    def _schedule(self) -> None:
        if self._source is not None:
            self._debounce.start()

    def _regenerate(self) -> None:
        if self._source is None:
            return
        generator = next(g for g in available_generators() if g.id == self.generator.currentData())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._character = generator.generate(self._source, self.options())
            self.cutout.set_image(self._character.cutout)
            self.animation.set_character(self._character)
            self.create_btn.setEnabled(True)
        except ValueError as exc:
            self._character = None
            self.cutout.set_image(None, str(exc))
            self.animation.set_character(None)
            self.create_btn.setEnabled(False)
        except Exception:
            log.exception("生成角色失敗")
            self._character = None
            self.create_btn.setEnabled(False)
            self.cutout.set_image(None, "生成失敗，詳細原因請看 logs/app.log")
        finally:
            QApplication.restoreOverrideCursor()

    # ---- 建立 ----
    def _create(self) -> None:
        if self._character is None:
            return
        name = self.name.text().strip() or Path(self._path).stem or "我的角色"
        try:
            self.skin_id, _ = write_skin(self._character, name, self._path)
        except OSError:
            log.exception("寫入角色皮膚失敗")
            QMessageBox.warning(self, "建立失敗", "無法寫入角色檔案，詳細原因請看 logs/app.log。")
            return
        self.accept()

    # 測試用：不經過檔案對話框直接操作
    @property
    def character(self) -> GeneratedCharacter | None:
        return self._character

