"""Build the AudioSet ablation manifests.

Four folders under manifests/test-envsound-no-audioset. Every folder uses the
same test file: the original EnvSound test split with AudioSet removed.
EnvSound Category and SubCategory stay the original labels. FoleySet
Category and SubCategory come from scoring/experiments/min075-envsound-foleyset,
the UCS labels scored on manifests/envsound-foleyset.

audioset-same-size draws train and val from the original split, so AudioSet
clips stay eligible, but each Category/SubCategory has the same number of
rows as no-audioset. Within a pair, slots are split across sources in
proportion to how often each source appears, and the clips taken from a
source are evenly spaced in path order. Pairs that exist only on AudioSet
are absent here, as they are in no-audioset.

no-audioset-foleyset adds the FoleySet train split to train and the FoleySet
val split to val. The FoleySet test split is left out so the shared test
stays EnvSound only.

Usage:
  python scripts/make_test_envsound_no_audioset.py
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGINAL = ROOT / "manifests" / "original-envsound"
DEFAULT_FOLEY = ROOT / "scoring" / "experiments" / "min075-envsound-foleyset"
DEFAULT_OUT = ROOT / "manifests" / "test-envsound-no-audioset"
SPLIT_NAMES = ("train", "val", "test")
FOLDERS = ("1-original", "2-no-audioset", "3-audioset-same-size", "4-no-audioset-foleyset")
COLUMNS = ["filename", "Category", "SubCategory", "Keywords", "source", "path", "exists"]
AUDIOSET = "AudioSet"
FOLEYSET = "FoleySet"


def resolve_under_root(path: Path) -> Path:
    if path.is_absolute():
        return path
    return ROOT / path


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"manifest not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        missing = [name for name in COLUMNS if name not in fieldnames]
        if missing:
            raise SystemExit(f"{path} is missing columns: {', '.join(missing)}")
        return [{name: row.get(name) or "" for name in COLUMNS} for row in reader]


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def pair_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("Category") or "", row.get("SubCategory") or "")


def without_audioset(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("source") != AUDIOSET]


def source_quotas(counts: dict[str, int], target: int) -> dict[str, int]:
    """Give each source a share of ``target`` proportional to ``counts``.

    Largest remainder fills the leftover slots. Equal remainders go to the
    source name that sorts first.
    """
    total = sum(counts.values())
    if target < 0:
        raise ValueError(f"target must be >= 0, got {target}")
    if target > total:
        raise ValueError(f"target {target} exceeds {total} rows")
    quotas = {source: target * count // total for source, count in counts.items()}
    leftover = target - sum(quotas.values())
    order = sorted(counts, key=lambda source: (-(target * counts[source] % total), source))
    for source in order:
        if leftover == 0:
            break
        if quotas[source] >= counts[source]:
            continue
        quotas[source] += 1
        leftover -= 1
    if leftover:
        raise ValueError(f"could not place {leftover} of {target} slots")
    return quotas


def evenly_spaced(rows: list[dict[str, str]], count: int) -> list[dict[str, str]]:
    """``count`` rows, spread through ``rows`` after sorting by path."""
    ordered = sorted(rows, key=lambda row: (row.get("path") or "", row.get("filename") or ""))
    size = len(ordered)
    if count >= size:
        return ordered
    if count <= 0:
        return []
    return [ordered[int((index + 0.5) * size / count)] for index in range(count)]


def match_pair_counts(full: list[dict[str, str]], target: list[dict[str, str]]) -> list[dict[str, str]]:
    """Sample ``full`` so each UCS pair has as many rows as in ``target``.

    ``target`` is the no-AudioSet split. AudioSet rows in ``full`` can be
    chosen. The result keeps the relative order of ``full``.
    """
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in full:
        grouped[pair_key(row)].append(row)
    needed: dict[tuple[str, str], int] = defaultdict(int)
    for row in target:
        needed[pair_key(row)] += 1
    missing = [pair for pair in needed if pair not in grouped]
    if missing:
        label = "/".join(missing[0])
        raise SystemExit(f"no-audioset pair {label} is not in the original split")

    chosen: set[int] = set()
    for pair, group in grouped.items():
        count = needed.get(pair, 0)
        if count == 0:
            continue
        by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in group:
            by_source[row.get("source") or ""].append(row)
        quotas = source_quotas({source: len(source_rows) for source, source_rows in by_source.items()}, count)
        for source, quota in quotas.items():
            for row in evenly_spaced(by_source[source], quota):
                chosen.add(id(row))
    picked = [row for row in full if id(row) in chosen]
    if len(picked) != len(target):
        raise SystemExit(f"same-size split has {len(picked)} rows, expected {len(target)}")
    return picked


def foley_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("source") == FOLEYSET]


def build(
    original: dict[str, list[dict[str, str]]],
    foley: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Return the four folders, each with train, val, and the shared test."""
    for name in SPLIT_NAMES:
        if name not in original:
            raise SystemExit(f"original split missing: {name}")
    test = without_audioset(original["test"])
    no_audio = {
        "train": without_audioset(original["train"]),
        "val": without_audioset(original["val"]),
        "test": test,
    }
    same_size = {
        "train": match_pair_counts(original["train"], no_audio["train"]),
        "val": match_pair_counts(original["val"], no_audio["val"]),
        "test": test,
    }
    added = {
        "train": foley_rows(foley.get("train", [])),
        "val": foley_rows(foley.get("val", [])),
    }
    with_foley = {
        "train": no_audio["train"] + added["train"],
        "val": no_audio["val"] + added["val"],
        "test": test,
    }
    folders = {
        "1-original": {"train": list(original["train"]), "val": list(original["val"]), "test": test},
        "2-no-audioset": no_audio,
        "3-audioset-same-size": same_size,
        "4-no-audioset-foleyset": with_foley,
    }
    _check_disjoint(folders, foley_rows(foley.get("test", [])))
    return folders


