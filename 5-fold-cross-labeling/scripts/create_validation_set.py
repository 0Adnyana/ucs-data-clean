"""Build all.csv, a 3000-clip sample, and the 700-clip eval.csv.

``all.csv`` keeps every master row. ``recording`` is filled here and then
left alone. When ``all.csv`` already exists, ``Category`` and ``SubCategory``
are copied from it, so a later fill is not replaced by the master label.

The sample is two passes, both by UCS pair (``Category``, ``SubCategory``).
The first pass draws whole recordings up to ``--pool`` clips (default 3000)
and writes ``eval-<pool>.csv``. The second pass draws ``--clips`` clips
(default 700) from those recordings and writes ``eval.csv``. Each pass adds a
recording for the pair the sample so far covers with the fewest clips, so a
pair that exists is in the 3000 and then in the 700 when a recording of it
fits. A recording is never split. Nothing is added once the next recording
would pass the clip budget. The whole 3000 stays out of the training piles.
The probe scores the 700.

``eval.csv`` and the 3000-clip copy have the master columns only. ``Category``
and ``SubCategory`` are the labels the probe scores. The same rows always
produce the same sample.

``pile`` on ``all.csv`` stays empty until ``split_to_piles.py``. Re-running
refuses once an ``eval.csv`` label differs from the rows just built, or once
``all.csv`` already has pile letters.

Usage:
  python 5-fold-cross-labeling/scripts/create_validation_set.py
  python 5-fold-cross-labeling/scripts/create_validation_set.py --pool 3000 --clips 700
"""

from __future__ import annotations

import argparse
import heapq
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from fold_csv import (
    COLUMNS,
    DEFAULT_FOLEY,
    DEFAULT_MASTER,
    MASTER_COLUMNS,
    ORIGINAL,
    display,
    layout_row,
    load_foley_ids,
    read_csv,
    recording_id,
    resolve_under_root,
    row_keywords,
    row_ucs_pair,
    write_csv,
)

KeyFunc = Callable[[dict[str, str]], set[tuple[str, str]]]


def sample_recordings(
    groups: dict[str, list[dict[str, str]]],
    target_clips: int,
    keys: KeyFunc = row_keywords,
) -> list[str]:
    """Recording ids whose clips sum to at most ``target_clips``.

    Whole recordings only. Each step adds a recording for the key that the
    sample so far covers with the fewest clips. Ties break by the two parts
    of the key. Within a key, smaller recordings come first, then recording
    id. ``keys`` is ``row_keywords`` or ``row_ucs_pair``.
    """
    if target_clips < 1:
        raise SystemExit(f"clips must be >= 1, got {target_clips}")

    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for recording, rows in groups.items():
        present: set[tuple[str, str]] = set()
        for row in rows:
            present |= keys(row)
        for key in present:
            by_key[key].append(recording)
    for key, recordings in by_key.items():
        recordings.sort(key=lambda recording: (len(groups[recording]), recording))

    coverage = {key: 0 for key in by_key}
    pointers = {key: 0 for key in by_key}
    selected: list[str] = []
    selected_ids: set[str] = set()
    clips = 0
    heap = [(0, key[0], key[1]) for key in by_key]
    heapq.heapify(heap)

    def next_recording(key: tuple[str, str], room: int) -> str | None:
        recordings = by_key[key]
        index = pointers[key]
        while index < len(recordings):
            recording = recordings[index]
            if recording in selected_ids:
                index += 1
                continue
            if len(groups[recording]) > room:
                pointers[key] = index
                return None
            pointers[key] = index
            return recording
        pointers[key] = index
        return None

    while clips < target_clips and heap:
        room = target_clips - clips
        covered, first, second = heapq.heappop(heap)
        key = (first, second)
        if covered != coverage[key]:
            continue
        recording = next_recording(key, room)
        if recording is None:
            continue
        selected.append(recording)
        selected_ids.add(recording)
        clips += len(groups[recording])
        touched: set[tuple[str, str]] = set()
        for row in groups[recording]:
            for key in keys(row):
                coverage[key] += 1
                touched.add(key)
        for key in touched:
            heapq.heappush(heap, (coverage[key], key[0], key[1]))
    return selected


