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

Prints the decision and the top candidates (`--top`, default 8). `--category` breaks a tie. `--pp`, `--uploader-tags`, `--title`, and `--description` are the FSD50K fields for that probe.

## Rebuild manifests

```bash
python scripts/score_ucs.py --make-manifests
```

Writes `manifests/slice/envsound_test.csv` only. Train and val stay as they are, so hand tags are not replaced. `--write-splits train,val,test`, or `"splits"` in the config, adds those files back.

Membership is the `filename`, `source`, and `path` already on the slice file. Keywords and FSD50K metadata come from `audio/`. `exists` is whether `audio/<path>` is a file. `--source-dir` defaults to `manifests/original-envsound/`. When `envsound_<split>.csv` exists there, `Category` and `SubCategory` are copied from it.

## Run an experiment

```bash
python scripts/score_ucs.py --experiment configs/default-open.json
```

Writes a fresh manifest set under `experiments/<name>/`. `manifests/slice/` stays unchanged. Repeat `--experiment` for several configs. `--experiment-dir configs` runs every JSON file in that directory except `configs/default.json`. `--experiment-name` builds one experiment from flags, or renames a single `--experiment` file. `--output-dir` changes the destination. A config may set `"output_dir"` itself.

`Category` and `SubCategory` in the experiment CSV are the scorer’s assignment. A blank prediction writes both fields empty. `config.json` is the resolved setup, including any closed pair the workbook does not contain. `report.txt` is the agreement report, one section per split.

By default an experiment scores test only. Train and val are copied from `manifests/slice/`. A config that lists those splits, or `--write-splits train,val,test`, scores them into the same folder. A split left off the list is still copied in.

## Check the scorer

```bash
python scripts/score_ucs.py --self-test
```

Checks the scorer against the full UCS list and prints the subcategory count.

## Flags

| Flag | Use |
| --- | --- |
| `-o`, `--output` | CSV with `pred_*` columns. |
| `--config` | JSON config for a manifest score, a rebuild, or `--experiment-name`. |
| `--no-audio` | Score the columns already on the CSV. |
| `--audio`, `--ucs`, `--ontology` | Dataset root, UCS workbook, AudioSet ontology. |
| `--min-score`, `--on-tie` | Cutoff and tie handling. |
| `--set NAME=VALUE` | Override one weight or `min_score`. Repeatable. |
| `--taxonomy` | `open`, `closed`, `categories`, or `pairs`. |
| `--categories`, `--pairs` | Label lists for those taxonomy modes. |
| `--closed-slice` | Same as `--taxonomy closed`. |
| `--keywords` and `--category`, `--pp`, `--uploader-tags`, `--title`, `--description`, `--top` | One-off probe. |
| `--make-manifests`, `--write-splits`, `--source-dir`, `--manifest-dir` | Rebuild slice CSVs. |
| `--experiment`, `--experiment-dir`, `--experiment-name`, `--output-dir` | Write `experiments/<name>/`. |
| `--self-test` | Check the scorer and print the subcategory count. |
