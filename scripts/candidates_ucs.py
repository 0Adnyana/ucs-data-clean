"""List the top UCS candidates for each clip, for tagging by hand.

``score_ucs.py`` keeps one Category/SubCategory per row and leaves a row
blank on a tie or a weak match. This script scores the same tags the same
way (``score_text``, the same config and weights), but it writes the
``--top`` best subcategories for every row (10 by default), each with its
score, so a person can pick the right one.

Each candidate gets four columns, numbered from 1:

  cand_<n>_category, cand_<n>_subcategory   the UCS pair
  cand_<n>_score                            raw points, same scale as ``pred_score``
  cand_<n>_conf                             that score divided by the sum of
                                            every matched subcategory's score
                                            for the row (0 to 1)

``--evidence`` adds ``cand_<n>_evidence``, the tags that produced the points.
A row with fewer matches than ``--top`` leaves the remaining cells empty.
The ``pred_*`` columns from ``score_ucs.py`` are written too, so the single
decision sits beside the list. The run prints the ``score_ucs.py`` report
plus how often the existing SubCategory is among the candidates.

A single manifest (``-o``) keeps ``Category`` and ``SubCategory`` as they
were. ``--experiment``, ``--experiment-dir``, and ``--experiment-name``
work as in ``score_ucs.py``: every split the config lists is scored, the
rest are copied from ``manifests/slice/``, and ``config.json`` and
``report.txt`` are written. As there, ``Category`` and ``SubCategory`` in
those CSVs are the scorer's assignment. The folder is
``experiments/<name>-candidates/`` so the ``score_ucs.py`` output of the
same config is not replaced. A config's own ``output_dir`` gets the same
``-candidates`` suffix. ``--output-dir`` is used as given.

The taxonomy in the config decides which subcategories can be listed. A
closed or pairs taxonomy only lists those pairs.

Usage:
  python scripts/candidates_ucs.py --experiment configs/open-weighted-min075.json --evidence
  python scripts/candidates_ucs.py --experiment configs/open-weighted-min075.json --output-dir experiments/my-tags
  python scripts/candidates_ucs.py manifests/slice/envsound_test.csv -o candidates_test.csv
  python scripts/candidates_ucs.py manifests/slice/envsound_train.csv -o candidates_train.csv --top 15 --evidence
  python scripts/candidates_ucs.py --keywords "Meow,Cat,Animal"
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from score_ucs import (
    DEFAULT_AUDIO,
    DEFAULT_MANIFESTS,
    DEFAULT_ONTOLOGY,
    DEFAULT_UCS,
    META_COLUMNS,
    SplitWriter,
    TAXONOMY_MODES,
    Catalog,
    ExperimentConfig,
    Prediction,
    _optional,
    apply_audio,
    apply_cli,
    build_catalog,
    catalog_for,
    check_experiment_name,
    collect_experiments,
    default_config,
    format_scoring,
    labeled_rows,
    load_audio_index,
    load_config_file,
    load_manifest,
    load_ontology,
    load_ucs,
    matched_phrase,
    missing_pairs_message,
    report,
    run_experiments,
    score_manifest,
    score_text,
)

DEFAULT_TOP = 10
PRED_COLUMNS = ["pred_category", "pred_subcategory", "pred_score", "pred_status", "pred_evidence"]


@dataclass(frozen=True)
class Candidate:
    category: str
    subcategory: str
    score: float
    conf: float
    evidence: str


def candidates_for(
    catalog: Catalog,
    keywords: str,
    *,
    config: ExperimentConfig,
    top: int,
    category: str = "",
    pp_labels: str = "",
    uploader_tags: str = "",
    title: str = "",
    description: str = "",
) -> tuple[Prediction, list[Candidate]]:
    """The single decision and the ``top`` best subcategories for one tag list."""
    prediction = score_text(
        catalog,
        keywords,
        category=category,
        pp_labels=pp_labels,
        uploader_tags=uploader_tags,
        title=title,
        description=description,
        min_score=config.min_score,
        weights=config.weights,
        on_tie=config.on_tie,
        # Every matched subcategory, so ``conf`` is a share of the whole row.
        keep_ranked=len(catalog.entries),
    )
    ranked = [item for item in prediction.ranked if item[2] > 0]
    total = sum(score for _category, _subcategory, score, _evidence in ranked)
    candidates = [
        Candidate(category_name, subcategory, score, score / total if total else 0.0, evidence)
        for category_name, subcategory, score, evidence in ranked[:top]
    ]
    prediction.ranked = []
    return prediction, candidates


def row_candidates(
    catalog: Catalog, rows: list[dict[str, str]], *, config: ExperimentConfig, top: int
) -> list[list[Candidate]]:
    return [
        candidates_for(
            catalog,
            row.get("Keywords") or "",
            config=config,
            top=top,
            category=row.get("Category") or "",
            pp_labels=_optional(row, "pp_labels", "pp"),
            uploader_tags=_optional(row, "uploader_tags", "tags"),
            title=_optional(row, "title"),
            description=_optional(row, "description"),
        )[1]
        for row in rows
    ]


def candidate_config(config: ExperimentConfig) -> ExperimentConfig:
    """Rename an experiment so its folder sits beside the score_ucs.py one."""
    name = check_experiment_name(f"{config.name}-candidates")
    output_dir = config.output_dir
    if output_dir is not None:
        output_dir = output_dir.with_name(f"{output_dir.name}-candidates")
    return replace(config, name=name, output_dir=output_dir)


def split_writer(top: int, evidence: bool) -> SplitWriter:
    """Write one experiment split: the score_ucs.py CSV plus pred_* and cand_* columns."""

    def write(
        destination: Path,
        fieldnames: list[str],
        rows: list[dict[str, str]],
        predictions: list[Prediction],
        catalog: Catalog,
        config: ExperimentConfig,
    ) -> str:
        results = list(zip(predictions, row_candidates(catalog, rows, config=config, top=top)))
        write_candidates(
            destination, fieldnames, labeled_rows(rows, predictions), results, top=top, evidence=evidence
        )
        return coverage(rows, results, top)

    return write


def candidate_columns(top: int, evidence: bool) -> list[str]:
    columns: list[str] = []
    for n in range(1, top + 1):
        columns += [f"cand_{n}_category", f"cand_{n}_subcategory", f"cand_{n}_score", f"cand_{n}_conf"]
        if evidence:
            columns.append(f"cand_{n}_evidence")
    return columns


def write_candidates(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    results: list[tuple[Prediction, list[Candidate]]],
    *,
    top: int,
    evidence: bool,
) -> None:
    columns = list(fieldnames)
    for name in PRED_COLUMNS + ["cand_count"] + candidate_columns(top, evidence):
        if name not in columns:
            columns.append(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row, (prediction, candidates) in zip(rows, results):
            out = dict(row)
            out["pred_category"] = prediction.category
            out["pred_subcategory"] = prediction.subcategory
            out["pred_score"] = f"{prediction.score:.2f}"
            out["pred_status"] = prediction.status
            out["pred_evidence"] = prediction.evidence
            out["cand_count"] = str(len(candidates))
            for n, candidate in enumerate(candidates, start=1):
                out[f"cand_{n}_category"] = candidate.category
                out[f"cand_{n}_subcategory"] = candidate.subcategory
                out[f"cand_{n}_score"] = f"{candidate.score:.2f}"
                out[f"cand_{n}_conf"] = f"{candidate.conf:.3f}"
                if evidence:
                    out[f"cand_{n}_evidence"] = candidate.evidence
            writer.writerow(out)


def coverage(rows: list[dict[str, str]], results: list[tuple[Prediction, list[Candidate]]], top: int) -> str:
    """How often the row's existing Category/SubCategory is among the candidates."""
    total = 0
    found = 0
    first = 0
    category_total = 0
    category_found = 0
    empty = 0
    for row, (_prediction, candidates) in zip(rows, results):
        if not candidates:
            empty += 1
        gold_cat = (row.get("Category") or "").strip()
        gold_sub = (row.get("SubCategory") or "").strip()
        if gold_cat:
            category_total += 1
            if any(candidate.category == gold_cat for candidate in candidates):
                category_found += 1
        if not gold_cat or not gold_sub:
            continue
        total += 1
        pairs = [(candidate.category, candidate.subcategory) for candidate in candidates]
        if (gold_cat, gold_sub) in pairs:
            found += 1
            if pairs[0] == (gold_cat, gold_sub):
                first += 1

    def share(part: int, whole: int) -> str:
        return f"{part}/{whole} ({100 * part / whole:.1f}%)" if whole else "0"

    return "\n".join(
        [
            f"rows with no candidate {empty}/{len(rows)}",
            f"gold category among top {top} {share(category_found, category_total)}",
            f"gold category/subcategory among top {top} {share(found, total)}",
            f"gold category/subcategory ranked first {share(first, total)}",
        ]
    )


