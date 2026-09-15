import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "scripts" / "cover_compositor.py"
SPEC = importlib.util.spec_from_file_location("cover_compositor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CoverCompositorTests(unittest.TestCase):
    def make_source(self, path: Path) -> None:
        Image.new("RGB", (1200, 800), (224, 215, 198)).save(path)

    def test_brand_cover_records_verified_text_and_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            result = MODULE.compose(source, output, manifest, "brand-wide", "brand",
                                    "unused", "把灵感，拼成画面", "墨尘 / BLACK DUST")
            self.assertEqual(result["schema"], "black-dust-cover-v1")
            self.assertEqual(result["canvas_px"], [1672, 941])
            self.assertEqual(result["verified_text"]["brand"], "墨尘")
            self.assertEqual(result["verified_text"]["subtitle_accent"], "拼")
            self.assertEqual(result["verified_text"]["subtitle_underline"], "拼成画面")
            self.assertEqual(result["accent_hex"], "#FF5A1F")
            self.assertIn("role-weighted pigment load", result["text_rendering"]["surface"])
            self.assertIn("directional dry-brush", result["text_rendering"]["surface"])
            self.assertIn("holes and loose pieces excluded", result["text_rendering"]["occlusion_policy"])
            self.assertFalse(result["puzzle_elements_present"])
            self.assertEqual(len(result["text_boxes"]), 3)
            for box in result["puzzle_protected_boxes_normalized"]:
                self.assertTrue(all(0 <= value <= 1 for value in box))

    def test_article_lead_keeps_text_inside_center_square_safe_zone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            result = MODULE.compose(source, output, manifest, "wechat-lead", "article",
                                    "把灵感，拼成画面", "一个主题，一幅拼面", "墨尘 / BLACK DUST")
            safe = result["safe_zone_px"]
            title = next(item for item in result["text_boxes"] if item["role"] == "article_title")
            self.assertGreaterEqual(title["bbox_px"][0], safe[0])
            self.assertLessEqual(title["bbox_px"][2], safe[2])
            self.assertGreaterEqual(title["bbox_px"][1], safe[1])
            self.assertLessEqual(title["bbox_px"][3], safe[3])
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(loaded["verified_text"]["title"], "把灵感，拼成画面")

    def test_cli_default_is_continuous_brand_stage(self):
        args = MODULE.build_parser().parse_args(["in.png", "out.png", "--manifest", "out.json"])
        self.assertEqual(args.mode, "brand")
        self.assertEqual(args.preset, "brand-wide")
        self.assertEqual(args.layout, "auto")
        self.assertEqual(args.skill_color, "orange")

    def test_brand_cover_can_keep_skill_charcoal_and_leave_orange_to_subtitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            result = MODULE.compose(
                source, output, manifest, "twitter", "brand", "unused",
                "把灵感，拼成画面", "墨尘 / BLACK DUST", skill_color="charcoal",
            )
            self.assertEqual(result["english_mark_color"], "charcoal")
            rendered = Image.open(output).convert("RGB")
            skill_box = next(
                item["bbox_px"] for item in result["text_boxes"]
                if item["role"] == "english_mark"
            )
            crop = rendered.crop(tuple(skill_box))
            self.assertFalse(any(
                red > 180 and red > green * 1.7 and green > blue
                for red, green, blue in crop.getdata()
            ))

    def test_square_brand_lockup_separates_title_skill_and_subtitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            result = MODULE.compose(source, output, manifest, "xiaohongshu", "brand",
                                    "unused", "把灵感，拼成画面", "墨尘 / BLACK DUST")
            boxes = {item["role"]: item["bbox_px"] for item in result["text_boxes"]}
            pad = round(result["canvas_px"][0] * .025)
            self.assertLess(boxes["brand_title"][3] - pad,
                            boxes["english_mark"][1] + pad)
            self.assertLess(boxes["english_mark"][3] - pad,
                            boxes["subtitle"][1] + pad)
            self.assertEqual(result["layout"], "brand-lockup")
            self.assertEqual(result["text_rendering"]["cjk_skeleton"], "msyhbd.ttc")
            self.assertEqual(result["text_rendering"]["latin_skeleton"], "ARIALN.TTF")

    def test_article_brand_lockup_is_separated_and_center_crop_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            result = MODULE.compose(
                source, output, manifest, "wechat-lead", "article", "unused",
                "把灵感，拼成画面", "墨尘 / BLACK DUST", layout="brand-lockup",
            )
            boxes = {item["role"]: item["bbox_px"] for item in result["text_boxes"]}
            safe = result["safe_zone_px"]
            for box in boxes.values():
                self.assertGreaterEqual(box[0], safe[0])
                self.assertGreaterEqual(box[1], safe[1])
                self.assertLessEqual(box[2], safe[2])
                self.assertLessEqual(box[3], safe[3])
            pad = round(result["canvas_px"][1] * .025)
            self.assertLess(boxes["brand_title"][2] - pad,
                            boxes["english_mark"][0] + pad)
            self.assertLess(max(boxes["brand_title"][3], boxes["english_mark"][3]) - pad,
                            boxes["subtitle"][1] + pad)
            self.assertEqual(result["layout"], "brand-lockup")

    def test_wide_article_uses_subject_led_upper_left_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            result = MODULE.compose(source, output, manifest, "article-wide", "article",
                                    "驶向未完成", "木炭叙事 · 精确拼图", "墨尘 / ARTICLE STUDY")
            title = next(item for item in result["text_boxes"] if item["role"] == "article_title")
            subtitle = next(item for item in result["text_boxes"] if item["role"] == "article_subtitle")
            self.assertLess(title["bbox_px"][0], result["canvas_px"][0] * .10)
            self.assertLessEqual(title["bbox_px"][2], result["canvas_px"][0] * .30)
            self.assertLessEqual(subtitle["bbox_px"][2], result["canvas_px"][0] * .30)
            self.assertIsNone(result["safe_zone_px"])

    def test_twitter_article_is_exact_five_by_two_with_readable_semantic_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            title_text = "我们以为AI只用了三年，其实它准备了十多年"
            result = MODULE.compose(
                source, output, manifest, "twitter", "article",
                title_text, "", "", title_accent="十多年",
                title_underline="十多年",
            )
            title = next(item for item in result["text_boxes"] if item["role"] == "article_title")
            self.assertEqual(result["canvas_px"], [1500, 600])
            self.assertEqual(result["verified_text"]["title"], title_text)
            self.assertLess(title["bbox_px"][0], 1500 * .10)
            self.assertGreater(title["bbox_px"][2] - title["bbox_px"][0], 1500 * .30)
            self.assertLessEqual(title["bbox_px"][2], 1500 * .62)
            self.assertLessEqual(title["bbox_px"][3], 600 * .60)
            rendered = Image.open(output).convert("RGB")
            self.assertGreater(
                sum(1 for red, green, blue in rendered.getdata()
                    if red > 180 and red > green * 1.7 and green > blue),
                50,
            )

    def test_vertical_article_preserves_semantic_breaks_at_readable_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, manifest = root / "source.png", root / "cover.png", root / "cover.json"
            self.make_source(source)
            title_text = "GPT-6 Astra\n为什么烧配额\n这么快？"
            result = MODULE.compose(
                source, output, manifest, "xiaohongshu", "article",
                title_text, "", "", title_accent="烧",
                title_underline="烧配额",
            )
            title = next(item for item in result["text_boxes"] if item["role"] == "article_title")
            title_width = title["bbox_px"][2] - title["bbox_px"][0]
            self.assertEqual(result["verified_text"]["title"], title_text)
            self.assertEqual(result["verified_text"]["title_accent"], "烧")
            self.assertEqual(result["verified_text"]["title_underline"], "烧配额")
            self.assertNotIn("kicker", {item["role"] for item in result["text_boxes"]})
            self.assertGreater(title_width, result["canvas_px"][0] * .35)
            self.assertLessEqual(title["bbox_px"][2], result["canvas_px"][0] * .94)
            self.assertLessEqual(title["bbox_px"][3], result["canvas_px"][1] * .45)
            rendered = Image.open(output).convert("RGB")
            self.assertGreater(
                sum(1 for red, green, blue in rendered.getdata()
                    if red > 180 and red > green * 1.7 and green > blue),
                50,
            )

    def test_charcoal_pigment_load_rejects_a_flat_low_density_mark(self):
        image = Image.new("RGBA", (20, 20), (224, 215, 198, 255))
        mask = Image.new("L", image.size, 255)
        with self.assertRaises(ValueError):
            MODULE.apply_charcoal_mask(
                image, mask, MODULE.CHARCOAL, seed=1, pigment_load=.40
            )


if __name__ == "__main__":
    unittest.main()
