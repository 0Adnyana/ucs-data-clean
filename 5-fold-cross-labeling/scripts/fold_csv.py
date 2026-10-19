"""Shared columns, recording ids, and CSV IO for the 5-fold labeling split."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER_COLUMNS = [
    "filename",
    "Category",
    "SubCategory",
    "Keywords",
    "source",
    "path",
    "exists",
]
LISTEN_COLUMNS = [
    "model_prediction_1_category",
    "model_prediction_1_subcategory",
    "model_confidence_1",
    "model_prediction_2_category",
    "model_prediction_2_subcategory",
    "model_confidence_2",
    "model_prediction_3_category",
    "model_prediction_3_subcategory",
    "model_confidence_3",
    "model_prediction_4_category",
    "model_prediction_4_subcategory",
    "model_confidence_4",
    "model_prediction_5_category",
    "model_prediction_5_subcategory",
    "model_confidence_5",
    "human_category",
    "human_subcategory",
]
COLUMNS = MASTER_COLUMNS + ["recording", "pile"] + LISTEN_COLUMNS
PILES = ("A", "B", "C", "D", "E")
HELD_PILE = "eval"
SAMPLE_PILE = "sample"
SPLITS = ROOT / "5-fold-cross-labeling" / "splits"
ORIGINAL = SPLITS / "original-labeled"
DEFAULT_MASTER = ROOT / "manifests" / "master.csv"
DEFAULT_FOLEY = ROOT / "audio" / "FoleySet" / "metadata" / "foleyset_metadata.csv"
SOURCES = ("AudioSet", "ESC-50", "FSD50K", "FoleySet")


def resolve_under_root(path: Path) -> Path:
    """Resolve a relative path from the repo root, not the working directory."""
    if path.is_absolute():
        return path
    return ROOT / path


def display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def split_labels(text: str) -> list[str]:
    """Split a keyword list.

    AudioSet labels contain commas of their own ("Waves, surf"). The
    separator between labels is a comma that is not followed by a space.
    """
    text = (text or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r",(?=\S)", text) if part.strip()]


def row_keywords(row: dict[str, str]) -> set[tuple[str, str]]:
    """``(source, keyword)`` pairs on one row. An empty keyword list is one pair."""
    source = (row.get("source") or "").strip()
    labels = split_labels(row.get("Keywords") or "")
    if not labels:
        return {(source, "")}
    return {(source, label) for label in labels}


def row_ucs_pair(row: dict[str, str]) -> set[tuple[str, str]]:
    """The ``(Category, SubCategory)`` on one row. Both empty is its own pair."""
    return {((row.get("Category") or "").strip(), (row.get("SubCategory") or "").strip())}


def is_blank(row: dict[str, str]) -> bool:
    return not (row.get("Category") or "").strip() and not (row.get("SubCategory") or "").strip()


def has_listen_marks(rows: list[dict[str, str]]) -> bool:
    return any((row.get(column) or "").strip() for row in rows for column in LISTEN_COLUMNS)


def train_piles(pile: str) -> tuple[str, ...]:
    """The other four piles, in the order probe ``pile`` trains on."""
    if pile not in PILES:
        raise ValueError(f"pile must be one of {', '.join(PILES)}, got {pile!r}")
    start = PILES.index(pile)
    return tuple(PILES[(start + offset) % len(PILES)] for offset in range(1, len(PILES)))


def clear_listen(row: dict[str, str]) -> dict[str, str]:
    copy = dict(row)
    for column in LISTEN_COLUMNS:
        copy[column] = ""
    return copy


def promote_row(row: dict[str, str]) -> dict[str, str]:
    """Copy a pile row into the next round.

    A filled ``human_category`` replaces ``Category`` and ``SubCategory``,
    even when ``human_subcategory`` is empty. Empty human columns keep the
    current label. Listen columns start empty.
    """
    copy = dict(row)
    category = (row.get("human_category") or "").strip()
    if category:
        copy["Category"] = category
        copy["SubCategory"] = (row.get("human_subcategory") or "").strip()
    return clear_listen(copy)


def read_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"file not found: {display(path)}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        missing = [column for column in required if column not in fields]
        if missing:
            raise SystemExit(f"{display(path)} is missing columns: {', '.join(missing)}")
        return [{key: value or "" for key, value in row.items()} for row in reader]


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames or COLUMNS, lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def load_foley_ids(path: Path) -> dict[str, str]:
    """FoleySet filename to freesound id, from ``name`` and ``freesound-id``."""
    if not path.is_file():
        raise SystemExit(f"file not found: {display(path)}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        missing = [column for column in ("name", "freesound-id") if column not in fields]
        if missing:
            raise SystemExit(f"{display(path)} is missing columns: {', '.join(missing)}")
        found: dict[str, str] = {}
        for row in reader:
            name = (row.get("name") or "").strip()
            freesound_id = (row.get("freesound-id") or "").strip()
            if name:
                found[name] = freesound_id
    return found


def recording_id(row: dict[str, str], foley_ids: dict[str, str]) -> str:
    """The group that stays in one pile, or in the hand-checked set."""
    source = (row.get("source") or "").strip()
    filename = (row.get("filename") or "").strip()
    if source == "AudioSet":
        if not (filename.startswith("Y") and filename.endswith(".wav") and len(filename) > 5):
            raise SystemExit(f"AudioSet filename is not Y….wav: {filename}")
        return "AudioSet:" + filename[1:-4]
    if source == "ESC-50":
        parts = filename.split("-")
        if len(parts) < 2 or not parts[1]:
            raise SystemExit(f"ESC-50 filename has no freesound id: {filename}")
        return "ESC-50:" + parts[1]
    if source == "FSD50K":
        if not filename.endswith(".wav") or filename == ".wav":
            raise SystemExit(f"FSD50K filename is not a .wav: {filename}")
        return "FSD50K:" + filename[:-4]
    if source == "FoleySet":
        if filename not in foley_ids:
            raise SystemExit(f"FoleySet filename is not in foleyset_metadata.csv: {filename}")
        freesound_id = foley_ids[filename]
        if not freesound_id:
            raise SystemExit(f"FoleySet filename {filename} has an empty freesound id")
        return "FoleySet:" + freesound_id
    raise SystemExit(f"unknown source: {source}")


def layout_row(row: dict[str, str], recording: str, pile: str) -> dict[str, str]:
    laid = {column: (row.get(column) or "") for column in MASTER_COLUMNS}
    laid["recording"] = recording
    laid["pile"] = pile
    for column in LISTEN_COLUMNS:
        laid[column] = ""
    return laid


def group_recordings(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["recording"], []).append(row)
    return groups


def round_has_listen_marks(round_dir: Path) -> bool:
    for pile in PILES:
        path = round_dir / pile / "pile.csv"
        if path.is_file() and has_listen_marks(read_csv(path, COLUMNS)):
            return True
    return False


def round_pile_paths(round_dir: Path) -> list[Path]:
    return [round_dir / pile / "pile.csv" for pile in PILES if (round_dir / pile / "pile.csv").is_file()]
