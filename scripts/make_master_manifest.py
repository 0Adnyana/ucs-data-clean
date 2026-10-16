"""Build manifests/master.csv from the original-envsound splits.

Train, val, and test are concatenated into one file. The result has no split
column. Category and SubCategory are left empty.

Usage:
  python scripts/make_master_manifest.py
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "manifests" / "original-envsound"
OUT = ROOT / "manifests" / "master.csv"
SPLITS = ("train", "val", "test")
COLUMNS = [
    "filename",
    "Category",
    "SubCategory",
    "Keywords",
    "source",
    "path",
    "exists",
]


def load_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_manifest(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def master_rows(src_dir: Path) -> list[dict[str, str]]:
    """Every split row, in train then val then test order, with the master columns only."""
    rows: list[dict[str, str]] = []
    for name in SPLITS:
        path = src_dir / f"envsound_{name}.csv"
        if not path.is_file():
            raise SystemExit(f"manifest not found: {path}")
        fields, split_rows = load_manifest(path)
        missing = [column for column in COLUMNS if column not in fields]
        if missing:
            raise SystemExit(f"{path.name} is missing columns: {', '.join(missing)}")
        for row in split_rows:
            built = {column: row.get(column, "") for column in COLUMNS}
            built["Category"] = ""
            built["SubCategory"] = ""
            rows.append(built)
    return rows


def main() -> None:
    rows = master_rows(SRC_DIR)
    write_manifest(OUT, list(COLUMNS), rows)
    print(f"wrote {OUT} ({len(rows)} rows from {', '.join(SPLITS)})")


if __name__ == "__main__":
    main()
