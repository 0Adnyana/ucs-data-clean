"""Bucket cross-labelling flags by whether a tag already names the suggestion.

The flag rule is unchanged: a class threshold is the mean probability of that
label on clips that carry it. A clip is flagged when the most probable class
above its own threshold is not the given label and beats the given label's
probability. Outside the top 5, that probability is the rank-5 confidence.

``bucket_all`` treats every tag as support. ``bucket_strict`` does not treat a
generic tag as support while the clip has another candidate. Sorting and the
listening sample use ``bucket_strict``.

Suggestions of OBJECTS||WHEELED are listed apart from other unsupported flags.
That pair was trained on rock clips whose tag Roll was mapped to a rolling object.

Usage:
  python 5-fold-cross-labeling/scripts/cross_label_flags.py \\
    --round-dir "/path/to/round 1" --candidates 5-fold-cross-labeling/candidates/candidates.csv
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidates import (  # noqa: E402
    WHEELED,
    bucket_flags,
    class_thresholds,
    decide_flag,
    draw_sample,
    pair_key,
    parse_candidate_tags,
    read_csv,
    require_columns,
    write_csv,
)

DEFAULT_CANDIDATES = ROOT / "5-fold-cross-labeling" / "candidates" / "candidates.csv"
DEFAULT_OUTPUT = ROOT / "5-fold-cross-labeling" / "candidates"
PILES = ("A", "B", "C", "D", "E")
FLAG_TYPES = ("cross_category", "within_category", "within_category_misc")
BUCKETS = ("tag_supported", "unsupported")
CLIP_COLUMNS = ("source", "filename", "Category", "SubCategory", "Keywords")
QUEUE_COLUMNS = [
    "source",
    "filename",
    "path",
    "recording",
    "pile",
    "Category",
    "SubCategory",
    "Keywords",
    "suggested",
    "margin",
    "flag",
    "flag_type",
    "bucket_all",
    "bucket_strict",
    "support_level",
    "supporting_tags",
]
SUMMARY_COLUMNS = ["which", "source", "flag_type", "bucket", "count"]
PAIR_COLUMNS = ["given_label", "suggested_label", "supporting_tag", "count"]
SAMPLE_COLUMNS = [
    "source",
    "filename",
    "path",
    "Category",
    "SubCategory",
    "Keywords",
    "suggested",
    "margin",
    "flag_type",
    "bucket_strict",
    "support_level",
    "supporting_tags",
    "label_wrong",
    "predominant_is",
    "human_category",
    "human_subcategory",
    "notes",
]


def prediction_columns() -> tuple[str, ...]:
    names = []
    for index in range(1, 6):
        names.append(f"model_prediction_{index}_category")
        names.append(f"model_prediction_{index}_subcategory")
        names.append(f"model_confidence_{index}")
    return tuple(names)


def verbose_paths(round_dir: Path | None, given: list[Path]) -> list[Path]:
    paths = []
    if round_dir is not None:
        directory = round_dir if round_dir.is_absolute() else ROOT / round_dir
        for pile in PILES:
            paths.append(directory / pile / "pair" / "verbose_test.csv")
    for path in given:
        paths.append(path if path.is_absolute() else ROOT / path)
    if not paths:
        raise SystemExit("pass --round-dir or at least one --verbose file")
    return paths


def load_verbose(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: dict[tuple[str, str], Path] = {}
    required = CLIP_COLUMNS + prediction_columns()
    for path in paths:
        fieldnames, file_rows = read_csv(path)
        require_columns(path, fieldnames, required)
        for row in file_rows:
            key = ((row.get("source") or "").strip(), (row.get("filename") or "").strip())
            previous = seen.get(key)
            if previous is not None:
                raise SystemExit(
                    f"{path} repeats source={key[0]} filename={key[1]}, already read from {previous}"
                )
            seen[key] = path
            for index in range(1, 6):
                category = (row.get(f"model_prediction_{index}_category") or "").strip()
                raw = (row.get(f"model_confidence_{index}") or "").strip()
                if not category or not raw:
                    raise SystemExit(
                        f"{path} is missing prediction {index} for source={key[0]} filename={key[1]}. "
                        f"columns found: {', '.join(fieldnames)}"
                    )
                try:
                    float(raw)
                except ValueError:
                    raise SystemExit(
                        f"{path} has a non-numeric model_confidence_{index} "
                        f"for source={key[0]} filename={key[1]}: {raw!r}"
                    ) from None
            rows.append(row)
    return rows


def load_candidate_index(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    fieldnames, rows = read_csv(path)
    require_columns(path, fieldnames, ("source", "filename", "candidates", "candidate_pairs"))
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = ((row.get("source") or "").strip(), (row.get("filename") or "").strip())
        if key in index:
            raise SystemExit(f"{path} repeats source={key[0]} filename={key[1]}")
        index[key] = row
    return index


def queue_rows(
    clips: list[dict[str, str]],
    candidates: dict[tuple[str, str], dict[str, str]],
    candidate_path: Path,
) -> list[dict[str, str]]:
    missing = []
    for clip in clips:
        key = ((clip.get("source") or "").strip(), (clip.get("filename") or "").strip())
        if key not in candidates:
            missing.append(key)
    if missing:
        source, filename = missing[0]
        found = ", ".join(candidates[next(iter(candidates))].keys()) if candidates else "(empty)"
        raise SystemExit(
            f"{candidate_path} has no row for source={source} filename={filename} "
            f"({len(missing)} clips did not match). columns found: {found}"
        )

    thresholds = class_thresholds(clips)
    queued = []
    for clip in clips:
        decision = decide_flag(clip, thresholds)
        if decision is None:
            continue
        key = ((clip.get("source") or "").strip(), (clip.get("filename") or "").strip())
        record = candidates[key]
        try:
            tag_pairs = parse_candidate_tags(record.get("candidates") or "")
        except ValueError as exc:
            raise SystemExit(
                f"{candidate_path} has a candidate without '>' for "
                f"source={key[0]} filename={key[1]}: {exc}"
            ) from None
        buckets = bucket_flags(tag_pairs, decision["suggested"])
        queued.append(
            {
                "source": key[0],
                "filename": key[1],
                "path": clip.get("path") or "",
                "recording": clip.get("recording") or "",
                "pile": clip.get("pile") or "",
                "Category": (clip.get("Category") or "").strip(),
                "SubCategory": (clip.get("SubCategory") or "").strip(),
                "Keywords": clip.get("Keywords") or "",
                "suggested": decision["suggested"],
                "margin": decision["margin"],
                "flag": decision["flag"],
                "flag_type": decision["flag_type"],
                "bucket_all": buckets["bucket_all"],
                "bucket_strict": buckets["bucket_strict"],
                "support_level": buckets["support_level"],
                "supporting_tags": buckets["supporting_tags"],
            }
        )
    queued.sort(
        key=lambda row: (
            0 if row["bucket_strict"] == "tag_supported" else 1,
            -float(row["margin"]),
            row["source"],
            row["filename"],
        )
    )
    return queued


def summary_table(clips: list[dict[str, str]], queued: list[dict[str, str]]) -> list[dict[str, str]]:
    sources = sorted({(clip.get("source") or "").strip() for clip in clips})
    rows = []
    for which in ("bucket_all", "bucket_strict"):
        counts = Counter((row["source"], row["flag_type"], row[which]) for row in queued)
        for source in sources:
            for flag_type in FLAG_TYPES:
                for bucket in BUCKETS:
                    rows.append(
                        {
                            "which": which,
                            "source": source,
                            "flag_type": flag_type,
                            "bucket": bucket,
                            "count": str(counts[(source, flag_type, bucket)]),
                        }
                    )
    return rows


def supported_pair_rows(queued: list[dict[str, str]]) -> list[dict[str, str]]:
    """Strict support only. Generic side tags are already out of that bucket."""
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in queued:
        if row["bucket_strict"] != "tag_supported":
            continue
        given = pair_key(row["Category"], row["SubCategory"])
        for tag in row["supporting_tags"].split("|"):
            if tag:
                counts[(given, row["suggested"], tag)] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "given_label": given,
            "suggested_label": suggested,
            "supporting_tag": tag,
            "count": str(count),
        }
        for (given, suggested, tag), count in ordered
    ]


def sample_rows(queued: list[dict[str, str]], total: int, seed: int) -> list[dict[str, str]]:
    drawn = draw_sample(queued, total=total, minimum=5, seed=seed)
    samples = []
    for row in drawn:
        sample = {column: row.get(column, "") for column in SAMPLE_COLUMNS}
        for column in ("label_wrong", "predominant_is", "human_category", "human_subcategory", "notes"):
            sample[column] = ""
        samples.append(sample)
    return samples


def render_summary(
    clips: list[dict[str, str]],
    queued: list[dict[str, str]],
    table: list[dict[str, str]],
    pairs: list[dict[str, str]],
    samples: list[dict[str, str]],
    seed: int,
) -> str:
    lines = [
        f"scored clips {len(clips)}",
        f"flagged {len(queued)} ({len(queued) / len(clips):.3f})" if clips else "flagged 0",
        "threshold: mean probability of the given label on clips with that label",
        "a flag's top class is above its own threshold and beats the given label",
        "bucket_strict ignores generic-only support when the clip has another candidate",
        "supported_pairs counts bucket_strict = tag_supported, one row per supporting tag",
        f"precision sample {len(samples)} clips, seed {seed}",
    ]
    lines.append("bucket summary")
    for row in table:
        lines.append(
            f"  {row['which']} {row['source']} {row['flag_type']} {row['bucket']} {row['count']}"
        )
    wheeled_given = [
        clip
        for clip in clips
        if pair_key(clip.get("Category") or "", clip.get("SubCategory") or "") == WHEELED
    ]
    wheeled_flags = [row for row in queued if row["suggested"] == WHEELED]
    other_unsupported = [
        row for row in queued if row["bucket_strict"] == "unsupported" and row["suggested"] != WHEELED
    ]
    lines.append(f"given label {WHEELED} {len(wheeled_given)}")
    given_sources = Counter((clip.get("source") or "").strip() for clip in wheeled_given)
    for source in sorted(given_sources):
        lines.append(f"  {source} {given_sources[source]}")
    flagged_given = [
        row for row in queued if pair_key(row["Category"], row["SubCategory"]) == WHEELED
    ]
    lines.append(f"flagged with given label {WHEELED} {len(flagged_given)}")
    suggestion_buckets = Counter(row["bucket_strict"] for row in wheeled_flags)
    lines.append(f"suggestion {WHEELED} {len(wheeled_flags)}")
    lines.append(
        f"  tag_supported {suggestion_buckets['tag_supported']} "
        "(a tag on the clip maps to this pair)"
    )
    lines.append(
        f"  unsupported {suggestion_buckets['unsupported']} "
        "(contaminated class; not counted as model error)"
    )
    strict_unsupported = sum(row["bucket_strict"] == "unsupported" for row in queued)
    lines.append(f"bucket_strict unsupported {strict_unsupported}")
    lines.append(f"bucket_strict unsupported excluding {WHEELED} suggestions {len(other_unsupported)}")
    lines.append(f"supported pair rows {len(pairs)}")
    for row in pairs[:30]:
        lines.append(
            f"  {row['count']} {row['given_label']} -> {row['suggested_label']} via {row['supporting_tag']}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Flag cross-labelling clips and bucket them by tag support.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--round-dir", type=Path, help="round folder with A/pair/verbose_test.csv through E")
    parser.add_argument("--verbose", type=Path, nargs="*", default=[], help="verbose_test.csv files")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    candidate_path = args.candidates if args.candidates.is_absolute() else ROOT / args.candidates
    output = args.output if args.output.is_absolute() else ROOT / args.output
    clips = load_verbose(verbose_paths(args.round_dir, args.verbose))
    candidates = load_candidate_index(candidate_path)
    queued = queue_rows(clips, candidates, candidate_path)
    table = summary_table(clips, queued)
    pairs = supported_pair_rows(queued)
    samples = sample_rows(queued, args.sample_size, args.seed)
    text = render_summary(clips, queued, table, pairs, samples, args.seed)

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "review_queue.csv", QUEUE_COLUMNS, queued)
    write_csv(output / "bucket_summary.csv", SUMMARY_COLUMNS, table)
    write_csv(output / "supported_pairs.csv", PAIR_COLUMNS, pairs)
    write_csv(output / "precision_sample.csv", SAMPLE_COLUMNS, samples)
    (output / "summary.txt").write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
