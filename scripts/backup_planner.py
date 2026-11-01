"""Create a consistent SQLite backup plus planner configuration."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file():
        parser.error("Database does not exist.")
    destination = args.output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(destination / "flight_tracker.db") as target:
            source.backup(target)
    shutil.copy2(ROOT / "flight-tracker/config/settings.yaml", destination / "settings.yaml")
    print(destination.resolve())


if __name__ == "__main__":
    main()
