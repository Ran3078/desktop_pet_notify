"""把生成的角色寫成圖片皮膚（skin.json + sheet.png），放到 data/skins/<資料夾>/。"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from ... import app_paths
from .animator import FRAME
from .generator import GeneratedCharacter

log = logging.getLogger(__name__)

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def slugify(name: str) -> str:
    """資料夾名稱：保留中文與英數，去掉 Windows 不允許的字元。"""
    slug = _INVALID.sub("", name.strip())
    slug = re.sub(r"\s+", "-", slug).strip(".- ")
    return slug[:40] or "my-pet"


def unique_dir(root: Path, slug: str) -> Path:
    path = root / slug
    n = 2
    while path.exists():
        path = root / f"{slug}-{n}"
        n += 1
    return path


def build_sheet(character: GeneratedCharacter) -> tuple[QImage, dict]:
    cols = max(len(frames) for _, frames in character.states.values())
    rows = len(character.states)
    sheet = QImage(cols * FRAME, rows * FRAME, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(Qt.transparent)
    states = {}
    p = QPainter(sheet)
    for row, (state, (fps, frames)) in enumerate(character.states.items()):
        for col, frame in enumerate(frames):
            p.drawImage(QRectF(col * FRAME, row * FRAME, FRAME, FRAME), frame)
        states[state] = {"row": row, "frames": len(frames), "fps": fps}
    p.end()
    return sheet, states


def write_skin(character: GeneratedCharacter, name: str, source_path: str = "",
               root: Path | None = None) -> tuple[str, Path]:
    """寫出皮膚，回傳 (skin_id, 資料夾路徑)。"""
    root = root or app_paths.USER_SKINS
    root.mkdir(parents=True, exist_ok=True)
    folder = unique_dir(root, slugify(name))
    folder.mkdir(parents=True)
    sheet, states = build_sheet(character)
    if not sheet.save(str(folder / "sheet.png")):
        raise OSError(f"無法寫入 {folder / 'sheet.png'}")
    character.cutout.save(str(folder / "cutout.png"))
    if source_path and Path(source_path).is_file():
        shutil.copyfile(source_path, folder / ("original" + Path(source_path).suffix.lower()))
    manifest = {
        "name": name.strip() or folder.name,
        "frame_size": [FRAME, FRAME],
        "sheet": "sheet.png",
        "flip_when_left": True,
        "states": states,
        "generated_by": character.generator,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    (folder / "skin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("已建立角色皮膚：%s（%s）", manifest["name"], folder)
    return f"dir:{folder.name}", folder


def is_user_skin(skin_id: str) -> bool:
    return skin_id.startswith("dir:") and (app_paths.USER_SKINS / skin_id[4:] / "skin.json").is_file()


def delete_skin(skin_id: str) -> None:
    if not is_user_skin(skin_id):
        raise ValueError(f"不是使用者建立的皮膚：{skin_id}")
    folder = app_paths.USER_SKINS / skin_id[4:]
    shutil.rmtree(folder)
    log.info("已刪除角色皮膚：%s", folder)
