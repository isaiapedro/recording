#!/usr/bin/env python3
"""Review or explicitly delete aged files from the service recording root."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from storage import recordings_root


def candidates(older_than_days: int) -> list[Path]:
    cutoff = time.time() - older_than_days * 24 * 60 * 60
    root = recordings_root()
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.resolve().is_relative_to(root) and path.stat().st_mtime < cutoff
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Review aged local video artifacts")
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument("--confirm-delete", action="store_true")
    args = parser.parse_args()
    if args.older_than_days < 1:
        parser.error("--older-than-days must be at least 1")

    expired = candidates(args.older_than_days)
    action = "Deleting" if args.confirm_delete else "Reviewing"
    print(f"{action} {len(expired)} file(s) under {recordings_root()}")
    for path in expired:
        print(path.relative_to(recordings_root()))
    if not args.confirm_delete:
        print("No files deleted. Re-run with --confirm-delete after reviewing this list.")
        return 0
    for path in expired:
        path.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