def explain(prediction: Prediction, candidates: list[Candidate]) -> str:
    lines = [
        f"{prediction.status}  {prediction.category} / {prediction.subcategory}  {prediction.score:.2f}".rstrip(),
        prediction.evidence,
        "",
    ]
    for n, candidate in enumerate(candidates, start=1):
        lines.append(
            f"{n:3d}  {candidate.score:7.2f}  {candidate.conf:6.3f}  {candidate.category} / {candidate.subcategory}"
        )
        if candidate.evidence:
            lines.append(f"                        {candidate.evidence}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List the top UCS candidates per clip for hand tagging.")
    parser.add_argument("manifest", nargs="?", type=Path, help="envsound CSV to score")
    parser.add_argument("-o", "--output", type=Path, help="CSV with pred_* and cand_* columns added")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"candidates per row (default: {DEFAULT_TOP})")
    parser.add_argument("--evidence", action="store_true", help="add cand_<n>_evidence columns")
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO, help="dataset root containing AudioSet, ESC-50, and FSD50K")
    parser.add_argument("--no-audio", action="store_true", help="score the CSV columns only, without the audio-folder label files")
    parser.add_argument("--ucs", type=Path, default=DEFAULT_UCS)
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument("--config", type=Path, help="JSON scoring config (default: configs/default.json)")
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help=f"cutoff for the pred_* decision (default: {default_config().min_score:g}). Candidates are listed regardless",
    )
    parser.add_argument("--closed-slice", action="store_true", help="same as --taxonomy closed")
    parser.add_argument("--taxonomy", choices=TAXONOMY_MODES, help="open, closed, categories, or pairs")
    parser.add_argument("--categories", help="comma-separated UCS categories for --taxonomy categories")
    parser.add_argument("--pairs", dest="pair_list", help="comma-separated CATEGORY/SUBCATEGORY pairs for --taxonomy pairs")
    parser.add_argument("--on-tie", choices=("blank", "first"), help="tie handling for the pred_* decision")
    parser.add_argument("--set", action="append", default=None, metavar="NAME=VALUE", help="override one weight or min_score")
    parser.add_argument("--keywords", help="score one keyword list and print the candidates")
    parser.add_argument("--category", default="", help="existing Category, used only to break a tie")
    parser.add_argument("--pp", default="", help="predominant labels, comma-separated like Keywords")
    parser.add_argument("--uploader-tags", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--description", default="")
    parser.add_argument(
        "--experiment",
        action="append",
        type=Path,
        default=None,
        help="JSON config to run like score_ucs.py --experiment. Repeat to run several. Writes experiments/<name>-candidates/",
    )
    parser.add_argument("--experiment-dir", type=Path, help="run every JSON config in this directory except configs/default.json")
    parser.add_argument("--experiment-name", help="name for an experiment built from flags, or rename a single --experiment file")
    parser.add_argument("--output-dir", type=Path, help="folder for experiment manifests. A batch writes one subfolder per name")
    parser.add_argument("--write-splits", help="splits to score, comma-separated, for example train,val,test. Default is the config's list")
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=DEFAULT_MANIFESTS,
        help="slice manifests (manifests/slice). Experiments read from here and never write here",
    )
    args = parser.parse_args(argv)

    if args.top < 1:
        raise SystemExit("--top must be at least 1")
    experiment_mode = bool(args.experiment or args.experiment_dir or args.experiment_name)
    if not experiment_mode and (args.output_dir is not None or args.write_splits is not None):
        raise SystemExit("--output-dir and --write-splits apply to --experiment")
    if experiment_mode:
        if args.manifest is not None or args.keywords is not None:
            raise SystemExit("pass an experiment or a manifest to score, not both")
        configs = [candidate_config(config) for config in collect_experiments(args)]
        run_experiments(
            configs,
            ucs_path=args.ucs,
            ontology_path=args.ontology,
            manifest_dir=args.manifest_dir,
            audio_dir=args.audio,
            no_audio=args.no_audio,
            output_dir=args.output_dir,
            write_split=split_writer(args.top, args.evidence),
        )
        return 0
    if args.keywords is None and args.manifest is None:
        parser.print_help()
        return 2
    if args.manifest is not None and args.output is None:
        raise SystemExit("pass -o for the candidates CSV")
    if not args.ucs.is_file():
        raise SystemExit(f"UCS list not found: {args.ucs}")
    if not args.ontology.is_file():
        raise SystemExit(f"AudioSet ontology not found: {args.ontology}")

    base = load_config_file(args.config) if args.config else default_config()
    config = apply_cli(base, args)
    depths, alias = load_ontology(args.ontology)
    records = load_ucs(args.ucs, None)
    catalog, _resolved, skipped, borrowed = catalog_for(config, records, depths, alias)
    print(format_scoring(config, len(catalog.entries)))
    print(f"top {args.top} candidates per row")
    if borrowed:
        print("borrowed: " + "; ".join(borrowed))
    if skipped:
        print("warning: " + missing_pairs_message(skipped) + " (not scored)")

    if args.keywords is not None:
        prediction, candidates = candidates_for(
            catalog,
            args.keywords,
            config=config,
            top=args.top,
            category=args.category,
            pp_labels=args.pp,
            uploader_tags=args.uploader_tags,
            title=args.title,
            description=args.description,
        )
        print(explain(prediction, candidates))
        return 0

    fieldnames, rows = load_manifest(args.manifest)
    is_split = "Keywords" not in fieldnames and {"filename", "source", "path"} <= set(fieldnames)
    if is_split and args.no_audio:
        raise SystemExit(
            f"{args.manifest} has no Keywords column. Drop --no-audio so labels are read from the audio folder."
        )
    if not args.no_audio:
        if not args.audio.is_dir():
            raise SystemExit(f"audio folder not found: {args.audio}")
        counts = apply_audio(rows, load_audio_index(args.audio))
        if is_split and counts["missing"]:
            raise SystemExit(f"{counts['missing']} split rows have no label file under {args.audio}")
        for name in META_COLUMNS:
            if name not in fieldnames:
                fieldnames.append(name)
        print(f"audio folder {matched_phrase(counts)}")

    lists = row_candidates(catalog, rows, config=config, top=args.top)
    background = None if config.taxonomy == "open" else build_catalog(records, depths, alias)
    decisions = score_manifest(
        catalog,
        rows,
        min_score=config.min_score,
        weights=config.weights,
        on_tie=config.on_tie,
        background=background,
        allowed_pairs=None if background is None else {(entry.category, entry.subcategory) for entry in catalog.entries},
    )
    results = list(zip(decisions, lists))
    print(report(rows, [prediction for prediction, _candidates in results]))
    print(coverage(rows, results, args.top))
    write_candidates(args.output, fieldnames, rows, results, top=args.top, evidence=args.evidence)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
