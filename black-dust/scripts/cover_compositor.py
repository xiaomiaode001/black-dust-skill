#!/usr/bin/env python3
"""Deterministic typography stage for Black Dust social and article covers.

The input must be a continuous, uncut image. This script crops it to a named
canvas, draws verified text, and records normalized protection boxes for the
later exact-jigsaw stage. It intentionally does not draw puzzle seams.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat


ORANGE = (255, 90, 31, 255)
CHARCOAL = (30, 29, 27, 255)
GRAPHITE = (67, 64, 60, 255)
FONT_ROOT = Path(__file__).resolve().parents[1] / "assets" / "fonts"
BUNDLED_FONTS = {
    "cjk_bold": FONT_ROOT / "zcoolqingkehuangyou" / "ZCOOLQingKeHuangYou-Regular.ttf",
    "cjk": FONT_ROOT / "zcoolxiaowei" / "ZCOOLXiaoWei-Regular.ttf",
    "cjk_hand": FONT_ROOT / "mashanzheng" / "MaShanZheng-Regular.ttf",
    "latin_narrow": FONT_ROOT / "barlowcondensed" / "BarlowCondensed-Regular.ttf",
    "latin_hand": FONT_ROOT / "kalam" / "Kalam-Regular.ttf",
}


def select_font(preferred: Path, bundled: Path, profile: str | None = None) -> Path:
    """Retain installed design fonts, with a redistributable cross-platform fallback."""
    profile = profile or os.environ.get("BLACK_DUST_FONT_PROFILE", "auto")
    if profile not in {"auto", "portable"}:
        raise ValueError("BLACK_DUST_FONT_PROFILE must be auto or portable")
    if profile == "auto" and preferred.is_file():
        return preferred
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(f"Bundled font is missing; reinstall the complete skill: {bundled}")


FONT_CJK_BOLD = select_font(Path(r"C:\Windows\Fonts\msyhbd.ttc"), BUNDLED_FONTS["cjk_bold"])
FONT_CJK = select_font(Path(r"C:\Windows\Fonts\msyh.ttc"), BUNDLED_FONTS["cjk"])
FONT_CJK_HAND = select_font(Path(r"C:\Windows\Fonts\STXINWEI.TTF"), BUNDLED_FONTS["cjk_hand"])
FONT_LATIN_NARROW = select_font(Path(r"C:\Windows\Fonts\ARIALN.TTF"), BUNDLED_FONTS["latin_narrow"])
FONT_LATIN_HAND = select_font(Path(r"C:\Windows\Fonts\Inkfree.ttf"), BUNDLED_FONTS["latin_hand"])


@dataclass(frozen=True)
class Preset:
    width: int
    height: int
    role: str
    anchor: tuple[float, float]
    safe_zone: tuple[int, int, int, int] | None = None


PRESETS = {
    "brand-wide": Preset(1672, 941, "wide_social_brand_cover", (0.50, 0.50)),
    "article-wide": Preset(1500, 844, "wide_article_theme_cover", (0.50, 0.50)),
    "twitter": Preset(1500, 600, "wide_social_cover", (0.50, 0.50)),
    "xiaohongshu": Preset(1080, 1440, "note_cover", (0.50, 0.50)),
    "wechat-lead": Preset(
        900,
        383,
        "article_lead_cover",
        (0.50, 0.62),
        (258, 0, 641, 383),
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"Required deterministic font is missing: {path}")
    return ImageFont.truetype(str(path), max(8, round(size)))


def font_fingerprint(mode: str = "article", layout: str = "theme-title") -> dict:
    """Include actual font bytes in manifests and cache keys across machines."""
    if mode == "brand" or layout == "brand-lockup":
        fonts = {"cjk_bold": FONT_CJK_BOLD, "cjk": FONT_CJK, "latin_narrow": FONT_LATIN_NARROW}
    else:
        fonts = {"cjk_hand": FONT_CJK_HAND, "latin_hand": FONT_LATIN_HAND}
    return {role: {"file": path.name, "sha256": sha256(path)} for role, path in fonts.items()}


def text_bbox(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
              font: ImageFont.FreeTypeFont, spacing: int = 4) -> tuple[int, int, int, int]:
    return tuple(int(v) for v in draw.multiline_textbbox(xy, text, font=font, spacing=spacing))


def expand_box(box: tuple[int, int, int, int], pad: int,
               size: tuple[int, int]) -> tuple[int, int, int, int]:
    return (
        max(0, box[0] - pad),
        max(0, box[1] - pad),
        min(size[0], box[2] + pad),
        min(size[1], box[3] + pad),
    )


def normalized(box: tuple[int, int, int, int], size: tuple[int, int]) -> list[float]:
    return [round(box[0] / size[0], 6), round(box[1] / size[1], 6),
            round(box[2] / size[0], 6), round(box[3] / size[1], 6)]


def apply_charcoal_mask(image: Image.Image, mask: Image.Image,
                        fill: tuple[int, int, int, int], seed: int,
                        pigment_load: float = .90) -> None:
    """Lay pigment into a text mask with directional rubs, not salt-and-pepper noise."""
    box = mask.getbbox()
    if not box:
        return
    if not .55 <= pigment_load <= 1.0:
        raise ValueError("pigment_load must be between 0.55 and 1.0")
    rng = random.Random(seed)
    width, height = box[2] - box[0], box[3] - box[1]
    low_w, low_h = max(2, width // 20), max(2, height // 14)
    coarse = Image.new("L", (low_w, low_h))
    # Broad pressure variation creates a compact charcoal body. Role-specific
    # pigment load keeps the main title dense while subtitles remain lighter.
    coarse_low = round(140 + 80 * pigment_load)
    coarse.putdata([rng.randint(coarse_low, 255) for _ in range(low_w * low_h)])
    texture = coarse.resize((width, height), Image.Resampling.BICUBIC)
    marks = ImageDraw.Draw(texture)
    for _ in range(max(6, width * height // 5200)):
        x = rng.randint(0, max(0, width - 1))
        y = rng.randint(0, max(0, height - 1))
        length = rng.randint(max(4, width // 55), max(7, width // 22))
        drift = rng.randint(-2, 2)
        mark_low = round(98 + 54 * pigment_load)
        marks.line((x, y, min(width - 1, x + length), max(0, min(height - 1, y + drift))),
                   fill=rng.randint(mark_low, min(218, mark_low + 58)),
                   width=max(1, height // 110))
    # Sample the actual paper under the glyph. Fine height differences interrupt
    # pigment naturally; they do not create synthetic speckles or repeated gaps.
    surface = image.crop(box).convert("L")
    surface_blur = surface.filter(ImageFilter.GaussianBlur(max(.75, min(2.2, height / 85))))
    surface_detail = ImageChops.difference(surface, surface_blur)
    tooth_floor = round(145 + 55 * pigment_load)
    paper_tooth = surface_detail.point(
        lambda value: max(tooth_floor, 255 - min(255 - tooth_floor, value * 5))
    )
    texture = ImageChops.multiply(texture, paper_tooth)
    # Dense charcoal still retains micro-tooth; it should not dissolve into a
    # pale distressed print. Blend toward full pigment according to role.
    body_mix = .10 + .24 * pigment_load
    texture = Image.blend(texture, Image.new("L", (width, height), 255), body_mix)
    local_mask = mask.crop(box)
    opacity = .82 + .18 * pigment_load
    alpha = ImageChops.multiply(local_mask, texture).point(
        lambda value: round(value * opacity)
    )
    # A very low, soft rub around the stroke keeps the edge physical without
    # turning the letter into a generic glow or embossed decal.
    halo = local_mask.filter(ImageFilter.GaussianBlur(max(.55, height / 150))).point(
        lambda value: round(value * (.035 + .025 * pigment_load))
    )
    pigment = Image.new("RGBA", image.size, (0, 0, 0, 0))
    halo_layer = Image.new("RGBA", (width, height), fill[:3] + (0,))
    halo_layer.putalpha(halo)
    pigment.alpha_composite(halo_layer, (box[0], box[1]))
    face_layer = Image.new("RGBA", (width, height), fill[:3] + (0,))
    face_layer.putalpha(alpha)
    pigment.alpha_composite(face_layer, (box[0], box[1]))
    image.alpha_composite(pigment)


def ensure_text_visibility(image: Image.Image, mask: Image.Image,
                           fill: tuple[int, int, int, int]) -> None:
    """Quiet a locally conflicting scene without adding a visible label box."""
    box = mask.getbbox()
    if not box:
        return
    local_mask = mask.crop(box)
    local_luma = ImageStat.Stat(image.crop(box).convert("L"), mask=local_mask).mean[0]
    ink_luma = .2126 * fill[0] + .7152 * fill[1] + .0722 * fill[2]
    if abs(local_luma - ink_luma) >= 74:
        return
    height = max(1, box[3] - box[1])
    quiet = local_mask.filter(ImageFilter.GaussianBlur(max(5, height / 7))).point(
        lambda value: round(value * .24)
    )
    tone = (242, 236, 224, 0) if ink_luma < 128 else (24, 23, 21, 0)
    field = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), tone)
    field.putalpha(quiet)
    image.alpha_composite(field, (box[0], box[1]))


def draw_charcoal_text(image: Image.Image, xy: tuple[int, int], text: str,
                       font: ImageFont.FreeTypeFont,
                       fill: tuple[int, int, int, int], seed: int,
                       spacing: int = 4, stroke_width: int = 0,
                       pigment_load: float = .90) -> tuple[int, int, int, int]:
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.multiline_text(xy, text, font=font, fill=255, spacing=spacing,
                             stroke_width=stroke_width, stroke_fill=255)
    box = mask.getbbox()
    ensure_text_visibility(image, mask, fill)
    apply_charcoal_mask(image, mask, fill, seed, pigment_load)
    return tuple(int(v) for v in box) if box else (xy[0], xy[1], xy[0], xy[1])


def draw_tracked(image: Image.Image, xy: tuple[int, int], text: str,
                 font: ImageFont.FreeTypeFont, fill: tuple[int, int, int, int],
                 tracking: int, seed: int,
                 pigment_load: float = .86,
                 x_scale: float = 1.0) -> tuple[int, int, int, int]:
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    rng = random.Random(seed)
    x, y = xy
    start = x
    top = y
    bottom = y
    for char in text:
        # Tiny baseline changes preserve legibility while avoiding the rigid,
        # typeset rhythm that makes a charcoal title look like a flat sticker.
        jitter_y = rng.choice((-1, 0, 0, 0, 1)) * max(1, round(font.size * .018))
        draw.text((x, y + jitter_y), char, font=font, fill=255)
        bounds = draw.textbbox((x, y + jitter_y), char, font=font)
        x += round(draw.textlength(char, font=font)) + tracking
        top = min(top, bounds[1])
        bottom = max(bottom, bounds[3])
    box = (start, top, max(start, x - tracking), bottom)
    # The approved lockup uses a genuinely condensed editorial wordmark.  The
    # Windows Arial Narrow skeleton is retained for portability, then its
    # rendered mask is compressed horizontally so the letter strokes stay
    # tall and narrow instead of reading as a wide sans title.
    if not 0.45 <= x_scale <= 1.0:
        raise ValueError("x_scale must be between 0.45 and 1.0")
    if x_scale != 1.0:
        crop_right = min(image.width, max(start + 1, round(box[2])))
        cropped = mask.crop((start, 0, crop_right, image.height))
        scaled = cropped.resize(
            (max(1, round(cropped.width * x_scale),), cropped.height),
            Image.Resampling.LANCZOS,
        )
        mask = Image.new("L", image.size, 0)
        mask.paste(scaled, (start, 0))
        box = mask.getbbox() or (start, top, start, bottom)
    ensure_text_visibility(image, mask, fill)
    apply_charcoal_mask(image, mask, fill, seed, pigment_load)
    return box


def fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: Path,
             start_size: int, max_width: int, multiline: bool = False,
             spacing: int = 4) -> ImageFont.FreeTypeFont:
    size = start_size
    while size >= 12:
        font = load_font(font_path, size)
        if multiline:
            bounds = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
        else:
            bounds = draw.textbbox((0, 0), text, font=font)
        if bounds[2] - bounds[0] <= max_width:
            return font
        size -= 2
    return load_font(font_path, 12)


def draw_accented_line(image: Image.Image, xy: tuple[int, int], text: str,
                       accent: str, font: ImageFont.FreeTypeFont,
                       base_fill=CHARCOAL, accent_fill=ORANGE,
                       seed: int = 41,
                       pigment_load: float = .76) -> tuple[int, int, int, int]:
    draw = ImageDraw.Draw(image, "RGBA")
    x, y = xy
    if not accent or accent not in text:
        return draw_charcoal_text(
            image, (x, y), text, font, base_fill, seed, pigment_load=pigment_load
        )
    before, after = text.split(accent, 1)
    draw_charcoal_text(
        image, (x, y), before, font, base_fill, seed, pigment_load=pigment_load
    )
    x2 = x + round(draw.textlength(before, font=font))
    draw_charcoal_text(
        image, (x2, y), accent, font, accent_fill, seed + 1,
        pigment_load=min(1.0, pigment_load + .08),
    )
    x3 = x2 + round(draw.textlength(accent, font=font))
    draw_charcoal_text(
        image, (x3, y), after, font, base_fill, seed + 2,
        pigment_load=pigment_load,
    )
    return tuple(int(v) for v in draw.textbbox((x, y), text, font=font))


def draw_accented_multiline(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    accent: str,
    font: ImageFont.FreeTypeFont,
    spacing: int = 4,
    stroke_width: int = 0,
    base_fill=CHARCOAL,
    accent_fill=ORANGE,
    seed: int = 139,
    pigment_load: float = .94,
) -> tuple[int, int, int, int]:
    """Draw one semantic accent without leaving dark pigment beneath it."""
    if not accent or accent not in text:
        return draw_charcoal_text(
            image, xy, text, font, base_fill, seed, spacing,
            stroke_width, pigment_load,
        )

    full_mask = Image.new("L", image.size, 0)
    full_draw = ImageDraw.Draw(full_mask)
    full_draw.multiline_text(
        xy, text, font=font, fill=255, spacing=spacing,
        stroke_width=stroke_width, stroke_fill=255,
    )
    accent_mask = Image.new("L", image.size, 0)
    accent_draw = ImageDraw.Draw(accent_mask)
    measure = ImageDraw.Draw(Image.new("L", (1, 1), 0))
    line_advance = (
        measure.textbbox((0, 0), "A", font=font, stroke_width=stroke_width)[3]
        + stroke_width + spacing
    )
    accented = False
    for line_index, line in enumerate(text.split("\n")):
        if accented or accent not in line:
            continue
        before = line.split(accent, 1)[0]
        accent_x = xy[0] + round(measure.textlength(before, font=font))
        accent_y = xy[1] + line_index * line_advance
        accent_draw.text(
            (accent_x, accent_y), accent, font=font, fill=255,
            stroke_width=stroke_width, stroke_fill=255,
        )
        accented = True

    base_mask = ImageChops.subtract(full_mask, accent_mask)
    ensure_text_visibility(image, full_mask, base_fill)
    apply_charcoal_mask(image, base_mask, base_fill, seed, pigment_load)
    apply_charcoal_mask(
        image, accent_mask, accent_fill, seed + 1,
        min(1.0, pigment_load + .04),
    )
    box = full_mask.getbbox()
    return tuple(int(value) for value in box) if box else (xy[0], xy[1], xy[0], xy[1])


def draw_charcoal_underline(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    target: str,
    font: ImageFont.FreeTypeFont,
    spacing: int = 4,
    seed: int = 181,
) -> tuple[int, int, int, int] | None:
    """Add one restrained, pressure-varied charcoal underline to a title phrase."""
    if not target or target not in text:
        return None
    measure = ImageDraw.Draw(Image.new("L", (1, 1), 0))
    line_advance = measure.textbbox((0, 0), "A", font=font)[3] + spacing
    target_line = target_before = None
    line_index = 0
    for index, line in enumerate(text.split("\n")):
        if target in line:
            target_line = line
            target_before = line.split(target, 1)[0]
            line_index = index
            break
    if target_line is None or target_before is None:
        return None

    x0 = xy[0] + round(measure.textlength(target_before, font=font))
    target_width = round(measure.textlength(target, font=font))
    lead_in = max(3, round(font.size * .035))
    tail_lift = max(2, round(font.size * .020))
    x0 -= lead_in
    # The hand lifts just before the final glyph edge; this keeps the mark
    # gestural and leaves a clean safety gap for nearby puzzle punctuation.
    x1 = x0 + target_width + lead_in - tail_lift
    line_y = xy[1] + line_index * line_advance
    line_bottom = measure.textbbox((xy[0], line_y), target_line, font=font)[3]
    stroke = max(6, round(font.size * .065))
    underline_y = line_bottom + max(3, round(font.size * .035))

    rng = random.Random(seed)
    mask = Image.new("L", image.size, 0)
    marks = ImageDraw.Draw(mask)
    span = max(1, x1 - x0)
    pressure = (.20, .68, 1.00, .88, .54, .16)
    centres = []
    for step, weight in enumerate(pressure):
        fraction = step / (len(pressure) - 1)
        # A shallow lift through the centre reads as one quick hand motion.
        bow = -round(stroke * .34 * (1 - abs(2 * fraction - 1)))
        jitter = rng.choice((-1, 0, 0, 1))
        centres.append((
            round(x0 + span * fraction), underline_y + bow + jitter,
            max(1, round(stroke * weight / 2)),
        ))
    upper = [(px, py - radius) for px, py, radius in centres]
    lower = [(px, py + radius) for px, py, radius in reversed(centres)]
    marks.polygon([*upper, *lower], fill=236)
    # A few short, directional dry channels expose paper inside the stroke.
    # They stay subordinate to the continuous body and never become speckles.
    for start_fraction, length_fraction, offset in ((.13, .17, -1), (.48, .13, 2), (.73, .16, 0)):
        sx = round(x0 + span * start_fraction)
        ex = round(sx + span * length_fraction)
        marks.line((sx, underline_y + offset, ex, underline_y + offset - 1),
                   fill=108, width=1)
    apply_charcoal_mask(image, mask, CHARCOAL, seed, pigment_load=.78)
    box = mask.getbbox()
    return tuple(int(value) for value in box) if box else None


def compose_brand(image: Image.Image, preset_name: str, subtitle: str,
                  skill_fill=ORANGE) -> tuple[Image.Image, list[dict]]:
    draw = ImageDraw.Draw(image, "RGBA")
    w, h = image.size
    boxes: list[dict] = []
    if preset_name == "xiaohongshu":
        # Three distinct tiers follow the square brand reference: heavy CJK,
        # widely tracked SKILL, then the small explanatory line.
        title_xy = (round(w * .075), round(h * .062))
        title_font = fit_font(draw, "墨尘", FONT_CJK_BOLD, round(w * .220), round(w * .56))
        title_box = text_bbox(draw, title_xy, "墨尘", title_font)
        draw_charcoal_text(
            image, title_xy, "墨尘", title_font, CHARCOAL, 101,
            stroke_width=1, pigment_load=1.0,
        )
        skill_font = load_font(FONT_LATIN_NARROW, round(w * .126))
        skill_box = draw_tracked(
            image, (round(w * .078), round(h * .274)), "SKILL", skill_font,
            skill_fill, round(w * .046), 103, pigment_load=.90,
        )
        subtitle_font = fit_font(draw, subtitle, FONT_CJK, round(w * .049), round(w * .82))
        subtitle_box = draw_accented_line(
            image, (round(w * .078), round(h * .405)), subtitle, "拼", subtitle_font,
            seed=107, pigment_load=.78,
        )
        underline_box = draw_charcoal_underline(
            image, (round(w * .078), round(h * .405)), subtitle,
            "拼成画面", subtitle_font, seed=131,
        )
        pad = round(w * .025)
    else:
        # Match the proven landscape lockup: main CJK at left, SKILL aligned to
        # its lower half with a deliberate gap, subtitle on an independent row.
        # The approved 5:2 lockup is intentionally bold and close-set: the
        # Chinese mark carries the first read, while SKILL sits just to its
        # right instead of floating in the middle of the canvas.
        title_xy = (round(w * .055), round(h * .038))
        title_font = fit_font(draw, "墨尘", FONT_CJK_BOLD, round(h * .285), round(w * .34))
        title_box = text_bbox(draw, title_xy, "墨尘", title_font)
        draw_charcoal_text(
            image, title_xy, "墨尘", title_font, CHARCOAL, 109,
            stroke_width=1, pigment_load=1.0,
        )
        skill_font = load_font(FONT_LATIN_NARROW, round(h * .150))
        skill_box = draw_tracked(
            image, (round(w * .290), round(h * .205)), "SKILL", skill_font,
            skill_fill, round(w * .020), 113, pigment_load=.94, x_scale=.65,
        )
        # Wide brand covers need the explanatory line to survive a ~320 px feed
        # thumbnail; keep it subordinate, but not annotation-small.
        subtitle_font = fit_font(draw, subtitle, FONT_CJK, round(h * .074), round(w * .42))
        subtitle_box = draw_accented_line(
            image, (round(w * .063), round(h * .390)), subtitle, "拼", subtitle_font,
            seed=127, pigment_load=.86,
        )
        underline_box = draw_charcoal_underline(
            image, (round(w * .063), round(h * .390)), subtitle,
            "拼成画面", subtitle_font, seed=137,
        )
        pad = round(h * .025)
    if underline_box:
        subtitle_box = (
            min(subtitle_box[0], underline_box[0]),
            min(subtitle_box[1], underline_box[1]),
            max(subtitle_box[2], underline_box[2]),
            max(subtitle_box[3], underline_box[3]),
        )
    for role, box, text in (("brand_title", title_box, "墨尘"),
                            ("english_mark", skill_box, "SKILL"),
                            ("subtitle", subtitle_box, subtitle)):
        boxes.append({"role": role, "text": text,
                      "bbox_px": list(expand_box(box, pad, image.size))})
    return image, boxes


def compose_brand_article(image: Image.Image, subtitle: str,
                          skill_fill=ORANGE) -> tuple[Image.Image, list[dict]]:
    """Landscape brand-topic article lockup based on the approved reference."""
    draw = ImageDraw.Draw(image, "RGBA")
    w, h = image.size
    x = round(w * .30)
    title_y = round(h * .085)
    title_font = fit_font(draw, "墨尘", FONT_CJK_BOLD, round(h * .225), round(w * .19))
    title_box = text_bbox(draw, (x, title_y), "墨尘", title_font)
    draw_charcoal_text(
        image, (x, title_y), "墨尘", title_font, CHARCOAL, 157,
        stroke_width=1, pigment_load=1.0,
    )
    skill_font = load_font(FONT_LATIN_NARROW, round(h * .125))
    skill_x = max(round(w * .49), title_box[2] + round(w * .018))
    skill_box = draw_tracked(
        image, (skill_x, round(h * .128)), "SKILL", skill_font,
        skill_fill, round(w * .010), 163, pigment_load=.90,
    )
    subtitle_font = fit_font(draw, subtitle, FONT_CJK, round(h * .068), round(w * .37))
    subtitle_y = max(title_box[3], skill_box[3]) + round(h * .045)
    subtitle_box = draw_accented_line(
        image, (x, subtitle_y), subtitle, "拼", subtitle_font,
        seed=167, pigment_load=.78,
    )
    underline_box = draw_charcoal_underline(
        image, (x, subtitle_y), subtitle, "拼成画面", subtitle_font, seed=173,
    )
    if underline_box:
        subtitle_box = (
            min(subtitle_box[0], underline_box[0]),
            min(subtitle_box[1], underline_box[1]),
            max(subtitle_box[2], underline_box[2]),
            max(subtitle_box[3], underline_box[3]),
        )
    pad = round(h * .025)
    boxes = []
    for role, box, text in (
        ("brand_title", title_box, "墨尘"),
        ("english_mark", skill_box, "SKILL"),
        ("subtitle", subtitle_box, subtitle),
    ):
        boxes.append({"role": role, "text": text,
                      "bbox_px": list(expand_box(box, pad, image.size))})
    return image, boxes


def split_article_title(title: str) -> str:
    # Explicit line breaks are editorial layout instructions, not new copy.
    # Keep them so mixed Chinese/Latin titles can be grouped semantically.
    if "\n" in title:
        return title
    for token in ("，", ":", "：", "｜", "|"):
        if token in title:
            left, right = title.split(token, 1)
            return f"{left}{token}\n{right}"
    midpoint = max(1, len(title) // 2)
    return title[:midpoint] + "\n" + title[midpoint:]


def compose_article(image: Image.Image, preset_name: str, title: str, subtitle: str,
                    kicker: str, title_accent: str = "",
                    title_underline: str = "") -> tuple[Image.Image, list[dict]]:
    draw = ImageDraw.Draw(image, "RGBA")
    w, h = image.size
    center_safe = preset_name == "wechat-lead"
    vertical_social = preset_name == "xiaohongshu"
    five_two_social = preset_name == "twitter"
    # The WeChat lead keeps every irreplaceable glyph inside the center-square
    # crop. A general wide article uses the upper-left negative space so a
    # subject-led charcoal drawing remains unobstructed.
    x = round(w * (.30 if center_safe else .065 if vertical_social else .06))
    kicker_box = None
    if kicker.strip():
        kicker_y = round(h * (.09 if center_safe else .045))
        if "/" in kicker:
            kicker_cjk, kicker_latin = (part.strip() for part in kicker.split("/", 1))
        else:
            kicker_cjk, kicker_latin = "", kicker.strip()
        kicker_cjk_font = load_font(FONT_CJK_HAND, round(h * .052))
        cjk_box = draw.textbbox((x, kicker_y), kicker_cjk, font=kicker_cjk_font)
        if kicker_cjk:
            draw_charcoal_text(
                image, (x, kicker_y), kicker_cjk, kicker_cjk_font, GRAPHITE, 131,
                pigment_load=.80,
            )
        latin_x = x + (
            round(draw.textlength(kicker_cjk, font=kicker_cjk_font)) + round(w * .014)
            if kicker_cjk else 0
        )
        kicker_font = load_font(FONT_LATIN_HAND, round(h * .045))
        latin_box = draw_tracked(
            image, (latin_x, kicker_y), kicker_latin.upper(), kicker_font, ORANGE,
            round(w * .003), 137, pigment_load=.84,
        )
        kicker_box = (
            min(cjk_box[0], latin_box[0]) if kicker_cjk else latin_box[0],
            min(cjk_box[1], latin_box[1]) if kicker_cjk else latin_box[1],
            max(cjk_box[2], latin_box[2]) if kicker_cjk else latin_box[2],
            max(cjk_box[3], latin_box[3]) if kicker_cjk else latin_box[3],
        )
    title_multiline = split_article_title(title) if (
        center_safe or vertical_social or five_two_social
    ) else (
        title[:max(1, len(title) // 2)] + "\n" + title[max(1, len(title) // 2):]
        if len(title) >= 5 else title
    )
    # Leave a deliberate right-hand punctuation lane for social-cover puzzle
    # elements while keeping the three-line headline thumbnail-readable.
    title_max_width = round(w * (
        .39 if center_safe else .72 if vertical_social else .53 if five_two_social else .18
    ))
    title_spacing = round(h * (.010 if vertical_social else .018 if five_two_social else .015))
    title_font = fit_font(
        draw, title_multiline, FONT_CJK_HAND,
        round(h * (
            .165 if center_safe else .094 if vertical_social else .165 if five_two_social else .125
        )),
        title_max_width, "\n" in title_multiline, title_spacing,
    )
    title_y_ratio = .17 if center_safe else (
        .055 if vertical_social and not kicker_box else
        .115 if vertical_social else .12 if five_two_social else .10
    )
    title_xy = (x, round(h * title_y_ratio))
    draw_accented_multiline(
        image, title_xy, title_multiline, title_accent, title_font,
        spacing=title_spacing, stroke_width=1, seed=139, pigment_load=.94,
    )
    title_box = text_bbox(draw, title_xy, title_multiline, title_font, title_spacing)
    underline_box = draw_charcoal_underline(
        image, title_xy, title_multiline, title_underline, title_font,
        spacing=title_spacing,
    )
    if underline_box:
        title_box = (
            min(title_box[0], underline_box[0]),
            min(title_box[1], underline_box[1]),
            max(title_box[2], underline_box[2]),
            max(title_box[3], underline_box[3]),
        )
    subtitle_box = None
    if subtitle:
        subtitle_font = fit_font(
            draw, subtitle, FONT_CJK_HAND,
            round(h * (.042 if vertical_social else .050)),
            round(w * (
                .39 if center_safe else .78 if vertical_social else .50 if five_two_social else .17
            )),
        )
        subtitle_xy = (x, title_box[3] + round(h * .025))
        subtitle_box = draw_accented_line(
            image, subtitle_xy, subtitle, "", subtitle_font,
            seed=149, pigment_load=.76,
        )
    pad = round(h * .02)
    boxes = []
    if kicker_box:
        boxes.append(
            {"role": "kicker", "text": kicker,
             "bbox_px": list(expand_box(kicker_box, pad, image.size))}
        )
    boxes.append(
        {"role": "article_title", "text": title,
         "bbox_px": list(expand_box(title_box, pad, image.size))}
    )
    if subtitle_box:
        boxes.append({"role": "article_subtitle", "text": subtitle,
                      "bbox_px": list(expand_box(subtitle_box, pad, image.size))})
    return image, boxes


def compose(input_path: Path, output_path: Path, manifest_path: Path,
            preset_name: str, mode: str, title: str, subtitle: str,
            kicker: str, layout: str = "auto", title_accent: str = "",
            title_underline: str = "", skill_color: str = "orange") -> dict:
    preset = PRESETS[preset_name]
    with Image.open(input_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    image = ImageOps.fit(
        source,
        (preset.width, preset.height),
        method=Image.Resampling.LANCZOS,
        centering=preset.anchor,
    ).convert("RGBA")
    resolved_layout = "brand-lockup" if mode == "brand" else (
        "theme-title" if layout == "auto" else layout
    )
    skill_fill = ORANGE if skill_color == "orange" else CHARCOAL
    if mode == "brand":
        image, text_boxes = compose_brand(image, preset_name, subtitle, skill_fill)
        verified_text = {
            "brand": "墨尘",
            "english": "SKILL",
            "subtitle": subtitle,
            "subtitle_accent": "拼" if "拼" in subtitle else "",
            "subtitle_underline": "拼成画面" if "拼成画面" in subtitle else "",
        }
        cjk_skeleton, latin_skeleton = FONT_CJK_BOLD, FONT_LATIN_NARROW
    elif resolved_layout == "brand-lockup":
        image, text_boxes = compose_brand_article(image, subtitle, skill_fill)
        verified_text = {
            "brand": "墨尘",
            "english": "SKILL",
            "subtitle": subtitle,
            "subtitle_accent": "拼" if "拼" in subtitle else "",
            "subtitle_underline": "拼成画面" if "拼成画面" in subtitle else "",
        }
        cjk_skeleton, latin_skeleton = FONT_CJK_BOLD, FONT_LATIN_NARROW
    else:
        image, text_boxes = compose_article(
            image, preset_name, title, subtitle, kicker, title_accent,
            title_underline,
        )
        verified_text = {
            "kicker": kicker, "title": title, "subtitle": subtitle,
            "title_accent": title_accent,
            "title_underline": title_underline,
        }
        cjk_skeleton, latin_skeleton = FONT_CJK_HAND, FONT_LATIN_HAND
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, quality=96)
    size = image.size
    protection = [normalized(tuple(item["bbox_px"]), size) for item in text_boxes]
    result = {
        "schema": "black-dust-cover-v1",
        "stage": "continuous_typeset_base",
        "mode": mode,
        "layout": resolved_layout,
        "preset": preset_name,
        "role": preset.role,
        "canvas_px": list(size),
        "source": str(input_path.resolve()),
        "source_sha256": sha256(input_path),
        "output": str(output_path.resolve()),
        "output_sha256": sha256(output_path),
        "verified_text": verified_text,
        "text_boxes": text_boxes,
        "puzzle_protected_boxes_normalized": protection,
        "safe_zone_px": list(preset.safe_zone) if preset.safe_zone else None,
        "accent_hex": "#FF5A1F",
        "english_mark_color": skill_color,
        "text_rendering": {
            "cjk_skeleton": cjk_skeleton.name,
            "latin_skeleton": latin_skeleton.name,
            "font_assets": font_fingerprint(mode, resolved_layout),
            "surface": "role-weighted pigment load + sampled paper tooth + low-frequency charcoal pressure + directional dry-brush",
            "visibility": "negative-space placement + adaptive feathered quieting",
            "occlusion_policy": "text above scene; holes and loose pieces excluded from protected boxes",
        },
        "puzzle_elements_present": False,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crop a continuous Black Dust image and add deterministic cover typography."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="brand-wide")
    parser.add_argument("--mode", choices=("brand", "article"), default="brand")
    parser.add_argument(
        "--layout", choices=("auto", "brand-lockup", "theme-title"), default="auto",
        help="brand-lockup reproduces the stable 墨尘 / SKILL / subtitle relationship",
    )
    parser.add_argument("--title", default="把灵感，拼成画面")
    parser.add_argument("--subtitle", default="把灵感，拼成画面")
    parser.add_argument("--kicker", default="墨尘 / BLACK DUST")
    parser.add_argument(
        "--title-accent", default="",
        help="Highlight the first matching title phrase with Signal Orange.",
    )
    parser.add_argument(
        "--title-underline", default="",
        help="Underline the first matching title phrase with a hand-drawn charcoal stroke.",
    )
    parser.add_argument(
        "--skill-color", choices=("orange", "charcoal"), default="orange",
        help="Brand lockup color for SKILL; the subtitle accent remains Signal Orange.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "article" and not args.title.strip():
        raise SystemExit("Article mode requires a non-empty --title")
    result = compose(args.input, args.output, args.manifest, args.preset,
                     args.mode, args.title.strip(), args.subtitle.strip(), args.kicker.strip(),
                     args.layout, args.title_accent.strip(), args.title_underline.strip(),
                     args.skill_color)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
