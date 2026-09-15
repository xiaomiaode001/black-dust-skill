#!/usr/bin/env python3
"""Read-only audit of a compositor manifest and its PNG assets."""
import argparse
import json
from pathlib import Path
from puzzle_compositor import audit_manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    result = audit_manifest(args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
