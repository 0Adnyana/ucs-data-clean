"""Candidate sets and flag buckets for the cross-labelling review.

A clip's label is one pair chosen from its tags. The candidate set is every
tag's pair before that choice, so a later flag can tell a second sound on the
clip from a suggestion no tag supports.
"""

from __future__ import annotations

import csv
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from make_master_manifest import split_labels  # noqa: E402

# Broad tags that ride along on many clips. Strict support ignores a suggestion
# that only these tags produce, when the clip also mapped to something else.
GENERIC_TAGS = (
    "Music",
    "Speech",
    "Animal",
    "Domestic animals, pets",
    "Vehicle",
    "Human voice",
    "Domestic sounds and home sounds",
    "Wild animals",
    "Mechanisms",
    "Liquid",
    "Water",
    "Sound effect",
    "Environmental noise",
)

# Objects/Wheeled was filled by the tag Roll on rock-music clips. Suggestions of
# that pair are contamination from those clips, not a fresh model mistake.
WHEELED = "OBJECTS||WHEELED"

PAIR_SPLIT = re.compile(r"(?<!\|)\|(?!\|)")
CANDIDATE_COLUMNS = [
    "source",
    "filename",
    "candidates",
    "candidate_pairs",
    "candidate_categories",
    "generic_tags",
    "given_pair_in_candidates",
    "given_category_in_candidates",
]


def normalize_tag(tag: str) -> str:
    return tag.lower().replace("_", " ")


GENERIC_NORMALIZED = {normalize_tag(tag) for tag in GENERIC_TAGS}


def is_generic(tag: str) -> bool:
    return normalize_tag(tag) in GENERIC_NORMALIZED


def pair_key(category: str, subcategory: str) -> str:
    """Category-only mappings use ``*`` so they stay distinct from a real subcategory."""
    sub = (subcategory or "").strip()
    return f"{(category or '').strip()}||{sub if sub else '*'}"


def split_pair(pair: str) -> tuple[str, str]:
    category, subcategory = pair.split("||", 1)
    return category, subcategory


def split_stored_pairs(text: str) -> list[str]:
    """Undo ``|``-joining pairs that themselves contain ``||``."""
    if not text:
        return []
    return PAIR_SPLIT.split(text)


def parse_candidate_tags(text: str) -> list[tuple[str, str]]:
    """``tag>CATEGORY||SUBCATEGORY`` entries in the order they were written."""
    if not text:
        return []
    parsed = []
    for part in text.split("; "):
        if ">" not in part:
            raise ValueError(part)
        tag, pair = part.split(">", 1)
        parsed.append((tag, pair))
    return parsed


def unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def candidate_record(
    row: dict[str, str],
    mappings: list[tuple[str, str, str]],
) -> dict[str, str]:
    """One output row. ``mappings`` is ``(tag, category, subcategory)`` in tag order."""
    parts: list[str] = []
    pairs: list[str] = []
    categories: list[str] = []
    for tag, category, subcategory in mappings:
        pair = pair_key(category, subcategory)
        parts.append(f"{tag}>{pair}")
        if pair not in pairs:
            pairs.append(pair)
        if category not in categories:
            categories.append(category)

    keywords = row.get("Keywords") or ""
    generic = [tag for tag in split_labels(keywords) if is_generic(tag)]
    category = (row.get("Category") or "").strip()
    subcategory = (row.get("SubCategory") or "").strip()
    given = pair_key(category, subcategory) if category else ""
    star = f"{category}||*" if category else ""
    # The chosen label is one of the tag mappings, or the category-only form of it.
    pair_hit = bool(given) and (given in pairs or star in pairs)
    category_hit = bool(category) and category in categories
    return {
        "source": row.get("source") or "",
        "filename": row.get("filename") or "",
        "candidates": "; ".join(parts),
        "candidate_pairs": "|".join(pairs),
        "candidate_categories": "|".join(categories),
        "generic_tags": "|".join(unique(generic)),
        "given_pair_in_candidates": "True" if pair_hit else "False",
        "given_category_in_candidates": "True" if category_hit else "False",
    }


