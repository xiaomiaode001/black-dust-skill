import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "scripts" / "render_social_cover.py"
SPEC = importlib.util.spec_from_file_location("render_social_cover", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SocialCoverPipelineTests(unittest.TestCase):
    def test_utf8_request_renders_once_then_uses_content_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.png"
            output = root / "output"
            request = root / "request.json"
            Image.new("RGB", (1000, 400), (232, 223, 207)).save(base)
            request.write_text(
                json.dumps(
                    {
                        "base": str(base),
                        "output_dir": str(output),
                        "cover": {
                            "preset": "twitter",
                            "title": "速度缓存测试，保留中文",
                            "title_accent": "中文",
                            "title_underline": "中文",
                        },
                        "puzzle": {
                            "rows": 6,
                            "cols": 15,
                            "missing_count": 1,
                            "content_policy": "any",
                            "min_piece_detail": 0,
                            "seed": 17,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_audit = MODULE.puzzle_compositor.audit_manifest
            with mock.patch.object(
                MODULE.puzzle_compositor,
                "audit_manifest",
                wraps=original_audit,
            ) as audited:
                first = MODULE.render(request)
                second = MODULE.render(request)
                self.assertEqual(audited.call_count, 1)

            self.assertEqual(first["cache"]["cover_composite"], "rendered")
            self.assertEqual(first["cache"]["puzzle_composite_and_audit"], "rendered")
            self.assertEqual(second["cache"]["cover_composite"], "hit")
            self.assertEqual(second["cache"]["puzzle_composite_and_audit"], "hit")
            self.assertTrue(second["pair_audit_passed"])
            with Image.open(output / "final.png") as rendered:
                self.assertEqual(rendered.size, (1500, 600))
            cover = json.loads((output / "typeset.cover.json").read_text(encoding="utf-8"))
            self.assertEqual(cover["verified_text"]["title"], "速度缓存测试，保留中文")
            stored_audit = json.loads((output / "final.audit.json").read_text(encoding="utf-8"))
            self.assertTrue(stored_audit["promotion_verified"])
            independent = original_audit(output / "final.puzzle.json")
            self.assertTrue(independent["passed"], independent["errors"])

            previous_hash = cover["output_sha256"]
            replacement = MODULE.cover_compositor.BUNDLED_FONTS["cjk"]
            with mock.patch.object(MODULE.cover_compositor, "FONT_CJK_HAND", replacement):
                changed = MODULE.render(request)
                cached = MODULE.render(request)
            self.assertEqual(changed["cache"]["cover_composite"], "rendered")
            self.assertEqual(changed["cache"]["puzzle_composite_and_audit"], "rendered")
            self.assertTrue(changed["pair_audit_passed"])
            self.assertEqual(cached["cache"]["cover_composite"], "hit")
            updated = json.loads((output / "typeset.cover.json").read_text(encoding="utf-8"))
            self.assertNotEqual(updated["output_sha256"], previous_hash)
            self.assertEqual(
                updated["text_rendering"]["font_assets"]["cjk_hand"]["file"],
                replacement.name,
            )


if __name__ == "__main__":
    unittest.main()
