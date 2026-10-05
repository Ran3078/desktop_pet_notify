"""桌寵狀態：好感度、等級解鎖、已提醒紀錄、每日事件紀錄 → data/pet_state.json。"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Signal

from . import app_paths

log = logging.getLogger(__name__)

POINTS_PER_LEVEL = 100

# 名稱 → (顯示名稱, 解鎖等級)
COLORS: dict[str, tuple[str, int]] = {
    "cream": ("奶油", 1),
    "pink": ("櫻花粉", 2),
    "mint": ("薄荷", 3),
    "milktea": ("奶茶", 4),
}
ACCESSORIES: dict[str, tuple[str, int]] = {
    "none": ("無", 1),
    "bow": ("蝴蝶結", 2),
    "hat": ("小帽子", 3),
    "scarf": ("圍巾", 5),
}


def level_for(points: int) -> int:
    return 1 + max(0, points) // POINTS_PER_LEVEL


def unlocked(table: dict[str, tuple[str, int]], level: int) -> list[str]:
    return [k for k, (_, need) in table.items() if level >= need]


def next_unlock(level: int) -> tuple[int, list[str]] | None:
    """下一個有東西可以解鎖的等級與項目名稱；全部解鎖時回傳 None。"""
    needs = sorted({need for table in (COLORS, ACCESSORIES) for _, need in table.values() if need > level})
    if not needs:
        return None
    return needs[0], newly_unlocked(needs[0] - 1, needs[0])


def newly_unlocked(old_level: int, new_level: int) -> list[str]:
    names = []
    for table in (COLORS, ACCESSORIES):
        for _key, (label, need) in table.items():
            if old_level < need <= new_level:
                names.append(label)
    return names


@dataclass
class PetState:
    affection: int = 0
    # key = "event_id|start_iso|stage" → 活動開始時間（ISO），用來清掉舊紀錄
    notified: dict[str, str] = field(default_factory=dict)
    last_brief_date: str = ""
    agenda_fired: dict[str, str] = field(default_factory=dict)  # 定時今日行程：HH:MM → 最後發出日期
    last_greet_date: str = ""
    last_lunch_date: str = ""
    last_click_reward: str = ""

    @property
    def level(self) -> int:
        return level_for(self.affection)

    @property
    def level_progress(self) -> int:
        return self.affection % POINTS_PER_LEVEL


class StateManager(QObject):
    affection_changed = Signal(int, int)  # points, level
    level_up = Signal(int, list)  # new level, 解鎖項目名稱

    def __init__(self, path=app_paths.STATE_FILE):
        super().__init__()
        self._path = path
        self.state = self._load()

    def _load(self) -> PetState:
        if not self._path.exists():
            return PetState()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(PetState)}
            return PetState(**{k: v for k, v in raw.items() if k in known})
        except Exception:
            log.exception("狀態檔讀取失敗，改用預設值")
            return PetState()

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.state), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            log.exception("狀態檔儲存失敗")

    # ---- 好感度 ----
    def add_affection(self, points: int, reason: str) -> None:
        old_level = self.state.level
        self.state.affection = max(0, self.state.affection + points)
        new_level = self.state.level
        log.info("好感度 %+d（%s）→ %d 分，Lv.%d", points, reason, self.state.affection, new_level)
        self.save()
        self.affection_changed.emit(self.state.affection, new_level)
        if new_level > old_level:
            self.level_up.emit(new_level, newly_unlocked(old_level, new_level))

    # ---- 已提醒紀錄 ----
    def is_notified(self, key: str) -> bool:
        return key in self.state.notified

    def mark_notified(self, keys: list[str], event_start: datetime) -> None:
        for k in keys:
            self.state.notified[k] = event_start.isoformat()
        self._prune()
        self.save()

    def _prune(self) -> None:
        cutoff = datetime.now().astimezone() - timedelta(days=2)
        stale = []
        for k, start_iso in self.state.notified.items():
            try:
                if datetime.fromisoformat(start_iso) < cutoff:
                    stale.append(k)
            except ValueError:
                stale.append(k)
        for k in stale:
            del self.state.notified[k]

    def mark_agenda_fired(self, hhmm: str, date_str: str) -> None:
        self.state.agenda_fired[hhmm] = date_str
        self.save()

    def set_date_flag(self, name: str, date_str: str) -> None:
        setattr(self.state, name, date_str)
        self.save()
