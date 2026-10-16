"""Build manifests/master.csv from the metadata shipped with each dataset.

Each run replaces the file. Rows come from the label files under ``audio/``,
not from the envsound manifests. A FoleySet clip whose Freesound id is
already an FSD50K or ESC-50 clip is left out, so the same upload is not
listed twice.

  AudioSet   ``audio/AudioSet/audios/{balanced_train,eval}_segments.csv`` ``human_labels``
  ESC-50     ``audio/ESC-50/meta/esc50.csv`` ``category``
  FSD50K     ``audio/FSD50K/FSD50K.ground_truth/{dev,eval}.csv`` ``labels``
  FoleySet   ``audio/FoleySet/metadata/foleyset_metadata.csv`` ``category`` and ``sub-category``

``--fill-ucs`` writes Category and SubCategory from a map of those unique
keywords. A keyword the map does not list is skipped. ``context`` and
``group`` labels are skipped, and so is a label with an empty category. A
label that names a subcategory outranks one that only names a category.
One agreed pair is written in full. Several subcategories in one category
keep that category and leave SubCategory empty. Several categories, or no
usable label, leave both empty.

Usage:
  python scripts/make_master_manifest.py
  python scripts/make_master_manifest.py --fill-ucs references/mapping/label_map_llm.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "audio"
OUT = ROOT / "manifests" / "master.csv"
DEFAULT_LABEL_MAP = ROOT / "references" / "mapping" / "label_map_llm.csv"
COLUMNS = [
    "filename",
    "Category",
    "SubCategory",
    "Keywords",
    "source",
    "path",
    "exists",
]
MAP_COLUMNS = ["source", "label", "role", "category", "subcategory"]
SKIPPED_ROLES = frozenset({"context", "group"})


def split_labels(text: str) -> list[str]:
    """Split a keyword list.

    AudioSet labels contain commas of their own ("Waves, surf"). The
    separator between labels is a comma that is not followed by a space.
    """
    text = (text or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r",(?=\S)", text) if part.strip()]


def resolve_under_root(path: Path) -> Path:
    if path.is_absolute():
        return path
    return ROOT / path


def write_manifest(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_label_map(path: Path) -> dict[tuple[str, str], tuple[str, str, str]]:
    """``(source, label)`` to ``(role, category, subcategory)``."""
    if not path.is_file():
        raise SystemExit(f"label map not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        missing = [column for column in MAP_COLUMNS if column not in fields]
        if missing:
            raise SystemExit(f"{path.name} is missing columns: {', '.join(missing)}")
        found: dict[tuple[str, str], tuple[str, str, str]] = {}
        for row in reader:
            key = ((row.get("source") or "").strip(), (row.get("label") or "").strip())
            value = (
                (row.get("role") or "").strip(),
                (row.get("category") or "").strip(),
                (row.get("subcategory") or "").strip(),
            )
            previous = found.get(key)
            if previous is not None and previous != value:
                raise SystemExit(f"{path.name} repeats {key[0]} label {key[1]!r} with a different UCS pair")
            found[key] = value
    return found


def ucs_for_keywords(
    source: str,
    keywords: str,
    label_map: dict[tuple[str, str], tuple[str, str, str]],
    missing: set[tuple[str, str]] | None = None,
) -> tuple[str, str]:
    """The agreed UCS pair for one keyword list. Both strings are empty when none is agreed."""
    specific: list[tuple[str, str]] = []
    broad: list[str] = []
    for label in split_labels(keywords):
        mapped = label_map.get((source, label))
        if mapped is None:
            if missing is not None:
                missing.add((source, label))
            continue
        role, category, subcategory = mapped
        if role in SKIPPED_ROLES or not category:
            continue
        if subcategory:
            pair = (category, subcategory)
            if pair not in specific:
                specific.append(pair)
        elif category not in broad:
            broad.append(category)
    if specific:
        categories = list(dict.fromkeys(category for category, _sub in specific))
        if len(specific) == 1:
            return specific[0]
        if len(categories) == 1:
            return categories[0], ""
        return "", ""
    if len(broad) == 1:
        return broad[0], ""
    return "", ""


def fill_ucs(
    rows: list[dict[str, str]],
    label_map: dict[tuple[str, str], tuple[str, str, str]],
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Write Category and SubCategory from the label map.

    Returns the assigned, category, and blank counts, and the keywords the map does not list.
    """
    missing: set[tuple[str, str]] = set()
    chosen: list[tuple[str, str]] = []
    for row in rows:
        source = row.get("source") or ""
        chosen.append(ucs_for_keywords(source, row.get("Keywords") or "", label_map, missing))
    counts = {"assigned": 0, "category": 0, "blank": 0, "unmapped": len(missing)}
    for row, (category, subcategory) in zip(rows, chosen):
        row["Category"] = category
        row["SubCategory"] = subcategory
        if category and subcategory:
            counts["assigned"] += 1
        elif category:
            counts["category"] += 1
        else:
            counts["blank"] += 1
    return counts, sorted(missing)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"dataset file not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _audioset_keywords(human_labels: str) -> str:
    """AudioSet separates labels with ';' and keeps commas inside a label."""
    return ",".join(part.strip() for part in (human_labels or "").split(";") if part.strip())


