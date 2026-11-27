import unittest

from web_editor.ambient_fx import AMBIENT_FX_CATALOG, VALID_AMBIENT_FX, render_ambient_fx


class TestAmbientFx(unittest.TestCase):
    def test_catalog_count_and_ids(self):
        self.assertGreaterEqual(len(AMBIENT_FX_CATALOG), 14)  # off + 3 classic + 10 new
        self.assertIn("off", VALID_AMBIENT_FX)
        for expected in (
            "waves", "particles", "dual",
            "aurora", "plasma", "metaballs", "matrix", "synthgrid",
            "starfield", "circuit", "hexpulse", "radar", "fireflies",
        ):
            self.assertIn(expected, VALID_AMBIENT_FX)

    def test_off_returns_none(self):
        self.assertIsNone(
            render_ambient_fx("off", 960, 360, 1.0, 0.8, (0, 229, 255), (168, 85, 247), (255, 136, 0))
        )

    def test_all_effects_render_rgba(self):
        c1, c2, c3 = (0, 229, 255), (168, 85, 247), (255, 136, 0)
        for item in AMBIENT_FX_CATALOG:
            mid = item["id"]
            if mid == "off":
                continue
            img = render_ambient_fx(mid, 960, 360, 2.5, 0.8, c1, c2, c3)
            self.assertIsNotNone(img, f"Effect {mid} returned None")
            self.assertEqual(img.size, (960, 360))
            self.assertEqual(img.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
