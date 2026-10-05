"""去背與裁切（只用 QImage，不加額外套件）。

自動去背：從圖片四邊找出背景色，用 flood fill 把和邊緣相連、顏色在容差內的區域設成透明；
使用者在原圖上點選的顏色則是整張圖都去掉（例如被角色包住的背景空隙）。
"""
from __future__ import annotations

import logging
from collections import Counter, deque

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

log = logging.getLogger(__name__)

MAX_SIDE = 400            # 處理前先縮小，加快速度（最後影格也只有約 150px 高）
TRANSPARENT_RATIO = 0.02  # 透明像素超過這個比例，就視為「本來就去好背」
FEATHER_ALPHA = 170       # 邊緣羽化：緊鄰透明區的像素改成半透明

AUTO, ALPHA_ONLY, NONE = "auto", "alpha", "none"
SIDES = ("top", "bottom", "left", "right")
TOUCH_RATIO = 0.05        # 某一邊超過這個比例的像素不是背景 → 角色碰到這一邊（例如半身圖的下緣）
TOUCH_TOLERANCE = 24


def load_image(path: str) -> QImage:
    img = QImage(path)
    if img.isNull():
        raise ValueError(f"無法讀取圖片：{path}")
    return prepare(img)


def prepare(img: QImage) -> QImage:
    """轉成 ARGB32 並把長邊縮到 MAX_SIDE 以內。"""
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return img.convertToFormat(QImage.Format_ARGB32)


def _pixels(img: QImage) -> bytearray:
    """ARGB32 在 little-endian 下的位元組順序是 B, G, R, A。"""
    data = bytearray(img.constBits().tobytes())
    stride = img.bytesPerLine()
    w = img.width()
    if stride == w * 4:
        return data
    rows = [data[y * stride:y * stride + w * 4] for y in range(img.height())]
    return bytearray(b"".join(rows))


def _from_pixels(data: bytearray, w: int, h: int) -> QImage:
    return QImage(bytes(data), w, h, w * 4, QImage.Format_ARGB32).copy()


def has_transparency(img: QImage, ratio: float = TRANSPARENT_RATIO) -> bool:
    data = _pixels(img)
    total = len(data) // 4
    transparent = sum(1 for a in data[3::4] if a < 250)
    return transparent / max(1, total) > ratio


def color_at(img: QImage, x: int, y: int) -> tuple[int, int, int]:
    c = img.pixelColor(max(0, min(x, img.width() - 1)), max(0, min(y, img.height() - 1)))
    return c.red(), c.green(), c.blue()


