"""活動顏色：Google 日曆的 11 種標準活動顏色（colorId 1~11）。"""
from __future__ import annotations

# colorId → (中文名稱, 色碼)
EVENT_COLORS: dict[str, tuple[str, str]] = {
    "1": ("薰衣草紫", "#7986CB"),
    "2": ("鼠尾草綠", "#33B679"),
    "3": ("葡萄紫", "#8E24AA"),
    "4": ("火鶴紅", "#E67C73"),
    "5": ("香蕉黃", "#F6BF26"),
    "6": ("橘子橙", "#F4511E"),
    "7": ("孔雀藍", "#039BE5"),
    "8": ("石墨灰", "#616161"),
    "9": ("藍莓藍", "#3F51B5"),
    "10": ("羅勒綠", "#0B8043"),
    "11": ("番茄紅", "#D50000"),
}

DEFAULT_COLOR = "#E8789A"   # 沒有指定顏色時使用（桌寵主題粉）
HOLIDAY_COLOR = "#0B8043"


def color_hex(color_id: str, holiday: bool = False) -> str:
    if holiday:
        return HOLIDAY_COLOR
    return EVENT_COLORS.get(color_id, ("", DEFAULT_COLOR))[1]
