"""設定器：行事曆 / 桌寵 / 通知 / 不打擾 / 小幫手。所有設定變更立即生效並存檔。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout,
    QWidget,
)

from .. import win_sys
from ..pet.generator.skin_writer import delete_skin, is_user_skin
from ..pet.skins.registry import list_skins
from ..reminders.pomodoro import PHASE_LABEL
from ..sound import BUILTIN_SOUNDS
from ..state import ACCESSORIES, COLORS, POINTS_PER_LEVEL, next_unlock
from .calendar.calendar_tab import CalendarTab

log = logging.getLogger(__name__)

STYLE = """
QWidget { font-family: "Microsoft JhengHei UI"; font-size: 10pt; color: #4A3B3F; }
SettingsWindow, QDialog { background: #FFF7F9; }
QTableWidget, QListWidget, QLineEdit, QSpinBox, QTimeEdit, QDateTimeEdit, QComboBox, QPlainTextEdit {
    background: #FFFFFF; color: #4A3B3F; selection-background-color: #FFD3E0; selection-color: #4A3B3F; }
QTableWidget { alternate-background-color: #FFF5F8; gridline-color: #F3DDE4; }
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled { background: #F4F0F1; color: #B9A9AE; }
QHeaderView::section { background: #FBE9EF; color: #7A4A5A; border: none; padding: 4px; }
QTabWidget::pane { border: 1px solid #F0C9D5; border-radius: 8px; top: -1px; background: #FFFDFD; }
QTabBar::tab { padding: 6px 14px; margin-right: 2px; border-top-left-radius: 8px; border-top-right-radius: 8px;
               background: #FBE9EF; color: #7A4A5A; }
QTabBar::tab:selected { background: #FFFDFD; border: 1px solid #F0C9D5; border-bottom: none; font-weight: bold; }
QPushButton { background: #FFE4EC; color: #7A3550; border: 1px solid #F3B2C6; border-radius: 8px; padding: 5px 12px; }
QPushButton:hover { background: #FFD3E0; }
QPushButton:disabled { background: #F2F2F2; color: #AAAAAA; border-color: #DDDDDD; }
QGroupBox { border: 1px solid #F0C9D5; border-radius: 8px; margin-top: 12px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #A0506B; font-weight: bold; }
QProgressBar { border: 1px solid #F0C9D5; border-radius: 6px; text-align: center; background: #FFF5F8; height: 14px; }
QProgressBar::chunk { background: #FF9EB5; border-radius: 5px; }
"""


def _row(*widgets) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if x == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(x)
    return w


class SettingsWindow(QWidget):
    def __init__(self, config, state_mgr, calendar, sound, pomodoro, show_agenda=None):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("桌寵設定器")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLE)
        self._config = config
        self._state = state_mgr
        self._cal = calendar
        self._sound = sound
        self._pomodoro = pomodoro
        self._show_agenda = show_agenda
        self._loading = False

        tabs = QTabWidget()
        self.calendar_tab = CalendarTab(config, calendar)
        tabs.addTab(self.calendar_tab, "📅 行事曆")
        tabs.addTab(self._build_pet_tab(), "🐱 桌寵")
        tabs.addTab(self._build_notify_tab(), "🔔 通知")
        tabs.addTab(self._build_dnd_tab(), "🌙 不打擾")
        tabs.addTab(self._build_helper_tab(), "🍅 小幫手")
        self.tabs = tabs

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)

        state_mgr.affection_changed.connect(lambda *_: self._refresh_affection())
        pomodoro.phase_changed.connect(lambda *_: self._refresh_pomodoro())
        config.changed.connect(self._on_config_changed)

        self._load_values()

    def show_and_raise(self) -> None:
        self._load_values()
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def _set(self, **kw) -> None:
        if not self._loading:
            self._config.update(**kw)

    # ================= 桌寵 =================
    def _build_pet_tab(self) -> QWidget:
        w = QWidget()
        self._pet_visible = QCheckBox("顯示桌寵")
        self._pet_visible.toggled.connect(lambda v: self._set(pet_visible=v))
        self._pet_size = QComboBox()
        for key, label in (("small", "小"), ("medium", "中"), ("large", "大")):
            self._pet_size.addItem(label, key)
        self._pet_size.currentIndexChanged.connect(lambda _: self._set(pet_size=self._pet_size.currentData()))
        self._skin = QComboBox()
        self._skin.currentIndexChanged.connect(self._on_skin_choice)
        self._color = QComboBox()
        self._color.currentIndexChanged.connect(lambda _: self._set(color=self._color.currentData()))
        self._accessory = QComboBox()
        self._accessory.currentIndexChanged.connect(lambda _: self._set(accessory=self._accessory.currentData()))
        self._walk = QCheckBox("沒事時左右散步")
        self._walk.toggled.connect(lambda v: self._set(walk_enabled=v))
        self._night = QCheckBox("深夜（23:00–06:00）自動睡覺")
        self._night.toggled.connect(lambda v: self._set(night_sleep=v))
        self._autostart = QCheckBox("開機時自動啟動")
        self._autostart.toggled.connect(self._toggle_autostart)

        self._level_label = QLabel()
        self._level_bar = QProgressBar()
        self._next_unlock = QLabel()
        self._next_unlock.setStyleSheet("color: #A0506B;")
        self._level_bar.setRange(0, POINTS_PER_LEVEL)
        hint = QLabel("摸摸頭、準時處理提醒、完成番茄鐘都能增加好感度，升級可以解鎖新配色與配件！")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8A7A80; font-size: 9pt;")

        appearance = QGroupBox("外觀")
        f = QFormLayout(appearance)
        f.addRow(self._pet_visible)
        f.addRow("大小", self._pet_size)
        self._create_char = QPushButton("🎨 從圖片建立角色…")
        self._create_char.clicked.connect(self._open_creator)
        self._delete_char = QPushButton("🗑 刪除這個角色")
        self._delete_char.clicked.connect(self._delete_character)
        f.addRow("皮膚", self._skin)
        f.addRow("", _row(self._create_char, self._delete_char, "stretch"))
        f.addRow("配色", self._color)
        f.addRow("配件", self._accessory)
        # 圖片皮膚不支援配色與配件：說明原因並提供一鍵切回內建皮膚
        self._skin_hint = QLabel()
        self._skin_hint.setWordWrap(True)
        self._skin_hint.setStyleSheet("color: #B26A00; font-size: 9pt;")
        self._back_builtin = QPushButton("切換回麻糬貓")
        self._back_builtin.clicked.connect(lambda: self._skin.setCurrentIndex(max(0, self._skin.findData("builtin"))))
        self._back_builtin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._skin_hint_row = _row(self._skin_hint, self._back_builtin)
        f.addRow("", self._skin_hint_row)

        behavior = QGroupBox("行為")
        b = QVBoxLayout(behavior)
        for x in (self._walk, self._night, self._autostart):
            b.addWidget(x)

        bond = QGroupBox("好感度")
        g = QVBoxLayout(bond)
        g.addWidget(self._level_label)
        g.addWidget(self._level_bar)
        g.addWidget(self._next_unlock)
        g.addWidget(hint)

        lay = QVBoxLayout(w)
        lay.addWidget(appearance)
        lay.addWidget(behavior)
        lay.addWidget(bond)
        lay.addStretch(1)
        return w

    def _fill_locked_combo(self, combo: QComboBox, table: dict, current: str) -> None:
        """全部項目都列出來；還沒解鎖的加上鎖頭、變灰色、不能選，滑鼠移上去會顯示還差幾點。"""
        st = self._state.state
        combo.blockSignals(True)
        combo.clear()
        for key, (label, need) in table.items():
            if st.level >= need:
                combo.addItem(label, key)
                continue
            combo.addItem(f"🔒 {label}（Lv.{need} 解鎖）", key)
            item = combo.model().item(combo.count() - 1)
            item.setEnabled(False)
            item.setForeground(QColor("#B9A9AE"))
            missing = (need - 1) * POINTS_PER_LEVEL - st.affection
            item.setToolTip(f"升到 Lv.{need} 解鎖，還差 {missing} 點好感度")
        idx = combo.findData(current)
        combo.setCurrentIndex(max(0, idx))
        combo.blockSignals(False)

    def _refresh_appearance(self) -> None:
        s = self._config.settings
        self._fill_locked_combo(self._color, COLORS, s.color)
        self._fill_locked_combo(self._accessory, ACCESSORIES, s.accessory)
        custom = self._skin.currentData() not in (None, "builtin")
        tip = "目前使用圖片皮膚，配色與配件只適用於內建的麻糬貓" if custom else ""
        for combo in (self._color, self._accessory):
            combo.setEnabled(not custom)
            combo.setToolTip(tip)
        self._skin_hint.setText(f"ℹ️ 「{self._skin.currentText()}」是圖片皮膚，配色與配件只適用於內建的麻糬貓。")
        self._skin_hint_row.setVisible(custom)
        self._delete_char.setVisible(is_user_skin(self._skin.currentData() or ""))

    def _on_skin_choice(self) -> None:
        self._set(skin=self._skin.currentData() or "builtin")
        if not self._loading:
            self._refresh_appearance()

    def _reload_skins(self, select: str) -> None:
        self._loading = True
        try:
            self._skin.clear()
            for skin_id, name in list_skins():
                self._skin.addItem(name, skin_id)
        finally:
            self._loading = False
        self._skin.setCurrentIndex(max(0, self._skin.findData(select)))
        self._on_skin_choice()

    def _open_creator(self) -> None:
        from .character_creator import CharacterCreator

        dlg = CharacterCreator(self)
        if dlg.exec() and dlg.skin_id:
            self._reload_skins(dlg.skin_id)

    def _delete_character(self) -> None:
        skin_id = self._skin.currentData() or ""
        if not is_user_skin(skin_id):
            return
        name = self._skin.currentText()
        if QMessageBox.question(self, "刪除角色", f"確定要刪除「{name}」嗎？角色圖片會一起刪掉，無法復原。") != QMessageBox.Yes:
            return
        self._reload_skins("builtin")  # 先切回內建皮膚，避免桌寵正在使用被刪的檔案
        try:
            delete_skin(skin_id)
        except OSError:
            log.exception("刪除角色失敗")
            QMessageBox.warning(self, "刪除失敗", "無法刪除角色檔案，詳細原因請看 logs/app.log。")
        self._reload_skins("builtin")

    def _refresh_affection(self) -> None:
        st = self._state.state
        self._level_label.setText(f"Lv.{st.level}　（總計 {st.affection} 點）")
        self._level_bar.setValue(st.level_progress)
        self._level_bar.setFormat(f"{st.level_progress} / {POINTS_PER_LEVEL}")
        nxt = next_unlock(st.level)
        if nxt:
            need, names = nxt
            missing = (need - 1) * POINTS_PER_LEVEL - st.affection
            self._next_unlock.setText(f"🎁 下一個解鎖：Lv.{need} {'、'.join(names)}（還差 {missing} 點）")
        else:
            self._next_unlock.setText("🎉 所有配色與配件都解鎖了！")
        self._refresh_appearance()

    def _toggle_autostart(self, enabled: bool) -> None:
        if self._loading:
            return
        if win_sys.set_autostart(enabled):
            self._set(autostart=enabled)
        else:
            QMessageBox.warning(self, "設定失敗", "無法寫入開機自動啟動設定，詳細原因請看 logs/app.log。")

    # ================= 通知 =================
    def _build_notify_tab(self) -> QWidget:
        w = QWidget()
        self._sound_on = QCheckBox("播放提醒音效")
        self._sound_on.toggled.connect(lambda v: self._set(sound_enabled=v))
        self._sound_name = QComboBox()
        for key, label in BUILTIN_SOUNDS.items():
            self._sound_name.addItem(label, key)
        self._sound_name.addItem("自訂 WAV 檔…", "custom")
        self._sound_name.currentIndexChanged.connect(self._on_sound_choice)
        self._custom_path = QLabel()
        self._custom_path.setStyleSheet("color: #8A7A80; font-size: 9pt;")
        self._browse = QPushButton("選擇檔案")
        self._browse.clicked.connect(self._browse_sound)
        self._volume = QSlider(Qt.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.valueChanged.connect(lambda v: self._set(volume=v / 100))
        test = QPushButton("▶ 試聽")
        test.clicked.connect(lambda: self._sound.play(force=True))

        self._stages = QLineEdit()
        self._stages.setPlaceholderText("例如：10, 1, 0")
        self._stages.editingFinished.connect(self._apply_stages)
        self._brief = QCheckBox("每天第一次使用電腦時，告訴我今天的行程")
        self._brief.toggled.connect(lambda v: self._set(daily_brief=v))
        self._sync_interval = QSpinBox()
        self._sync_interval.setRange(1, 60)
        self._sync_interval.setSuffix(" 分鐘")
        self._sync_interval.valueChanged.connect(lambda v: self._set(sync_interval_min=v))

        sound = QGroupBox("音效")
        f = QFormLayout(sound)
        f.addRow(self._sound_on)
        f.addRow("音效", _row(self._sound_name, self._browse, "stretch"))
        f.addRow("", self._custom_path)
        f.addRow("音量", _row(self._volume, test))

        rem = QGroupBox("提醒")
        g = QFormLayout(rem)
        g.addRow("提前幾分鐘提醒", self._stages)
        tip = QLabel("用逗號分隔多個時間點，0 代表活動開始時。預設：10 分鐘前、1 分鐘前、開始時。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #8A7A80; font-size: 9pt;")
        g.addRow("", tip)
        g.addRow(self._brief)
        g.addRow("與 Google 同步間隔", self._sync_interval)

        lay = QVBoxLayout(w)
        lay.addWidget(sound)
        lay.addWidget(rem)
        lay.addWidget(self._build_agenda_box())
        lay.addStretch(1)
        return w

    def _build_agenda_box(self) -> QGroupBox:
        box = QGroupBox("定時列出今日行程")
        self._agenda_list = QListWidget()
        self._agenda_list.setMaximumHeight(90)
        self._agenda_time = QTimeEdit(QTime(9, 0))
        self._agenda_time.setDisplayFormat("HH:mm")
        add = QPushButton("＋ 新增時間")
        add.clicked.connect(self._add_agenda_time)
        remove = QPushButton("移除選取")
        remove.clicked.connect(self._remove_agenda_time)
        preview = QPushButton("👀 立即顯示一次")
        preview.clicked.connect(lambda: self._show_agenda and self._show_agenda())
        tip = QLabel("每天到了這些時間，桌寵會把今天的所有行程（含已結束的）列出來。"
                     "電腦睡眠或關機錯過的話，1 小時內開機仍會補發。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #8A7A80; font-size: 9pt;")
        g = QVBoxLayout(box)
        g.addWidget(self._agenda_list)
        g.addWidget(_row(self._agenda_time, add, remove, "stretch", preview))
        g.addWidget(tip)
        return box

    def _fill_agenda(self) -> None:
        self._agenda_list.clear()
        for hhmm in sorted(self._config.settings.agenda_times):
            self._agenda_list.addItem(f"每天 {hhmm}")

    def _add_agenda_time(self) -> None:
        hhmm = self._agenda_time.time().toString("HH:mm")
        times = list(self._config.settings.agenda_times)
        if hhmm in times:
            QMessageBox.information(self, "時間重複", f"已經有 {hhmm} 了。")
            return
        self._set(agenda_times=sorted(times + [hhmm]))
        self._fill_agenda()

    def _remove_agenda_time(self) -> None:
        row = self._agenda_list.currentRow()
        if row < 0:
            return
        times = sorted(self._config.settings.agenda_times)
        del times[row]
        self._set(agenda_times=times)
        self._fill_agenda()

    def _on_sound_choice(self) -> None:
        key = self._sound_name.currentData()
        self._browse.setVisible(key == "custom")
        self._custom_path.setVisible(key == "custom")
        if key == "custom" and not self._config.settings.custom_sound_path and not self._loading:
            self._browse_sound()
        self._set(sound_name=key)

    def _browse_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇提醒音效", "", "WAV 音效 (*.wav)")
        if path:
            self._set(custom_sound_path=path, sound_name="custom")
            self._custom_path.setText(path)

    def _apply_stages(self) -> None:
        try:
            stages = sorted({int(x) for x in self._stages.text().replace("，", ",").split(",") if x.strip()},
                            reverse=True)
            if not stages or any(s < 0 or s > 1440 for s in stages):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "格式錯誤", "請輸入 0–1440 之間的數字，用逗號分隔，例如：10, 1, 0")
            self._stages.setText(", ".join(map(str, self._config.settings.stages_sorted)))
            return
        self._stages.setText(", ".join(map(str, stages)))
        self._set(reminder_stages=stages)

    # ================= 不打擾 =================
    def _build_dnd_tab(self) -> QWidget:
        w = QWidget()
        self._dnd_full = QCheckBox("全螢幕（遊戲、簡報、影片）時不跳泡泡，改用系統通知，離開全螢幕後再補顯示")
        self._dnd_full.toggled.connect(lambda v: self._set(dnd_fullscreen=v))
        self._idle = QSpinBox()
        self._idle.setRange(0, 120)
        self._idle.setSuffix(" 分鐘")
        self._idle.setSpecialValueText("關閉")
        self._idle.valueChanged.connect(lambda v: self._set(idle_defer_min=v))

        self._quiet_list = QListWidget()
        self._quiet_list.setMaximumHeight(120)
        self._q_start = QTimeEdit(QTime(12, 0))
        self._q_end = QTimeEdit(QTime(13, 0))
        for t in (self._q_start, self._q_end):
            t.setDisplayFormat("HH:mm")
        add = QPushButton("＋ 新增時段")
        add.clicked.connect(self._add_quiet)
        remove = QPushButton("移除選取")
        remove.clicked.connect(self._remove_quiet)

        box1 = QGroupBox("自動偵測")
        f = QFormLayout(box1)
        self._dnd_full.setStyleSheet("QCheckBox { spacing: 6px; }")
        f.addRow(self._dnd_full)
        f.addRow("離開電腦超過", _row(self._idle, QLabel("就先保留提醒，回來再通知"), "stretch"))

        box2 = QGroupBox("勿擾時段（只發系統通知，不出聲、不跳泡泡）")
        g = QVBoxLayout(box2)
        g.addWidget(self._quiet_list)
        g.addWidget(_row(QLabel("從"), self._q_start, QLabel("到"), self._q_end, add, remove, "stretch"))

        lay = QVBoxLayout(w)
        lay.addWidget(box1)
        lay.addWidget(box2)
        lay.addStretch(1)
        return w

    def _fill_quiet(self) -> None:
        self._quiet_list.clear()
        for start, end in self._config.settings.quiet_periods:
            self._quiet_list.addItem(f"{start} – {end}")

    def _add_quiet(self) -> None:
        start, end = self._q_start.time().toString("HH:mm"), self._q_end.time().toString("HH:mm")
        if start == end:
            QMessageBox.warning(self, "時間錯誤", "開始與結束時間不能相同。")
            return
        periods = list(self._config.settings.quiet_periods) + [[start, end]]
        self._set(quiet_periods=periods)
        self._fill_quiet()

    def _remove_quiet(self) -> None:
        row = self._quiet_list.currentRow()
        if row < 0:
            return
        periods = list(self._config.settings.quiet_periods)
        del periods[row]
        self._set(quiet_periods=periods)
        self._fill_quiet()

    # ================= 小幫手 =================
    def _build_helper_tab(self) -> QWidget:
        w = QWidget()

        def spin(lo, hi, key):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.valueChanged.connect(lambda v: self._set(**{key: v}))
            return s

        self._p_focus = spin(1, 120, "pomodoro_focus")
        self._p_short = spin(1, 60, "pomodoro_short_break")
        self._p_long = spin(1, 120, "pomodoro_long_break")
        self._p_rounds = spin(1, 12, "pomodoro_rounds")
        for s in (self._p_focus, self._p_short, self._p_long):
            s.setSuffix(" 分鐘")
        self._p_rounds.setSuffix(" 輪")
        self._p_btn = QPushButton()
        self._p_btn.clicked.connect(self._toggle_pomodoro)
        self._p_state = QLabel()

        self._water_on = QCheckBox("提醒喝水，每")
        self._water_on.toggled.connect(lambda v: self._set(water_enabled=v))
        self._water_int = spin(10, 240, "water_interval")
        self._water_int.setSuffix(" 分鐘")
        self._stretch_on = QCheckBox("提醒起來伸展，每")
        self._stretch_on.toggled.connect(lambda v: self._set(stretch_enabled=v))
        self._stretch_int = spin(10, 240, "stretch_interval")
        self._stretch_int.setSuffix(" 分鐘")

        pomo = QGroupBox("番茄鐘")
        f = QFormLayout(pomo)
        f.addRow("專注", self._p_focus)
        f.addRow("短休息", self._p_short)
        f.addRow("長休息", self._p_long)
        f.addRow("每幾輪長休息一次", self._p_rounds)
        f.addRow(_row(self._p_btn, self._p_state, "stretch"))

        health = QGroupBox("健康提醒")
        g = QVBoxLayout(health)
        g.addWidget(_row(self._water_on, self._water_int, "stretch"))
        g.addWidget(_row(self._stretch_on, self._stretch_int, "stretch"))
        note = QLabel("離開電腦超過 5 分鐘會自動重新計時；桌寵睡覺時不會提醒。")
        note.setStyleSheet("color: #8A7A80; font-size: 9pt;")
        g.addWidget(note)

        lay = QVBoxLayout(w)
        lay.addWidget(pomo)
        lay.addWidget(health)
        lay.addStretch(1)
        return w

    def _toggle_pomodoro(self) -> None:
        if self._pomodoro.running:
            self._pomodoro.stop()
        else:
            self._pomodoro.start()

    def _refresh_pomodoro(self) -> None:
        running = self._pomodoro.running
        self._p_btn.setText("⏹ 停止番茄鐘" if running else "▶ 開始番茄鐘")
        self._p_state.setText(f"目前：{PHASE_LABEL[self._pomodoro.phase]}" if running else "")

    # ================= 載入 =================
    def _on_config_changed(self, keys: set) -> None:
        if keys & {"pet_visible"}:
            self._loading = True
            self._pet_visible.setChecked(self._config.settings.pet_visible)
            self._loading = False

    def _load_values(self) -> None:
        self._loading = True
        try:
            s = self._config.settings
            self._pet_visible.setChecked(s.pet_visible)
            self._pet_size.setCurrentIndex(max(0, self._pet_size.findData(s.pet_size)))
            self._skin.clear()
            for skin_id, name in list_skins():
                self._skin.addItem(name, skin_id)
            self._skin.setCurrentIndex(max(0, self._skin.findData(s.skin)))
            self._walk.setChecked(s.walk_enabled)
            self._night.setChecked(s.night_sleep)
            self._autostart.setChecked(win_sys.get_autostart())
            self._refresh_affection()

            self._sound_on.setChecked(s.sound_enabled)
            self._sound_name.setCurrentIndex(max(0, self._sound_name.findData(s.sound_name)))
            self._custom_path.setText(s.custom_sound_path or "（尚未選擇）")
            self._volume.setValue(round(s.volume * 100))
            self._stages.setText(", ".join(map(str, s.stages_sorted)))
            self._brief.setChecked(s.daily_brief)
            self._fill_agenda()
            self._sync_interval.setValue(s.sync_interval_min)

            self._dnd_full.setChecked(s.dnd_fullscreen)
            self._idle.setValue(s.idle_defer_min)
            self._fill_quiet()

            self._p_focus.setValue(s.pomodoro_focus)
            self._p_short.setValue(s.pomodoro_short_break)
            self._p_long.setValue(s.pomodoro_long_break)
            self._p_rounds.setValue(s.pomodoro_rounds)
            self._water_on.setChecked(s.water_enabled)
            self._water_int.setValue(s.water_interval)
            self._stretch_on.setChecked(s.stretch_enabled)
            self._stretch_int.setValue(s.stretch_interval)
            self._refresh_pomodoro()
        finally:
            self._loading = False
        self._on_sound_choice_visibility()

    def _on_sound_choice_visibility(self) -> None:
        custom = self._sound_name.currentData() == "custom"
        self._browse.setVisible(custom)
        self._custom_path.setVisible(custom)
