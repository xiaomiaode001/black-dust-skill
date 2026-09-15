#!/usr/bin/env python3
"""Measure a clean local render and an identical cache hit."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "black-dust" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import render_social_cover  # noqa: E402


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timed_render(request: Path) -> tuple[dict, float]:
    started = time.perf_counter()
    result = render_social_cover.render(request)
    return result, round(time.perf_counter() - started, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="existing UTF-8 social-cover request")
    args = parser.parse_args()
    source_request = args.request.resolve()
    spec = json.loads(source_request.read_text(encoding="utf-8"))
    base = render_social_cover.resolve_path(str(spec["base"]), source_request.parent)
    spec["base"] = str(base)

    benchmark_root = ROOT / "output"
    benchmark_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".benchmark-", dir=benchmark_root) as temporary:
        temp = Path(temporary)
        spec["output_dir"] = str(temp / "rendered")
        request = temp / "render.request.json"
        request.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        first, first_seconds = timed_render(request)
        first_hash = file_hash(Path(first["output"]))
        second, cached_seconds = timed_render(request)
        second_hash = file_hash(Path(second["output"]))

    result = {
        "schema": "black-dust-render-benchmark/v1",
        "first_render_seconds": first_seconds,
        "cached_render_seconds": cached_seconds,
        "first_stage_timings_seconds": first["timings_seconds"],
        "first_cache": first["cache"],
        "second_cache": second["cache"],
        "pair_audit_passed": first["pair_audit_passed"] and second["pair_audit_passed"],
        "identical_output": first_hash == second_hash,
        "note": "Measures deterministic local stages only; image-model latency is external.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pair_audit_passed"] and result["identical_output"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
