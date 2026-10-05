import random
import unittest

from pet_notify.pet import physics
from pet_notify.pet.behavior import BehaviorInput, PetBehavior
from pet_notify.pet.physics import WALK_SPEED, Bounds
from pet_notify.pet.skins.base import ANGRY, DRAG, HAPPY, WALK

B = Bounds(left=-24, right=1700, top=0, bottom=900)


class PhysicsTest(unittest.TestCase):
    def test_stays_where_placed(self):
        # 沒有重力：放在半空中不會掉下來
        x, y, d = physics.step(500, 300, 1.0, B)
        self.assertEqual((x, y, d), (500, 300, 0))

    def test_walk_keeps_height(self):
        x, y, d = physics.step(500, 300, 1.0, B, walk_dir=1)
        self.assertAlmostEqual(x, 500 + WALK_SPEED)
        self.assertEqual((y, d), (300, 1))

    def test_turns_at_screen_edges(self):
        x, _, d = physics.step(B.right - 1, 300, 1.0, B, walk_dir=1)
        self.assertEqual((x, d), (B.right, -1))
        x, _, d = physics.step(B.left + 1, 300, 1.0, B, walk_dir=-1)
        self.assertEqual((x, d), (B.left, 1))

    def test_clamp_inside_screen(self):
        self.assertEqual(physics.clamp(-500, -500, B), (B.left, B.top))
        self.assertEqual(physics.clamp(9999, 9999, B), (B.right, B.bottom))
        self.assertEqual(physics.clamp(100, 200, B), (100, 200))

    def test_step_pulls_back_offscreen_position(self):
        # 例如解析度變小後，舊位置超出螢幕
        x, y, _ = physics.step(5000, 5000, 0.03, B)
        self.assertEqual((x, y), (B.right, B.bottom))


class BehaviorTest(unittest.TestCase):
    def test_drag_state(self):
        b = PetBehavior(random.Random(0))
        b.update(0.03, BehaviorInput(dragging=True))
        self.assertEqual(b.state, DRAG)

    def test_click_happy_then_angry(self):
        b = PetBehavior(random.Random(0))
        self.assertEqual(b.on_click(), HAPPY)
        for _ in range(3):
            b.on_click()
        self.assertEqual(b.on_click(), ANGRY)

    def test_walks_when_enabled_only(self):
        b = PetBehavior(random.Random(0))
        seen = set()
        for _ in range(30 * 120):
            b.update(1 / 30, BehaviorInput(walk_enabled=False))
            seen.add(b.state)
        self.assertNotIn(WALK, seen)
        b = PetBehavior(random.Random(0))
        for _ in range(30 * 120):
            b.update(1 / 30, BehaviorInput())
            seen.add(b.state)
        self.assertIn(WALK, seen)


if __name__ == "__main__":
    unittest.main()