def _paths(rows: list[dict[str, str]]) -> set[str]:
    return {row.get("path") or "" for row in rows}


def _check_disjoint(
    folders: dict[str, dict[str, list[dict[str, str]]]],
    foley_test: list[dict[str, str]],
) -> None:
    shared = folders["2-no-audioset"]["test"]
    shared_paths = _paths(shared)
    if any(row.get("source") == AUDIOSET for row in shared):
        raise SystemExit("shared test still contains AudioSet")
    for name, splits in folders.items():
        if splits["test"] is not shared and splits["test"] != shared:
            raise SystemExit(f"{name} test is not the shared test")
        overlap = _paths(splits["train"]) & shared_paths
        overlap |= _paths(splits["val"]) & shared_paths
        if overlap:
            sample = sorted(overlap)[0]
            raise SystemExit(f"{name} leaks into the test set: {sample}")
        if _paths(splits["train"]) & _paths(splits["val"]):
            raise SystemExit(f"{name} repeats a clip in train and val")
    leaked = _paths(foley_test) & shared_paths
    if leaked:
        raise SystemExit(f"FoleySet test clip is already in the shared test: {sorted(leaked)[0]}")


def _count(rows: list[dict[str, str]], source: str) -> int:
    return sum(1 for row in rows if row.get("source") == source)


def _print_summary(
    folders: dict[str, dict[str, list[dict[str, str]]]],
    foley_test: list[dict[str, str]],
) -> None:
    test = folders["2-no-audioset"]["test"]
    print(
        "shared test "
        f"{len(test)} "
        f"(FSD50K {_count(test, 'FSD50K')}, ESC-50 {_count(test, 'ESC-50')}, AudioSet {_count(test, AUDIOSET)})"
    )
    for name in FOLDERS:
        splits = folders[name]
        parts = []
        for split in ("train", "val"):
            rows = splits[split]
            detail = f"{split} {len(rows)}"
            audioset = _count(rows, AUDIOSET)
            foley = _count(rows, FOLEYSET)
            if audioset:
                detail += f" (AudioSet {audioset})"
            if foley:
                labeled = sum(1 for row in rows if row.get("source") == FOLEYSET and (row.get("Category") or ""))
                detail += f" (FoleySet {foley}, labeled {labeled})"
            parts.append(detail)
        print(f"{name}: {', '.join(parts)}")
    if foley_test:
        print(f"FoleySet test clips left out: {len(foley_test)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the AudioSet ablation manifests.")
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL, help="original EnvSound split directory")
    parser.add_argument(
        "--foley",
        type=Path,
        default=DEFAULT_FOLEY,
        help="scored envsound-foleyset directory (FoleySet UCS labels)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    args = parser.parse_args(argv)
    original_dir = resolve_under_root(args.original)
    foley_dir = resolve_under_root(args.foley)
    out_dir = resolve_under_root(args.out)
    original = {name: read_rows(original_dir / f"envsound_{name}.csv") for name in SPLIT_NAMES}
    foley = {name: read_rows(foley_dir / f"envsound_{name}.csv") for name in SPLIT_NAMES}
    folders = build(original, foley)
    for name in FOLDERS:
        for split in SPLIT_NAMES:
            write_rows(out_dir / name / f"envsound_{split}.csv", folders[name][split])
    print(f"wrote {out_dir}")
    _print_summary(folders, foley_rows(foley["test"]))


if __name__ == "__main__":
    main()
