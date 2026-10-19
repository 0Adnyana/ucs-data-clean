"""Fill empty Category and SubCategory cells in the original-labeled all.csv.

A blank row has an empty Category and an empty SubCategory. A category-only
row has a Category and an empty SubCategory. Rows that already have a
subcategory are left alone. Categories come from mapping/label_map_llm.csv.
Labels that map leaves without a category are read from
mapping/label_map_fallback.csv and used only while filling blanks.
Labels that map leaves without a subcategory are read from
mapping/label_map_parent_sub.csv and used only when the row still has none.

Context labels (Music, Speech, a room, a genre) are used only when the row has
no sound-event label. A sound-event label is a primary or parent label with a
category. Group labels are ignored, as in make_master_manifest.

When several categories remain:

- A label with a subcategory outranks one that only names a category.
- A label that is an ontology ancestor of another label on the row is dropped.
- The category with the most remaining labels wins.
- A tie uses the earliest keyword in the row.
- One category whose labels name different subcategories keeps the subcategory
  with the most remaining labels. A tie uses the earliest keyword.

Usage:
  python mapping/fill_blank_ucs.py
  python mapping/fill_blank_ucs.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "mapping"))

from make_label_map_base import HIERARCHY, display_name, load_hierarchy  # noqa: E402
from make_master_manifest import load_label_map, split_labels  # noqa: E402

LLM_MAP = ROOT / "mapping" / "label_map_llm.csv"
FALLBACK_MAP = ROOT / "mapping" / "label_map_fallback.csv"
PARENT_MAP = ROOT / "mapping" / "label_map_parent_sub.csv"
ALL_CSV = ROOT / "5-fold-cross-labeling" / "splits" / "original-labeled" / "all.csv"
UCS_LIST = (
    ROOT
    / "references"
    / "beck_lerch_tools"
    / "ucs-sfx-tools-main"
    / "UCS_Convert"
    / "UCS_v8.2.1_Full_List.csv"
)


def load_ucs(path: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Category names, and every category/subcategory pair, from the UCS workbook."""
    if not path.is_file():
        raise SystemExit(f"UCS list not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        next(handle)
        next(handle)
        rows = list(csv.DictReader(handle))
    categories: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        category = (row.get("Category") or "").strip()
        subcategory = (row.get("SubCategory") or "").strip()
        if category:
            categories.add(category)
        if category and subcategory:
            pairs.add((category, subcategory))
    if not categories:
        raise SystemExit(f"{path.name} has no categories")
    return categories, pairs


def effective_map(
    llm: dict[tuple[str, str], tuple[str, str, str]],
    fallback: dict[tuple[str, str], tuple[str, str, str]],
    categories: set[str],
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], tuple[str, str, str]]:
    """LLM map with fallback categories overlaid on labels that had none."""
    merged = dict(llm)
    for key, (role, category, subcategory) in fallback.items():
        prior = llm.get(key)
        if prior is None:
            raise SystemExit(f"fallback label is not in the llm map: {key[0]} {key[1]!r}")
        prior_role, prior_category, prior_subcategory = prior
        if prior_role != role:
            raise SystemExit(f"fallback role for {key[0]} {key[1]!r} is {role}, llm map says {prior_role}")
        if prior_category or prior_subcategory:
            raise SystemExit(f"fallback repeats a label the llm map already categorizes: {key[0]} {key[1]!r}")
        if category not in categories:
            raise SystemExit(f"fallback category {category!r} for {key[1]!r} is not in the UCS list")
        if subcategory and (category, subcategory) not in pairs:
            raise SystemExit(f"fallback pair {category}/{subcategory} for {key[1]!r} is not in the UCS list")
        merged[key] = (role, category, subcategory)
    return merged


class Ontology:
    """Depth and ancestor checks for AudioSet display names."""

    def __init__(self, path: Path) -> None:
        self.hierarchy = load_hierarchy(path)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        ancestor_name = display_name(ancestor)
        descendant_name = display_name(descendant)
        if ancestor_name == descendant_name:
            return False
        node = self.hierarchy.by_name.get(descendant_name)
        if node is None:
            return False
        return ancestor_name in self.hierarchy.ancestor_names(str(node["id"]))


def sound_items(
    source: str,
    keywords: str,
    label_map: dict[tuple[str, str], tuple[str, str, str]],
    *,
    include_context: bool,
) -> list[dict[str, object]]:
    """Mapped labels on one row. Context is included only when asked."""
    items: list[dict[str, object]] = []
    for index, label in enumerate(split_labels(keywords)):
        mapped = label_map.get((source, label))
        if mapped is None:
            continue
        role, category, subcategory = mapped
        if role == "group" or not category:
            continue
        if role == "context" and not include_context:
            continue
        items.append(
            {
                "index": index,
                "label": label,
                "category": category,
                "subcategory": subcategory,
            }
        )
    return items