def _norm_phrase(text: str) -> str:
    text = text.lower().replace("_", " ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _foley_keywords(category: str, subcategory: str) -> str:
    """FoleySet class labels, in the same comma style as the other sources."""
    parts: list[str] = []
    seen: set[str] = set()
    for raw in ((category or "").strip(), re.sub(r"(?<=[a-z])(?=[A-Z])", " ", (subcategory or "").strip())):
        key = _norm_phrase(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        parts.append(raw.replace(",", " ").strip())
    return ",".join(part for part in parts if part)


def _clip(audio_dir: Path, filename: str, source: str, path: str, keywords: str) -> dict[str, str]:
    return {
        "filename": filename,
        "Category": "",
        "SubCategory": "",
        "Keywords": keywords,
        "source": source,
        "path": path,
        "exists": "True" if (audio_dir / path).is_file() else "False",
    }


def rows_from_audio(audio_dir: Path) -> tuple[list[dict[str, str]], dict[str, int]]:
    """One row per metadata record. FoleySet uploads already in FSD50K or ESC-50 are omitted."""
    rows: list[dict[str, str]] = []
    freesound: set[str] = set()
    audioset = audio_dir / "AudioSet" / "audios"
    for folder, name in (
        ("balanced_train_segments", "balanced_train_segments.csv"),
        ("eval_segments", "eval_segments.csv"),
    ):
        for row in _read_csv(audioset / name):
            filename = (row.get("filename") or "").strip()
            if not filename:
                continue
            rows.append(
                _clip(
                    audio_dir,
                    filename,
                    "AudioSet",
                    f"AudioSet/audios/{folder}/{filename}",
                    _audioset_keywords(row.get("human_labels") or ""),
                )
            )
    for row in _read_csv(audio_dir / "ESC-50" / "meta" / "esc50.csv"):
        filename = (row.get("filename") or "").strip()
        if not filename:
            continue
        src_file = (row.get("src_file") or "").strip()
        if src_file:
            freesound.add(src_file)
        rows.append(_clip(audio_dir, filename, "ESC-50", f"ESC-50/audio/{filename}", (row.get("category") or "").strip()))
    ground = audio_dir / "FSD50K" / "FSD50K.ground_truth"
    for folder, name in (("FSD50K.dev_audio", "dev.csv"), ("FSD50K.eval_audio", "eval.csv")):
        for row in _read_csv(ground / name):
            fname = (row.get("fname") or "").strip()
            if not fname:
                continue
            freesound.add(fname)
            labels = [part.strip() for part in (row.get("labels") or "").split(",") if part.strip()]
            filename = f"{fname}.wav"
            rows.append(_clip(audio_dir, filename, "FSD50K", f"FSD50K/{folder}/{filename}", ",".join(labels)))
    foley_omitted = 0
    for row in _read_csv(audio_dir / "FoleySet" / "metadata" / "foleyset_metadata.csv"):
        filename = (row.get("name") or "").strip()
        if not filename:
            continue
        fid = (row.get("freesound-id") or "").strip()
        if fid and fid in freesound:
            foley_omitted += 1
            continue
        rows.append(
            _clip(
                audio_dir,
                filename,
                "FoleySet",
                f"FoleySet/audio/{filename}",
                _foley_keywords(row.get("category") or "", row.get("sub-category") or ""),
            )
        )
    missing_wav = sum(1 for row in rows if row["exists"] != "True")
    return rows, {"foley_omitted": foley_omitted, "missing_wav": missing_wav}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build manifests/master.csv from the dataset metadata in audio/.")
    parser.add_argument(
        "--fill-ucs",
        type=Path,
        nargs="?",
        const=DEFAULT_LABEL_MAP,
        metavar="MAP",
        help=(
            "fill Category and SubCategory from a label map CSV "
            f"(default {DEFAULT_LABEL_MAP.relative_to(ROOT)})"
        ),
    )
    args = parser.parse_args(argv)
    rows, stats = rows_from_audio(AUDIO_DIR)
    filled = ""
    if args.fill_ucs is not None:
        label_path = resolve_under_root(args.fill_ucs)
        counts, missing = fill_ucs(rows, load_label_map(label_path))
        filled = (
            f"; ucs from {label_path.name}: "
            f"{counts['assigned']} assigned, {counts['category']} category only, {counts['blank']} blank"
        )
        if missing:
            shown = ", ".join(f"{source}:{label}" for source, label in missing[:12])
            extra = f" (+{len(missing) - 12} more)" if len(missing) > 12 else ""
            filled += f"; {len(missing)} keywords not in the map: {shown}{extra}"
    write_manifest(OUT, list(COLUMNS), rows)
    by_source: dict[str, int] = {}
    for row in rows:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    sources = ", ".join(f"{name} {by_source[name]}" for name in ("AudioSet", "ESC-50", "FSD50K", "FoleySet") if name in by_source)
    print(
        f"wrote {OUT} ({len(rows)} rows: {sources}; "
        f"FoleySet overlap omitted {stats['foley_omitted']}; "
        f"wavs missing {stats['missing_wav']}{filled})"
    )


if __name__ == "__main__":
    main()
