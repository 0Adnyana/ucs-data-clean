"""Write per-clip UCS candidate sets without changing any label.

The labels in original-labeled/all.csv come from the label maps, not from the
Beck cascade. Each tag is looked up in label_map_llm.csv, then the fallback
category and the parent subcategory are applied — the same overlays
fill_blank_ucs uses — and every tag is kept. The winner rules are not run.
Replaying those winner rules must reproduce Category and SubCategory exactly;
if it does not, this script stops before writing candidates.

Usage:
  python 5-fold-cross-labeling/scripts/build_candidates.py
  python 5-fold-cross-labeling/scripts/build_candidates.py --output output/candidates
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "mapping"))

from candidates import (  # noqa: E402
    CANDIDATE_COLUMNS,
    candidate_records,
    pair_key,
    read_csv,
    require_columns,
    write_csv,
)
from fill_blank_ucs import (  # noqa: E402
    FALLBACK_MAP,
    LLM_MAP,
    PARENT_MAP,
    UCS_LIST,
    Ontology,
    effective_map,
    fill_blank,
    load_parent_subs,
    load_ucs,
    subcategory_for_category,
)
from make_label_map_base import HIERARCHY  # noqa: E402
from make_master_manifest import load_label_map, ucs_for_keywords  # noqa: E402

DEFAULT_CLIPS = ROOT / "5-fold-cross-labeling" / "splits" / "original-labeled" / "all.csv"
DEFAULT_OUTPUT = ROOT / "output" / "candidates"
CLIP_COLUMNS = ("source", "filename", "Keywords", "Category", "SubCategory")


class Tables:
    def __init__(self, llm, effective, parent_subs, ontology) -> None:
        self.llm = llm
        self.effective = effective
        self.parent_subs = parent_subs
        self.ontology = ontology


def load_tables() -> Tables:
    categories, pairs = load_ucs(UCS_LIST)
    llm = load_label_map(LLM_MAP)
    effective = effective_map(llm, load_label_map(FALLBACK_MAP), categories, pairs)
    parent_subs = load_parent_subs(PARENT_MAP, effective, pairs)
    return Tables(llm, effective, parent_subs, Ontology(HIERARCHY))


def assigned_label(row: dict[str, str], tables: Tables) -> tuple[str, str]:
    """The pair the labeling scripts would write for this clip."""
    source = row.get("source") or ""
    keywords = row.get("Keywords") or ""
    category, subcategory = ucs_for_keywords(source, keywords, tables.llm)
    if not category:
        category, subcategory, _reason = fill_blank(row, tables.effective, tables.ontology)
    if category and not subcategory:
        subcategory, _why = subcategory_for_category(
            source,
            keywords,
            category,
            tables.effective,
            tables.ontology,
            tables.parent_subs,
        )
    return category or "", subcategory or ""


def label_differences(rows: list[dict[str, str]], tables: Tables) -> list[dict[str, str]]:
    diffs = []
    for row in rows:
        category, subcategory = assigned_label(row, tables)
        given_category = (row.get("Category") or "").strip()
        given_subcategory = (row.get("SubCategory") or "").strip()
        if category != given_category or subcategory != given_subcategory:
            diffs.append(
                {
                    "source": row.get("source") or "",
                    "filename": row.get("filename") or "",
                    "Category": given_category,
                    "SubCategory": given_subcategory,
                    "replay_category": category,
                    "replay_subcategory": subcategory,
                    "Keywords": row.get("Keywords") or "",
                }
            )
    diffs.sort(key=lambda item: (item["source"], item["filename"]))
    return diffs


def category_bins(records: list[dict[str, str]]) -> dict[str, Counter]:
    bins: dict[str, Counter] = {}
    for record in records:
        text = record["candidate_categories"]
        count = 0 if not text else len(text.split("|"))
        slot = "3+" if count >= 3 else str(count)
        bins.setdefault(record["source"], Counter())[slot] += 1
        bins.setdefault("all", Counter())[slot] += 1
    return bins


def render_report(rows: list[dict[str, str]], records: list[dict[str, str]], diffs: list[dict[str, str]]) -> str:
    lines = [
        "Candidate sets from the label maps (llm, fallback, parent subcategory).",
        "Winner rules were not used. Labels were not written.",
        f"clips {len(rows)}",
        f"label differences after replay {len(diffs)}",
    ]
    if diffs:
        lines.append("replay does not match the current labels; candidates were not written")
        for item in diffs[:20]:
            lines.append(
                f"  {item['source']} {item['filename']}: "
                f"{item['Category']}||{item['SubCategory']} vs "
                f"{item['replay_category']}||{item['replay_subcategory']}"
            )
        return "\n".join(lines) + "\n"

    by_source: dict[str, list[dict[str, str]]] = {}
    for record in records:
        by_source.setdefault(record["source"], []).append(record)
    lines.append("given_pair_in_candidates")
    for source in sorted(by_source):
        group = by_source[source]
        hits = sum(record["given_pair_in_candidates"] == "True" for record in group)
        lines.append(f"  {source} {hits}/{len(group)} ({hits / len(group):.3f})")
    hits = sum(record["given_pair_in_candidates"] == "True" for record in records)
    lines.append(f"  all {hits}/{len(records)} ({hits / len(records):.3f})")

    lines.append("given_category_in_candidates")
    for source in sorted(by_source):
        group = by_source[source]
        hits = sum(record["given_category_in_candidates"] == "True" for record in group)
        lines.append(f"  {source} {hits}/{len(group)} ({hits / len(group):.3f})")

    labels = {
        (row.get("source") or "", row.get("filename") or ""): row
        for row in rows
    }
    mismatches = [record for record in records if record["given_pair_in_candidates"] == "False"]
    lines.append(f"given pair missing from candidates {len(mismatches)}")
    pair_counts: Counter[tuple[str, str]] = Counter()
    for record in mismatches:
        row = labels[(record["source"], record["filename"])]
        given = pair_key(row.get("Category") or "", row.get("SubCategory") or "")
        pair_counts[(given, record["candidate_pairs"])] += 1
    for (given, pairs), count in sorted(pair_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {count} {given} | {pairs}")

    lines.append("distinct candidate categories per clip")
    bins = category_bins(records)
    for source in sorted(source_name for source_name in bins if source_name != "all"):
        counts = bins[source]
        lines.append(
            f"  {source} 0={counts['0']} 1={counts['1']} 2={counts['2']} 3+={counts['3+']}"
        )
    counts = bins["all"]
    lines.append(f"  all 0={counts['0']} 1={counts['1']} 2={counts['2']} 3+={counts['3+']}")
    lines.append(f"clips with no candidate {counts['0']}")
    for source in sorted(by_source):
        lines.append(f"  {source} {bins[source]['0']}")
    return "\n".join(lines) + "\n"


def mismatch_rows(rows: list[dict[str, str]], records: list[dict[str, str]]) -> list[dict[str, str]]:
    labels = {(row.get("source") or "", row.get("filename") or ""): row for row in rows}
    found = []
    for record in records:
        if record["given_pair_in_candidates"] == "True":
            continue
        row = labels[(record["source"], record["filename"])]
        found.append(
            {
                "source": record["source"],
                "filename": record["filename"],
                "Category": row.get("Category") or "",
                "SubCategory": row.get("SubCategory") or "",
                "candidates": record["candidates"],
            }
        )
    return found


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write UCS candidate sets for every clip.")
    parser.add_argument("--clips", type=Path, default=DEFAULT_CLIPS, help="CSV with the current labels")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="directory for candidates.csv")
    args = parser.parse_args(argv)

    clips_path = args.clips if args.clips.is_absolute() else ROOT / args.clips
    output = args.output if args.output.is_absolute() else ROOT / args.output
    fieldnames, rows = read_csv(clips_path)
    require_columns(clips_path, fieldnames, CLIP_COLUMNS)
    keys = [(row.get("source") or "", row.get("filename") or "") for row in rows]
    if len(keys) != len(set(keys)):
        raise SystemExit(f"{clips_path} repeats a source and filename")

    tables = load_tables()
    diffs = label_differences(rows, tables)
    output.mkdir(parents=True, exist_ok=True)
    if diffs:
        report = render_report(rows, [], diffs)
        (output / "candidates_report.txt").write_text(report, encoding="utf-8")
        print(report, end="")
        write_csv(
            output / "label_differences.csv",
            [
                "source",
                "filename",
                "Category",
                "SubCategory",
                "replay_category",
                "replay_subcategory",
                "Keywords",
            ],
            diffs,
        )
        raise SystemExit(f"{len(diffs)} label differences; candidates were not written")

    records = candidate_records(rows, tables.effective, tables.parent_subs)
    report = render_report(rows, records, diffs)
    (output / "candidates_report.txt").write_text(report, encoding="utf-8")
    print(report, end="")
    write_csv(output / "candidates.csv", CANDIDATE_COLUMNS, records)
    write_csv(
        output / "candidates_mismatch.csv",
        ["source", "filename", "Category", "SubCategory", "candidates"],
        mismatch_rows(rows, records),
    )


if __name__ == "__main__":
    main()