def narrow(items: list[dict[str, object]], ontology: Ontology) -> list[dict[str, object]]:
    """Prefer labels that name a subcategory, then drop ontology ancestors."""
    specific = [item for item in items if item["subcategory"]]
    pool = specific if specific else list(items)
    kept = [
        item
        for item in pool
        if not any(
            ontology.is_ancestor(str(item["label"]), str(other["label"]))
            for other in pool
        )
    ]
    return kept or pool


def subcategory_of(pool: list[dict[str, object]]) -> str:
    """The subcategory those labels agree on. Empty when none of them names one.

    Several subcategories: the one with the most labels wins, and a tie uses
    the earliest keyword.
    """
    subcategories = list(dict.fromkeys(str(item["subcategory"]) for item in pool if item["subcategory"]))
    if len(subcategories) <= 1:
        return subcategories[0] if subcategories else ""

    def rank(subcategory: str) -> tuple[int, int]:
        group = [item for item in pool if item["subcategory"] == subcategory]
        earliest = min(int(item["index"]) for item in group)
        return (len(group), -earliest)

    return max(subcategories, key=rank)


def choose(items: list[dict[str, object]], ontology: Ontology) -> tuple[str, str]:
    """The UCS pair for one set of labels. Both strings are empty when items is empty."""
    if not items:
        return "", ""
    pool = narrow(items, ontology)
    categories = list(dict.fromkeys(str(item["category"]) for item in pool))
    if len(categories) > 1:
        def rank(category: str) -> tuple[int, int]:
            group = [item for item in pool if item["category"] == category]
            earliest = min(int(item["index"]) for item in group)
            return (len(group), -earliest)

        winner = max(categories, key=rank)
        pool = [item for item in pool if item["category"] == winner]
    return str(pool[0]["category"]), subcategory_of(pool)