def border_colors(img: QImage, max_colors: int = 3,
                  points: list[tuple[int, int]] | None = None) -> list[tuple[int, int, int]]:
    """邊緣（預設四邊，或指定的點）最常見的幾種顏色（量化後統計），當作背景色。"""
    w, h = img.width(), img.height()
    counter: Counter = Counter()
    samples = {}
    if points is None:
        points = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
        points += [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    for x, y in points:
        rgb = color_at(img, x, y)
        key = tuple(v // 24 for v in rgb)
        counter[key] += 1
        samples.setdefault(key, rgb)
    total = sum(counter.values())
    out = [samples[k] for k, n in counter.most_common(max_colors) if n / total >= 0.08]
    return out or [samples[counter.most_common(1)[0][0]]]


def _side_points(w: int, h: int, side: str) -> list[tuple[int, int]]:
    if side == "top":
        return [(x, 0) for x in range(w)]
    if side == "bottom":
        return [(x, h - 1) for x in range(w)]
    if side == "left":
        return [(0, y) for y in range(h)]
    return [(w - 1, y) for y in range(h)]


def side_ratios(img: QImage, bg: list[tuple[int, int, int]] | None = None) -> dict[str, float]:
    """每一邊「不是背景」的像素比例。"""
    bg = bg or border_colors(img)
    t2 = TOUCH_TOLERANCE * TOUCH_TOLERANCE * 3
    out = {}
    for side in SIDES:
        points = _side_points(img.width(), img.height(), side)
        hits = 0
        for x, y in points:
            c = img.pixelColor(x, y)
            if c.alpha() < 16:
                continue
            r, g, b = c.red(), c.green(), c.blue()
            if all((r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2 > t2 for cr, cg, cb in bg):
                hits += 1
        out[side] = hits / max(1, len(points))
    return out


def auto_seed_sides(img: QImage) -> set[str]:
    """自動決定要從哪些邊開始去背：角色碰到的邊不要用（不然會從那裡把角色內部的淺色吃掉）。"""
    ratios = side_ratios(img)
    sides = {side for side, r in ratios.items() if r <= TOUCH_RATIO}
    log.info("邊緣偵測：%s → 從 %s 開始去背",
             {k: round(v, 3) for k, v in ratios.items()}, sorted(sides) or "全部（四邊都被碰到）")
    return sides or set(SIDES)


def remove_background(img: QImage, mode: str = AUTO, tolerance: int = 40,
                      extra_colors: list[tuple[int, int, int]] | None = None,
                      seed_sides: set[str] | None = None) -> QImage:
    """回傳去背後的 ARGB32 圖片（尚未裁切）。seed_sides=None 表示自動偵測要從哪些邊開始。"""
    img = img.convertToFormat(QImage.Format_ARGB32)
    extra_colors = extra_colors or []
    if mode == NONE:
        out = img.copy()
        out.fill(Qt.transparent)
        from PySide6.QtGui import QPainter

        p = QPainter(out)
        p.drawImage(0, 0, img.convertToFormat(QImage.Format_RGB32))
        p.end()
        return out
    if mode == ALPHA_ONLY or (mode == AUTO and has_transparency(img) and not extra_colors):
        log.info("沿用圖片原本的透明背景")
        return img.copy()

    w, h = img.width(), img.height()
    data = _pixels(img)
    tol2 = tolerance * tolerance * 3
    if seed_sides is None:
        seed_sides = auto_seed_sides(img)
    bg_points = [pt for side in seed_sides for pt in _side_points(w, h, side)]
    bg = border_colors(img, points=bg_points) if bg_points else border_colors(img)
    log.info("自動去背：背景色 %s，容差 %d，額外顏色 %d 個，起點 %s", bg, tolerance, len(extra_colors),
             sorted(seed_sides))

    def near(i: int, colors) -> bool:
        b, g, r = data[i], data[i + 1], data[i + 2]
        for cr, cg, cb in colors:
            if (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2 <= tol2:
                return True
        return False

    removed = bytearray(w * h)  # 1 = 透明
    # 1) 和邊緣相連、接近背景色的區域
    queue: deque[int] = deque(y * w + x for x, y in bg_points)
    while queue:
        k = queue.popleft()
        if removed[k]:
            continue
        # 本來就透明，或顏色接近背景色，才算背景
        if data[k * 4 + 3] >= 16 and not near(k * 4, bg):
            continue
        removed[k] = 1
        x, y = k % w, k // w
        if x > 0 and not removed[k - 1]:
            queue.append(k - 1)
        if x < w - 1 and not removed[k + 1]:
            queue.append(k + 1)
        if y > 0 and not removed[k - w]:
            queue.append(k - w)
        if y < h - 1 and not removed[k + w]:
            queue.append(k + w)
    # 2) 使用者點選的顏色：整張圖都去掉
    if extra_colors:
        for k in range(w * h):
            if not removed[k] and near(k * 4, extra_colors):
                removed[k] = 1
    # 3) 套用：被判定為背景的像素設成透明
    for k in range(w * h):
        if removed[k]:
            data[k * 4 + 3] = 0
    # 4) 邊緣羽化
    for k in range(w * h):
        if removed[k] or data[k * 4 + 3] == 0:
            continue
        x, y = k % w, k // w
        if ((x > 0 and removed[k - 1]) or (x < w - 1 and removed[k + 1])
                or (y > 0 and removed[k - w]) or (y < h - 1 and removed[k + w])):
            data[k * 4 + 3] = min(data[k * 4 + 3], FEATHER_ALPHA)
    kept = w * h - sum(removed)
    log.info("去背完成：保留 %d / %d 像素", kept, w * h)
    return _from_pixels(data, w, h)


def opaque_bounds(img: QImage, threshold: int = 16) -> QRect | None:
    w, h = img.width(), img.height()
    data = _pixels(img)
    xs, ys = [], []
    for y in range(h):
        row = data[y * w * 4 + 3:(y + 1) * w * 4:4]
        cols = [x for x, a in enumerate(row) if a >= threshold]
        if cols:
            ys.append(y)
            xs.append(cols[0])
            xs.append(cols[-1])
    if not ys:
        return None
    return QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def trim(img: QImage, padding: int = 4) -> QImage:
    """裁掉四周的透明區域，保留 padding 的留白。完全透明時回傳原圖。"""
    box = opaque_bounds(img)
    if box is None:
        return img
    box = box.adjusted(-padding, -padding, padding, padding).intersected(img.rect())
    return img.copy(box)
