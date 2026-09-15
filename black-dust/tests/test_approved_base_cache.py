import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "scripts" / "approved_base_cache.py"
SPEC = importlib.util.spec_from_file_location("approved_base_cache", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ApprovedBaseCacheTests(unittest.TestCase):
    def test_exact_key_and_explicit_id_resolve_an_approved_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.png"
            cache = root / "cache"
            Image.new("RGB", (500, 200), (220, 210, 192)).save(base)

            registered = MODULE.register(
                cache,
                base,
                base_id="ai-history-wide",
                brief="AI 十年积累的时间剖面",
                aspect="5:2",
                theme_family="technology-history",
                composition_key="subject-left-title-right",
                user_approved=True,
            )
            by_id = MODULE.resolve(cache, base_id="ai-history-wide")
            exact = MODULE.resolve(
                cache,
                brief="AI 十年积累的时间剖面",
                aspect="5:2",
                theme_family="technology-history",
                composition_key="subject-left-title-right",
            )
            miss = MODULE.resolve(
                cache,
                brief="不同主题",
                aspect="5:2",
                theme_family="technology-history",
                composition_key="subject-left-title-right",
            )

            self.assertEqual(by_id["sha256"], registered["sha256"])
            self.assertEqual(exact["sha256"], registered["sha256"])
            self.assertIsNone(miss)

    def test_unapproved_registration_and_tampered_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.png"
            cache = root / "cache"
            Image.new("RGB", (500, 200), "white").save(base)

            with self.assertRaisesRegex(ValueError, "explicit user approval"):
                MODULE.register(
                    cache,
                    base,
                    base_id="draft",
                    brief="draft",
                    aspect="5:2",
                    theme_family="abstract",
                    composition_key="center",
                    user_approved=False,
                )

            registered = MODULE.register(
                cache,
                base,
                base_id="approved",
                brief="approved",
                aspect="5:2",
                theme_family="abstract",
                composition_key="center",
                user_approved=True,
            )
            Path(registered["resolved_path"]).write_bytes(b"tampered")
            self.assertIsNone(MODULE.resolve(cache, base_id="approved"))


if __name__ == "__main__":
    unittest.main()