def key_coverage(
    groups: dict[str, list[dict[str, str]]],
    selected: set[str],
    keys: KeyFunc,
) -> dict[tuple[str, str], int]:
    coverage: dict[tuple[str, str], int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()
    for rows in groups.values():
        for row in rows:
            seen |= keys(row)
    for key in seen:
        coverage[key] = 0
    for recording in selected:
        for row in groups[recording]:
            for key in keys(row):
                coverage[key] += 1
    return coverage


def build_rows(
    master_rows: list[dict[str, str]], foley_ids: dict[str, str]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for master in master_rows:
        path = (master.get("path") or "").strip()
        if not path:
            raise SystemExit("master row has an empty path")
        if path in seen_paths:
            raise SystemExit(f"master repeats path {path!r}")
        seen_paths.add(path)
        rows.append(layout_row(master, recording_id(master, foley_ids), ""))
    return rows


def labels_differ(existing: list[dict[str, str]], script_rows: list[dict[str, str]]) -> bool:
    """True when an eval row's Category or SubCategory is no longer the script label."""
    script = {(row.get("path") or "").strip(): row for row in script_rows}
    for row in existing:
        path = (row.get("path") or "").strip()
        original = script.get(path)
        if original is None:
            return True
        if (row.get("Category") or "").strip() != (original.get("Category") or "").strip():
            return True
        if (row.get("SubCategory") or "").strip() != (original.get("SubCategory") or "").strip():
            return True
    return False


def _apply_existing_labels(rows: list[dict[str, str]], all_path: Path, force: bool) -> None:
    """Keep Category and SubCategory already stored on all.csv.

    A later fill writes those cells on all.csv. Rebuilding from the master
    would put the old blanks back.
    """
    if not all_path.is_file():
        return
    existing = read_csv(all_path, COLUMNS)
    if not force and any((row.get("pile") or "").strip() for row in existing):
        raise SystemExit(f"{display(all_path)} already has pile assignments; not overwriting")
    saved = {
        (row.get("path") or "").strip(): ((row.get("Category") or ""), (row.get("SubCategory") or ""))
        for row in existing
    }
    missing = [row["path"] for row in rows if row["path"] not in saved]
    if missing:
        raise SystemExit(f"{display(all_path)} is missing {len(missing)} master paths; not mixing labels")
    for row in rows:
        category, subcategory = saved[row["path"]]
        row["Category"] = category
        row["SubCategory"] = subcategory


def _print_pairs(label: str, groups: dict[str, list[dict[str, str]]], selected: set[str]) -> None:
    coverage = key_coverage(groups, selected, row_ucs_pair)
    counts = sorted(coverage.values())
    least = counts[0] if counts else 0
    median = counts[len(counts) // 2] if counts else 0
    missing = [pair for pair, count in sorted(coverage.items()) if count == 0]
    text = f"{label}: pairs {len(counts)}, least {least} clip(s), median {median}"
    if missing:
        shown = ", ".join(
            (f"{category}/{subcategory}" if subcategory else category or "(blank)")
            for category, subcategory in missing[:12]
        )
        extra = f" (+{len(missing) - 12} more)" if len(missing) > 12 else ""
        text += f", missing {len(missing)}: {shown}{extra}"
    print(text)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sample the hand-checked set and write all.csv.")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER, help="labeled master CSV")
    parser.add_argument("--foley", type=Path, default=DEFAULT_FOLEY, help="FoleySet metadata CSV")
    parser.add_argument("--out", type=Path, default=ORIGINAL, help="directory for all.csv and eval.csv")
    parser.add_argument("--pool", type=int, default=3000, help="clip budget for the larger copy (default 3000)")
    parser.add_argument("--clips", type=int, default=700, help="clip budget for eval.csv, drawn from the pool (default 700)")
    parser.add_argument("--force", action="store_true", help="overwrite an eval.csv whose labels were edited")
    args = parser.parse_args(argv)

    if args.pool < args.clips:
        raise SystemExit(f"pool ({args.pool}) must be >= clips ({args.clips})")

    master_path = resolve_under_root(args.master)
    foley_path = resolve_under_root(args.foley)
    out_dir = resolve_under_root(args.out)
    all_path = out_dir / "all.csv"
    eval_path = out_dir / "eval.csv"
    pool_path = out_dir / f"eval-{args.pool}.csv"

    master_rows = read_csv(master_path, MASTER_COLUMNS)
    rows = build_rows(master_rows, load_foley_ids(foley_path))
    _apply_existing_labels(rows, all_path, args.force)
    if not args.force and eval_path.is_file() and labels_differ(read_csv(eval_path, MASTER_COLUMNS), rows):
        raise SystemExit(f"{display(eval_path)} labels differ from the script; not overwriting")
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["recording"], []).append(row)
    pool_ids = sample_recordings(groups, args.pool, row_ucs_pair)
    if rows and not pool_ids:
        raise SystemExit(f"no recording fits in {args.pool} clips")
    pool_groups = {recording: groups[recording] for recording in pool_ids}
    eval_ids = sample_recordings(pool_groups, args.clips, row_ucs_pair)
    if rows and not eval_ids:
        raise SystemExit(f"no recording fits in {args.clips} clips")
    pool_selected = set(pool_ids)
    eval_selected = set(eval_ids)
    pool_rows = [row for row in rows if row["recording"] in pool_selected]
    eval_rows = [row for row in rows if row["recording"] in eval_selected]
    all_rows = []
    for row in rows:
        copy = dict(row)
        copy["pile"] = ""
        all_rows.append(copy)

    write_csv(all_path, all_rows)
    write_csv(pool_path, pool_rows, MASTER_COLUMNS)
    write_csv(eval_path, eval_rows, MASTER_COLUMNS)

    blank = sum(1 for row in eval_rows if not row["Category"].strip() and not row["SubCategory"].strip())
    print(
        f"wrote {display(all_path)} ({len(all_rows)} rows), {display(pool_path)} "
        f"({len(pool_rows)} clips, {len(pool_selected)} recordings), and {display(eval_path)} "
        f"({len(eval_rows)} clips, {len(eval_selected)} recordings, {blank} blank)"
    )
    _print_pairs("pool", groups, pool_selected)
    _print_pairs("eval", groups, eval_selected)


if __name__ == "__main__":
    main()
