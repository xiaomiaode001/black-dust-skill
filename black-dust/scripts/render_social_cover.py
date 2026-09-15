#!/usr/bin/env python3
"""Resume-aware local renderer for a Black Dust social cover.

The expensive generative step stays outside this script.  Given one approved
continuous base image and a UTF-8 JSON request, it performs verified type,
exact jigsaw composition, and pair auditing.  Content-addressed stage hashes
let title or puzzle revisions restart at the first changed local stage instead
of regenerating the base image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cover_compositor  # noqa: E402
import puzzle_compositor  # noqa: E402


STATE_SCHEMA = "black-dust-social-render-cache/v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_path(value: str, request_dir: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (request_dir / path).resolve()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def artifact_hashes(output_dir: Path, relative_paths: list[str]) -> dict[str, str]:
    return {name: sha256(output_dir / name) for name in relative_paths}


def artifacts_match(output_dir: Path, expected: dict[str, str]) -> bool:
    if not expected:
        return False
    for relative, expected_hash in expected.items():
        path = output_dir / relative
        if not path.is_file() or sha256(path) != expected_hash:
            return False
    return True


def normalized_request(spec: dict[str, Any], request_dir: Path) -> dict[str, Any]:
    if "base" not in spec:
        raise ValueError("request requires a base image path")
    cover = dict(spec.get("cover", {}))
    title = str(cover.get("title", spec.get("title", ""))).strip()
    if not title:
        raise ValueError("request requires a non-empty cover.title")
    preset = str(cover.get("preset", "twitter"))
    if preset not in cover_compositor.PRESETS:
        raise ValueError(f"unknown cover preset: {preset}")

    puzzle = dict(spec.get("puzzle", {}))
    request = {
        "base": str(resolve_path(str(spec["base"]), request_dir)),
        "output_dir": str(
            resolve_path(str(spec.get("output_dir", ".")), request_dir)
        ),
        "cover": {
            "preset": preset,
            "mode": "article",
            "layout": str(cover.get("layout", "theme-title")),
            "title": title,
            "subtitle": str(cover.get("subtitle", "")).strip(),
            "kicker": str(cover.get("kicker", "")).strip(),
            "title_accent": str(cover.get("title_accent", "")).strip(),
            "title_underline": str(cover.get("title_underline", "")).strip(),
        },
        "subject_protected_boxes": spec.get("subject_protected_boxes", []),
        "puzzle": {
            "rows": int(puzzle.get("rows", 8)),
            "cols": int(puzzle.get("cols", 20)),
            "missing_count": int(puzzle.get("missing_count", 3)),
            "missing_cells": puzzle.get("missing_cells", []),
            "piece_placements": puzzle.get("piece_placements", []),
            "cut_style": str(puzzle.get("cut_style", "standard")),
            "material_preset": str(puzzle.get("material_preset", "ivory-board")),
            "knob_ratio": float(puzzle.get("knob_ratio", 0.20)),
            "seam_width": int(puzzle.get("seam_width", 2)),
            "max_rotation": float(puzzle.get("max_rotation", 12.0)),
            "hole_color": str(puzzle.get("hole_color", "#D8D0C4")),
            "shape_policy": str(puzzle.get("shape_policy", "mixed")),
            "content_policy": str(puzzle.get("content_policy", "recognizable")),
            "min_piece_detail": float(puzzle.get("min_piece_detail", 10.0)),
            "seed": int(puzzle.get("seed", 42)),
        },
    }
    return request


def render(request_path: Path) -> dict[str, Any]:
    request_path = request_path.resolve()
    request = normalized_request(read_json(request_path), request_path.parent)
    base = Path(request["base"])
    output_dir = Path(request["output_dir"])
    if not base.is_file():
        raise FileNotFoundError(f"base image not found: {base}")
    output_dir.mkdir(parents=True, exist_ok=True)

    typeset = output_dir / "typeset.png"
    cover_manifest_path = output_dir / "typeset.cover.json"
    final = output_dir / "final.png"
    assembled = output_dir / "final.assembled.png"
    puzzle_manifest_path = output_dir / "final.puzzle.json"
    pieces_dir = output_dir / "pieces"
    audit_path = output_dir / "final.audit.json"
    state_path = output_dir / ".render-state.json"
    state = read_json(state_path) if state_path.is_file() else {}

    base_hash = sha256(base)
    cover_signature = signature({
        "base_sha256": base_hash,
        "font_assets": cover_compositor.font_fingerprint(
            request["cover"]["mode"], request["cover"]["layout"]
        ),
        "compositor_sha256": sha256(Path(cover_compositor.__file__)),
        **request["cover"],
    })
    cover_assets = state.get("cover_artifacts", {})
    cover_hit = (
        state.get("schema") == STATE_SCHEMA
        and state.get("cover_signature") == cover_signature
        and artifacts_match(output_dir, cover_assets)
    )
    timings: dict[str, float] = {}

    if not cover_hit:
        started = time.perf_counter()
        cover = request["cover"]
        cover_compositor.compose(
            base,
            typeset,
            cover_manifest_path,
            cover["preset"],
            cover["mode"],
            cover["title"],
            cover["subtitle"],
            cover["kicker"],
            cover["layout"],
            cover["title_accent"],
            cover["title_underline"],
        )
        timings["cover_composite"] = round(time.perf_counter() - started, 4)

    cover_manifest = read_json(cover_manifest_path)
    protected = list(cover_manifest["puzzle_protected_boxes_normalized"])
    protected.extend(request["subject_protected_boxes"])
    puzzle_request = {**request["puzzle"], "protected_boxes": protected}
    typeset_hash = sha256(typeset)
    puzzle_signature = signature(
        {"typeset_sha256": typeset_hash, **puzzle_request}
    )
    puzzle_assets = state.get("puzzle_artifacts", {})
    puzzle_hit = (
        cover_hit
        and state.get("puzzle_signature") == puzzle_signature
        and artifacts_match(output_dir, puzzle_assets)
        and read_json(audit_path).get("passed") is True
    )

    if not puzzle_hit:
        started = time.perf_counter()
        stage = output_dir / f".render-stage-{uuid.uuid4().hex}"
        stage.mkdir()
        stage_final = stage / "final.png"
        stage_assembled = stage / "final.assembled.png"
        stage_manifest = stage / "final.puzzle.json"
        stage_pieces = stage / "pieces"
        p = puzzle_request
        try:
            puzzle_compositor.compose(
                input_path=typeset,
                output_path=stage_final,
                manifest_path=stage_manifest,
                rows=p["rows"],
                cols=p["cols"],
                missing_count=p["missing_count"],
                seed=p["seed"],
                protected_norm=p["protected_boxes"],
                manual_cells=[tuple(cell) for cell in p["missing_cells"]],
                knob_ratio=p["knob_ratio"],
                seam_width=p["seam_width"],
                max_rotation=p["max_rotation"],
                hole_color=puzzle_compositor.parse_hex_color(p["hole_color"]),
                pieces_dir=stage_pieces,
                cut_style=p["cut_style"],
                manual_placements=p["piece_placements"],
                material_preset=p["material_preset"],
                assembled_output_path=stage_assembled,
                shape_policy=p["shape_policy"],
                content_policy=p["content_policy"],
                min_piece_detail=p["min_piece_detail"],
            )
            stage_audit = puzzle_compositor.audit_manifest(stage_manifest)
            if not stage_audit["passed"]:
                raise RuntimeError(f"staged pair audit failed: {stage_audit['errors']}")

            staged_hashes = {
                "final.png": sha256(stage_final),
                "final.assembled.png": sha256(stage_assembled),
                **{
                    f"pieces/{path.name}": sha256(path)
                    for path in sorted(stage_pieces.glob("*.png"))
                },
            }

            atomic_copy(stage_final, final)
            atomic_copy(stage_assembled, assembled)
            next_pieces = output_dir / f".pieces-{uuid.uuid4().hex}"
            shutil.copytree(stage_pieces, next_pieces)
            previous_pieces = output_dir / f".pieces-old-{uuid.uuid4().hex}"
            if pieces_dir.exists():
                os.replace(pieces_dir, previous_pieces)
            os.replace(next_pieces, pieces_dir)
            if previous_pieces.exists():
                shutil.rmtree(previous_pieces)

            manifest = read_json(stage_manifest)
            manifest["output"] = str(final)
            manifest["assembled_output"] = str(assembled)
            for pair in manifest["pairs"]:
                pair["piece_asset"] = str(pieces_dir / f"{pair['pair_id']}.png")
            atomic_write_json(puzzle_manifest_path, manifest)

            promoted_paths = {
                "final.png": final,
                "final.assembled.png": assembled,
                **{
                    f"pieces/{path.name}": path
                    for path in sorted(pieces_dir.glob("*.png"))
                },
            }
            promotion_errors = [
                f"promoted asset hash mismatch: {name}"
                for name, expected in staged_hashes.items()
                if name not in promoted_paths or sha256(promoted_paths[name]) != expected
            ]
            if promotion_errors:
                raise RuntimeError("; ".join(promotion_errors))
            final_audit = {
                **stage_audit,
                "audit_strategy": "staged-full-audit-plus-promoted-byte-hashes",
                "promotion_verified": True,
                "promotion_errors": [],
                "scope": (
                    f"{stage_audit.get('scope', '')}; promoted final, assembled proof "
                    "and raw piece bytes verified before staging cleanup"
                ).strip("; "),
            }
            atomic_write_json(audit_path, final_audit)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        timings["puzzle_composite_and_audit"] = round(
            time.perf_counter() - started, 4
        )

    cover_relative = ["typeset.png", "typeset.cover.json"]
    piece_relative = sorted(
        str(path.relative_to(output_dir)).replace("\\", "/")
        for path in pieces_dir.glob("*.png")
    )
    puzzle_relative = [
        "final.png",
        "final.assembled.png",
        "final.puzzle.json",
        "final.audit.json",
        *piece_relative,
    ]
    new_state = {
        "schema": STATE_SCHEMA,
        "request": str(request_path),
        "base_sha256": base_hash,
        "cover_signature": cover_signature,
        "puzzle_signature": puzzle_signature,
        "cover_artifacts": artifact_hashes(output_dir, cover_relative),
        "puzzle_artifacts": artifact_hashes(output_dir, puzzle_relative),
    }
    atomic_write_json(state_path, new_state)
    return {
        "schema": "black-dust-social-render/v1",
        "delivery": "final_only",
        "output": str(final),
        "cache": {
            "cover_composite": "hit" if cover_hit else "rendered",
            "puzzle_composite_and_audit": "hit" if puzzle_hit else "rendered",
        },
        "timings_seconds": timings,
        "pair_audit_passed": read_json(audit_path).get("passed") is True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="UTF-8 JSON render request")
    return parser


def main() -> int:
    result = render(build_parser().parse_args().request)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    from cli_output import configure_utf8_output
    configure_utf8_output()
    raise SystemExit(main())
