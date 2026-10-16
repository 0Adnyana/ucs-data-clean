# Usage

Paths are resolved from the repo root, so the working directory does not matter. The flags at the end cover the variants of each command.

## Score a manifest

```bash
python scripts/score_ucs.py manifests/slice/envsound_val.csv -o predictions.csv
```

Prints the [report](scoring.md#report). `-o` writes the same CSV plus `pred_category`, `pred_subcategory`, `pred_score`, `pred_status`, and `pred_evidence`. `Category` and `SubCategory` on that copy stay as they were.

Without `--no-audio`, the audio folder refreshes `Keywords` and the FSD50K metadata before scoring. A file that only has `filename`, `source`, and `path` can be scored the same way. Pass `--config` to use a file other than `configs/default.json`.

## Probe one keyword list

```bash
python scripts/score_ucs.py --keywords "Meow,Cat,Animal"
```

Prints the decision and the top candidates (`--top`, default 8). `--category` breaks a tie.

## List candidates for hand tagging

```bash
python scripts/score_ucs.py manifests/slice/envsound_train.csv -o candidates_train.csv --candidates --config configs/default-open.json
```

`--candidates` writes the same CSV as `-o` above, plus `cand_count` and, for each of the `--top` best subcategories (default 10), `cand_<n>_category`, `cand_<n>_subcategory`, `cand_<n>_score`, and `cand_<n>_conf`. `conf` is that score's share of the total over every subcategory the row matched. `--evidence` adds `cand_<n>_evidence`, the tags that produced the points. The config's taxonomy limits which pairs can be listed. The default config is the closed list. `--keywords --candidates` prints the list for one probe. The run also reports how often the existing SubCategory is among the candidates.

```bash
python scripts/score_ucs.py --experiment configs/open-weighted-min075.json --candidates --manifest-dir manifests/original-envsound
```

`--experiment`, `--write-splits`, `--manifest-dir`, and `--output-dir` work as in [Run an experiment](#run-an-experiment). The CSVs are the experiment files with the `pred_*` and `cand_*` columns added, and `report.txt` includes the candidate coverage. The default folder is `experiments/<name>-candidates/`. `--output-dir` is used as given.

## Run an experiment

```bash
python scripts/score_ucs.py --experiment configs/default-open.json
```

Writes a fresh manifest set under `experiments/<name>/`. `manifests/slice/` stays unchanged. Repeat `--experiment` for several configs. `--output-dir` changes the destination. A config may set `"output_dir"` itself.

`Category` and `SubCategory` in the experiment CSV are the scorer’s assignment. A blank prediction writes both fields empty. `config.json` is the resolved setup, including any closed pair the workbook does not contain. `report.txt` is the agreement report, one section per split.

By default an experiment scores test only. Train and val are copied from `manifests/slice/`. A config that lists those splits, or `--write-splits train,val,test`, scores them into the same folder. A split left off the list is still copied in.

## Check the scorer

```bash
python -m unittest discover -s scripts/tests
```

Runs the tests in `scripts/tests/`. The scoring tests load the full UCS list and the AudioSet ontology from `references/`.

## Flags

| Flag | Use |
| --- | --- |
| `-o`, `--output` | CSV with `pred_*` columns. `--candidates` also adds `cand_*`. |
| `--config` | JSON config for one manifest. Weights, cutoff, ties, and taxonomy live in that file. |
| `--no-audio` | Score the columns already on the CSV. |
| `--keywords`, `--category`, `--top` | One-off probe. `--top` defaults to 8, or 10 with `--candidates`. |
| `--candidates`, `--evidence` | Ranked subcategories in the CSV. `--evidence` adds the reason for each one. |
| `--experiment`, `--write-splits`, `--manifest-dir`, `--output-dir` | Write `experiments/<name>/`. |
