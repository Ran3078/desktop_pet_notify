"""重複規則：RecurrenceRule ↔ RRULE 字串，以及中文描述。

只處理常用的 FREQ / INTERVAL / BYDAY / UNTIL / COUNT；其他部分（例如 BYMONTHDAY、BYSETPOS）
會原封不動保留在 extra，確保在 Google 上建立的複雜規則來回編輯不會被破壞。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]   # 對應 date.weekday()
WEEKDAY_NAMES = dict(zip(WEEKDAY_CODES, "一二三四五六日"))
FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
UNIT = {"DAILY": "天", "WEEKLY": "週", "MONTHLY": "個月", "YEARLY": "年"}


@dataclass(frozen=True)
class RecurrenceRule:
    freq: str
    interval: int = 1
    byday: tuple[str, ...] = ()
    until: date | None = None
    count: int | None = None
    extra: tuple[tuple[str, str], ...] = field(default=())

    # ---- 轉換 ----
    def to_rrule(self, all_day: bool = False, tz=None) -> str:
        parts = [f"FREQ={self.freq}"]
        if self.interval > 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.byday:
            ordered = sorted(self.byday, key=lambda c: WEEKDAY_CODES.index(c) if c in WEEKDAY_CODES else 9)
            parts.append("BYDAY=" + ",".join(ordered))
        parts.extend(f"{k}={v}" for k, v in self.extra)
        if self.count:
            parts.append(f"COUNT={self.count}")
        elif self.until:
            if all_day:
                parts.append(f"UNTIL={self.until:%Y%m%d}")
            else:
                # 計時活動的 UNTIL 必須是 UTC 時間：取當地當天最後一秒
                end = datetime.combine(self.until, time(23, 59, 59), tz or datetime.now().astimezone().tzinfo)
                parts.append(f"UNTIL={end.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}")
        return "RRULE:" + ";".join(parts)

    @classmethod
    def parse(cls, text: str) -> "RecurrenceRule | None":
        text = text.strip()
        if text.upper().startswith("RRULE:"):
            text = text[6:]
        elif ":" in text:
            return None  # EXDATE / RDATE 等不是規則本身
        values: dict[str, str] = {}
        for part in text.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                values[k.strip().upper()] = v.strip()
        freq = values.pop("FREQ", "").upper()
        if freq not in FREQS:
            return None
        interval = int(values.pop("INTERVAL", "1") or 1)
        byday_raw = values.pop("BYDAY", "")
        byday = tuple(c for c in byday_raw.split(",") if c) if byday_raw else ()
        count = values.pop("COUNT", None)
        until_raw = values.pop("UNTIL", None)
        until = None
        if until_raw:
            until = _parse_until(until_raw)
        return cls(freq=freq, interval=max(1, interval), byday=byday, until=until,
                   count=int(count) if count else None, extra=tuple(values.items()))

    @classmethod
    def from_recurrence(cls, recurrence: list[str] | None) -> "RecurrenceRule | None":
        for line in recurrence or []:
            rule = cls.parse(line)
            if rule:
                return rule
        return None

    # ---- 描述 ----
    def describe(self, start: date | None = None) -> str:
        n = self.interval
        if self.freq == "DAILY":
            text = "每天" if n == 1 else f"每 {n} 天"
        elif self.freq == "WEEKLY":
            days = self.byday or ((WEEKDAY_CODES[start.weekday()],) if start else ())
            names = "、".join(WEEKDAY_NAMES.get(c[-2:], c) for c in
                             sorted(days, key=lambda c: WEEKDAY_CODES.index(c[-2:]) if c[-2:] in WEEKDAY_CODES else 9))
            if n == 1:
                text = f"每週{names}" if names else "每週"
            else:
                text = f"每 {n} 週的{names}" if names else f"每 {n} 週"
        elif self.freq == "MONTHLY":
            prefix = "每月" if n == 1 else f"每 {n} 個月"
            text = f"{prefix} {start.day} 日" if start and not self.extra else prefix
        else:
            prefix = "每年" if n == 1 else f"每 {n} 年"
            text = f"{prefix} {start.month} 月 {start.day} 日" if start else prefix
        if self.count:
            text += f"，共 {self.count} 次"
        elif self.until:
            text += f"，到 {self.until:%Y/%m/%d}"
        return text


def _parse_until(raw: str) -> date | None:
    raw = raw.strip().upper()
    try:
        if "T" in raw:
            dt = datetime.strptime(raw.rstrip("Z"), "%Y%m%dT%H%M%S")
            if raw.endswith("Z"):
                dt = dt.replace(tzinfo=timezone.utc).astimezone()
            return dt.date()
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def preset(kind: str, start: date) -> RecurrenceRule | None:
    """對話框的快速選項：none / daily / weekly / monthly / yearly。"""
    if kind == "daily":
        return RecurrenceRule("DAILY")
    if kind == "weekly":
        return RecurrenceRule("WEEKLY", byday=(WEEKDAY_CODES[start.weekday()],))
    if kind == "monthly":
        return RecurrenceRule("MONTHLY")
    if kind == "yearly":
        return RecurrenceRule("YEARLY")
    return None
