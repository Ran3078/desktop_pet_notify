"""使用者設定：data/settings.json。"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields

from PySide6.QtCore import QObject, Signal

from . import app_paths

log = logging.getLogger(__name__)

PET_SCALES = {"small": 0.75, "medium": 1.0, "large": 1.35}


@dataclass
class Settings:
    # 桌寵
    pet_visible: bool = True
    pet_size: str = "medium"
    skin: str = "builtin"
    color: str = "cream"
    accessory: str = "none"
    walk_enabled: bool = True
    night_sleep: bool = True
    autostart: bool = False
    pos_x: int | None = None
    pos_y: int | None = None

    # 通知
    sound_enabled: bool = True
    sound_name: str = "chime"
    custom_sound_path: str = ""
    volume: float = 0.7
    reminder_stages: list[int] = field(default_factory=lambda: [10, 1, 0])
    daily_brief: bool = True
    agenda_times: list[str] = field(default_factory=list)  # 每天定時列出今日行程，例如 ["09:00", "13:30"]
    sync_interval_min: int = 5

    # 行事曆畫面
    calendar_view: str = "month"   # month / week / day
    week_start: str = "sun"        # sun / mon
    show_lunar: bool = True
    show_holidays: bool = True

    # 不打擾
    dnd_fullscreen: bool = True
    idle_defer_min: int = 5
    quiet_periods: list[list[str]] = field(default_factory=list)  # [["12:00", "13:00"], ...]

    # 小幫手
    pomodoro_focus: int = 25
    pomodoro_short_break: int = 5
    pomodoro_long_break: int = 15
    pomodoro_rounds: int = 4
    water_enabled: bool = True
    water_interval: int = 60
    stretch_enabled: bool = True
    stretch_interval: int = 90

    @property
    def pet_scale(self) -> float:
        return PET_SCALES.get(self.pet_size, 1.0)

    @property
    def stages_sorted(self) -> list[int]:
        return sorted({max(0, int(s)) for s in self.reminder_stages}, reverse=True) or [10]


class ConfigManager(QObject):
    """持有 Settings；update() 會存檔並發出 changed(set_of_keys)。"""

    changed = Signal(set)

    def __init__(self, path=app_paths.SETTINGS_FILE):
        super().__init__()
        self._path = path
        self.settings = self._load()

    def _load(self) -> Settings:
        if not self._path.exists():
            log.info("找不到設定檔，使用預設值")
            return Settings()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            return Settings(**{k: v for k, v in raw.items() if k in known})
        except Exception:
            log.exception("設定檔讀取失敗，改用預設值")
            return Settings()

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.settings), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            log.exception("設定檔儲存失敗")

    def update(self, **changes) -> None:
        changed = set()
        for key, value in changes.items():
            if not hasattr(self.settings, key):
                log.warning("未知的設定項目：%s", key)
                continue
            if getattr(self.settings, key) != value:
                setattr(self.settings, key, value)
                changed.add(key)
        if changed:
            self.save()
            # 位置變動很頻繁，不需要記 log
            if changed - {"pos_x", "pos_y"}:
                log.info("設定變更：%s", ", ".join(sorted(changed)))
            self.changed.emit(changed)
