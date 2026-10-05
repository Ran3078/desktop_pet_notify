"""事件離線快取：data/events_cache.json。"""
from __future__ import annotations

import json
import logging
import os

from .. import app_paths
from .models import CalendarEvent

log = logging.getLogger(__name__)


def load_cache() -> list[CalendarEvent]:
    path = app_paths.EVENTS_CACHE_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        events = [CalendarEvent.from_dict(d) for d in raw.get("events", [])]
        log.info("從快取載入 %d 個活動", len(events))
        return events
    except Exception:
        log.exception("活動快取讀取失敗")
        return []


def save_cache(events: list[CalendarEvent]) -> None:
    path = app_paths.EVENTS_CACHE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"events": [e.to_dict() for e in events]}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(tmp, path)
    except Exception:
        log.exception("活動快取儲存失敗")
