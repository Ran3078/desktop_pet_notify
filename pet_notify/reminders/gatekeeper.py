"""不打擾機制：決定一則通知現在要怎麼呈現。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class Route(Enum):
    SHOW = "show"            # 正常：桌寵泡泡 + 音效 + 系統匣通知
    QUIET = "quiet"          # 勿擾時段：只發系統匣通知，不播音效
    FULLSCREEN = "fullscreen"  # 全螢幕：先發系統匣通知，泡泡等離開全螢幕再顯示
    DEFER = "defer"          # 使用者不在電腦前：先保留，等使用者回來


@dataclass(frozen=True)
class Environment:
    now: datetime
    fullscreen: bool
    idle_seconds: float


def _parse(hhmm: str) -> time:
    h, m = hhmm.strip().split(":")
    return time(int(h), int(m))


def in_quiet_period(now: datetime, periods: list[list[str]]) -> bool:
    t = now.time().replace(second=0, microsecond=0)
    for period in periods:
        try:
            start, end = _parse(period[0]), _parse(period[1])
        except (ValueError, IndexError):
            continue
        if start == end:
            continue
        if start < end:
            if start <= t < end:
                return True
        elif t >= start or t < end:  # 跨午夜，例如 22:00–07:00
            return True
    return False


def decide(settings, env: Environment) -> Route:
    if in_quiet_period(env.now, settings.quiet_periods):
        return Route.QUIET
    if settings.idle_defer_min > 0 and env.idle_seconds >= settings.idle_defer_min * 60:
        return Route.DEFER
    if settings.dnd_fullscreen and env.fullscreen:
        return Route.FULLSCREEN
    return Route.SHOW