def load_parent_subs(
    path: Path,
    label_map: dict[tuple[str, str], tuple[str, str, str]],
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Subcategories for labels the map left at a category only."""
    if not path.is_file():
        raise SystemExit(f"parent subcategory map not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        missing = [column for column in ("source", "label", "subcategory") if column not in fields]
        if missing:
            raise SystemExit(f"{path.name} is missing columns: {', '.join(missing)}")
        found: dict[tuple[str, str], str] = {}
        for row in reader:
            key = ((row.get("source") or "").strip(), (row.get("label") or "").strip())
            subcategory = (row.get("subcategory") or "").strip()
            if not key[0] or not key[1] or not subcategory:
                raise SystemExit(f"{path.name} has a blank source, label, or subcategory")
            if key in found:
                raise SystemExit(f"{path.name} repeats {key[0]} label {key[1]!r}")
            prior = label_map.get(key)
            if prior is None:
                raise SystemExit(f"parent subcategory label is not in the map: {key[0]} {key[1]!r}")
            _role, category, existing = prior
            if not category:
                raise SystemExit(f"parent subcategory label has no category: {key[0]} {key[1]!r}")
            if existing:
                raise SystemExit(
                    f"parent subcategory repeats a label that already has {category}/{existing}: {key[1]!r}"
                )
            if (category, subcategory) not in pairs:
                raise SystemExit(f"parent pair {category}/{subcategory} for {key[1]!r} is not in the UCS list")
            found[key] = subcategory
    uncovered = [
        f"{source} {label!r}"
        for (source, label), (_role, category, subcategory) in label_map.items()
        if category and not subcategory and (source, label) not in found
    ]
    if uncovered:
        preview = "; ".join(uncovered[:8])
        raise SystemExit(f"{len(uncovered)} labels still have no subcategory: {preview}")
    return found


def subcategory_for_category(
    source: str,
    keywords: str,
    category: str,
    label_map: dict[tuple[str, str], tuple[str, str, str]],
    ontology: Ontology,
    parent_subs: dict[tuple[str, str], str],
) -> tuple[str, str]:
    """Subcategory for a row that already has ``category``, and where it came from."""
    sound = sound_items(source, keywords, label_map, include_context=False)
    items = [item for item in sound if item["category"] == category]
    if not items:
        context = sound_items(source, keywords, label_map, include_context=True)
        items = [item for item in context if item["category"] == category]
    if not items:
        return "", "none"
    chosen = subcategory_of(narrow(items, ontology))
    if chosen:
        return chosen, "specific"
    overlaid: list[dict[str, object]] = []
    for item in items:
        copy = dict(item)
        if not copy["subcategory"]:
            copy["subcategory"] = parent_subs.get((source, str(copy["label"])), "")
        overlaid.append(copy)
    chosen = subcategory_of(narrow(overlaid, ontology))
    if chosen:
        return chosen, "parent"
    return "", "none"


def fill_blank(
    row: dict[str, str],
    label_map: dict[tuple[str, str], tuple[str, str, str]],
    ontology: Ontology,
) -> tuple[str, str, str]:
    """Category, subcategory, and which label set supplied them."""
    source = row.get("source") or ""
    keywords = row.get("Keywords") or ""
    sound = sound_items(source, keywords, label_map, include_context=False)
    if sound:
        category, subcategory = choose(sound, ontology)
        return category, subcategory, "sound"
    context = sound_items(source, keywords, label_map, include_context=True)
    if context:
        category, subcategory = choose(context, ontology)
        return category, subcategory, "context"
    return "", "", "none"


def is_blank(row: dict[str, str]) -> bool:
    return not (row.get("Category") or "").strip() and not (row.get("SubCategory") or "").strip()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fill blank UCS labels in original-labeled/all.csv.")
    parser.add_argument("--all", type=Path, default=ALL_CSV, help="CSV to fill (default original-labeled/all.csv)")
    parser.add_argument("--prior", type=Path, default=LLM_MAP, help="label map already applied to the CSV")
    parser.add_argument("--fallback", type=Path, default=FALLBACK_MAP, help="categories for labels the prior map left empty")
    parser.add_argument("--parent", type=Path, default=PARENT_MAP, help="subcategories for labels the map left at category only")
    parser.add_argument("--dry-run", action="store_true", help="report what would be written and do not change the CSV")
    args = parser.parse_args(argv)

    categories, pairs = load_ucs(UCS_LIST)
    label_map = effective_map(
        load_label_map(args.prior if args.prior.is_absolute() else ROOT / args.prior),
        load_label_map(args.fallback if args.fallback.is_absolute() else ROOT / args.fallback),
        categories,
        pairs,
    )
    parent_subs = load_parent_subs(
        args.parent if args.parent.is_absolute() else ROOT / args.parent,
        label_map,
        pairs,
    )
    ontology = Ontology(HIERARCHY)
    all_path = args.all if args.all.is_absolute() else ROOT / args.all
    with all_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "Category" not in fieldnames or "SubCategory" not in fieldnames:
        raise SystemExit(f"{all_path.name} is missing Category or SubCategory")

    reasons: Counter[str] = Counter()
    sub_reasons: Counter[str] = Counter()
    pairs_written: Counter[str] = Counter()
    unresolved: list[str] = []
    for row in rows:
        category = (row.get("Category") or "").strip()
        subcategory = (row.get("SubCategory") or "").strip()
        if category and subcategory:
            continue
        if not category:
            category, subcategory, reason = fill_blank(row, label_map, ontology)
            reasons[reason] += 1
            if not category:
                unresolved.append(f"{row.get('source')} | {row.get('Keywords')}")
                continue
            row["Category"] = category
        if subcategory:
            row["SubCategory"] = subcategory
        else:
            subcategory, sub_reason = subcategory_for_category(
                row.get("source") or "",
                row.get("Keywords") or "",
                category,
                label_map,
                ontology,
                parent_subs,
            )
            sub_reasons[sub_reason] += 1
            if not subcategory:
                unresolved.append(f"{row.get('source')} | {category} | {row.get('Keywords')}")
                continue
            row["SubCategory"] = subcategory
        shown = f"{category}/{subcategory}"
        pairs_written[shown] += 1

    filled = sum(pairs_written.values())
    print(
        f"blank rows {sum(reasons.values())}: "
        f"{reasons['sound']} from sound labels, {reasons['context']} from context labels, "
        f"{reasons['none']} still blank"
    )
    print(
        f"empty subcategories {sum(sub_reasons.values())}: "
        f"{sub_reasons['specific']} from a label that already names one, "
        f"{sub_reasons['parent']} from the parent table, "
        f"{sub_reasons['none']} still empty"
    )
    print("most common fills:")
    for name, count in pairs_written.most_common(15):
        print(f"  {count:5} {name}")
    if unresolved:
        preview = "; ".join(unresolved[:8])
        raise SystemExit(f"{len(unresolved)} rows still have no UCS pair: {preview}")
    if args.dry_run:
        print(f"dry run: would fill {filled} rows in {all_path}")
        return
    with all_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"filled {filled} rows in {all_path}")


if __name__ == "__main__":
    main()
