"""Split a manifest into train, val, and test at 70/15/15.

Rows are grouped by UCS pair (Category, SubCategory). Blank rows are one
group. Rows with a category and no subcategory are one group per category.
Inside a group, sources are spread evenly through the list, and the list is
cut by largest remainder so the counts land on 70/15/15. The same file always
produces the same three CSVs. Every input row goes to exactly one split.

``--check`` copies two rows of each pair from the test split into
``envsound_test_check.csv`` for listening after a training run. Category
and SubCategory are empty on that copy so they can be filled by hand. The
same rows stay labeled in the test file. A pair with fewer than two test
rows contributes what it has, and the script names it.

``--out`` is the destination directory. A different directory leaves an
earlier split where it is.

Usage:
  python scripts/make_split_manifest.py
  python scripts/make_split_manifest.py --master manifests/master.csv --out manifests/split-70
  python scripts/make_split_manifest.py --out manifests/split-70 --check
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MASTER = ROOT / "manifests" / "master.csv"
DEFAULT_OUT = ROOT / "manifests" / "split"
SPLIT_NAMES = ("train", "val", "test")
WEIGHTS = (70, 15, 15)
SOURCE_ORDER = ("AudioSet", "ESC-50", "FSD50K", "FoleySet")
CHECK_COUNT = 2
REQUIRED = ("Category", "SubCategory", "source", "path")
SPLIT_FILES = {
    "train": "envsound_train.csv",
    "val": "envsound_val.csv",
    "test": "envsound_test.csv",
}
CHECK_FILE = "envsound_test_check.csv"


@dataclass(frozen=True)
class SplitManifest:
    """One partition of a manifest, plus the optional listening sample."""

    splits: dict[str, list[dict[str, str]]]
    check: list[dict[str, str]]
    short: list[tuple[str, int]]


def resolve_under_root(path: Path) -> Path:
    if path.is_absolute():
        return path
    return ROOT / path


def pair_label(category: str, subcategory: str) -> str:
    if not category and not subcategory:
        return "(blank)"
    if not subcategory:
        return f"{category}/(category only)"
    return f"{category}/{subcategory}"


def source_rank(source: str) -> tuple[int, str]:
    try:
        return (SOURCE_ORDER.index(source), source)
    except ValueError:
        return (len(SOURCE_ORDER), source)


def allocate(count: int, weights: tuple[int, ...] = WEIGHTS) -> tuple[int, ...]:
    """Split ``count`` by largest remainder.

    Ties in the remainder go to val, then test, then train.
    """
    if count < 0:
        raise ValueError(f"count must be >= 0, got {count}")
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    quotas = [(count * weight) // total for weight in weights]
    leftover = count - sum(quotas)
    # Prefer val, then test, then train when two fractional parts match.
    tie = {0: 2, 1: 0, 2: 1}
    order = sorted(
        range(len(weights)),
        key=lambda index: (-((count * weights[index]) % total), tie.get(index, index)),
    )
    for step in range(leftover):
        quotas[order[step]] += 1
    return tuple(quotas)


def interleave(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Spread each source evenly through the group, in a fixed source order."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("source") or ""].append(row)
    sequenced: list[tuple[float, tuple[int, str], str, dict[str, str]]] = []
    for source, group in grouped.items():
        group.sort(key=lambda row: (row.get("path") or "", row.get("filename") or ""))
        rank = source_rank(source)
        size = len(group)
        for index, row in enumerate(group):
            sequenced.append(((index + 0.5) / size, rank, row.get("path") or "", row))
    sequenced.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in sequenced]


def blank_check(row: dict[str, str]) -> dict[str, str]:
    """A listening copy with Category and SubCategory left empty."""
    copy = dict(row)
    copy["Category"] = ""
    copy["SubCategory"] = ""
    return copy


def pick_check(test_rows: list[dict[str, str]], limit: int = CHECK_COUNT) -> list[dict[str, str]]:
    """Up to ``limit`` test rows, preferring different sources."""
    picked: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in test_rows:
        source = row.get("source") or ""
        if source in seen:
            continue
        picked.append(row)
        seen.add(source)
        if len(picked) == limit:
            return picked
    chosen = {id(row) for row in picked}
    for row in test_rows:
        if id(row) in chosen:
            continue
        picked.append(row)
        if len(picked) == limit:
            break
    return picked


def _row_key(row: dict[str, str]) -> tuple[tuple[int, str], str, str]:
    return (source_rank(row.get("source") or ""), row.get("path") or "", row.get("filename") or "")


def split_manifest(rows: list[dict[str, str]]) -> SplitManifest:
    """Partition ``rows`` into train, val, and test. Also build the check sample."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = ((row.get("Category") or "").strip(), (row.get("SubCategory") or "").strip())
        grouped[key].append(row)

    splits: dict[str, list[dict[str, str]]] = {name: [] for name in SPLIT_NAMES}
    check: list[dict[str, str]] = []
    short: list[tuple[str, int]] = []
    for key in sorted(grouped):
        sequence = interleave(grouped[key])
        counts = allocate(len(sequence))
        offset = 0
        parts: dict[str, list[dict[str, str]]] = {}
        for name, count in zip(SPLIT_NAMES, counts, strict=True):
            parts[name] = sequence[offset : offset + count]
            splits[name].extend(parts[name])
            offset += count
        test_count = counts[SPLIT_NAMES.index("test")]
        if test_count < CHECK_COUNT:
            short.append((pair_label(*key), test_count))
        check.extend(blank_check(row) for row in pick_check(parts["test"]))

    for name in SPLIT_NAMES:
        splits[name].sort(key=_row_key)
    check.sort(key=_row_key)
    short.sort(key=lambda item: item[0])
    return SplitManifest(splits=splits, check=check, short=short)


def read_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise SystemExit(f"manifest not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        missing = [name for name in REQUIRED if name not in fieldnames]
        if missing:
            raise SystemExit(f"manifest missing columns: {', '.join(missing)}")
        rows = [{key: value or "" for key, value in row.items()} for row in reader]
    return fieldnames, rows


def write_manifest(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Split a manifest into train, val, and test at 70/15/15.")
    parser.add_argument(
        "--master",
        type=Path,
        default=DEFAULT_MASTER,
        help=f"manifest to split (default {DEFAULT_MASTER.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"directory for the split CSVs (default {DEFAULT_OUT.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=f"also write {CHECK_FILE} with {CHECK_COUNT} test rows per UCS pair",
    )
    args = parser.parse_args(argv)
    master_path = resolve_under_root(args.master)
    out_dir = resolve_under_root(args.out)
    fieldnames, rows = read_manifest(master_path)
    result = split_manifest(rows)
    for name in SPLIT_NAMES:
        write_manifest(out_dir / SPLIT_FILES[name], fieldnames, result.splits[name])
    counts = ", ".join(f"{name} {len(result.splits[name])}" for name in SPLIT_NAMES)
    print(f"wrote {out_dir} ({counts})")
    if args.check:
        check_path = out_dir / CHECK_FILE
        write_manifest(check_path, fieldnames, result.check)
        print(f"check {check_path.name} ({len(result.check)} rows)")
        for label, test_count in result.short:
            print(f"  {label}: {test_count} in test")


if __name__ == "__main__":
    main()
