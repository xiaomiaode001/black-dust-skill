#!/usr/bin/env python3
"""Install the bundled Black Dust skill into the current user's Codex skills."""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "black-dust"
SKILL_NAME = "black-dust"
LICENSE_FILES = ("LICENSE", "LICENSING.md", "ASSET_LICENSE.md")
IGNORE = shutil.ignore_patterns("output", "tests", "__pycache__", "*.pyc", "*.pyo")


def install(target_root: Path, update: bool = False) -> tuple[Path, Path | None]:
    """Copy the release skill into *target_root* and return destination/backup."""
    target_root = target_root.expanduser().resolve()
    destination = target_root / SKILL_NAME
    source = SOURCE.resolve()
    if not (source / "SKILL.md").is_file():
        raise FileNotFoundError(f"Skill source is incomplete: {source}")
    for name in LICENSE_FILES:
        if not (source / name).is_file():
            raise FileNotFoundError(f"Skill source is missing its license file: {name}")
    if destination.resolve() == source:
        raise ValueError("The install destination cannot be the repository source folder.")
    if destination.exists() and not update:
        raise FileExistsError(
            f"{destination} already exists. Re-run with --update to create a backup and replace it."
        )

    target_root.mkdir(parents=True, exist_ok=True)
    staging = target_root / f".{SKILL_NAME}.install-{uuid4().hex}"
    backup: Path | None = None
    try:
        shutil.copytree(source, staging, ignore=IGNORE)
        if not (staging / "SKILL.md").is_file():
            raise RuntimeError("Staged package is missing SKILL.md.")
        if destination.exists():
            backup_root = target_root / ".black-dust-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = backup_root / f"{SKILL_NAME}-{stamp}-{uuid4().hex[:6]}"
            destination.rename(backup)
        staging.rename(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    return destination, backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install Black Dust into ~/.codex/skills without silently overwriting an existing copy."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.home() / ".codex" / "skills",
        help="Codex skills directory; the black-dust folder is created inside it",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="back up an existing installation, then replace it",
    )
    args = parser.parse_args()
    try:
        destination, backup = install(args.target, update=args.update)
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"Install stopped: {exc}", file=sys.stderr)
        return 2

    print("Black Dust installed")
    print(f"Destination: {destination}")
    if backup is not None:
        print(f"Backup: {backup}")
    print("Next: restart Codex, then invoke $black-dust")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
