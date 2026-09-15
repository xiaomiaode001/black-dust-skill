import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class UnicodeCommandTests(unittest.TestCase):
    def legacy_environment(self):
        return {
            **os.environ,
            "PYTHONIOENCODING": "cp1252",
            "PYTHONUTF8": "0",
            "BLACK_DUST_FONT_PROFILE": "portable",
        }

    def test_chinese_help_survives_redirected_legacy_output(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "black-dust/scripts/cover_compositor.py"), "--help"],
            env=self.legacy_environment(), capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertIn("墨尘", result.stdout.decode("utf-8"))

    def test_installer_reports_chinese_directory_on_legacy_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "中文安装"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/install_skill.py"), "--target", str(target)],
                env=self.legacy_environment(), capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertIn("中文安装", result.stdout.decode("utf-8"))
            self.assertTrue((target / "black-dust/assets/fonts/mashanzheng/OFL.txt").is_file())


if __name__ == "__main__":
    unittest.main()