def tag_mappings(
    source: str,
    keywords: str,
    effective: dict,
    parent_subs: dict,
) -> list[tuple[str, str, str]]:
    """Every tag that has a category after the fallback and parent overlays.

    Conflict rules are not applied. A tag with no category is omitted here and
    stays in Keywords. The parent subcategory is the same fill used when a
    label was left at category only, so candidate names match label names.
    """
    mapped_tags = []
    for tag in split_labels(keywords):
        mapped = effective.get((source, tag))
        if mapped is None:
            continue
        _role, category, subcategory = mapped
        if not category:
            continue
        if not subcategory:
            subcategory = parent_subs.get((source, tag), "")
        mapped_tags.append((tag, category, subcategory))
    return mapped_tags


def candidate_records(rows: list[dict[str, str]], effective: dict, parent_subs: dict) -> list[dict[str, str]]:
    records = [
        candidate_record(row, tag_mappings(row.get("source") or "", row.get("Keywords") or "", effective, parent_subs))
        for row in rows
    ]
    records.sort(key=lambda record: (record["source"], record["filename"]))
    return records


def support_for(tag_pairs: list[tuple[str, str]], suggestion: str) -> tuple[str, list[str]]:
    """Exact pair first, then a category-only candidate of the suggested category."""
    exact = [tag for tag, pair in tag_pairs if pair == suggestion]
    if exact:
        return "exact", unique(exact)
    category, _subcategory = split_pair(suggestion)
    starred = [tag for tag, pair in tag_pairs if pair == f"{category}||*"]
    if starred:
        return "category", unique(starred)
    return "", []


def bucket_flags(tag_pairs: list[tuple[str, str]], suggestion: str) -> dict[str, str]:
    """``bucket_all`` counts every tag. ``bucket_strict`` drops generic-only support.

    A suggestion that only generic tags map to is not support while the clip
    has another candidate pair. It still counts when those generic tags are the
    clip's only candidates, because there is no more specific tag to prefer.
    """
    level, tags = support_for(tag_pairs, suggestion)
    if not level:
        return {
            "bucket_all": "unsupported",
            "bucket_strict": "unsupported",
            "support_level": "",
            "supporting_tags": "",
        }
    supporting_pairs = {pair for tag, pair in tag_pairs if tag in tags}
    generic_only = all(is_generic(tag) for tag in tags)
    has_other_pair = any(pair not in supporting_pairs for _tag, pair in tag_pairs)
    if generic_only and has_other_pair:
        strict = "unsupported"
    else:
        strict = "tag_supported"
    return {
        "bucket_all": "tag_supported",
        "bucket_strict": strict,
        "support_level": level,
        "supporting_tags": "|".join(tags),
    }


def flag_type_for(given: str, suggested: str) -> str:
    """How the suggestion sits relative to the given label.

    ``MISC`` is the catch-all subcategory, so a same-category suggestion of it
    is not a swap between two specific subcategories.
    """
    given_category, _given_sub = split_pair(given)
    suggested_category, suggested_sub = split_pair(suggested)
    if given_category != suggested_category:
        return "cross_category"
    if suggested_sub in {"MISC", "*"}:
        return "within_category_misc"
    return "within_category"


def top_predictions(row: dict[str, str]) -> list[tuple[str, float]]:
    ranked = []
    for index in range(1, 6):
        category = (row.get(f"model_prediction_{index}_category") or "").strip()
        subcategory = (row.get(f"model_prediction_{index}_subcategory") or "").strip()
        confidence = float((row.get(f"model_confidence_{index}") or "").strip())
        ranked.append((pair_key(category, subcategory), confidence))
    return ranked


def given_probability(ranked: list[tuple[str, float]], given: str) -> float:
    """Probability of the given label.

    Outside the top 5 this is the rank-5 confidence, an upper bound, so a flag
    that still clears it would also clear the true (lower) probability.
    """
    for pair, confidence in ranked:
        if pair == given:
            return confidence
    return ranked[-1][1]


