"""Split the rows that are not in the 3000-clip sample into five piles.

Each recording stays in one pile. Recordings are dealt round-robin within
a category, so each category is spread across A–E. A recording with more
than one category is dealt with its rarer category. Recordings with no
category are spread on their own. Dealing is sorted by recording id, so
the same files always land in the same piles.

The whole ``eval-3000.csv`` sample stays out of A–E. Rows that are also in
``eval.csv`` are marked ``eval``. The rest of that sample is marked
``sample``. Neither is trained on.

Writes ``round-1/Y/pile.csv`` (every row of pile Y, including blanks) and
``round-1/Y/train.csv`` (the other four piles, blanks left out, listen
columns empty). Probe A trains on B+C+D+E, probe B on C+D+E+A, and so on.
Then writes ``pile`` back onto ``all.csv``.

Does not rewrite ``eval.csv`` or ``eval-3000.csv``. Refuses when a round
file already has human labels or model predictions.

Usage:
  python 5-fold-cross-labeling/scripts/split_to_piles.py
  python 5-fold-cross-labeling/scripts/split_to_piles.py --round 5-fold-cross-labeling/splits/round-1
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from fold_csv import (
    COLUMNS,
    HELD_PILE,
    MASTER_COLUMNS,
    ORIGINAL,
    PILES,
    SAMPLE_PILE,
    SPLITS,
    clear_listen,
    display,
    group_recordings,
    is_blank,
    read_csv,
    resolve_under_root,
    round_has_listen_marks,
    round_pile_paths,
    train_piles,
    write_csv,
)


def assign_piles(groups: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    """Map recording id to A–E. Every recording in ``groups`` is assigned."""
    frequency: dict[str, int] = defaultdict(int)
    categories: dict[str, set[str]] = {}
    for recording, rows in groups.items():
        present = {(row.get("Category") or "").strip() for row in rows}
        present.discard("")
        categories[recording] = present
        for category in present:
            frequency[category] += 1

    buckets: dict[str, list[str]] = defaultdict(list)
    for recording, present in categories.items():
        if not present:
            buckets[""].append(recording)
            continue
        rarest = min(present, key=lambda category: (frequency[category], category))
        buckets[rarest].append(recording)

    assigned: dict[str, str] = {}
    for recordings in buckets.values():
        for index, recording in enumerate(sorted(recordings)):
            assigned[recording] = PILES[index % len(PILES)]
    return assigned


def holdout_recordings(
    all_rows: list[dict[str, str]], held_rows: list[dict[str, str]], label: str
) -> set[str]:
    """Recording ids whose paths are in ``label``. Every row of each recording must be there."""
    groups = group_recordings(all_rows)
    by_path = {(row.get("path") or "").strip(): row for row in all_rows}
    held_paths: dict[str, set[str]] = defaultdict(set)
    for row in held_rows:
        path = (row.get("path") or "").strip()
        match = by_path.get(path)
        if match is None:
            raise SystemExit(f"{label} path {path} is not in all.csv")
        recording = (match.get("recording") or "").strip()
        if not recording:
            raise SystemExit(f"{path} has an empty recording in all.csv")
        held_paths[recording].add(path)
    for recording, paths in held_paths.items():
        expected = {(row.get("path") or "").strip() for row in groups[recording]}
        if paths != expected:
            raise SystemExit(f"recording {recording} is only partly in {label}")
    return set(held_paths)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deal the recordings that are not in the 3000-clip sample into five piles.")
    parser.add_argument("--all", type=Path, default=ORIGINAL / "all.csv", help="all.csv from create_validation_set.py")
    parser.add_argument("--eval", type=Path, default=ORIGINAL / "eval.csv", help="hand-checked eval.csv")
    parser.add_argument("--pool", type=Path, default=ORIGINAL / "eval-3000.csv", help="3000-clip sample; none of it is dealt into A-E")
    parser.add_argument("--round", type=Path, default=SPLITS / "round-1", help="directory for A–E")
    parser.add_argument("--force", action="store_true", help="overwrite a round that already has listen marks")
    args = parser.parse_args(argv)

    all_path = resolve_under_root(args.all)
    eval_path = resolve_under_root(getattr(args, "eval"))
    pool_path = resolve_under_root(args.pool)
    round_dir = resolve_under_root(args.round)
    all_rows = read_csv(all_path, COLUMNS)
    eval_rows = read_csv(eval_path, MASTER_COLUMNS)
    pool_rows = read_csv(pool_path, MASTER_COLUMNS)
    for row in all_rows:
        if not (row.get("recording") or "").strip():
            raise SystemExit(f"{display(all_path)} has a row with an empty recording")

    if round_pile_paths(round_dir) and not args.force:
        if round_has_listen_marks(round_dir):
            raise SystemExit(f"{display(round_dir)} already has human labels or model predictions; not overwriting")
        raise SystemExit(f"{display(round_dir)} already exists. Pass --force to replace it.")

    scored = holdout_recordings(all_rows, eval_rows, display(eval_path))
    sampled = holdout_recordings(all_rows, pool_rows, display(pool_path))
    outside = scored - sampled
    if outside:
        raise SystemExit(f"{len(outside)} eval recordings are not in {display(pool_path)}")
    groups = group_recordings(all_rows)
    remaining = {recording: rows for recording, rows in groups.items() if recording not in sampled}
    assigned = assign_piles(remaining)

    for row in all_rows:
        recording = row["recording"]
        if recording in scored:
            row["pile"] = HELD_PILE
        elif recording in sampled:
            row["pile"] = SAMPLE_PILE
        else:
            row["pile"] = assigned[recording]
    write_csv(all_path, all_rows)

    by_pile: dict[str, list[dict[str, str]]] = {pile: [] for pile in PILES}
    for row in all_rows:
        if row["pile"] in by_pile:
            by_pile[row["pile"]].append(row)

    for pile in PILES:
        pile_rows = by_pile[pile]
        write_csv(round_dir / pile / "pile.csv", pile_rows)
        train_rows = []
        for source in train_piles(pile):
            train_rows.extend(clear_listen(row) for row in by_pile[source] if not is_blank(row))
        write_csv(round_dir / pile / "train.csv", train_rows)

    print(f"wrote {display(round_dir)}")
    for pile in PILES:
        pile_rows = by_pile[pile]
        blank = sum(1 for row in pile_rows if is_blank(row))
        train_count = sum(len([row for row in by_pile[source] if not is_blank(row)]) for source in train_piles(pile))
        print(f"  {pile} pile {len(pile_rows)} ({blank} blank) train {train_count}")
    scored_clips = sum(1 for row in all_rows if row["pile"] == HELD_PILE)
    sample_clips = sum(1 for row in all_rows if row["pile"] == SAMPLE_PILE)
    print(f"held out {scored_clips} eval clips and {sample_clips} other sample clips")
    _print_missing_categories(by_pile)


def _print_missing_categories(by_pile: dict[str, list[dict[str, str]]]) -> None:
    present: dict[str, set[str]] = {pile: set() for pile in PILES}
    for pile, rows in by_pile.items():
        for row in rows:
            category = (row.get("Category") or "").strip()
            if category:
                present[pile].add(category)
    categories = set().union(*present.values())
    missing = [
        f"{category} missing from {', '.join(pile for pile in PILES if category not in present[pile])}"
        for category in sorted(categories)
        if any(category not in present[pile] for pile in PILES)
    ]
    if missing:
        print("categories missing from a pile:")
        for line in missing:
            print(f"  {line}")
    elif categories:
        print(f"every category is in every pile ({len(categories)})")


if __name__ == "__main__":
    main()
