"""列出與載入皮膚。使用者皮膚放在 data/skins/<名稱>/skin.json，會優先於內建同名皮膚。"""
from __future__ import annotations

import logging
from pathlib import Path

from ... import app_paths
from .base import Skin
from .painter_skin import PainterSkin

log = logging.getLogger(__name__)


def _skin_dirs() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in (app_paths.BUILTIN_SKINS, app_paths.USER_SKINS):  # 後者覆蓋前者
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if (d / "skin.json").is_file():
                found[d.name] = d
    return found


def list_skins() -> list[tuple[str, str]]:
    """回傳 [(skin_id, 顯示名稱)]。"""
    import json

    items = [(PainterSkin.id, PainterSkin.name)]
    for name, d in _skin_dirs().items():
        try:
            label = json.loads((d / "skin.json").read_text(encoding="utf-8")).get("name", name)
        except Exception:
            log.exception("讀取皮膚描述失敗：%s", d)
            continue
        items.append((f"dir:{name}", label))
    return items


def load_skin(skin_id: str) -> Skin:
    if skin_id.startswith("dir:"):
        d = _skin_dirs().get(skin_id[4:])
        if d is None:
            log.warning("找不到皮膚 %s，改用內建皮膚", skin_id)
        else:
            try:
                from .sprite_skin import SpriteSkin

                return SpriteSkin(d)
            except Exception:
                log.exception("載入皮膚 %s 失敗，改用內建皮膚", skin_id)
    return PainterSkin()
