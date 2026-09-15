#!/usr/bin/env python3
"""Build lightweight GitHub gallery boards from the Black Dust study images."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


GROUPS = [
    ("01-portrait.webp", "01 PORTRAIT", ["1.png", "2.png", "3.png", "3（2）.png"]),
    ("02-animal.webp", "02 ANIMAL", ["4.png", "4（2）.png", "4（3）.png"]),
    ("03-still-life.webp", "03 STILL LIFE / PRODUCT", ["5.png", "5（2）.png", "5（3）.png"]),
    ("04-landscape.webp", "04 LANDSCAPE", ["6.png", "6（2）.png", "6（21）.png"]),
    ("05-architecture.webp", "05 ARCHITECTURE", ["6（3）.png", "6（4）.png", "6（5）.png"]),
    (
        "06-mechanical.webp",
        "06 MECHANICAL / TRANSIT",
        ["7.png", "7（2）.png", "7（3）.png", "8.png", "8（2）.png", "8（3）.png", "8（4）.png"],
    ),
    (
        "07-typography.webp",
        "07 CHINESE / ENGLISH TYPE",
        ["9.png", "9（2）.png", "9（3）.png", "10.png", "10（1）.png", "10（2）.png"],
    ),
    (
        "08-social-cover.webp",
        "08 SOCIAL COVER / CHARCOAL OBJECT",
        ["11.png", "11（2）.png", "11（3）.png", "11（5）.png", "11(6).png", "12.png", "13.png"],
    ),
]

FEATURED = {
    "01-portrait.webp": "3（2）.png",
    "02-animal.webp": "4（3）.png",
    "03-still-life.webp": "5（3）.png",
    "04-landscape.webp": "6（21）.png",
    "05-architecture.webp": "6（5）.png",
    "06-mechanical.webp": "8（4）.png",
    "07-typography.webp": "9（3）.png",
    "08-social-cover.webp": "11(6).png",
}
PREVIEW_SIZE = (1440, 810)

BOARD_WIDTH = 1440
MARGIN = 36
GAP = 22
HEADER = 76
LABEL = 34
CELL_WIDTH = (BOARD_WIDTH - MARGIN * 2 - GAP) // 2
IMAGE_HEIGHT = 360
CELL_HEIGHT = IMAGE_HEIGHT + LABEL
BACKGROUND = (239, 232, 219)
INK = (31, 29, 26)
MUTED = (93, 87, 79)


def font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def fitted(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((CELL_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)
    cell = Image.new("RGB", (CELL_WIDTH, IMAGE_HEIGHT), (222, 216, 205))
    x = (CELL_WIDTH - image.width) // 2
    y = (IMAGE_HEIGHT - image.height) // 2
    cell.paste(image, (x, y))
    return cell


def card_x(index: int, count: int) -> int:
    """Center the final unpaired card so odd boards do not end with dead space."""
    if count % 2 and index == count - 1:
        return (BOARD_WIDTH - CELL_WIDTH) // 2
    return MARGIN + (index % 2) * (CELL_WIDTH + GAP)


def build_board(source_dir: Path, destination: Path, title: str, names: list[str]) -> dict:
    missing = [name for name in names if not (source_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing gallery sources for {title}: {missing}")
    rows = (len(names) + 1) // 2
    height = MARGIN + HEADER + rows * CELL_HEIGHT + max(0, rows - 1) * GAP + MARGIN
    board = Image.new("RGB", (BOARD_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(board)
    draw.text((MARGIN, MARGIN), title, fill=INK, font=font(34))
    draw.line((MARGIN, MARGIN + 51, BOARD_WIDTH - MARGIN, MARGIN + 51), fill=MUTED, width=2)
    for index, name in enumerate(names):
        row = index // 2
        x = card_x(index, len(names))
        y = MARGIN + HEADER + row * (CELL_HEIGHT + GAP)
        board.paste(fitted(source_dir / name), (x, y))
        display_name = f"STUDY {index + 1:02d} / {len(names):02d}"
        draw.text((x + 8, y + IMAGE_HEIGHT + 7), display_name, fill=INK, font=font(18))
    destination.parent.mkdir(parents=True, exist_ok=True)
    board.save(destination, "WEBP", quality=82, method=6)
    return {"file": destination.name, "title": title, "sources": names, "size": list(board.size)}


def build_latest(source: Path, destination: Path) -> dict:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((1800, 720), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "WEBP", quality=86, method=6)
        return {"file": destination.name, "source": source.name, "size": list(image.size)}


def build_preview(source: Path, destination: Path) -> dict:
    """Use a shared 16:9 canvas without stretching or cropping the artwork."""
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)
        preview = Image.new("RGB", PREVIEW_SIZE, BACKGROUND)
        preview.paste(image, ((preview.width - image.width) // 2, (preview.height - image.height) // 2))
        preview.save(destination, "WEBP", quality=86, method=6)
    return {"file": destination.name, "source": source.name, "size": list(PREVIEW_SIZE)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="directory containing historical study images")
    parser.add_argument("--output", type=Path, default=Path("docs/gallery"), help="gallery output directory")
    parser.add_argument("--latest", type=Path, help="optional latest final image")
    args = parser.parse_args()

    source_dir = args.source.resolve()
    output_dir = args.output.resolve()
    entries = []
    for filename, title, names in GROUPS:
        entry = build_board(source_dir, output_dir / filename, title, names)
        preview_path = output_dir / f"{Path(filename).stem}-preview.webp"
        entry["preview"] = build_preview(source_dir / FEATURED[filename], preview_path)
        entries.append(entry)
    manifest = {"schema": "black-dust-gallery/v1", "historical_image_count": sum(len(item[2]) for item in GROUPS), "boards": entries}
    if args.latest:
        manifest["latest"] = build_latest(args.latest.resolve(), output_dir / "09-latest-cover.webp")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_dir), "historical_image_count": manifest["historical_image_count"], "board_count": len(entries), "latest": "latest" in manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
