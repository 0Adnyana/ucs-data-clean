"""Convert dataset tags to UCS the way Beck and Lerch do, with one change.

The cascade is theirs: manual map, then subcategory name, then category name,
then synonym. A file's tags are reduced by the same two filters: if any mapped
tag has a subcategory, tags with only a category are dropped, then the category
with the most remaining tags wins.

Their last step picks the rightmost surviving tag when that set still disagrees.
This script leaves that disagreement empty instead.

  - Two categories tied for the most tags: Category and SubCategory stay empty.
  - One category, and the surviving tags name different subcategories: Category
    is kept and SubCategory stays empty.
  - The surviving tags already agree: that pair is written. Position is not used.
  - No tag maps: Category is MISCELLANEOUS, as in their converter.

Tags are split on every comma, then stripped. That is how UCS_Convert.py reads
a labels cell. ``paper_category`` and ``paper_subcategory`` are the rightmost
assignment, so a run can be compared with their result.

Usage:
  python scripts/beck_ucs_convert.py manifests/original-envsound/envsound_val.csv
  python scripts/beck_ucs_convert.py manifests/original-envsound/envsound_val.csv -o blank.csv
  python scripts/beck_ucs_convert.py manifest.csv --tiebreak rightmost -o paper.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BECK_DIR = ROOT / "references" / "beck_lerch_tools" / "ucs-sfx-tools-main" / "UCS_Convert"
DEFAULT_CONFIG = BECK_DIR / "config.json"
DEFAULT_UCS = BECK_DIR / "UCS_v8.2.1_Full_List.csv"
SYNONYM_COLUMN = "Synonyms - Comma Separated"

PAPER_CATEGORY = "paper_category"
PAPER_SUBCATEGORY = "paper_subcategory"
INPUT_CATEGORY = "input_category"
INPUT_SUBCATEGORY = "input_subcategory"
DECISION = "decision"


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_ucs_lookups(config: dict, ucs_path: Path):
    """Category, subcategory, manual, and synonym tables, in their lookup order."""
    cat_col = config["column_names"]["ucs_category_column"]
    subcat_col = config["column_names"]["ucs_subcategory_column"]

    with ucs_path.open(newline="", encoding="utf-8") as handle:
        for _ in range(2):
            next(handle)
        rows = list(csv.DictReader(handle))

    if not rows or cat_col not in rows[0] or subcat_col not in rows[0]:
        raise SystemExit(f"{ucs_path} is missing '{cat_col}' or '{subcat_col}'")

    subcat_to_cat: dict[str, str] = {}
    valid_categories: set[str] = set()
    for row in rows:
        category = (row.get(cat_col) or "").strip()
        subcategory = (row.get(subcat_col) or "").strip()
        if category:
            valid_categories.add(category.upper())
        if subcategory:
            subcat_to_cat[subcategory.lower()] = category.upper()

    manual_map: dict[str, dict[str, str | None]] = {}
    for tag, mapping in config.get("manual_mapping", {}).items():
        if not isinstance(mapping, dict):
            continue
        category = mapping.get("Category")
        subcategory = mapping.get("SubCategory")
        if isinstance(category, str) and category:
            category = category.upper()
        if isinstance(subcategory, str) and subcategory:
            subcategory = subcategory.upper()
        manual_map[tag.lower()] = {"Category": category, "SubCategory": subcategory}

    synonym_map: dict[str, dict[str, list[str]]] = {}
    if rows and SYNONYM_COLUMN in rows[0]:
        for row in rows:
            subcategory = (row.get(subcat_col) or "").strip()
            if not subcategory:
                continue
            category = (row.get(cat_col) or "").strip().upper()
            for synonym in (row.get(SYNONYM_COLUMN) or "").split(","):
                key = synonym.strip().lower()
                if not key:
                    continue
                by_category = synonym_map.setdefault(key, {})
                subs = by_category.setdefault(category, [])
                upper_sub = subcategory.upper()
                if upper_sub not in subs:
                    subs.append(upper_sub)

    return subcat_to_cat, valid_categories, manual_map, synonym_map


def classify_tag(tag, subcat_to_cat, valid_categories, manual_map, default_category, synonym_map):
    """Return Category, SubCategory for one tag. Unmapped tags get the default."""
    if tag is None:
        return default_category, None
    tag_lower = str(tag).lower().strip()
    if not tag_lower:
        return default_category, None

    tag_upper = tag_lower.upper()
    tag_normalized = tag_lower.replace("_", " ")

    if tag_lower in manual_map:
        mapping = manual_map[tag_lower]
        return mapping["Category"], mapping["SubCategory"]
    if tag_normalized in manual_map:
        mapping = manual_map[tag_normalized]
        return mapping["Category"], mapping["SubCategory"]

    if tag_lower in subcat_to_cat:
        return subcat_to_cat[tag_lower], tag_upper

    if tag_upper in valid_categories:
        matches = synonym_map.get(tag_normalized)
        if matches and tag_upper in matches:
            return tag_upper, matches[tag_upper][0]
        return tag_upper, None

    matches = synonym_map.get(tag_normalized)
    if matches:
        best_cat = max(matches, key=lambda category: len(matches[category]))
        return best_cat, matches[best_cat][0]

    return default_category, None


def split_tags(text: str, separator: str = ",") -> list[str]:
    return [part.strip() for part in (text or "").split(separator) if part.strip()]


def resolve(candidates: list[dict], default_category: str):
    """Paper pair, blank-tie pair, and why.

    ``decision`` is assigned, category_tie, subcategory_tie, or unmapped.
    The paper pair always uses the rightmost surviving tag.
    """
    if not candidates:
        pair = (default_category, None)
        return pair, pair, "unmapped"

    if any(candidate["sub"] is not None for candidate in candidates):
        filtered = [candidate for candidate in candidates if candidate["sub"] is not None]
    else:
        filtered = list(candidates)

    counts = Counter(candidate["cat"] for candidate in filtered)
    top_count = max(counts.values())
    top = {category for category, count in counts.items() if count == top_count}
    best = [candidate for candidate in filtered if candidate["cat"] in top]
    winner = max(best, key=lambda candidate: candidate["idx"])
    paper = (winner["cat"], winner["sub"])

    categories = {candidate["cat"] for candidate in best}
    subcategories = {candidate["sub"] for candidate in best}
    if len(categories) > 1:
        return paper, ("", None), "category_tie"
    if len(subcategories) > 1:
        return paper, (winner["cat"], None), "subcategory_tie"
    return paper, paper, "assigned"


def label_keywords(keywords: str, lookups, default_category: str, separator: str):
    subcat_to_cat, valid_categories, manual_map, synonym_map = lookups
    candidates = []
    for index, tag in enumerate(split_tags(keywords, separator)):
        category, subcategory = classify_tag(
            tag, subcat_to_cat, valid_categories, manual_map, default_category, synonym_map
        )
        if category != default_category:
            candidates.append({"tag": tag, "cat": category, "sub": subcategory, "idx": index})
    return resolve(candidates, default_category)


def cell(value) -> str:
    if value is None:
        return ""
    return str(value)


def same_label(category: str, subcategory: str, other_category: str, other_subcategory: str) -> bool:
    return cell(category).strip() == cell(other_category).strip() and cell(subcategory).strip() == cell(other_subcategory).strip()


def convert_rows(rows: list[dict[str, str]], lookups, config: dict, tiebreak: str) -> list[dict[str, str]]:
    default_category = config["defaults"]["default_category"]
    separator = config.get("tag_separator", ",")
    keywords_names = ("Keywords", config["column_names"]["fsd50k_tags_column"])
    converted = []
    for row in rows:
        keywords = ""
        for name in keywords_names:
            if name in row and row[name]:
                keywords = row[name]
                break
        paper, blank, decision = label_keywords(keywords, lookups, default_category, separator)
        chosen = paper if tiebreak == "rightmost" else blank
        out = dict(row)
        if "Category" in row or "SubCategory" in row:
            out[INPUT_CATEGORY] = row.get("Category", "")
            out[INPUT_SUBCATEGORY] = row.get("SubCategory", "")
        out["Category"] = cell(chosen[0])
        out["SubCategory"] = cell(chosen[1])
        out[PAPER_CATEGORY] = cell(paper[0])
        out[PAPER_SUBCATEGORY] = cell(paper[1])
        out[DECISION] = decision
        converted.append(out)
    return converted


def summarize(rows: list[dict[str, str]], tiebreak: str) -> str:
    counts = Counter(row[DECISION] for row in rows)
    lines = [
        f"rows {len(rows)}",
        (
            f"assigned {counts['assigned']}, category_tie {counts['category_tie']}, "
            f"subcategory_tie {counts['subcategory_tie']}, unmapped {counts['unmapped']}"
        ),
    ]

    def differ(left_cat: str, left_sub: str, right_cat: str, right_sub: str) -> bool:
        return not same_label(left_cat, left_sub, right_cat, right_sub)

    changed = [
        row for row in rows
        if differ(row["Category"], row["SubCategory"], row[PAPER_CATEGORY], row[PAPER_SUBCATEGORY])
    ]
    if tiebreak == "blank":
        lines.append(
            f"blank tiebreak differs from rightmost on {len(changed)} rows "
            f"({counts['category_tie']} category ties, {counts['subcategory_tie']} subcategory ties)"
        )
    else:
        lines.append("tiebreak rightmost: Category and SubCategory are the paper assignment")

    if rows and INPUT_CATEGORY in rows[0]:
        paper_match = sum(
            same_label(row[INPUT_CATEGORY], row[INPUT_SUBCATEGORY], row[PAPER_CATEGORY], row[PAPER_SUBCATEGORY])
            for row in rows
        )
        chosen_match = sum(
            same_label(row[INPUT_CATEGORY], row[INPUT_SUBCATEGORY], row["Category"], row["SubCategory"])
            for row in rows
        )
        lines.append(f"rightmost vs input labels: {paper_match}/{len(rows)} exact")
        lines.append(f"{tiebreak} vs input labels: {chosen_match}/{len(rows)} exact")
        mismatches = [
            row for row in rows
            if not same_label(row[INPUT_CATEGORY], row[INPUT_SUBCATEGORY], row[PAPER_CATEGORY], row[PAPER_SUBCATEGORY])
        ]
        if mismatches:
            lines.append(f"rightmost mismatches against the input labels: {len(mismatches)}")
            for row in mismatches[:8]:
                name = row.get("filename") or row.get("fname") or ""
                lines.append(
                    f"  {name}: input {row[INPUT_CATEGORY]}/{row[INPUT_SUBCATEGORY]} "
                    f"rightmost {row[PAPER_CATEGORY]}/{row[PAPER_SUBCATEGORY]} "
                    f"keywords {row.get('Keywords') or row.get('labels') or ''}"
                )
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"csv not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Beck/Lerch tag-to-UCS conversion with ties left blank instead of rightmost-tag."
    )
    parser.add_argument("csv", type=Path, help="CSV with a Keywords or labels column")
    parser.add_argument("-o", "--output", type=Path, help="write the converted CSV here")
    parser.add_argument(
        "--tiebreak",
        choices=("blank", "rightmost"),
        default="blank",
        help="blank leaves a tied category or subcategory empty (default); rightmost is the paper",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Beck UCS_Convert config.json")
    parser.add_argument("--ucs", type=Path, default=DEFAULT_UCS, help="UCS v8.2.1 full list CSV")
    args = parser.parse_args(argv)

    config_path = args.config if args.config.is_absolute() else Path.cwd() / args.config
    ucs_path = args.ucs if args.ucs.is_absolute() else Path.cwd() / args.ucs
    if not config_path.is_file():
        raise SystemExit(f"config not found: {config_path}")
    if not ucs_path.is_file():
        raise SystemExit(f"ucs list not found: {ucs_path}")

    config = load_config(config_path)
    lookups = load_ucs_lookups(config, ucs_path)
    source = args.csv if args.csv.is_absolute() else Path.cwd() / args.csv
    rows = convert_rows(read_csv(source), lookups, config, args.tiebreak)
    if args.output:
        output = args.output if args.output.is_absolute() else Path.cwd() / args.output
        write_csv(output, rows)
        print(f"wrote {output}")
    print(summarize(rows, args.tiebreak))


if __name__ == "__main__":
    main()
