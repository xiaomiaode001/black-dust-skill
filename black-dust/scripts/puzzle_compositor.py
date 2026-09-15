#!/usr/bin/env python3
"""Create an edge-to-edge jigsaw surface with exactly matched lifted pieces.

The same pixel mask is used to cut each hole and extract its corresponding
piece. An optional assembled proof preserves the complete die-cut board so a
reviewer can compare the removed design with the restored image directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat, ImageOps
except ImportError as exc:  # pragma: no cover - environment guidance
    raise SystemExit("Pillow is required: run this script with a Python environment that provides PIL.") from exc


TAB = 1
SOCKET = -1
FLAT = 0
STANDARD_GEOMETRY_VERSION = 5
STANDARD_COMPOSITOR_REVISION = "1.5-standard-bounded"
DEFAULT_MIN_PIECE_DETAIL = 10.0


@dataclass(frozen=True)
class Boundary:
    sign: int
    offset: float


class LabelMaskMap(Mapping[tuple[int, int], Image.Image]):
    """Lazy piece masks backed by one lossless owner-label image.

    A production board can contain hundreds of pieces. Materializing every
    piece as a full-canvas alpha image multiplies memory traffic by the piece
    count even though normal delivery needs only the three selected cells.
    This mapping preserves the public mask API while rasterizing a full mask
    only when a caller actually requests that cell.
    """

    def __init__(
        self,
        labels: Image.Image,
        rows: int,
        cols: int,
        xs: Sequence[int],
        ys: Sequence[int],
    ) -> None:
        self.labels = labels.convert("RGB")
        self.rows = rows
        self.cols = cols
        self.xs = tuple(xs)
        self.ys = tuple(ys)
        self._cache: dict[tuple[int, int], Image.Image] = {}
        self._local_cache: dict[
            tuple[int, int], tuple[Image.Image, tuple[int, int, int, int]]
        ] = {}

    def __len__(self) -> int:
        return self.rows * self.cols

    def __iter__(self) -> Iterator[tuple[int, int]]:
        for row in range(self.rows):
            for col in range(self.cols):
                yield row, col

    def _index(self, cell: tuple[int, int]) -> int:
        row, col = cell
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise KeyError(cell)
        return row * self.cols + col + 1

    @staticmethod
    def _owner_mask(labels: Image.Image, index: int) -> Image.Image:
        red, green, _ = labels.split()
        red_lut = [255 if value == index % 256 else 0 for value in range(256)]
        green_lut = [255 if value == index // 256 else 0 for value in range(256)]
        return ImageChops.multiply(red.point(red_lut), green.point(green_lut))

    def cropped(
        self, cell: tuple[int, int]
    ) -> tuple[Image.Image, tuple[int, int, int, int]]:
        """Return the tight local mask and its full-canvas bounding box."""
        if cell in self._local_cache:
            return self._local_cache[cell]
        index = self._index(cell)
        row, col = cell
        cell_w = max(self.xs[col + 1] - self.xs[col], 1)
        cell_h = max(self.ys[row + 1] - self.ys[row], 1)
        margin = max(4, math.ceil(max(cell_w, cell_h) * .5))
        search_box = (
            max(0, self.xs[col] - margin),
            max(0, self.ys[row] - margin),
            min(self.labels.width, self.xs[col + 1] + margin),
            min(self.labels.height, self.ys[row + 1] + margin),
        )
        search = self._owner_mask(self.labels.crop(search_box), index)
        local_box = search.getbbox()
        if local_box is None:
            raise ValueError(f"piece label has no pixels: {cell}")
        bbox = (
            search_box[0] + local_box[0],
            search_box[1] + local_box[1],
            search_box[0] + local_box[2],
            search_box[1] + local_box[3],
        )
        cropped = search.crop(local_box)
        self._local_cache[cell] = cropped, bbox
        return cropped, bbox

    def bbox(self, cell: tuple[int, int]) -> tuple[int, int, int, int]:
        return self.cropped(cell)[1]

    def __getitem__(self, cell: tuple[int, int]) -> Image.Image:
        if cell not in self._cache:
            cropped, bbox = self.cropped(cell)
            full = Image.new("L", self.labels.size, 0)
            full.paste(cropped, bbox[:2])
            self._cache[cell] = full
        return self._cache[cell]


@dataclass(frozen=True)
class MaterialPreset:
    """Low-relief paperboard rendering values; never alters source artwork globally."""

    highlight_rgb: tuple[int, int, int]
    seam_dark_low: int
    seam_dark_high: int
    seam_light_low: int
    seam_light_high: int
    shoulder_shadow: int
    seam_return_rgb: tuple[int, int, int]
    seam_return_low: int
    protected_strength: int
    hole_wall_alpha: int
    hole_shadow_alpha: int
    piece_near_shadow: int
    piece_far_shadow: int
    piece_depth: tuple[int, int]
    piece_wall_rgb: tuple[int, int, int]


MATERIAL_PRESETS = {
    "deep-charcoal": MaterialPreset(
        highlight_rgb=(48, 46, 42),
        seam_dark_low=14,
        seam_dark_high=48,
        seam_light_low=118,
        seam_light_high=150,
        shoulder_shadow=20,
        seam_return_rgb=(72, 68, 62),
        seam_return_low=0,
        protected_strength=226,
        hole_wall_alpha=140,
        hole_shadow_alpha=82,
        piece_near_shadow=88,
        piece_far_shadow=30,
        piece_depth=(5, 6),
        piece_wall_rgb=(126, 115, 98),
    ),
    "graphite-matte": MaterialPreset(
        highlight_rgb=(64, 60, 54),
        seam_dark_low=42,
        seam_dark_high=30,
        seam_light_low=110,
        seam_light_high=140,
        shoulder_shadow=28,
        seam_return_rgb=(0, 0, 0),
        seam_return_low=0,
        protected_strength=220,
        hole_wall_alpha=148,
        hole_shadow_alpha=76,
        piece_near_shadow=78,
        piece_far_shadow=24,
        piece_depth=(5, 6),
        piece_wall_rgb=(142, 132, 116),
    ),
    "ivory-board": MaterialPreset(
        # The social-cover reference is a shallow pressed cut in warm ivory
        # stock. Keep the shared groove readable at fit view, but suppress the
        # fixed-gray/grid impression of the previous pass.
        highlight_rgb=(46, 42, 37),
        seam_dark_low=26,
        seam_dark_high=17,
        seam_light_low=80,
        seam_light_high=140,
        shoulder_shadow=20,
        seam_return_rgb=(0, 0, 0),
        seam_return_low=0,
        protected_strength=220,
        # Pale stock needs depth from directional value changes, not from a
        # dark contour.  Keep the cut face close to the warm board colour and
        # let the upper/left occlusion plus lower/right lip describe relief.
        hole_wall_alpha=72,
        hole_shadow_alpha=62,
        piece_near_shadow=46,
        piece_far_shadow=12,
        piece_depth=(4, 4),
        piece_wall_rgb=(198, 189, 175),
    ),
}


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("color must be a six-digit hex value")
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("color must be hexadecimal") from exc


def parse_norm_box(value: str) -> tuple[float, float, float, float]:
    try:
        box = tuple(float(part) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("box must be x0,y0,x1,y1") from exc
    if len(box) != 4:
        raise argparse.ArgumentTypeError("box must contain four numbers")
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise argparse.ArgumentTypeError("box coordinates must satisfy 0 <= x0 < x1 <= 1")
    return x0, y0, x1, y1


def parse_cell(value: str) -> tuple[int, int]:
    try:
        row, col = (int(part) for part in value.split(","))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("cell must be row,column") from exc
    return row, col


def edge_name(value: int) -> str:
    return {TAB: "tab", SOCKET: "socket", FLAT: "flat"}[value]


def bounds(total: int, count: int) -> list[int]:
    return [round(index * total / count) for index in range(count + 1)]


def build_boundaries(
    rows: int,
    cols: int,
    rng: random.Random,
    offset_range: tuple[float, float] = (0.40, 0.60),
) -> tuple[list[list[Boundary]], list[list[Boundary]]]:
    low, high = offset_range
    vertical = [
        [Boundary(rng.choice((TAB, SOCKET)), rng.uniform(low, high)) for _ in range(cols - 1)]
        for _ in range(rows)
    ]
    horizontal = [
        [Boundary(rng.choice((TAB, SOCKET)), rng.uniform(low, high)) for _ in range(cols)]
        for _ in range(rows - 1)
    ]
    return vertical, horizontal


def piece_edges(
    row: int,
    col: int,
    rows: int,
    cols: int,
    vertical: Sequence[Sequence[Boundary]],
    horizontal: Sequence[Sequence[Boundary]],
) -> dict[str, int]:
    return {
        "north": FLAT if row == 0 else -horizontal[row - 1][col].sign,
        "east": FLAT if col == cols - 1 else vertical[row][col].sign,
        "south": FLAT if row == rows - 1 else horizontal[row][col].sign,
        "west": FLAT if col == 0 else -vertical[row][col - 1].sign,
    }


def _apply_circle(mask: Image.Image, bbox: tuple[int, int, int, int], mode: int,
                  axis: str, outward: int) -> Image.Image:
    # A shared neck/head cutter, oriented toward the tab owner. Both neighbors
    # use the identical raster cutter with opposite union/subtraction operations.
    shape = Image.new("L", mask.size, 0)
    draw = ImageDraw.Draw(shape)
    cx, cy = (bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2
    radius = (bbox[2]-bbox[0])/2
    dx = outward * mode * radius * 0.70 if axis == 'x' else 0
    dy = outward * mode * radius * 0.70 if axis == 'y' else 0
    head = radius * 0.72
    neck = radius * 0.34
    hx, hy = cx+dx, cy+dy
    if axis == 'x':
        draw.rectangle((min(cx,hx), cy-neck, max(cx,hx), cy+neck), fill=255)
    else:
        draw.rectangle((cx-neck, min(cy,hy), cx+neck, max(cy,hy)), fill=255)
    draw.ellipse((hx-head,hy-head,hx+head,hy+head), fill=255)
    return ImageChops.lighter(mask, shape) if mode == TAB else ImageChops.subtract(mask, shape)


def build_piece_mask(
    size: tuple[int, int],
    row: int,
    col: int,
    rows: int,
    cols: int,
    xs: Sequence[int],
    ys: Sequence[int],
    vertical: Sequence[Sequence[Boundary]],
    horizontal: Sequence[Sequence[Boundary]],
    knob_radius: int,
) -> Image.Image:
    x0, x1 = xs[col], xs[col + 1]
    y0, y1 = ys[row], ys[row + 1]
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
    edges = piece_edges(row, col, rows, cols, vertical, horizontal)

    if edges["north"]:
        offset = horizontal[row - 1][col].offset
        cx = round(x0 + offset * (x1 - x0))
        mask = _apply_circle(mask, (cx - knob_radius, y0 - knob_radius, cx + knob_radius, y0 + knob_radius), edges["north"], 'y', -1)
    if edges["south"]:
        offset = horizontal[row][col].offset
        cx = round(x0 + offset * (x1 - x0))
        mask = _apply_circle(mask, (cx - knob_radius, y1 - knob_radius, cx + knob_radius, y1 + knob_radius), edges["south"], 'y', 1)
    if edges["west"]:
        offset = vertical[row][col - 1].offset
        cy = round(y0 + offset * (y1 - y0))
        mask = _apply_circle(mask, (x0 - knob_radius, cy - knob_radius, x0 + knob_radius, cy + knob_radius), edges["west"], 'x', -1)
    if edges["east"]:
        offset = vertical[row][col].offset
        cy = round(y0 + offset * (y1 - y0))
        mask = _apply_circle(mask, (x1 - knob_radius, cy - knob_radius, x1 + knob_radius, cy + knob_radius), edges["east"], 'x', 1)
    return mask


def _masks_from_shared_paths(size, rows, cols, xs, ys, hpaths, vpaths):
    """Rasterize one shared cut graph into a complete, unique label partition."""
    width, height = size
    labels = Image.new('RGB', size)
    draw = ImageDraw.Draw(labels)
    for r in range(rows):
        for c in range(cols):
            index = r * cols + c + 1
            polygon = (
                hpaths[r][c]
                + vpaths[r][c + 1]
                + list(reversed(hpaths[r + 1][c]))
                + list(reversed(vpaths[r][c]))
            )
            draw.polygon(polygon, fill=(index % 256, index // 256, 0))
    red, green, _ = labels.split()
    if ImageChops.lighter(red, green).getextrema()[0] == 0:
        raise ValueError('shared cut graph left unowned pixels')

    masks = LabelMaskMap(labels, rows, cols, xs, ys)
    repairs = []
    for r in range(rows):
        for c in range(cols):
            index = r * cols + c + 1
            # Integer scan conversion can leave one-pixel islands at diagonal
            # junctions. Keep the core-connected region and transfer islands to
            # a touching neighbor; never manufacture uncovered pixels. Work on
            # each cell's small local crop rather than a full-canvas mask.
            crop, box = masks.cropped((r, c))
            crop = crop.copy()
            core = (
                round((xs[c] + xs[c + 1]) / 2) - box[0],
                round((ys[r] + ys[r + 1]) / 2) - box[1],
            )
            ImageDraw.floodfill(crop, core, 128)
            orphan = crop.point([255 if p == 255 else 0 for p in range(256)])
            if orphan.getbbox():
                repairs.extend(
                    (box[0] + i % crop.width, box[1] + i // crop.width, index)
                    for i, p in enumerate(orphan.tobytes()) if p
                )
    for x, y, index in repairs:
        candidates = []
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height:
                rr, gg, _ = labels.getpixel((nx, ny))
                neighbor = rr + 256 * gg
                if neighbor and neighbor != index:
                    candidates.append(neighbor)
        if not candidates:
            raise ValueError('cut produced a detached multi-pixel region')
        owner = max(sorted(set(candidates)), key=candidates.count)
        labels.putpixel((x, y), (owner % 256, owner // 256, 0))
    return LabelMaskMap(labels, rows, cols, xs, ys)


def standard_masks(
    size, rows, cols, xs, ys, vertical, horizontal, rng, knob_ratio,
    geometry_version=STANDARD_GEOMETRY_VERSION,
):
    """Make restrained die-cut paths with familiar round heads and natural necks.

    The path for each shared edge is sampled once. Small node drift, shallow
    baseline bow and bounded per-edge head/neck variation prevent a ruler-grid
    overlay while retaining the mature silhouette of a manufactured jigsaw.
    """
    width, height = size
    cw, ch = width / cols, height / rows
    cell_min = min(cw, ch)
    if geometry_version not in (3, 4, 5):
        raise ValueError("standard geometry supports versions 3, 4 and 5")
    # v4 is deliberately calmer at the grid nodes and more generous at the
    # round head. At fit view this reads as a manufactured jigsaw rather than a
    # ruled grid with tiny decorative bumps. v3 remains reproducible for audit.
    node_drift = .045 if geometry_version == 3 else .027
    nodes = [[(
        xs[c] + (rng.uniform(-node_drift, node_drift) * cw if 0 < c < cols else 0),
        ys[r] + (rng.uniform(-node_drift, node_drift) * ch if 0 < r < rows else 0),
    ) for c in range(cols + 1)] for r in range(rows + 1)]

    def curve(a, b, boundary, axis):
        if boundary is None:
            return [a, b]
        vx, vy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(vx, vy)
        tx, ty = vx / length, vy / length
        # Horizontal cuts point down; vertical cuts point right. This preserves
        # Boundary.sign semantics for the top/left owner of the shared edge.
        nx, ny = ((-ty, tx) if axis == 'y' else (ty, -tx))
        if geometry_version == 3:
            center_jitter = .016
            depth = cell_min * knob_ratio * rng.uniform(1.02, 1.18)
            head = depth * rng.uniform(.67, .75)
            neck = head * rng.uniform(.28, .37)
            bow_limit = .021
            lean_limit = .014
        elif geometry_version == 4:
            center_jitter = .012
            depth = cell_min * knob_ratio * rng.uniform(1.12, 1.25)
            head = depth * rng.uniform(.78, .86)
            neck = head * rng.uniform(.24, .31)
            bow_limit = .012
            lean_limit = .009
        else:
            # v5 keeps the familiar circular head but removes v4's pinched
            # micro-throat.  A broader neck and continuous-tangent shoulders
            # make the tab/socket read as one pressed die-cut curve.
            center_jitter = .010
            depth = cell_min * knob_ratio * rng.uniform(1.08, 1.18)
            head = depth * rng.uniform(.74, .80)
            neck = head * rng.uniform(.50, .58)
            # Retain a shallow full-edge bow so long shoulders do not collapse
            # back onto ruler-straight grid axes after integer rasterization.
            bow_limit = .020
            lean_limit = .007
        center = max(.42, min(.58, boundary.offset + rng.uniform(-center_jitter, center_jitter)))
        head_s, neck_s = head / length, neck / length
        center_depth = depth - head
        left_neck, right_neck = center - neck_s, center + neck_s
        left_head, right_head = center - head_s, center + head_s
        bow = cell_min * rng.uniform(-bow_limit, bow_limit)
        lean = rng.uniform(-lean_limit, lean_limit)
        kappa = .55228475
        if geometry_version == 5:
            # The shoulder curves deliberately overshoot only a little.  Their
            # baseline joins share a horizontal tangent with the straight cut,
            # avoiding the tiny inward hook visible in v4 at fit view.
            shoulder = max(.014, (head_s - neck_s) * .46)
            flat_handle = min(.030, max(.018, neck_s * .34))
            groups = [
                ((.16, 0), (left_neck - flat_handle, 0), (left_neck, 0)),
                ((left_neck + flat_handle, 0), (left_head, center_depth * .42),
                 (left_head, center_depth)),
                ((left_head, center_depth + kappa * head),
                 (center - kappa * head_s, depth), (center, depth)),
                ((center + kappa * head_s, depth),
                 (right_head, center_depth + kappa * head), (right_head, center_depth)),
                ((right_head, center_depth * .42), (right_neck - shoulder, 0),
                 (right_neck, 0)),
                ((right_neck + flat_handle, 0), (.84, 0), (1, 0)),
            ]
        else:
            groups = [
                ((.16, 0), (left_neck - .035, 0), (left_neck, 0)),
                ((left_neck, center_depth * .18), (left_head, center_depth * .36),
                 (left_head, center_depth)),
                ((left_head, center_depth + kappa * head),
                 (center - kappa * head_s, depth), (center, depth)),
                ((center + kappa * head_s, depth),
                 (right_head, center_depth + kappa * head), (right_head, center_depth)),
                ((right_head, center_depth * .36), (right_neck, center_depth * .18),
                 (right_neck, 0)),
                ((right_neck + .035, 0), (.84, 0), (1, 0)),
            ]
        local = [(0., 0.)]
        last = (0., 0.)
        for p1, p2, p3 in groups:
            for step in range(1, 15):
                t = step / 14
                u = 1 - t
                s = u*u*u*last[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0]
                d = u*u*u*last[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]
                s += lean * (d / depth)
                local.append((s, boundary.sign * d + math.sin(math.pi * s) * bow))
            last = p3
        return [
            (a[0] + tx * (s * length) + nx * d,
             a[1] + ty * (s * length) + ny * d)
            for s, d in local
        ]

    hpaths = [[
        curve(nodes[r][c], nodes[r][c + 1],
              None if r in (0, rows) else horizontal[r - 1][c], 'y')
        for c in range(cols)
    ] for r in range(rows + 1)]
    vpaths = [[
        curve(nodes[r][c], nodes[r + 1][c],
              None if c in (0, cols) else vertical[r][c - 1], 'x')
        for c in range(cols + 1)
    ] for r in range(rows)]
    return _masks_from_shared_paths(size, rows, cols, xs, ys, hpaths, vpaths)


def organic_masks(size, rows, cols, xs, ys, vertical, horizontal, rng, knob_ratio, geometry_version):
    """Rasterize a shared curved cut graph into one owner label per pixel.

    Neighbors reuse exactly the same sampled Bezier path in reverse. Raster
    boundary pixels have a single owner, not two independently feathered masks.
    """
    width, height = size
    cw, ch = width / cols, height / rows
    nodes = [[(xs[c] + (rng.uniform(-.105,.105)*cw if 0<c<cols else 0),
               ys[r] + (rng.uniform(-.105,.105)*ch if 0<r<rows else 0))
              for c in range(cols+1)] for r in range(rows+1)]

    def curve(a, b, boundary, axis):
        if boundary is None:
            return [a,b]
        center = boundary.offset + rng.uniform(-.025,.025)
        half = rng.uniform(.105,.145)
        neck = half * rng.uniform(.43,.62)
        lean = rng.uniform(-.018,.018)
        depth = min(cw,ch) * knob_ratio * rng.uniform(1.0,1.32) * boundary.sign
        bow0, bow1 = rng.uniform(-.08,.08), rng.uniform(-.08,.08)
        # Each group is two controls and endpoint; lobes are deliberately not circles.
        groups = [
            ((.14,bow0),(center-.19,bow1),(center-neck,0)),
            ((center-neck*.2,-.03),(center-half*.64,.30),(center-half,.54)),
            ((center-half*1.45,.96),(center-half*.72,1.12),(center+lean,1.10)),
            ((center+half*.90,1.09),(center+half*1.36,.83),(center+half*.85,.49)),
            ((center+half*.53,.28),(center+neck*.30,-.025),(center+neck,0)),
            ((center+.20,bow1),(.87,bow0),(1,0)),
        ]
        if geometry_version == 2:
            neck = half * .34
            groups = [
                ((.13,bow0*3),(center-.13,bow1*3),(center-neck*1.7,0)),
                ((center-neck*.2,0),(center-neck*.45,.19),(center-half*.65,.37)),
                ((center-half*1.70,.91),(center-half*.98,1.38),(center+lean,1.34)),
                ((center+half*1.18,1.30),(center+half*1.65,.84),(center+half*.58,.34)),
                ((center+neck*.6,.18),(center+neck*.2,0),(center+neck*1.7,0)),
                ((center+.14,bow1*3),(.86,bow0*3),(1,0)),
            ]
        local, last = [(0.,0.)], (0.,0.)
        for p1,p2,p3 in groups:
            for step in range(1,19):
                t=step/18; u=1-t
                local.append(tuple(u*u*u*last[k]+3*u*u*t*p1[k]+3*u*t*t*p2[k]+t*t*t*p3[k] for k in (0,1)))
            last=p3
        return [(a[0]+(b[0]-a[0])*t+(d*depth if axis=='x' else 0),
                 a[1]+(b[1]-a[1])*t+(d*depth if axis=='y' else 0)) for t,d in local]

    hpaths = [[curve(nodes[r][c],nodes[r][c+1], None if r in (0,rows) else horizontal[r-1][c], 'y')
               for c in range(cols)] for r in range(rows+1)]
    vpaths = [[curve(nodes[r][c],nodes[r+1][c], None if c in (0,cols) else vertical[r][c-1], 'x')
               for c in range(cols+1)] for r in range(rows)]
    return _masks_from_shared_paths(size, rows, cols, xs, ys, hpaths, vpaths)


def masks_and_signatures(
    size: tuple[int, int], rows: int, cols: int, seed: int, knob_ratio: float, cut_style: str = 'standard',
    geometry_version: int = STANDARD_GEOMETRY_VERSION,
) -> tuple[dict[tuple[int, int], Image.Image], dict[tuple[int, int], dict[str, int]], list[int], list[int]]:
    if not 0.08 <= knob_ratio <= 0.22:
        raise ValueError('knob-ratio must be between 0.08 and 0.22 for non-overlapping necked tabs')
    if cut_style not in ('standard','classic','organic'):
        raise ValueError('cut_style must be standard, classic or organic')
    if geometry_version not in (1,2,3,4,5):
        raise ValueError('unsupported geometry_version')
    if rows*cols >= 65536:
        raise ValueError('too many labeled pieces')
    width, height = size
    rng = random.Random(seed)
    xs, ys = bounds(width, cols), bounds(height, rows)
    radius = max(3, round(min(width / cols, height / rows) * knob_ratio))
    # Standard pieces keep the familiar centered round head/socket silhouette.
    # The slight offset prevents sterile repetition without turning the die line
    # into a free-form wave. ``classic`` retains the earlier wider offset range.
    offset_range = (0.45, 0.55) if cut_style == 'standard' else (0.40, 0.60)
    vertical, horizontal = build_boundaries(rows, cols, rng, offset_range)
    if cut_style == 'organic':
        # Versions 3+ change the production standard cut. Organic v2 remains a
        # stable comparison language when callers accept the newer default.
        organic_version = 2 if geometry_version >= 3 else geometry_version
        masks = organic_masks(size,rows,cols,xs,ys,vertical,horizontal,rng,knob_ratio,organic_version)
        signatures = {(r,c):piece_edges(r,c,rows,cols,vertical,horizontal) for r in range(rows) for c in range(cols)}
        return masks,signatures,xs,ys
    if cut_style == 'standard' and geometry_version in (3, 4, 5):
        masks = standard_masks(
            size, rows, cols, xs, ys, vertical, horizontal, rng,
            knob_ratio, geometry_version,
        )
        signatures = {(r,c):piece_edges(r,c,rows,cols,vertical,horizontal) for r in range(rows) for c in range(cols)}
        return masks,signatures,xs,ys
    masks: dict[tuple[int, int], Image.Image] = {}
    signatures: dict[tuple[int, int], dict[str, int]] = {}
    for row in range(rows):
        for col in range(cols):
            masks[(row, col)] = build_piece_mask(
                size, row, col, rows, cols, xs, ys, vertical, horizontal, radius
            )
            signatures[(row, col)] = piece_edges(row, col, rows, cols, vertical, horizontal)
    return masks, signatures, xs, ys


def boxes_intersect(a: Sequence[int], b: Sequence[int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def to_pixel_boxes(norm_boxes: Iterable[Sequence[float]], size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    width, height = size
    return [
        (round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height))
        for x0, y0, x1, y1 in norm_boxes
    ]


def local_variance(gray: Image.Image, bbox: Sequence[int]) -> float:
    crop = gray.crop(tuple(bbox))
    return float(ImageStat.Stat(crop).var[0]) if crop.width and crop.height else math.inf


def local_mean(gray: Image.Image, bbox: Sequence[int]) -> float:
    crop = gray.crop(tuple(bbox))
    return float(ImageStat.Stat(crop).mean[0]) if crop.width and crop.height else 127.5


def select_missing_cells(
    image: Image.Image,
    masks: dict[tuple[int, int], Image.Image],
    xs: Sequence[int],
    ys: Sequence[int],
    rows: int,
    cols: int,
    missing_count: int,
    protected: Sequence[Sequence[int]],
    rng: random.Random,
    signatures: dict[tuple[int, int], dict[str, int]] | None = None,
    shape_policy: str = "mixed",
    content_policy: str = "recognizable",
    min_piece_detail: float = DEFAULT_MIN_PIECE_DETAIL,
) -> list[tuple[int, int]]:
    gray = image.convert("L")
    width, height = image.size
    candidates: list[tuple[float, tuple[int, int]]] = []
    for row in range(rows):
        for col in range(cols):
            if (shape_policy == "mixed" and signatures is not None
                    and not is_readable_standard_piece(signatures[(row, col)])):
                continue
            cell = (row, col)
            if isinstance(masks, LabelMaskMap):
                local_mask, bbox = masks.cropped(cell)
            else:
                full_mask = masks[cell]
                bbox = full_mask.getbbox()
                local_mask = full_mask.crop(bbox) if bbox else None
            if bbox is None or any(boxes_intersect(bbox, zone) for zone in protected):
                continue
            content = piece_content_profile(
                gray.crop(bbox), local_mask, min_piece_detail
            )
            if content_policy == "recognizable" and not content["recognizable_content"]:
                continue
            cx, cy = (xs[col] + xs[col + 1]) / 2, (ys[row] + ys[row + 1]) / 2
            dx, dy = abs(cx - width / 2) / (width / 2), abs(cy - height / 2) / (height / 2)
            peripheral = math.hypot(dx, dy)
            outer_edge_penalty = 5000.0 if row in (0, rows - 1) or col in (0, cols - 1) else 0.0
            # A detached piece is easiest to pair when it contains a moderate
            # charcoal transition. Near-flat black/white cells may be exact,
            # but the viewer cannot recognize where they belong. Prefer useful
            # detail without chasing the highest-contrast subject area.
            detail = float(content["luma_stddev"])
            mean = float(content["luma_mean"])
            score = (
                abs(detail - 30.0) * 1.5
                + max(0.0, min_piece_detail + 4.0 - detail) * 40.0
                + max(0.0, 35.0 - mean) * 5.0
                + max(0.0, mean - 220.0) * 5.0
                - 55.0 * peripheral
                + outer_edge_penalty
                + rng.random()
            )
            candidates.append((score, (row, col)))
    candidates.sort(key=lambda item: item[0])
    chosen: list[tuple[int, int]] = []
    while candidates and len(chosen) < missing_count:
        def spread_cost(item):
            score, cell = item
            for other in chosen:
                distance = math.hypot((cell[0]-other[0])/rows, (cell[1]-other[1])/cols)
                score += 180 / max(distance, .05)
                if cell[0] == other[0] or cell[1] == other[1]:
                    score += 170
            return score
        best = min(candidates, key=spread_cost)
        candidates.remove(best)
        chosen.append(best[1])
    if len(chosen) == missing_count:
        return chosen
    raise ValueError("not enough unprotected cells for the requested missing-piece count")


def is_readable_standard_piece(edges: dict[str, int]) -> bool:
    """Prefer an immediately legible mix of one or more tabs and sockets."""
    shaped = [value for value in edges.values() if value != FLAT]
    return TAB in shaped and SOCKET in shaped


def piece_shape_profile(edges: dict[str, int]) -> dict[str, int | bool]:
    values = list(edges.values())
    return {
        "tabs": values.count(TAB),
        "sockets": values.count(SOCKET),
        "flats": values.count(FLAT),
        "recognizable_mixed_shape": is_readable_standard_piece(edges),
    }


def piece_content_profile(
    gray: Image.Image,
    mask: Image.Image,
    min_piece_detail: float = DEFAULT_MIN_PIECE_DETAIL,
) -> dict[str, float | bool]:
    """Describe whether a source cell carries enough tonal information to pair by eye."""
    gray = gray.convert("L")
    bbox = mask.getbbox()
    if bbox is None:
        return {
            "luma_mean": 0.0,
            "luma_stddev": 0.0,
            "recognizable_content": False,
        }
    if gray.size == mask.size and bbox != (0, 0, mask.width, mask.height):
        stat = ImageStat.Stat(gray.crop(bbox), mask.crop(bbox))
    else:
        stat = ImageStat.Stat(gray, mask)
    mean = float(stat.mean[0])
    stddev = float(stat.stddev[0])
    return {
        "luma_mean": round(mean, 3),
        "luma_stddev": round(stddev, 3),
        "recognizable_content": (
            stddev >= min_piece_detail and 5.0 <= mean <= 250.0
        ),
    }


def mask_boundary(mask: Image.Image, width: int) -> Image.Image:
    kernel = max(3, width * 2 + 1)
    if kernel % 2 == 0:
        kernel += 1
    expanded = mask.filter(ImageFilter.MaxFilter(kernel))
    contracted = mask.filter(ImageFilter.MinFilter(kernel))
    return ImageChops.subtract(expanded, contracted)


def alpha_layer(size: tuple[int, int], color: tuple[int, int, int], alpha: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", size, color + (0,))
    layer.putalpha(alpha)
    return layer


def tighten_die_cut_alpha(piece: Image.Image) -> Image.Image:
    """Remove the long translucent fringe created by rotating a cut piece.

    The short transition keeps a single anti-aliased edge pixel, while the
    paperboard sidewall and soft cast shadow remain separate physical layers.
    """
    cleaned = piece.copy()
    alpha = cleaned.getchannel("A")
    low, high = 36, 219

    def remap(value: int) -> int:
        if value <= low:
            return 0
        if value >= high:
            return 255
        unit = (value - low) / (high - low)
        smooth = unit * unit * (3 - 2 * unit)
        return round(255 * smooth)

    cleaned.putalpha(alpha.point([remap(value) for value in range(256)]))
    return cleaned


def tone_lift_layer(
    base: Image.Image,
    lift_rgb: tuple[int, int, int],
    alpha: Image.Image,
) -> Image.Image:
    """Lift the local artwork instead of painting a fixed gray seam color."""
    source = base.convert("RGB")
    lifted = ImageChops.add(source, Image.new("RGB", source.size, lift_rgb))
    layer = lifted.convert("RGBA")
    layer.putalpha(alpha)
    return layer


def material_profile(name: str) -> MaterialPreset:
    try:
        return MATERIAL_PRESETS[name]
    except KeyError as exc:
        choices = ", ".join(MATERIAL_PRESETS)
        raise ValueError(f"material_preset must be one of: {choices}") from exc


def shift_mask(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    """Translate an alpha mask without the edge wrapping of ImageChops.offset."""
    shifted = Image.new("L", mask.size, 0)
    shifted.paste(mask, (dx, dy))
    return shifted


def owner_change(labels: Image.Image, dx: int, dy: int) -> Image.Image:
    """Mark pixels whose owner differs from the owner at a shifted position."""
    shifted = Image.new("RGB", labels.size, 0)
    shifted.paste(labels, (dx, dy))
    difference = ImageChops.difference(labels, shifted)
    bands = difference.split()
    changed = ImageChops.lighter(bands[0], ImageChops.lighter(bands[1], bands[2]))
    changed = changed.point([0] + [255] * 255)
    # The jigsaw occupies the whole canvas; the outside canvas edge is not a
    # die cut and must not become a decorative frame.
    draw = ImageDraw.Draw(changed)
    if dx > 0:
        draw.rectangle((0, 0, dx - 1, labels.height - 1), fill=0)
    elif dx < 0:
        draw.rectangle((labels.width + dx, 0, labels.width - 1, labels.height - 1), fill=0)
    if dy > 0:
        draw.rectangle((0, 0, labels.width - 1, dy - 1), fill=0)
    elif dy < 0:
        draw.rectangle((0, labels.height + dy, labels.width - 1, labels.height - 1), fill=0)
    return changed


def seam_fields_from_labels(
    labels: Image.Image, seam_width: int, shoulder_width: int
) -> tuple[Image.Image, Image.Image, Image.Image, Image.Image, Image.Image]:
    """Build physical seam fields in constant full-canvas passes.

    The previous renderer repeated the same morphology for every piece. Owner
    labels already encode every shared boundary, so directional comparisons
    reproduce the opposing shoulders without work proportional to piece count.
    """
    labels = labels.convert("RGB")

    def axis_shoulder(dx: int, dy: int) -> tuple[Image.Image, Image.Image]:
        core = owner_change(labels, dx, dy)
        mid_extent = owner_change(
            labels, dx * (shoulder_width - 1), dy * (shoulder_width - 1)
        )
        far_extent = owner_change(labels, dx * shoulder_width, dy * shoulder_width)
        middle = ImageChops.subtract(mid_extent, core).point(
            [round(value * .52) for value in range(256)]
        )
        far = ImageChops.subtract(far_extent, mid_extent).point(
            [round(value * .22) for value in range(256)]
        )
        return core, ImageChops.lighter(core, ImageChops.lighter(middle, far))

    top_core, top = axis_shoulder(0, 1)
    left_core, left = axis_shoulder(1, 0)
    bottom_core, bottom = axis_shoulder(0, -1)
    right_core, right = axis_shoulder(-1, 0)
    edge_core = ImageChops.lighter(
        ImageChops.lighter(top_core, bottom_core),
        ImageChops.lighter(left_core, right_core),
    )
    cut_kernel = max(3, seam_width * 2 + 1)
    shoulder_kernel = max(3, shoulder_width * 2 + 1)
    cut_seam = edge_core.filter(ImageFilter.MaxFilter(cut_kernel))
    seam = edge_core.filter(ImageFilter.MaxFilter(shoulder_kernel))
    upper_left = ImageChops.lighter(
        top, left.point([round(value * .72) for value in range(256)])
    )
    lower_right = ImageChops.lighter(
        bottom, right.point([round(value * .82) for value in range(256)])
    )
    upper_left = ImageChops.multiply(upper_left, seam)
    lower_right = ImageChops.multiply(lower_right, seam)
    cut_owner = ImageChops.lighter(bottom_core, right_core)
    return cut_seam, seam, upper_left, lower_right, cut_owner


def extrude_mask(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    """Sweep a face mask through every integer depth step, without gaps."""
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return mask.copy()
    extrusion = mask.copy()
    for step in range(1, steps + 1):
        sx = round(dx * step / steps)
        sy = round(dy * step / steps)
        extrusion = ImageChops.lighter(extrusion, shift_mask(mask, sx, sy))
    return extrusion


def adaptive_alpha(mask: Image.Image, luma: Image.Image, low: int, high: int) -> Image.Image:
    weights = luma.point([round(low + (high - low) * value / 255) for value in range(256)])
    return ImageChops.multiply(mask, weights)


def low_frequency_seam_modulation(size: tuple[int, int], seed: int) -> Image.Image:
    """Return slow pressure variation, never pixel noise or dust speckling."""
    width, height = size
    small_size = (max(2, width // 48), max(2, height // 48))
    rng = random.Random(seed)
    field = Image.frombytes("L", small_size, rng.randbytes(small_size[0] * small_size[1]))
    field = field.filter(ImageFilter.GaussianBlur(1.25)).resize(size, Image.Resampling.BICUBIC)
    return field.point([round(190 + 65 * value / 255) for value in range(256)])


def add_puzzle_seams(base: Image.Image, masks: Iterable[Image.Image], seam_width: int,
                     protected: Sequence[Sequence[int]] = (),
                     material_preset: str = "graphite-matte",
                     relief_seed: int = 0,
                     owner_labels: Image.Image | None = None) -> Image.Image:
    profile = material_profile(material_preset)
    # A broad, low-amplitude shoulder makes the assembled board readable at
    # fit view without turning the shared cut into a drawn outline. The source
    # is still modified only inside this narrow physical seam band.
    shoulder_width = max(4, seam_width + 3)
    if owner_labels is not None:
        cut_seam, seam, upper_left, lower_right, cut_owner = seam_fields_from_labels(
            owner_labels, seam_width, shoulder_width
        )
    else:
        piece_masks = list(masks)
        cut_seam = Image.new("L", base.size, 0)
        seam = Image.new("L", base.size, 0)
        upper_left = Image.new("L", base.size, 0)
        lower_right = Image.new("L", base.size, 0)
        cut_owner = Image.new("L", base.size, 0)

        def axis_shoulder(
            piece_mask: Image.Image, dx: int, dy: int
        ) -> tuple[Image.Image, Image.Image]:
            core = ImageChops.subtract(
                piece_mask, shift_mask(piece_mask, dx, dy)
            )
            mid_extent = ImageChops.subtract(
                piece_mask,
                shift_mask(
                    piece_mask,
                    dx * (shoulder_width - 1),
                    dy * (shoulder_width - 1),
                ),
            )
            far_extent = ImageChops.subtract(
                piece_mask,
                shift_mask(
                    piece_mask,
                    dx * shoulder_width,
                    dy * shoulder_width,
                ),
            )
            middle = ImageChops.subtract(mid_extent, core).point(
                lambda p: round(p * .52)
            )
            far = ImageChops.subtract(far_extent, mid_extent).point(
                lambda p: round(p * .22)
            )
            return core, ImageChops.lighter(core, ImageChops.lighter(middle, far))

        for piece_mask in piece_masks:
            cut_seam = ImageChops.lighter(
                cut_seam, mask_boundary(piece_mask, seam_width)
            )
            seam = ImageChops.lighter(seam, mask_boundary(piece_mask, shoulder_width))
            # Preserve ownership and separate horizontal/vertical face normals.
            top_core, top = axis_shoulder(piece_mask, 0, 1)
            left_core, left = axis_shoulder(piece_mask, 1, 0)
            bottom_core, bottom = axis_shoulder(piece_mask, 0, -1)
            right_core, right = axis_shoulder(piece_mask, -1, 0)
            upper_left = ImageChops.lighter(
                upper_left,
                ImageChops.lighter(top, left.point(lambda p: round(p * .72))),
            )
            lower_right = ImageChops.lighter(
                lower_right,
                ImageChops.lighter(bottom, right.point(lambda p: round(p * .82))),
            )
            cut_owner = ImageChops.lighter(
                cut_owner, ImageChops.lighter(bottom_core, right_core),
            )
        upper_left = ImageChops.multiply(upper_left, seam)
        lower_right = ImageChops.multiply(lower_right, seam)
    # Min/Max filters extend at the image boundary: there is no exterior outline
    # to erase. Clearing border strips used to cut off internal seams as well.
    strength = Image.new('L', base.size, 255)
    for box in protected:
        ImageDraw.Draw(strength).rectangle(tuple(box), fill=profile.protected_strength)
    strength = strength.filter(ImageFilter.GaussianBlur(5))
    raw_cut_pressure = low_frequency_seam_modulation(base.size, relief_seed)
    cut_pressure = raw_cut_pressure.point(
        lambda p: round(224 + (p - 190) * 31 / 65)
    )
    raw_shoulder_pressure = low_frequency_seam_modulation(
        base.size, relief_seed + 104729
    )
    shoulder_pressure = raw_shoulder_pressure.point(
        lambda p: round(165 + (p - 190) * 90 / 65)
    )
    cut_relief = ImageChops.multiply(
        strength,
        cut_pressure,
    )
    shoulder_relief = ImageChops.multiply(
        strength,
        shoulder_pressure,
    )
    cut_seam = ImageChops.multiply(cut_seam, cut_relief)
    cut_owner = ImageChops.multiply(cut_owner, cut_relief)
    seam = ImageChops.multiply(seam, shoulder_relief)
    upper_left = ImageChops.multiply(upper_left, shoulder_relief)
    lower_right = ImageChops.multiply(lower_right, shoulder_relief)

    result = base.convert("RGBA")
    luma = base.convert("L")
    # A faint shared depression keeps antialiased curves continuous. The
    # actual cut channel sits on only one owner side, leaving the neighbor's
    # shoulder available to catch light rather than darkening both equally.
    shared_groove = cut_seam.filter(
        ImageFilter.GaussianBlur(max(.25, seam_width * .25))
    )
    shared_dark = adaptive_alpha(
        shared_groove, luma,
        max(1, round(profile.seam_dark_low * .055)),
        max(1, round(profile.seam_dark_high * .055)),
    )
    result = Image.alpha_composite(
        result, alpha_layer(base.size, (10, 10, 10), shared_dark)
    )
    cut_face = ImageChops.darker(cut_owner, cut_seam)
    cut_channel = adaptive_alpha(
        cut_face.filter(ImageFilter.GaussianBlur(.32)),
        luma, profile.seam_dark_low, profile.seam_dark_high,
    )
    result = Image.alpha_composite(
        result, alpha_layer(base.size, (8, 8, 8), cut_channel)
    )

    # Both shoulders remain inside the cut band, so untouched charcoal stays
    # pixel-exact while adjacent pieces receive opposing relief.
    lower_shadow = lower_right.filter(ImageFilter.GaussianBlur(.28)).point(
        lambda p: round(p * profile.shoulder_shadow / 255)
    )
    result = Image.alpha_composite(result, alpha_layer(base.size, (5, 5, 5), lower_shadow))
    if profile.seam_return_low:
        return_light = adaptive_alpha(
            lower_right, luma, profile.seam_return_low, 0
        )
        result = Image.alpha_composite(
            result, tone_lift_layer(base, profile.seam_return_rgb, return_light)
        )

    highlight = adaptive_alpha(
        upper_left.filter(ImageFilter.GaussianBlur(.24)),
        luma,
        profile.seam_light_low,
        profile.seam_light_high,
    )
    result = Image.alpha_composite(
        result, tone_lift_layer(base, profile.highlight_rgb, highlight)
    )
    return result


def make_substrate(size: tuple[int, int], color: tuple[int, int, int], seed: int) -> Image.Image:
    """Build quiet two-scale board tooth without salt-and-pepper speckling."""
    width, height = size
    small_size = (max(2, width // 4), max(2, height // 4))
    rng = random.Random(seed)
    coarse = Image.frombytes(
        "L", small_size, rng.randbytes(small_size[0] * small_size[1])
    )
    coarse = coarse.filter(ImageFilter.GaussianBlur(1.15)).resize(
        size, Image.Resampling.BICUBIC
    )
    # A second softly blurred field supplies the fine paper tooth visible in
    # the reference holes. Both fields remain continuous, so this cannot turn
    # into isolated ink dots or synthetic salt-and-pepper grain.
    fine = Image.frombytes("L", size, rng.randbytes(width * height)).filter(
        ImageFilter.GaussianBlur(.9)
    )
    coarse_term = coarse.point(lambda p: 128 + round((p - 128) / 19))
    fine_term = fine.point(lambda p: 128 + round((p - 128) / 27))
    channels = []
    for channel in color:
        textured = ImageChops.add(
            Image.new("L", size, channel), coarse_term, offset=-128
        )
        textured = ImageChops.add(textured, fine_term, offset=-128)
        channels.append(textured)
    return Image.merge("RGB", channels).convert("RGBA")


def _render_hole_region(
    surface: Image.Image,
    hole_union: Image.Image,
    hole_color: tuple[int, int, int],
    seed: int,
    material_preset: str = "graphite-matte",
) -> Image.Image:
    """Seat exact hole masks into a quiet board substrate with a directional cut wall."""
    profile = material_profile(material_preset)
    result = surface.convert("RGBA").copy()
    substrate = make_substrate(surface.size, hole_color, seed)
    result.paste(substrate, (0, 0), hole_union)

    # Build the visible paperboard section as quiet nested rings. The depth is
    # tied to the same material preset as the detached piece, so the cavity and
    # its counterpart agree instead of looking like unrelated flat icons.
    current = hole_union
    wall_depth = max(profile.piece_depth)
    for layer in range(wall_depth):
        eroded = current.filter(ImageFilter.MinFilter(3))
        ring = ImageChops.subtract(current, eroded)
        # A cut wall needs an actual tonal ramp on both pale and dark backing
        # boards. Ratio-only darkening disappears when ``hole_color`` is near
        # charcoal, so blend the exposed paper core toward a warm occlusion
        # tone and progressively open it into the quiet substrate. The rings
        # are continuous masks, never a decorative outline or dot texture.
        progress = layer / max(1, wall_depth - 1)
        if material_preset == "ivory-board":
            # On pale paperboard the exposed core is only modestly darker
            # than the printed face.  A near-black symmetric ring reads as a
            # vector outline; use the warm paper core here and reserve true
            # occlusion for the directional upper/left wall below.
            occlusion_rgb = profile.piece_wall_rgb
            shadow_mix = .62 + (.18 - .62) * progress
            wall_opacity = min(176, profile.hole_wall_alpha + 34 - layer * 7)
        else:
            occlusion_rgb = (12, 11, 10)
            shadow_mix = .74 + (.16 - .74) * progress
            wall_opacity = min(230, profile.hole_wall_alpha + 72 - layer * 10)
        wall_color = tuple(
            round(channel * (1 - shadow_mix) + occlusion * shadow_mix)
            for channel, occlusion in zip(hole_color, occlusion_rgb)
        )
        wall_alpha = ring.point(
            lambda p, opacity=wall_opacity: round(p * opacity / 255)
        )
        result = Image.alpha_composite(
            result, alpha_layer(surface.size, wall_color, wall_alpha)
        )
        current = eroded

    # Seat the backing plane down and slightly away from the upper-left light.
    # Its offset exposes a full-depth top/left paperboard section and only a
    # narrow reflected lip at bottom/right.  A symmetric dark ring around a
    # uniform fill reads as a gray puzzle tile; this parallax is the decisive
    # cavity cue visible in the physical reference.
    floor_inset = hole_union.filter(ImageFilter.MinFilter(3))
    floor_plane = ImageChops.multiply(
        floor_inset,
        shift_mask(floor_inset, wall_depth - 1, wall_depth - 1),
    )
    result.paste(substrate, (0, 0), floor_plane)
    wall_band = ImageChops.subtract(hole_union, floor_plane)
    # Recessed material reverses the polarity of a loose raised piece under the
    # same upper-left light: upper/left cavity walls fall into shade, while the
    # lower/right wall catches a restrained reflected edge. This directional
    # cue is what prevents a filled hole from reading as a blank puzzle tile.
    top_wall = ImageChops.multiply(
        wall_band,
        ImageChops.subtract(hole_union, shift_mask(hole_union, 0, wall_depth)),
    )
    left_wall = ImageChops.multiply(
        wall_band,
        ImageChops.subtract(hole_union, shift_mask(hole_union, wall_depth, 0)),
    )
    bottom_wall = ImageChops.multiply(
        wall_band,
        ImageChops.subtract(hole_union, shift_mask(hole_union, 0, -wall_depth)),
    )
    right_wall = ImageChops.multiply(
        wall_band,
        ImageChops.subtract(hole_union, shift_mask(hole_union, -wall_depth, 0)),
    )
    upper_left_wall = ImageChops.lighter(top_wall, left_wall)
    lower_right_wall = ImageChops.lighter(bottom_wall, right_wall)
    inner_shadow = ImageChops.multiply(
        upper_left_wall.filter(ImageFilter.GaussianBlur(1.35)), hole_union
    ).point(lambda p: round(p * profile.hole_shadow_alpha / 255))
    result = Image.alpha_composite(
        result, alpha_layer(surface.size, (12, 11, 10), inner_shadow)
    )
    # The lowered backing receives a short, warm contact shadow just beyond
    # the top/left cut face. It uses the backing colour itself, so even a dark
    # still-life cavity gains depth without acquiring a black vector outline.
    floor_cast = min(4, max(3, wall_depth))
    floor_top = ImageChops.subtract(
        floor_plane, shift_mask(floor_plane, 0, floor_cast)
    )
    floor_left = ImageChops.subtract(
        floor_plane, shift_mask(floor_plane, floor_cast, 0)
    )
    floor_contact = ImageChops.multiply(
        ImageChops.lighter(floor_top, floor_left).filter(ImageFilter.GaussianBlur(1.25)),
        floor_plane,
    ).point(lambda p: round(p * profile.hole_shadow_alpha * .88 / 255))
    floor_shadow_rgb = tuple(round(channel * .42) for channel in hole_color)
    result = Image.alpha_composite(
        result, alpha_layer(surface.size, floor_shadow_rgb, floor_contact)
    )

    reflected_rgb = tuple(round(channel * .82 + 255 * .18) for channel in hole_color)
    reflected = ImageChops.multiply(
        lower_right_wall.filter(ImageFilter.GaussianBlur(.45)), hole_union
    ).point(lambda p: round(p * profile.hole_wall_alpha * .40 / 255))
    result = Image.alpha_composite(
        result, alpha_layer(surface.size, reflected_rgb, reflected)
    )
    # The reflected cue belongs at the *inner* edge of the cut face. Spreading
    # it across the entire right/bottom wall flattens the wall into one gray
    # patch, especially on dark still-life backings.
    inner_lip = ImageChops.subtract(
        floor_plane.filter(ImageFilter.MaxFilter(3)), floor_plane
    )
    reflected_lip = ImageChops.multiply(inner_lip, lower_right_wall).point(
        lambda p: round(p * min(128, profile.hole_wall_alpha * .82) / 255)
    )
    result = Image.alpha_composite(
        result, alpha_layer(surface.size, reflected_rgb, reflected_lip)
    )
    return result


def _hole_patch(
    surface: Image.Image,
    hole_union: Image.Image,
    hole_color: tuple[int, int, int],
    seed: int,
    material_preset: str = "graphite-matte",
) -> tuple[tuple[int, int], Image.Image] | None:
    """Return one bounded cavity patch and its destination origin."""
    bbox = hole_union.getbbox()
    if bbox is None:
        return None
    profile = material_profile(material_preset)
    padding = max(profile.piece_depth) + 8
    x0 = max(0, bbox[0] - padding)
    y0 = max(0, bbox[1] - padding)
    x1 = min(surface.width, bbox[2] + padding)
    y1 = min(surface.height, bbox[3] + padding)
    region = (x0, y0, x1, y1)
    patch = _render_hole_region(
        surface.crop(region), hole_union.crop(region), hole_color, seed,
        material_preset,
    )
    return (x0, y0), patch


def render_holes(
    surface: Image.Image,
    hole_union: Image.Image,
    hole_color: tuple[int, int, int],
    seed: int,
    material_preset: str = "graphite-matte",
) -> Image.Image:
    """Render sparse cavities in a bounded patch instead of a full-canvas field.

    Hole relief uses only local masks, so allocating fibre noise and repeated
    morphology for every pixel of a wide social cover wastes most of the
    runtime.  The padded crop contains the complete wall, reflected lip and
    both shadow scales; pixels outside it are copied without modification.
    """
    rendered = _hole_patch(
        surface, hole_union, hole_color, seed, material_preset
    )
    result = surface.convert("RGBA").copy()
    if rendered is not None:
        origin, patch = rendered
        result.alpha_composite(patch, origin)
    return result


def place_lifted_piece(
    canvas: Image.Image,
    piece: Image.Image,
    left: int,
    top: int,
    hole_color: tuple[int, int, int],
    material_preset: str = "graphite-matte",
) -> Image.Image:
    """Place an exact top face over thin sidewall and two-scale contact shadows."""
    profile = material_profile(material_preset)
    result = canvas.convert("RGBA").copy()
    alpha = piece.getchannel("A")

    depth_x, depth_y = profile.piece_depth
    far_shadow = alpha.filter(ImageFilter.GaussianBlur(4.2)).point(
        lambda p: round(p * profile.piece_far_shadow / 255)
    )
    result.alpha_composite(
        alpha_layer(piece.size, (0, 0, 0), far_shadow),
        (left + depth_x + 3, top + depth_y + 3),
    )
    near_shadow = alpha.filter(ImageFilter.GaussianBlur(1.25)).point(
        lambda p: round(p * profile.piece_near_shadow / 255)
    )
    result.alpha_composite(
        alpha_layer(piece.size, (0, 0, 0), near_shadow),
        (left + depth_x + 1, top + depth_y + 1),
    )

    derived_wall = tuple(channel * .58 for channel in hole_color)
    target_wall_mean = sum(profile.piece_wall_rgb) / 3
    wall_scale = max(1., target_wall_mean / max(1., sum(derived_wall) / 3))
    wall_color = tuple(min(255, round(channel * wall_scale)) for channel in derived_wall)
    # Paint the paperboard core as successive translated silhouettes on the
    # destination canvas. A single union mask creates one flat gray strip and
    # clips the outermost tabs at the tight source crop. Far-to-near layering
    # preserves the full 4–6 px extrusion and adds a restrained depth falloff.
    depth_steps = max(abs(depth_x), abs(depth_y))
    for step in range(depth_steps, 0, -1):
        sx = round(depth_x * step / depth_steps)
        sy = round(depth_y * step / depth_steps)
        distance = (step - 1) / max(1, depth_steps - 1)
        shade = 1.08 - .36 * distance
        layer_color = tuple(
            max(0, min(255, round(channel * shade))) for channel in wall_color
        )
        wall_alpha = alpha.point(lambda p: round(p * .92))
        result.alpha_composite(
            alpha_layer(piece.size, layer_color, wall_alpha),
            (left + sx, top + sy),
        )
    if material_preset != "ivory-board":
        upper_edge = ImageChops.subtract(shift_mask(alpha, -1, -1), alpha).point(
            lambda p: round(p * .42)
        )
        result.alpha_composite(
            alpha_layer(piece.size, profile.highlight_rgb, upper_edge), (left, top)
        )
    # A physical die-cut piece has a restrained bevel on its printed face.
    # Keep the original artwork pixel-exact away from the narrow edge band;
    # only the top/left and bottom/right rims receive directional relief.
    face = piece.copy()
    top_edge = ImageChops.subtract(alpha, shift_mask(alpha, 0, 1))
    left_edge = ImageChops.subtract(alpha, shift_mask(alpha, 1, 0))
    bottom_edge = ImageChops.subtract(alpha, shift_mask(alpha, 0, -1))
    right_edge = ImageChops.subtract(alpha, shift_mask(alpha, -1, 0))
    upper_rim = ImageChops.lighter(top_edge, left_edge).filter(ImageFilter.GaussianBlur(.35))
    lower_rim = ImageChops.lighter(bottom_edge, right_edge).filter(ImageFilter.GaussianBlur(.35))
    upper_strength = .14 if material_preset == "ivory-board" else .32
    upper_rim = ImageChops.multiply(upper_rim, alpha).point(
        lambda p: round(p * upper_strength)
    )
    lower_strength = .15 if material_preset == "ivory-board" else .28
    lower_rim = ImageChops.multiply(lower_rim, alpha).point(
        lambda p: round(p * lower_strength)
    )
    if material_preset == "ivory-board":
        # Lighten the printed face relative to its own pixels instead of
        # painting a fixed dark stroke around it.  This keeps the exact source
        # artwork intact away from the one-pixel bevel and removes the sticker
        # outline visible on pale social covers.
        face = Image.alpha_composite(
            face, tone_lift_layer(face, profile.highlight_rgb, upper_rim)
        )
    else:
        face = Image.alpha_composite(
            face, alpha_layer(piece.size, profile.highlight_rgb, upper_rim)
        )
    face = Image.alpha_composite(face, alpha_layer(piece.size, (8, 8, 8), lower_rim))
    face.putalpha(alpha)
    result.alpha_composite(face, (left, top))
    return result


def extract_piece(source: Image.Image, mask: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError("empty piece mask")
    rgba = source.convert("RGBA").crop(bbox)
    rgba.putalpha(mask.crop(bbox))
    return rgba, bbox


def hash_image(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def choose_destination(
    rotated_size: tuple[int, int],
    source_bbox: Sequence[int],
    candidate_centers: Sequence[tuple[float, float, float, float]],
    piece_luma: float,
    blocked: Sequence[Sequence[int]],
    canvas_size: tuple[int, int],
) -> tuple[int, int, tuple[int, int, int, int]]:
    width, height = canvas_size
    rw, rh = rotated_size
    # Prefer readable but moderate contrast, not a white sticker on the darkest
    # available spot. Keep the correspondence locally understandable.
    sx, sy = (source_bbox[0]+source_bbox[2])/2, (source_bbox[1]+source_bbox[3])/2
    ranked = sorted(candidate_centers, key=lambda item:
        math.sqrt(item[0]) + abs(abs(item[1]-piece_luma)-28)*2
        + math.hypot((item[2]-sx)/width,(item[3]-sy)/height)*45)
    # A regular sample grid can miss a valid narrow corridor by a few pixels.
    # Add candidates flush with obstacle edges before declaring packing failure.
    obstacles = [source_bbox, *blocked]
    lefts = {2, width-rw-2}
    tops = {2, height-rh-2}
    for box in obstacles:
        lefts.update((box[0]-rw-2, box[2]+2))
        tops.update((box[1]-rh-2, box[3]+2))
    ranked.extend((0, 0, x+rw/2, y+rh/2) for y in sorted(tops) for x in sorted(lefts))
    for _, _, cx, cy in ranked:
        left, top = round(cx - rw / 2), round(cy - rh / 2)
        bbox = (left, top, left + rw, top + rh)
        if left < 2 or top < 2 or bbox[2] > width - 2 or bbox[3] > height - 2:
            continue
        if boxes_intersect(bbox, source_bbox):
            continue
        if any(boxes_intersect(bbox, item) for item in blocked):
            continue
        return left, top, bbox
    raise ValueError("unable to place lifted pieces; reduce missing count or protected area")


def compose(
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    rows: int,
    cols: int,
    missing_count: int,
    seed: int,
    protected_norm: Sequence[Sequence[float]],
    manual_cells: Sequence[tuple[int, int]],
    knob_ratio: float,
    seam_width: int,
    max_rotation: float,
    hole_color: tuple[int, int, int],
    pieces_dir: Path | None = None,
    cut_style: str = 'standard',
    manual_placements: Sequence[Sequence[float]] = (),
    material_preset: str = "graphite-matte",
    assembled_output_path: Path | None = None,
    shape_policy: str = "mixed",
    content_policy: str = "recognizable",
    min_piece_detail: float = DEFAULT_MIN_PIECE_DETAIL,
    preserve_existing_seams: bool = False,
) -> dict:
    material_profile(material_preset)
    if assembled_output_path is None:
        assembled_output_path = output_path.with_name(
            output_path.stem + ".assembled.png"
        )
    destinations = [output_path, manifest_path, assembled_output_path]
    if pieces_dir:
        destinations += [pieces_dir / f'p-{i:02d}.png' for i in range(1, missing_count+1)]
    resolved = [input_path.resolve(), *(p.resolve() for p in destinations)]
    if len(set(resolved)) != len(resolved):
        raise ValueError('source, output, manifest and piece paths must be distinct')
    if any(p.exists() for p in destinations):
        raise ValueError('output already exists; choose a new versioned destination')
    if output_path.suffix.lower() != '.png':
        raise ValueError('use lossless PNG for an auditable composite')
    if assembled_output_path.suffix.lower() != '.png':
        raise ValueError('use lossless PNG for the assembled proof')
    if shape_policy not in ('mixed', 'any'):
        raise ValueError("shape_policy must be 'mixed' or 'any'")
    if content_policy not in ('recognizable', 'any'):
        raise ValueError("content_policy must be 'recognizable' or 'any'")
    if not math.isfinite(min_piece_detail) or not 0 <= min_piece_detail <= 64:
        raise ValueError('min_piece_detail must be finite and between 0 and 64')
    if not math.isfinite(max_rotation) or not 0 <= max_rotation <= 45:
        raise ValueError('max_rotation must be finite and between 0 and 45')
    if manual_placements and len(manual_placements) != missing_count:
        raise ValueError('placement count must equal missing_count, in selected-cell order')
    for placement in manual_placements:
        if (len(placement) != 3 or not all(math.isfinite(p) for p in placement)
                or not 0 <= placement[0] <= 1 or not 0 <= placement[1] <= 1
                or abs(placement[2]) > max_rotation):
            raise ValueError('placement must be normalized center x,y and rotation within max_rotation')
    if not isinstance(seam_width, int) or not 1 <= seam_width <= 4:
        raise ValueError('seam_width must be an integer between 1 and 4')
    for box in protected_norm:
        if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise ValueError('invalid normalized protected box')
    with Image.open(input_path) as opened:
        source = ImageOps.exif_transpose(opened).convert('RGBA')
    if source.getchannel('A').getextrema() != (255,255):
        raise ValueError('flatten transparent input onto the intended paper before cutting')
    width, height = source.size
    if rows < 2 or cols < 2:
        raise ValueError("rows and cols must both be at least 2")
    if missing_count < 1:
        raise ValueError("missing-count must be at least 1")
    if min(width/cols, height/rows) < 24:
        raise ValueError('cells must be at least 24 pixels on each axis')
    # Standard-v5 uses one owner-label raster and expands only the selected
    # piece masks, so its memory cost is O(canvas + selected pieces), not
    # O(canvas * every grid cell).  Keep the legacy ceiling for modes that
    # still materialize the complete mask set.
    if cut_style != 'standard' and width*height*rows*cols > 300_000_000:
        raise ValueError('mask memory budget exceeded; reduce resolution or grid density')
    if manual_cells and len(manual_cells) != missing_count:
        raise ValueError('manual cell count must equal missing_count')
    if not 0.08 <= knob_ratio <= 0.22:
        raise ValueError("knob-ratio must be between 0.08 and 0.22")

    masks, signatures, xs, ys = masks_and_signatures(source.size, rows, cols, seed, knob_ratio, cut_style)
    protected = to_pixel_boxes(protected_norm, source.size)
    rng = random.Random(seed + 991)
    source_gray = source.convert("L")

    if manual_cells:
        if len(set(manual_cells)) != len(manual_cells):
            raise ValueError("manual missing cells must be unique")
        selected = list(manual_cells)
        for cell in selected:
            if cell not in masks:
                raise ValueError(f"manual cell out of range: {cell}")
            if isinstance(masks, LabelMaskMap):
                local_mask, bbox = masks.cropped(cell)
            else:
                local_mask = masks[cell]
                bbox = local_mask.getbbox()
            if bbox and any(boxes_intersect(bbox, zone) for zone in protected):
                raise ValueError(f"manual cell intersects a protected box: {cell}")
            if (cut_style == 'standard' and shape_policy == 'mixed'
                    and not is_readable_standard_piece(signatures[cell])):
                raise ValueError(
                    f"manual cell lacks a mixed tab/socket silhouette under the mixed shape policy: {cell}"
                )
            if (content_policy == 'recognizable'
                    and not piece_content_profile(
                        source_gray.crop(bbox),
                        local_mask if isinstance(masks, LabelMaskMap) else local_mask.crop(bbox),
                        min_piece_detail,
                    )['recognizable_content']):
                raise ValueError(
                    f"manual cell lacks recognizable source detail under the recognizable content policy: {cell}"
                )
    else:
        selected = select_missing_cells(
            source, masks, xs, ys, rows, cols, missing_count, protected, rng,
            signatures, shape_policy if cut_style == 'standard' else 'any',
            content_policy, min_piece_detail,
        )

    surface = source.copy() if preserve_existing_seams else add_puzzle_seams(
        source, masks.values(), seam_width, protected, material_preset, seed + 271,
        owner_labels=masks.labels if isinstance(masks, LabelMaskMap) else None,
    )
    result = surface.copy()
    hole_union = Image.new("L", source.size, 0)
    hole_bboxes: list[tuple[int, int, int, int]] = []
    for cell in selected:
        hole_union = ImageChops.lighter(hole_union, masks[cell])
        bbox = masks[cell].getbbox()
        if bbox:
            hole_bboxes.append(bbox)
    # Cavities are sparse. Render each exact mask in its own bounded patch so
    # paper fibres and morphology scale with the three holes rather than the
    # entire cover. The cell-derived seed keeps each texture stable even if
    # pair ordering changes.
    for row, col in selected:
        rendered_hole = _hole_patch(
            result, masks[(row, col)], hole_color,
            seed + 515 + row * 4099 + col, material_preset,
        )
        if rendered_hole is not None:
            origin, patch = rendered_hole
            result.alpha_composite(patch, origin)

    gray = source_gray
    grid_centers: list[tuple[float, float, float, float]] = []
    sample_w = max(12, round(width / cols))
    sample_h = max(12, round(height / rows))
    step_x = max(6, sample_w // 4)
    step_y = max(6, sample_h // 4)
    for cy in range(sample_h // 2, height, step_y):
        for cx in range(sample_w // 2, width, step_x):
            bbox = (
                max(0, cx - sample_w // 2),
                max(0, cy - sample_h // 2),
                min(width, cx + sample_w // 2),
                min(height, cy + sample_h // 2),
            )
            if any(boxes_intersect(bbox, zone) for zone in protected):
                continue
            score = local_variance(gray, bbox) + rng.random() * 5
            mean = local_mean(gray, bbox)
            grid_centers.append((score, mean, cx, cy))
    grid_centers.sort(key=lambda item: item[0])

    pending_assets = []
    placed: list[tuple[int, int, int, int]] = []
    pairs: list[dict] = []
    for index, cell in enumerate(selected, start=1):
        piece, source_bbox = extract_piece(source, masks[cell])
        pair_id = f"p-{index:02d}"
        content_hash = hash_image(piece)
        mask_hash = hash_image(masks[cell].crop(source_bbox))
        asset_path = None
        if pieces_dir:
            asset = pieces_dir / f"{pair_id}.png"
            pending_assets.append((asset, piece.copy()))
            asset_path = str(asset)

        rotation = manual_placements[index-1][2] if manual_placements else rng.uniform(-max_rotation, max_rotation)
        rotated = piece.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True)
        rotated = tighten_die_cut_alpha(rotated)
        # Padding reserves the entire shadow footprint, including near canvas edges.
        rotated = ImageOps.expand(rotated, border=10, fill=(0,0,0,0))
        piece_luma = float(ImageStat.Stat(piece.convert("L"), piece.getchannel("A")).mean[0])
        if manual_placements:
            nx,ny,_ = manual_placements[index-1]
            left,top = round(nx*width-rotated.width/2),round(ny*height-rotated.height/2)
            destination_bbox = (left,top,left+rotated.width,top+rotated.height)
            if (not (2 <= left and 2 <= top and destination_bbox[2] <= width-2 and destination_bbox[3] <= height-2)
                    or any(boxes_intersect(destination_bbox,box) for box in [*protected,*hole_bboxes,*placed])):
                raise ValueError(f'designed placement {index} intersects a hole, protected region, another piece or canvas edge')
        else:
            left, top, destination_bbox = choose_destination(
                rotated.size, source_bbox, grid_centers, piece_luma,
                [*protected, *hole_bboxes, *placed], source.size,
            )
        placed.append(destination_bbox)

        result = place_lifted_piece(
            result, rotated, left, top, hole_color, material_preset
        )

        edge_values = signatures[cell]
        edges = {key: edge_name(value) for key, value in edge_values.items()}
        content_profile = piece_content_profile(gray, masks[cell], min_piece_detail)
        pairs.append(
            {
                "pair_id": pair_id,
                "cell": [cell[0], cell[1]],
                "source_bbox": list(source_bbox),
                "edges": edges,
                "shape_profile": piece_shape_profile(edge_values),
                "content_profile": content_profile,
                "rotation_degrees": rotation,
                "mirrored": False,
                "destination_center": [round(left + rotated.width / 2), round(top + rotated.height / 2)],
                "destination_bbox": list(destination_bbox),
                "mask_sha256": mask_hash,
                "content_sha256": content_hash,
                "piece_asset": asset_path,
            }
        )

    # Geometry/placement failures have no output side effects. Disk I/O failures
    # can still leave files; never overwrite a previous run when retrying.
    for asset, piece in pending_assets:
        asset.parent.mkdir(parents=True, exist_ok=True)
        piece.save(asset)
    assembled_output_path.parent.mkdir(parents=True, exist_ok=True)
    surface.save(assembled_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_image = result.convert("RGB") if output_path.suffix.lower() in {".jpg", ".jpeg"} else result
    save_image.save(output_path)

    geometry_version = STANDARD_GEOMETRY_VERSION if cut_style == 'standard' else 2
    compositor_revision = STANDARD_COMPOSITOR_REVISION if cut_style == 'standard' else f'0.6-{cut_style}'
    manifest = {
        "schema": "black-dust-puzzle/v3",
        "mode": "exact_composite",
        "compositor_revision": compositor_revision,
        "material_preset": material_preset,
        "material_lighting": "upper-left",
        "seam_relief_seed": seed + 271,
        "preserve_existing_seams": bool(preserve_existing_seams),
        "rendering_note": "Unrotated assets are exact source crops; rotated display edges are bicubic resampled and receive relief only in a narrow face-edge band. Inverse-rotating the display is not pixel-exact.",
        "display_edge_profile": "clean-die-cut; compact one-pixel antialias, separate paperboard sidewall and soft cast shadow",
        "substrate_rgb": list(hole_color),
        "source": str(input_path),
        "output": str(output_path),
        "assembled_output": str(assembled_output_path),
        "assembled_sha256": hash_image(surface),
        "image_size": [width, height],
        "grid": {"rows": rows, "cols": cols, "knob_ratio": knob_ratio, "seed": seed, "cut_style": cut_style, "geometry_version": geometry_version, "seam_width": seam_width},
        "shape_policy": shape_policy,
        "content_policy": content_policy,
        "min_piece_detail": min_piece_detail,
        "placement_mode": "designed" if manual_placements else "automatic_candidate",
        "protected_boxes_normalized": [list(box) for box in protected_norm],
        "pairs": pairs,
        "checks": {
            "unique_pair_ids": len({item["pair_id"] for item in pairs}) == len(pairs),
            "unique_source_cells": len({tuple(item["cell"]) for item in pairs}) == len(pairs),
            "same_mask_used_for_hole_and_piece": True,
            "all_mirrored_false": all(not item["mirrored"] for item in pairs),
            "pair_count_matches": len(pairs) == len(selected),
            "all_selected_shapes_recognizable": (
                shape_policy != 'mixed'
                or cut_style != 'standard'
                or all(item['shape_profile']['recognizable_mixed_shape'] for item in pairs)
            ),
            "all_selected_content_recognizable": (
                content_policy != 'recognizable'
                or all(item['content_profile']['recognizable_content'] for item in pairs)
            ),
        },
        "review_required": [
            "subject and typography are not obscured",
            "lifted-piece placement is compositionally balanced",
            "seam relief and shadows match the visual brief",
            "assembled proof restores the complete printed pattern at every removed cell",
            "each default loose piece carries enough source detail to match by eye",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def audit_manifest(manifest_path: Path) -> dict:
    """Read saved artifacts; do not trust the manifest's self-reported checks.

    Pixel-exact source assets and opaque displayed interiors are verified.
    Antialiased borders, substrate styling and aesthetics require visual review.
    """
    errors = []
    def resolve(value):
        path = Path(value)
        if path.is_absolute() or path.exists():
            return path
        return manifest_path.parent / path
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        with Image.open(resolve(manifest['source'])) as opened:
            source = ImageOps.exif_transpose(opened).convert('RGB')
        with Image.open(resolve(manifest['output'])) as opened:
            output = opened.convert('RGB')
        if source.size != output.size or list(source.size) != manifest['image_size']:
            errors.append('canvas size mismatch')
        pairs = manifest['pairs']
        if not pairs:
            errors.append('no pairs to audit')
        if len({p['pair_id'] for p in pairs}) != len(pairs) or len({tuple(p['cell']) for p in pairs}) != len(pairs):
            errors.append('duplicate pair id or source cell')
        protected = to_pixel_boxes(manifest['protected_boxes_normalized'], source.size)
        grid = manifest['grid']
        masks, signatures, _, _ = masks_and_signatures(source.size, grid['rows'], grid['cols'], grid['seed'], grid['knob_ratio'], grid.get('cut_style','classic'), grid.get('geometry_version',1))
        assembled_value = manifest.get('assembled_output')
        if manifest.get('schema') in ('black-dust-puzzle/v2', 'black-dust-puzzle/v3'):
            if not assembled_value:
                errors.append('missing assembled proof')
            else:
                with Image.open(resolve(assembled_value)) as opened:
                    assembled = opened.convert('RGBA')
                expected_assembled = (
                    source.convert('RGBA')
                    if manifest.get('preserve_existing_seams')
                    else add_puzzle_seams(
                        source.convert('RGBA'), masks.values(),
                        int(grid.get('seam_width', 1)), protected,
                        manifest['material_preset'], int(manifest['seam_relief_seed']),
                        owner_labels=masks.labels if isinstance(masks, LabelMaskMap) else None,
                    )
                )
                if assembled.size != source.size:
                    errors.append('assembled proof size mismatch')
                elif (hash_image(assembled) != manifest.get('assembled_sha256')
                      or ImageChops.difference(assembled, expected_assembled).getbbox()):
                    errors.append('assembled proof does not restore the complete die-cut image')
        all_holes = [p['source_bbox'] for p in pairs]
        placed = []
        for pair in pairs:
            label = pair['pair_id']
            if pair['mirrored'] or not math.isfinite(pair['rotation_degrees']):
                errors.append(label + ': invalid orientation')
            if not pair.get('piece_asset'):
                errors.append(label + ': missing audit asset (use --pieces-dir)')
                continue
            with Image.open(resolve(pair['piece_asset'])) as opened:
                asset = opened.convert('RGBA')
            box = tuple(pair['source_bbox'])
            crop = source.crop(box)
            if asset.size != crop.size or hash_image(asset) != pair['content_sha256']:
                errors.append(label + ': content hash or size mismatch')
            elif ImageChops.difference(asset.convert('RGB'), crop).getbbox():
                errors.append(label + ': content is not the source crop')
            mask = masks[tuple(pair['cell'])]
            expected_profile = piece_shape_profile(signatures[tuple(pair['cell'])])
            if (manifest.get('schema') in ('black-dust-puzzle/v2', 'black-dust-puzzle/v3')
                    and pair.get('shape_profile') != expected_profile):
                errors.append(label + ': shape profile mismatch')
            if (manifest.get('shape_policy') == 'mixed'
                    and grid.get('cut_style') == 'standard'
                    and not expected_profile['recognizable_mixed_shape']):
                errors.append(label + ': selected shape is not a readable tab/socket mix')
            alpha = asset.getchannel('A')
            if manifest.get('schema') == 'black-dust-puzzle/v3':
                expected_content = piece_content_profile(
                    source.convert('L'), mask,
                    float(manifest.get('min_piece_detail', DEFAULT_MIN_PIECE_DETAIL)),
                )
                if pair.get('content_profile') != expected_content:
                    errors.append(label + ': content profile mismatch')
                if (manifest.get('content_policy') == 'recognizable'
                        and not expected_content['recognizable_content']):
                    errors.append(label + ': selected source content is not recognizable')
            if box != mask.getbbox() or hash_image(alpha) != pair['mask_sha256']:
                errors.append(label + ': mask mismatch')
            elif ImageChops.difference(alpha, mask.crop(box)).getbbox():
                errors.append(label + ': incorrect cell geometry')
            destination = pair['destination_bbox']
            if any(boxes_intersect(box, p) or boxes_intersect(destination, p) for p in protected):
                errors.append(label + ': protected region violated')
            if any(boxes_intersect(destination, p) for p in [*all_holes, *placed]):
                errors.append(label + ': overlapping destination')
            if not (0 <= destination[0] < destination[2] <= source.width and 0 <= destination[1] < destination[3] <= source.height):
                errors.append(label + ': destination outside canvas')
            placed.append(destination)
            revision = manifest.get('compositor_revision', '')
            if (revision in ('0.2-test','0.3-organic')
                    or revision.startswith(('0.4-', '0.5-', '0.6-', '0.7-', '0.8-', '0.9-', '1.'))):
                display = ImageOps.expand(asset.rotate(pair['rotation_degrees'], Image.Resampling.BICUBIC, expand=True), border=10, fill=(0,0,0,0))
                actual = output.crop(destination)
                if display.size != actual.size:
                    errors.append(label + ': rendered size mismatch')
                else:
                    difference = ImageChops.difference(actual, display.convert('RGB'))
                    # v1.0 adds physical relief only to the narrow face rim.
                    # Compare the safely inset top-face interior to the exact
                    # source asset and audit the rim through the assembled proof.
                    opaque = display.getchannel('A').filter(
                        ImageFilter.MinFilter(7)
                    ).point(lambda p: 255 if p == 255 else 0)
                    masked = Image.composite(difference, Image.new('RGB', actual.size), opaque)
                    if masked.getbbox():
                        errors.append(label + ': displayed content mismatch')
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        errors.append('unreadable or invalid artifact: ' + str(exc))
    return {'passed': not errors, 'errors': errors,
            'scope': 'saved raw pieces, geometry, bounds, protection and opaque displayed interiors; not aesthetic approval'}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=10)
    parser.add_argument("--cols", type=int, default=16)
    parser.add_argument("--missing-count", type=int, default=3, help="number of exact hole/piece pairs")
    parser.add_argument("--missing-cell", type=parse_cell, action="append", default=[])
    parser.add_argument(
        "--cut-style",
        choices=('standard','classic','organic'),
        default='standard',
        help="standard is the production visual; classic and organic are comparison modes",
    )
    parser.add_argument(
        "--material-preset",
        choices=tuple(MATERIAL_PRESETS),
        default="graphite-matte",
        help="paperboard relief tuned to the artwork value range",
    )
    parser.add_argument("--piece-placement", type=lambda value: tuple(float(p) for p in value.split(',')),
                        action='append', default=[], help='normalized center x,y,rotation-degrees; one per missing cell, same order')
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--protected-box", type=parse_norm_box, action="append", default=[])
    parser.add_argument("--knob-ratio", type=float, default=0.19)
    parser.add_argument(
        "--seam-width", type=int, default=2,
        help="pressed cut-channel width; 2px is the fit-view production baseline",
    )
    parser.add_argument(
        "--preserve-existing-seams", action="store_true",
        help="keep an already die-cut full-board surface and rebuild only exact hole/piece pairs",
    )
    parser.add_argument("--max-rotation", type=float, default=9.0)
    parser.add_argument("--hole-color", type=parse_hex_color, default=parse_hex_color("#D8D0C4"))
    parser.add_argument("--pieces-dir", type=Path)
    parser.add_argument(
        "--assembled-output", type=Path,
        help="complete no-hole die-cut board used as a visual reassembly proof",
    )
    parser.add_argument(
        "--piece-shape-policy", choices=("mixed", "any"), default="mixed",
        help="mixed keeps each selected loose piece visibly jigsaw-like",
    )
    parser.add_argument(
        "--piece-content-policy", choices=("recognizable", "any"), default="recognizable",
        help="recognizable avoids near-flat black/white cells that cannot be paired by eye",
    )
    parser.add_argument(
        "--min-piece-detail", type=float, default=DEFAULT_MIN_PIECE_DETAIL,
        help="minimum masked luma standard deviation for recognizable piece content",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = compose(
        input_path=args.input,
        output_path=args.output,
        manifest_path=args.manifest,
        rows=args.rows,
        cols=args.cols,
        missing_count=args.missing_count,
        seed=args.seed,
        protected_norm=args.protected_box,
        manual_cells=args.missing_cell,
        knob_ratio=args.knob_ratio,
        seam_width=args.seam_width,
        max_rotation=args.max_rotation,
        hole_color=args.hole_color,
        pieces_dir=args.pieces_dir,
        cut_style=args.cut_style,
        manual_placements=args.piece_placement,
        material_preset=args.material_preset,
        assembled_output_path=args.assembled_output,
        shape_policy=args.piece_shape_policy,
        content_policy=args.piece_content_policy,
        min_piece_detail=args.min_piece_detail,
        preserve_existing_seams=args.preserve_existing_seams,
    )
    print(json.dumps({"output": manifest["output"], "pairs": len(manifest["pairs"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
