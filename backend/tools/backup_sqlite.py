"""Create and verify a consistent SQLite backup for local installations."""

import argparse
from pathlib import Path
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination.resolve()
    if source == destination:
        raise SystemExit("Source and destination must be different")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    with sqlite3.connect(destination) as check:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = check.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or foreign_keys:
        destination.unlink(missing_ok=True)
        raise SystemExit(f"Backup verification failed: integrity={integrity}, foreign_keys={len(foreign_keys)}")
    print(f"Verified backup: {destination}")


if __name__ == "__main__":
    main()
