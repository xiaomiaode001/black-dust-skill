#!/usr/bin/env python3
"""Store and resolve user-approved continuous Black Dust base images.

This cache is intentionally conservative. An image is reusable only when the
caller names its base id explicitly, or when the full normalized creative key
matches. It never performs fuzzy or visual-similarity matching.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image


SCHEMA = "black-dust-approved-base-cache/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def creative_key(
    *, brief: str, aspect: str, theme_family: str, composition_key: str
) -> str:
    payload = {
        "aspect": normalized_text(aspect).lower(),
        "brief": normalized_text(brief),
        "composition_key": normalized_text(composition_key).lower(),
        "theme_family": normalized_text(theme_family).lower(),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _index_path(cache_dir: Path) -> Path:
    return cache_dir / "index.json"


def _read_index(cache_dir: Path) -> dict[str, Any]:
    path = _index_path(cache_dir)
    if not path.exists():
        return {"schema": SCHEMA, "bases": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or not isinstance(value.get("bases"), dict):
        raise ValueError(f"unsupported cache index: {path}")
    return value


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def register(
    cache_dir: Path,
    base: Path,
    *,
    base_id: str,
    brief: str,
    aspect: str,
    theme_family: str,
    composition_key: str,
    user_approved: bool,
) -> dict[str, Any]:
    base = base.resolve()
    cache_dir = cache_dir.resolve()
    base_id = normalized_text(base_id)
    if not base_id:
        raise ValueError("base_id cannot be empty")
    if not user_approved:
        raise ValueError("registration requires explicit user approval")
    if not base.is_file():
        raise FileNotFoundError(base)

    with Image.open(base) as image:
        width, height = image.size
        image.verify()

    digest = sha256(base)
    suffix = base.suffix.lower() or ".png"
    relative_asset = Path("assets") / f"{digest}{suffix}"
    asset = cache_dir / relative_asset
    asset.parent.mkdir(parents=True, exist_ok=True)
    if not asset.exists():
        temporary = asset.with_name(f".{asset.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(base, temporary)
        os.replace(temporary, asset)

    index = _read_index(cache_dir)
    existing = index["bases"].get(base_id)
    if existing and existing.get("sha256") != digest:
        raise ValueError(
            f"base_id {base_id!r} already points to a different image; use a new id"
        )
    record = {
        "base_id": base_id,
        "status": "user_approved",
        "asset": relative_asset.as_posix(),
        "sha256": digest,
        "width": width,
        "height": height,
        "aspect": normalized_text(aspect).lower(),
        "theme_family": normalized_text(theme_family).lower(),
        "composition_key": normalized_text(composition_key).lower(),
        "brief": normalized_text(brief),
        "creative_key": creative_key(
            brief=brief,
            aspect=aspect,
            theme_family=theme_family,
            composition_key=composition_key,
        ),
    }
    index["bases"][base_id] = record
    _atomic_write_json(_index_path(cache_dir), index)
    return {**record, "resolved_path": str(asset)}


def _verified_record(cache_dir: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("status") != "user_approved":
        return None
    asset = (cache_dir / str(record.get("asset", ""))).resolve()
    try:
        asset.relative_to(cache_dir.resolve())
    except ValueError:
        return None
    if not asset.is_file() or sha256(asset) != record.get("sha256"):
        return None
    return {**record, "resolved_path": str(asset)}


def resolve(
    cache_dir: Path,
    *,
    base_id: str | None = None,
    brief: str | None = None,
    aspect: str | None = None,
    theme_family: str | None = None,
    composition_key: str | None = None,
) -> dict[str, Any] | None:
    cache_dir = cache_dir.resolve()
    index = _read_index(cache_dir)
    if base_id:
        record = index["bases"].get(normalized_text(base_id))
        return _verified_record(cache_dir, record) if record else None

    fields = (brief, aspect, theme_family, composition_key)
    if any(value is None or not normalized_text(value) for value in fields):
        raise ValueError(
            "exact lookup requires brief, aspect, theme_family, and composition_key"
        )
    wanted = creative_key(
        brief=str(brief),
        aspect=str(aspect),
        theme_family=str(theme_family),
        composition_key=str(composition_key),
    )
    for record in index["bases"].values():
        if record.get("creative_key") == wanted:
            return _verified_record(cache_dir, record)
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("output/.approved-base-cache")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("register", help="register an explicitly approved base")
    add.add_argument("--base", type=Path, required=True)
    add.add_argument("--base-id", required=True)
    add.add_argument("--brief", required=True)
    add.add_argument("--aspect", required=True)
    add.add_argument("--theme-family", required=True)
    add.add_argument("--composition-key", required=True)
    add.add_argument("--user-approved", action="store_true", required=True)

    find = subparsers.add_parser("resolve", help="resolve by id or exact creative key")
    find.add_argument("--base-id")
    find.add_argument("--brief")
    find.add_argument("--aspect")
    find.add_argument("--theme-family")
    find.add_argument("--composition-key")

    subparsers.add_parser("list", help="list cache records without resolving assets")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "register":
            result: Any = register(
                args.cache_dir,
                args.base,
                base_id=args.base_id,
                brief=args.brief,
                aspect=args.aspect,
                theme_family=args.theme_family,
                composition_key=args.composition_key,
                user_approved=args.user_approved,
            )
        elif args.command == "resolve":
            record = resolve(
                args.cache_dir,
                base_id=args.base_id,
                brief=args.brief,
                aspect=args.aspect,
                theme_family=args.theme_family,
                composition_key=args.composition_key,
            )
            result = {"hit": record is not None, "base": record}
        else:
            result = _read_index(args.cache_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from cli_output import configure_utf8_output
    configure_utf8_output()
    sys.exit(main())
