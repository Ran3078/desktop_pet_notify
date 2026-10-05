"""集中管理所有路徑。

開發模式：根目錄 = 專案根目錄。
打包模式（PyInstaller）：根目錄 = exe 所在資料夾；唯讀資源從 sys._MEIPASS 讀取。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _root()
BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))

ASSETS = BUNDLE / "assets"
BUILTIN_SKINS = ASSETS / "skins"

DATA = ROOT / "data"
LOGS = ROOT / "logs"
SOUNDS = DATA / "sounds"
USER_SKINS = DATA / "skins"

SETTINGS_FILE = DATA / "settings.json"
STATE_FILE = DATA / "pet_state.json"
EVENTS_CACHE_FILE = DATA / "events_cache.json"

CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"


def ensure_dirs() -> None:
    for d in (DATA, LOGS, SOUNDS, USER_SKINS):
        d.mkdir(parents=True, exist_ok=True)
