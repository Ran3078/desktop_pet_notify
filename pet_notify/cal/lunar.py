"""農曆換算：使用 Windows 10 以上內建的 ICU（icu.dll）中國曆法，不需額外套件。

找不到 ICU（例如舊版 Windows）時 lunar_date() 回傳 None，介面就不顯示農曆。
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

log = logging.getLogger(__name__)

MONTH_NAMES = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "臘"]
FESTIVALS = {(1, 1): "春節", (1, 15): "元宵", (5, 5): "端午", (7, 7): "七夕", (7, 15): "中元",
             (8, 15): "中秋", (9, 9): "重陽"}

_UCAL_TRADITIONAL = 0
_UCAL_MONTH, _UCAL_DATE, _UCAL_IS_LEAP_MONTH = 2, 5, 22


@dataclass(frozen=True)
class LunarDate:
    month: int
    day: int
    leap: bool = False

    @property
    def month_name(self) -> str:
        return ("閏" if self.leap else "") + MONTH_NAMES[self.month - 1] + "月"

    @property
    def day_name(self) -> str:
        d = self.day
        if d == 10:
            return "初十"
        if d == 20:
            return "二十"
        if d == 30:
            return "三十"
        prefix = "初十廿三"[d // 10]
        return prefix + "一二三四五六七八九"[d % 10 - 1]


class _IcuChineseCalendar:
    def __init__(self):
        self._lock = threading.Lock()
        self._cal = None
        if sys.platform != "win32":
            return
        try:
            icu = ctypes.WinDLL("icu.dll")
            icu.ucal_open.restype = ctypes.c_void_p
            icu.ucal_open.argtypes = [ctypes.c_wchar_p, ctypes.c_int32, ctypes.c_char_p, ctypes.c_int32,
                                      ctypes.POINTER(ctypes.c_int32)]
            icu.ucal_setMillis.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.POINTER(ctypes.c_int32)]
            icu.ucal_get.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32)]
            icu.ucal_get.restype = ctypes.c_int32
            err = ctypes.c_int32(0)
            # 用 UTC 計算：傳入當天 UTC 中午，避免時區造成跨日
            cal = icu.ucal_open("UTC", -1, b"zh_TW@calendar=chinese", _UCAL_TRADITIONAL, ctypes.byref(err))
            if not cal or err.value > 0:
                log.warning("ICU 中國曆法初始化失敗（錯誤碼 %s），不顯示農曆", err.value)
                return
            self._icu, self._cal = icu, cal
        except OSError:
            log.warning("找不到 icu.dll，不顯示農曆")

    @property
    def available(self) -> bool:
        return self._cal is not None

    def convert(self, d: date) -> LunarDate | None:
        if self._cal is None:
            return None
        noon = datetime.combine(d, time(12), timezone.utc)
        with self._lock:
            err = ctypes.c_int32(0)
            self._icu.ucal_setMillis(self._cal, noon.timestamp() * 1000, ctypes.byref(err))
            month = self._icu.ucal_get(self._cal, _UCAL_MONTH, ctypes.byref(err)) + 1
            day = self._icu.ucal_get(self._cal, _UCAL_DATE, ctypes.byref(err))
            leap = bool(self._icu.ucal_get(self._cal, _UCAL_IS_LEAP_MONTH, ctypes.byref(err)))
        if err.value > 0:
            return None
        return LunarDate(month, day, leap)


_calendar: _IcuChineseCalendar | None = None


def _get() -> _IcuChineseCalendar:
    global _calendar
    if _calendar is None:
        _calendar = _IcuChineseCalendar()
    return _calendar


def available() -> bool:
    return _get().available


@lru_cache(maxsize=2048)
def lunar_date(d: date) -> LunarDate | None:
    return _get().convert(d)


def festival(d: date) -> str:
    """農曆節日名稱（含除夕），沒有就回傳空字串。"""
    ld = lunar_date(d)
    if ld is None:
        return ""
    if not ld.leap and (ld.month, ld.day) in FESTIVALS:
        return FESTIVALS[(ld.month, ld.day)]
    nxt = lunar_date(d + timedelta(days=1))
    if nxt and (nxt.month, nxt.day, nxt.leap) == (1, 1, False):
        return "除夕"
    return ""


def short_label(d: date) -> str:
    """月曆格子用的短標籤：節日 > 初一顯示月份 > 日。"""
    ld = lunar_date(d)
    if ld is None:
        return ""
    return festival(d) or (ld.month_name if ld.day == 1 else ld.day_name)


def full_label(d: date) -> str:
    """例如「農曆八月廿五」、「農曆八月十五 中秋」。"""
    ld = lunar_date(d)
    if ld is None:
        return ""
    fest = festival(d)
    return f"農曆{ld.month_name}{ld.day_name}" + (f" {fest}" if fest else "")
