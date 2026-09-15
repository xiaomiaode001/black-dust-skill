#!/usr/bin/env python3
"""Check the local Black Dust tree for GitHub release-readiness invariants."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "README.md",
    ROOT / "LICENSE",
    ROOT / "black-dust" / "LICENSE",
    ROOT / "black-dust" / "LICENSING.md",
    ROOT / "black-dust" / "ASSET_LICENSE.md",
    ROOT / "black-dust" / "assets" / "fonts" / "README.md",
    ROOT / ".gitignore",
    ROOT / "tools" / "install_skill.py",
    ROOT / "black-dust" / "SKILL.md",
    ROOT / "black-dust" / "agents" / "openai.yaml",
    ROOT / "black-dust" / "requirements.txt",
    ROOT / "examples" / "social-cover.request.example.json",
    ROOT / "docs" / "GALLERY.md",
    ROOT / "black-dust" / "CREATIVE-PROCESS.md",
    ROOT / "docs" / "gallery" / "manifest.json",
]
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".txt"}
WINDOWS_HOME = r"[A-Za-z]:[\\/]" + "Users"
WINDOWS_REFERENCE = r"[A-Za-z]:[\\/]" + "Midjourney"
MAC_HOME = "/" + "Users" + "/"
LINUX_HOME = "/" + "home" + "/"
LOCAL_PATH = re.compile(
    f"(?:{WINDOWS_HOME}|{WINDOWS_REFERENCE}|{re.escape(MAC_HOME)}|{re.escape(LINUX_HOME)})"
)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HTML_IMAGE = re.compile(r"<img\s+[^>]*src=[\"']([^\"']+)[\"']", re.IGNORECASE)
MAX_PUBLIC_FILE_BYTES = 10 * 1024 * 1024


def candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in {"output", "validation", ".git"} for part in relative.parts):
            continue
        if relative.as_posix() == "BLACK_DUST_PROJECT_KICKOFF.md":
            continue
        if "__pycache__" in relative.parts:
            continue
        files.append(path)
    return files


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    for path in REQUIRED:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    files = candidate_files()
    for path in files:
        relative = path.relative_to(ROOT)
        if path.stat().st_size > MAX_PUBLIC_FILE_BYTES:
            errors.append(f"public file exceeds 10 MiB: {relative}")
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"text file is not UTF-8: {relative}")
                continue
            if LOCAL_PATH.search(text):
                errors.append(f"local absolute path exposed: {relative}")

    readme = ROOT / "README.md"
    if readme.is_file():
        readme_text = readme.read_text(encoding="utf-8")
        image_targets = MARKDOWN_IMAGE.findall(readme_text) + HTML_IMAGE.findall(readme_text)
        for target in image_targets:
            if "://" in target or target.startswith("data:"):
                continue
            clean = target.strip("<>").split("#", 1)[0]
            linked = (ROOT / clean).resolve()
            if not linked.is_file():
                errors.append(f"README image not found: {target}")
        for target in MARKDOWN_LINK.findall(readme_text):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            clean = target.strip("<>").split("#", 1)[0]
            if clean and not (ROOT / clean).resolve().exists():
                errors.append(f"README link not found: {target}")
        for marker in ("## 中文", "## English", "python tools/install_skill.py", "$black-dust"):
            if marker not in readme_text:
                errors.append(f"README is missing bilingual/install marker: {marker}")
        for marker in ("Midjourney 8.2", "black-dust/CREATIVE-PROCESS.md"):
            if marker not in readme_text:
                errors.append(f"README is missing its production disclosure: {marker}")
        referenced_boards = {
            target.strip("<>").split("#", 1)[0]
            for target in image_targets
            if target.startswith("docs/gallery/") and re.search(r"/0[1-8]-", target)
        }
        if len(referenced_boards) != 8:
            errors.append("README must display all eight unique category previews")

    manifest_path = ROOT / "docs" / "gallery" / "manifest.json"

    creative_process = ROOT / "black-dust" / "CREATIVE-PROCESS.md"
    if creative_process.is_file():
        creative_text = creative_process.read_text(encoding="utf-8")
        for marker in ("## 中文", "## English", "Midjourney 8.2", "确定性", "deterministic"):
            if marker not in creative_text:
                errors.append(f"creative process is missing disclosure marker: {marker}")
        creative_targets = (
            MARKDOWN_IMAGE.findall(creative_text)
            + HTML_IMAGE.findall(creative_text)
            + MARKDOWN_LINK.findall(creative_text)
        )
        for target in creative_targets:
            if "://" in target or target.startswith(("data:", "#", "mailto:")):
                continue
            clean = target.strip("<>").split("#", 1)[0]
            if clean and not (creative_process.parent / clean).resolve().exists():
                errors.append(f"creative-process link not found: {target}")
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("historical_image_count") != 36:
            errors.append("gallery must account for all 36 historical images")
        boards = manifest.get("boards", [])
        gallery_text = (ROOT / "docs" / "GALLERY.md").read_text(encoding="utf-8")
        if len(boards) != 8:
            errors.append("gallery must contain exactly 8 category boards")
        for board in boards:
            if f"(gallery/{board.get('file')})" not in gallery_text:
                errors.append(f"full gallery must display category board: {board.get('file')}")
            board_path = manifest_path.parent / board.get("file", "")
            if not board_path.is_file():
                errors.append(f"gallery board missing: {board.get('file')}")
            else:
                with Image.open(board_path) as opened:
                    if list(opened.size) != board.get("size"):
                        errors.append(f"gallery board size does not match manifest: {board.get('file')}")
            preview = board.get("preview", {})
            preview_path = manifest_path.parent / preview.get("file", "")
            if not preview_path.is_file():
                errors.append(f"category preview missing: {board.get('file')}")
            else:
                with Image.open(preview_path) as opened:
                    if opened.size != (1440, 810) or list(opened.size) != preview.get("size"):
                        errors.append(f"category preview must use a 1440x810 canvas: {preview.get('file')}")
            if f"docs/gallery/{preview.get('file')}" not in referenced_boards:
                errors.append(f"README must display the category's declared preview: {preview.get('file')}")
        latest = manifest.get("latest", {})
        latest_path = manifest_path.parent / latest.get("file", "")
        if not latest_path.is_file():
            errors.append("latest verified cover is missing from gallery")
        else:
            with Image.open(latest_path) as opened:
                if list(opened.size) != latest.get("size"):
                    errors.append("latest verified cover size does not match manifest")

    gitignore = ROOT / ".gitignore"
    if gitignore.is_file() and "output/" not in gitignore.read_text(encoding="utf-8").splitlines():
        errors.append(".gitignore must exclude output/")

    root_license = ROOT / "LICENSE"
    installed_license = ROOT / "black-dust" / "LICENSE"
    if root_license.is_file() and installed_license.is_file():
        root_terms = root_license.read_text(encoding="utf-8")
        if not root_terms.startswith("MIT License\n"):
            errors.append("root LICENSE must contain the approved MIT license")
        if root_terms != installed_license.read_text(encoding="utf-8"):
            errors.append("installed skill LICENSE must match the root MIT license")
    asset_license = ROOT / "black-dust" / "ASSET_LICENSE.md"
    if asset_license.is_file():
        asset_terms = asset_license.read_text(encoding="utf-8")
        if "SPDX-License-Identifier: CC-BY-4.0" not in asset_terms:
            errors.append("image license must declare CC-BY-4.0")
        for scope in ("black-dust/assets/", "docs/gallery/"):
            if scope not in asset_terms:
                errors.append(f"image license is missing its scope: {scope}")
    if "<your-repository-url>" in readme.read_text(encoding="utf-8"):
        warnings.append("replace the README clone URL after the GitHub repository is created")

    font_root = ROOT / "black-dust" / "assets" / "fonts"
    font_readme = font_root / "README.md"
    if font_readme.is_file() and "SIL Open Font License" not in font_readme.read_text(encoding="utf-8"):
        errors.append("bundled fonts must carry their OFL notice")
    font_paths = list(font_root.rglob("*.ttf"))
    if len(font_paths) != 5:
        errors.append("release must contain all five bundled fonts")
    for font in font_paths:
        notice = font.parent / "OFL.txt"
        if not notice.is_file() or "SIL OPEN FONT LICENSE" not in notice.read_text(encoding="utf-8"):
            errors.append(f"bundled font is missing its OFL license: {font.relative_to(ROOT)}")

    result = {
        "schema": "black-dust-release-check/v1",
        "status": "failed" if errors else ("ready_with_warnings" if warnings else "ready"),
        "public_file_count": len(files),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
