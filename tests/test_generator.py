import json
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

from pet_notify.pet.generator import animator, background  # noqa: E402
from pet_notify.pet.generator.generator import GenerateOptions, LocalGenerator, available_generators  # noqa: E402
from pet_notify.pet.generator.skin_writer import slugify, unique_dir, write_skin  # noqa: E402
from pet_notify.pet.skins.sprite_skin import SpriteSkin  # noqa: E402


def circle_on(bg: str, size=120, radius=40, color="#E53935", alpha_bg=False) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent if alpha_bg else QColor(bg))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(size / 2, size / 2), radius, radius)
    p.end()
    return img


def alpha(img: QImage, x: int, y: int) -> int:
    return img.pixelColor(x, y).alpha()


class BackgroundTest(unittest.TestCase):
    def test_white_background_removed(self):
        out = background.remove_background(circle_on("#FFFFFF"))
        self.assertEqual(alpha(out, 2, 2), 0)
        self.assertEqual(alpha(out, 60, 60), 255)

    def test_existing_alpha_kept(self):
        src = circle_on("", alpha_bg=True)
        self.assertTrue(background.has_transparency(src))
        out = background.remove_background(src)
        self.assertEqual(alpha(out, 60, 60), 255)
        self.assertEqual(alpha(out, 2, 2), 0)

    def test_enclosed_hole_needs_picked_color(self):
        # 紅圓中間有一塊白色（被包住、和邊緣不相連）
        img = circle_on("#FFFFFF")
        p = QPainter(img)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(60, 60), 8, 8)
        p.end()
        auto = background.remove_background(img)
        self.assertEqual(alpha(auto, 60, 60), 255)  # 自動模式只去掉和邊緣相連的
        picked = background.remove_background(img, extra_colors=[(255, 255, 255)])
        self.assertEqual(alpha(picked, 60, 60), 0)

    def test_tolerance(self):
        img = circle_on("#FFFFFF", color="#F0F0F0")  # 和背景很接近的淺灰
        strict = background.remove_background(img, tolerance=5)
        loose = background.remove_background(img, tolerance=40)
        self.assertEqual(alpha(strict, 60, 60), 255)
        self.assertEqual(alpha(loose, 60, 60), 0)

    def test_none_mode_keeps_everything(self):
        out = background.remove_background(circle_on("#FFFFFF"), mode=background.NONE)
        self.assertEqual(alpha(out, 2, 2), 255)

    def test_trim(self):
        out = background.trim(background.remove_background(circle_on("#FFFFFF")), padding=2)
        self.assertTrue(80 <= out.width() <= 86 and 80 <= out.height() <= 86, (out.width(), out.height()))

    def test_border_colors(self):
        self.assertEqual(background.border_colors(circle_on("#336699"))[0], (0x33, 0x66, 0x99))

    def test_prepare_downscales(self):
        big = QImage(1600, 800, QImage.Format_RGB32)
        big.fill(QColor("white"))
        small = background.prepare(big)
        self.assertEqual((small.width(), small.height()), (background.MAX_SIDE, background.MAX_SIDE // 2))


def bottom_row(img: QImage) -> int:
    for y in range(img.height() - 1, -1, -1):
        if any(img.pixelColor(x, y).alpha() > 40 for x in range(0, img.width(), 2)):
            return y
    return -1


class AnimatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cut = LocalGenerator().cutout(circle_on("#FFFFFF", color="#4477CC"), GenerateOptions())
        cls.states = animator.animate(cut)

    def test_all_states_and_sizes(self):
        self.assertEqual(set(self.states), set(animator.STATES))
        for state, (fps, frames) in self.states.items():
            self.assertGreater(fps, 0)
            self.assertEqual(len(frames), len(animator.STATES[state][1]))
            for f in frames:
                self.assertEqual((f.width(), f.height()), (animator.FRAME, animator.FRAME))

    def test_feet_on_ground_when_not_jumping(self):
        ground = animator.FRAME - animator.BOTTOM_MARGIN - 1
        for state in ("idle", "sit", "stretch", "pomodoro"):
            for f in self.states[state][1]:
                self.assertLessEqual(abs(bottom_row(f) - ground), 2, state)

    def test_hops_leave_ground(self):
        frames = self.states["alert"][1]
        self.assertLess(min(bottom_row(f) for f in frames), animator.FRAME - 20)

    def test_angry_is_red(self):
        normal = self.states["idle"][1][0].pixelColor(100, 150)
        angry = self.states["angry"][1][0].pixelColor(100, 150)
        self.assertGreater(angry.red(), normal.red())


class WriterTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("  我的 小狗 "), "我的-小狗")
        self.assertEqual(slugify('a<b>:c"/d\\e|f?g*'), "abcdefg")
        self.assertEqual(slugify("..."), "my-pet")

    def test_write_and_load(self):
        ch = LocalGenerator().generate(circle_on("#FFFFFF"), GenerateOptions())
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skin_id, folder = write_skin(ch, "小紅球", root=root)
            self.assertEqual(skin_id, "dir:小紅球")
            manifest = json.loads((folder / "skin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "小紅球")
            self.assertEqual(manifest["frame_size"], [animator.FRAME, animator.FRAME])
            skin = SpriteSkin(folder)
            self.assertEqual(skin.name, "小紅球")
            # 重名自動加序號
            skin_id2, _ = write_skin(ch, "小紅球", root=root)
            self.assertEqual(skin_id2, "dir:小紅球-2")
            self.assertEqual(unique_dir(root, "小紅球").name, "小紅球-3")

    def test_fully_transparent_rejected(self):
        blank = QImage(50, 50, QImage.Format_ARGB32)
        blank.fill(Qt.transparent)
        with self.assertRaises(ValueError):
            LocalGenerator().generate(blank, GenerateOptions(bg_mode=background.ALPHA_ONLY))

    def test_generators(self):
        self.assertEqual([g.id for g in available_generators()], ["local"])



class TouchingSidesTest(unittest.TestCase):
    """半身圖：角色被下緣切到，臉和身體是和背景一樣的白色。"""

    def make(self) -> QImage:
        img = QImage(120, 120, QImage.Format_ARGB32)
        img.fill(QColor("#FCFAFA"))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QPen

        p.setPen(QPen(QColor("#222222"), 4))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(60, 110), 45, 70)  # 白色身體，下半部超出圖片
        p.end()
        return img

    def test_detects_bottom(self):
        img = self.make()
        ratios = background.side_ratios(img)
        self.assertGreater(ratios["bottom"], background.TOUCH_RATIO)
        self.assertEqual(background.auto_seed_sides(img), {"top", "left", "right"})

    def test_white_body_kept_with_auto_sides(self):
        img = self.make()
        auto = background.remove_background(img)
        self.assertEqual(alpha(auto, 60, 100), 255)   # 白色身體保留
        self.assertEqual(alpha(auto, 3, 3), 0)        # 外面的背景去掉
        all_sides = background.remove_background(img, seed_sides=set(background.SIDES))
        self.assertEqual(alpha(all_sides, 60, 100), 0)  # 舊行為：從下緣把身體吃掉

    def test_all_sides_touched_falls_back(self):
        img = QImage(60, 60, QImage.Format_ARGB32)
        img.fill(QColor("#336699"))
        p = QPainter(img)
        p.fillRect(0, 0, 60, 6, QColor("#EEEEEE"))
        p.fillRect(0, 54, 60, 6, QColor("#EEEEEE"))
        p.end()
        self.assertEqual(background.auto_seed_sides(img), set(background.SIDES))


if __name__ == "__main__":
    unittest.main()
