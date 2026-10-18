"""Build manifests/envsound-foleyset from blank-envsound plus FoleySet.

FoleySet clips are segments of Freesound uploads. FSD50K and ESC-50 use the
same Freesound ids, and a shared upload often sits in a different split than
the FoleySet segment. Those clips are left out so the combined manifests do
not repeat a recording or leak it across train, val, and test.

AudioSet ids are YouTube ids, so they are not compared here.

Usage:
  python scripts/make_envsound_foleyset.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scoring"))

from score_ucs import (  # noqa: E402
    MANIFEST_COLUMNS,
    META_COLUMNS,
    ROOT,
    foley_clip,
    load_manifest,
    write_manifest,
)

BLANK_DIR = ROOT / "manifests" / "blank-envsound"
OUT_DIR = ROOT / "manifests" / "envsound-foleyset"
AUDIO = ROOT / "audio"
SPLITS = ("train", "val", "test")
FIELDS = list(MANIFEST_COLUMNS) + list(META_COLUMNS)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def freesound_ids(audio_dir: Path) -> dict[str, set[str]]:
    """Freesound ids already present in FSD50K and ESC-50."""
    found = {"FSD50K": set(), "ESC-50": set()}
    for name in ("dev.csv", "eval.csv"):
        path = audio_dir / "FSD50K" / "FSD50K.ground_truth" / name
        for row in _read_csv(path):
            fname = (row.get("fname") or "").strip()
            if fname:
                found["FSD50K"].add(fname)
    for row in _read_csv(audio_dir / "ESC-50" / "meta" / "esc50.csv"):
        src = (row.get("src_file") or "").strip()
        if src:
            found["ESC-50"].add(src)
    return found


def _env_id(row: dict[str, str]) -> str:
    source = row.get("source") or ""
    filename = row.get("filename") or ""
    if source == "FSD50K":
        return Path(filename).stem
    if source == "ESC-50":
        parts = filename.split("-")
        return parts[1] if len(parts) > 1 else ""
    return ""


def env_splits(blank_dir: Path) -> dict[str, set[str]]:
    """Freesound id to the blank-envsound splits that already contain it."""
    splits: dict[str, set[str]] = defaultdict(set)
    for name in SPLITS:
        _fields, rows = load_manifest(blank_dir / f"envsound_{name}.csv")
        for row in rows:
            fid = _env_id(row)
            if fid:
                splits[fid].add(name)
    return splits


def foley_rows(
    audio_dir: Path,
    ids: dict[str, set[str]],
    where: dict[str, set[str]],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    meta = audio_dir / "FoleySet" / "metadata" / "foleyset_metadata.csv"
    rows: dict[str, list[dict[str, str]]] = {name: [] for name in SPLITS}
    stats = {
        "foley": 0,
        "kept": 0,
        "excluded": 0,
        "fsd_only": 0,
        "esc_only": 0,
        "both": 0,
        "same_split": 0,
        "cross_split": 0,
        "not_in_blank": 0,
    }
    for row in _read_csv(meta):
        stats["foley"] += 1
        split = (row.get("split") or "").strip()
        if split not in rows:
            raise SystemExit(f"FoleySet split must be train, val, or test, got {split!r}")
        fid = (row.get("freesound-id") or "").strip()
        in_fsd = fid in ids["FSD50K"]
        in_esc = fid in ids["ESC-50"]
        if in_fsd or in_esc:
            stats["excluded"] += 1
            if in_fsd and in_esc:
                stats["both"] += 1
            elif in_fsd:
                stats["fsd_only"] += 1
            else:
                stats["esc_only"] += 1
            held = where.get(fid, set())
            if not held:
                stats["not_in_blank"] += 1
            elif held == {split}:
                stats["same_split"] += 1
            else:
                stats["cross_split"] += 1
            continue
        filename = (row.get("name") or "").strip()
        path = f"FoleySet/audio/{filename}"
        clip = foley_clip(row)
        built = {name: "" for name in FIELDS}
        built.update(clip)
        built["filename"] = filename
        built["source"] = "FoleySet"
        built["path"] = path
        built["exists"] = "True" if (audio_dir / path).is_file() else "False"
        rows[split].append(built)
        stats["kept"] += 1
    return rows, stats


def main() -> None:
    ids = freesound_ids(AUDIO)
    where = env_splits(BLANK_DIR)
    added, stats = foley_rows(AUDIO, ids, where)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(
        "FoleySet overlap with FSD50K or ESC-50: "
        f"{stats['excluded']} clips excluded "
        f"({stats['fsd_only']} FSD50K, {stats['esc_only']} ESC-50, {stats['both']} both)"
    )
    print(
        f"  {stats['same_split']} already in the same blank-envsound split, "
        f"{stats['cross_split']} in a different split or in more than one, "
        f"{stats['not_in_blank']} in the source dataset but not in blank-envsound"
    )
    print(f"keeping {stats['kept']} of {stats['foley']} FoleySet clips")
    for name in SPLITS:
        _fields, blank = load_manifest(BLANK_DIR / f"envsound_{name}.csv")
        missing = [column for column in FIELDS if column not in _fields]
        if missing:
            raise SystemExit(f"blank-envsound {name} is missing columns: {', '.join(missing)}")
        combined = [{column: row.get(column, "") for column in FIELDS} for row in blank]
        combined.extend(added[name])
        out = OUT_DIR / f"envsound_{name}.csv"
        write_manifest(out, FIELDS, combined)
        missing_audio = sum(1 for row in added[name] if row["exists"] != "True")
        print(
            f"wrote {out} ({len(blank)} blank-envsound + {len(added[name])} FoleySet "
            f"= {len(combined)} rows, {missing_audio} FoleySet files missing)"
        )


if __name__ == "__main__":
    main()
