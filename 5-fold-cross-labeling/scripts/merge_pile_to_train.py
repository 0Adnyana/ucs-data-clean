"""Build the next round from the five pile.csv files.

Where ``human_category`` is filled, that pair becomes ``Category`` and
``SubCategory``, even if ``human_subcategory`` is empty. Where it is empty,
the training label stays as it was. Recordings stay in the same piles.
Human and model columns start empty. ``train.csv`` again drops rows whose
category and subcategory are both empty, so a blank row enters training
only after a human category is written. ``eval.csv`` and ``all.csv`` are
not read.

With no arguments, the latest ``splits/round-N`` is promoted to
``splits/round-(N+1)``. Refuses when the destination already exists.

Usage:
  python 5-fold-cross-labeling/scripts/merge_pile_to_train.py
  python 5-fold-cross-labeling/scripts/merge_pile_to_train.py --round 1
  python 5-fold-cross-labeling/scripts/merge_pile_to_train.py --src 5-fold-cross-labeling/splits/round-1 --dst 5-fold-cross-labeling/splits/round-2
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fold_csv import (
    COLUMNS,
    PILES,
    SPLITS,
    display,
    is_blank,
    promote_row,
    read_csv,
    resolve_under_root,
    round_pile_paths,
    train_piles,
    write_csv,
)


def latest_round(splits_dir: Path) -> int | None:
    found: list[int] = []
    if not splits_dir.is_dir():
        return None
    for child in splits_dir.iterdir():
        if not child.is_dir() or not child.name.startswith("round-"):
            continue
        suffix = child.name[len("round-") :]
        if suffix.isdigit():
            found.append(int(suffix))
    return max(found) if found else None


def promote_round(src: Path, dst: Path) -> tuple[dict[str, list[dict[str, str]]], int]:
    promoted: dict[str, list[dict[str, str]]] = {}
    applied = 0
    seen: dict[str, str] = {}
    for pile in PILES:
        path = src / pile / "pile.csv"
        rows = read_csv(path, COLUMNS)
        next_rows: list[dict[str, str]] = []
        for row in rows:
            recording = (row.get("recording") or "").strip()
            if not recording:
                raise SystemExit(f"{display(path)} has a row with an empty recording")
            previous = seen.get(recording)
            if previous is not None and previous != pile:
                raise SystemExit(f"recording {recording} is in pile {previous} and pile {pile}")
            seen[recording] = pile
            if (row.get("pile") or "").strip() not in ("", pile):
                raise SystemExit(f"recording {recording} is filed under {row['pile']} in {display(path)}")
            if (row.get("human_category") or "").strip():
                applied += 1
            updated = promote_row(row)
            updated["pile"] = pile
            next_rows.append(updated)
        promoted[pile] = next_rows
        write_csv(dst / pile / "pile.csv", next_rows)
    for pile in PILES:
        train_rows: list[dict[str, str]] = []
        for source in train_piles(pile):
            train_rows.extend(row for row in promoted[source] if not is_blank(row))
        write_csv(dst / pile / "train.csv", train_rows)
    return promoted, applied


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Promote human labels into the next round.")
    parser.add_argument("--round", type=int, default=None, help="round to read; writes the next round")
    parser.add_argument("--src", type=Path, default=None, help="round directory to read")
    parser.add_argument("--dst", type=Path, default=None, help="round directory to write")
    parser.add_argument("--force", action="store_true", help="replace a destination that already exists")
    args = parser.parse_args(argv)

    if args.src or args.dst:
        if args.src is None or args.dst is None:
            raise SystemExit("pass both --src and --dst")
        src = resolve_under_root(args.src)
        dst = resolve_under_root(args.dst)
    else:
        number = args.round if args.round is not None else latest_round(SPLITS)
        if number is None:
            raise SystemExit("no round folder found. Run split_to_piles.py first, or pass --src and --dst.")
        src = SPLITS / f"round-{number}"
        dst = SPLITS / f"round-{number + 1}"

    missing = [pile for pile in PILES if not (src / pile / "pile.csv").is_file()]
    if missing:
        raise SystemExit(f"{display(src)} is missing pile.csv for {', '.join(missing)}")
    if round_pile_paths(dst) and not args.force:
        raise SystemExit(f"{display(dst)} already exists. Pass --force to replace it.")

    _promoted, applied = promote_round(src, dst)
    print(f"wrote {display(dst)} from {display(src)} ({applied} human labels applied)")


if __name__ == "__main__":
    main()