def class_thresholds(rows: list[dict[str, str]]) -> dict[str, float]:
    """Mean probability of each given label, over the clips that carry it."""
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        category = (row.get("Category") or "").strip()
        if not category:
            continue
        given = pair_key(category, (row.get("SubCategory") or "").strip())
        ranked = top_predictions(row)
        totals[given] += given_probability(ranked, given)
        counts[given] += 1
    return {label: totals[label] / counts[label] for label in totals}


def decide_flag(row: dict[str, str], thresholds: dict[str, float]) -> dict[str, str] | None:
    """Flag when the best class above its own threshold is not the given label.

    The class must also beat the given label's probability. A class that is
    never a given label has no threshold and cannot clear this test.
    """
    category = (row.get("Category") or "").strip()
    if not category:
        return None
    ranked = top_predictions(row)
    given = pair_key(category, (row.get("SubCategory") or "").strip())
    probability = given_probability(ranked, given)
    eligible = [
        (pair, confidence)
        for pair, confidence in ranked
        if pair in thresholds and confidence > thresholds[pair]
    ]
    if not eligible:
        return None
    suggestion, suggested_probability = eligible[0]
    if suggestion == given or not suggested_probability > probability:
        return None
    return {
        "suggested": suggestion,
        "margin": f"{suggested_probability - probability:.6f}",
        "flag": "True",
        "flag_type": flag_type_for(given, suggestion),
        "given_probability": f"{probability:.6f}",
        "suggested_probability": f"{suggested_probability:.6f}",
    }


def allocate(counts: dict[tuple[str, str], int], total: int, minimum: int) -> dict[tuple[str, str], int]:
    """Proportional counts with a floor. The floor wins when it already exceeds ``total``."""
    cells = sorted(counts)
    base = {cell: min(minimum, counts[cell]) for cell in cells}
    if sum(base.values()) >= total:
        return base
    remaining = total - sum(base.values())
    capacity = {cell: counts[cell] - base[cell] for cell in cells}
    cap_sum = sum(capacity.values())
    if cap_sum == 0 or remaining == 0:
        return base
    extra = {}
    remainders = []
    given = 0
    for cell in cells:
        share = remaining * capacity[cell]
        extra[cell] = share // cap_sum
        remainders.append((share % cap_sum, cell))
        given += extra[cell]
    leftover = remaining - given
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _remainder, cell in remainders:
        if leftover == 0:
            break
        if extra[cell] < capacity[cell]:
            extra[cell] += 1
            leftover -= 1
    return {cell: base[cell] + extra[cell] for cell in cells}


def draw_sample(rows: list[dict[str, str]], total: int = 100, minimum: int = 5, seed: int = 0) -> list[dict[str, str]]:
    """Stratify on ``bucket_strict`` × ``flag_type``. Seed fixes the draw."""
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["bucket_strict"], row["flag_type"])].append(row)
    for group in groups.values():
        group.sort(key=lambda row: (row["source"], row["filename"]))
    quota = allocate({key: len(group) for key, group in groups.items()}, total, minimum)
    rng = random.Random(seed)
    chosen: list[dict[str, str]] = []
    for key in sorted(quota):
        pool = groups[key]
        count = quota[key]
        if count >= len(pool):
            chosen.extend(pool)
        else:
            chosen.extend(rng.sample(pool, count))
    chosen.sort(
        key=lambda row: (
            0 if row["bucket_strict"] == "tag_supported" else 1,
            -float(row["margin"]),
            row["source"],
            row["filename"],
        )
    )
    return chosen


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise SystemExit(f"csv not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            raise SystemExit(f"{path} has no header")
        return fieldnames, list(reader)


def require_columns(path: Path, fieldnames: list[str], required: tuple[str, ...]) -> None:
    missing = [column for column in required if column not in fieldnames]
    if missing:
        found = ", ".join(fieldnames)
        absent = ", ".join(missing)
        raise SystemExit(f"{path} is missing columns: {absent}. columns found: {found}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
