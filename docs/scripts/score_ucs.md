# score_ucs

## Name

`score_ucs` — score keywords against the UCS list

## Synopsis

```
python scripts/score_ucs.py manifest [-o output [--candidates [--evidence] [--top n]]] [--no-audio] [--config file]
python scripts/score_ucs.py --keywords list [--category name] [--candidates] [--top n] [--config file]
python scripts/score_ucs.py --experiment file [--experiment file]... [--write-splits list] [--manifest-dir dir] [--output-dir dir] [--no-audio] [--candidates [--evidence] [--top n]]
```

## Description

Scores each row's keywords against the UCS subcategories a config allows and prints the agreement report. See [Scoring](scoring.md) for the method and [Configs](configs.md) for the settings. A manifest run writes a scored copy only with `-o` and leaves the input unchanged. A `--keywords` probe prints one decision and writes nothing. An `--experiment` run writes `experiments/<name>/` with `envsound_<split>.csv`, `config.json`, and `report.txt`, where `Category` and `SubCategory` are the scorer's assignment, and never writes inside `--manifest-dir`.

`--experiment` cannot be combined with `manifest`, `--keywords`, or `--config`. `--write-splits` and `--output-dir` require `--experiment`, and `--manifest-dir` is ignored without it. `--evidence` requires `--candidates`, and `--candidates` with a manifest requires `-o`. Given both a manifest and `--keywords`, only the probe runs.

The UCS workbook, the ontology, `audio/`, `configs/default.json`, `manifests/slice/`, and `experiments/` are fixed under the repo root. `manifest`, `-o`, `--config`, `--experiment`, and `--manifest-dir` are resolved from the working directory. A relative `--output-dir`, and a config's `output_dir` and taxonomy `file`, are joined to the repo root.

## Options

**manifest**

Envsound CSV to score. A file with `filename`, `source`, and `path` but no `Keywords` column takes its labels from `audio/` and cannot be used with `--no-audio`.

```bash
python scripts/score_ucs.py manifests/slice/envsound_val.csv
```

**-o**, **--output** *file*

Writes the manifest with `pred_category`, `pred_subcategory`, `pred_score`, `pred_status`, and `pred_evidence` added, and `Category` and `SubCategory` as they were. With `--candidates` it also gets the `cand_*` columns.

```bash
python scripts/score_ucs.py manifests/slice/envsound_val.csv -o predictions.csv
```

**--no-audio**

Scores the columns already on the CSV instead of refreshing `Keywords`, `pp_labels`, `uploader_tags`, `title`, and `description` from `audio/`. Applies to manifest and experiment runs.

```bash
python scripts/score_ucs.py manifests/slice/envsound_val.csv --no-audio
```

**--manifest-dir** *dir*

Folder of `envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` that an experiment scores and copies unscored splits from. Default is `manifests/slice`.

```bash
python scripts/score_ucs.py --experiment configs/default-open.json --manifest-dir manifests/original-envsound
```

**--config** *file*

JSON scoring config for a manifest or a probe, with omitted fields taken from `configs/default.json`. Default is `configs/default.json`.

```bash
python scripts/score_ucs.py manifests/slice/envsound_test.csv --config configs/default-open.json
```

**--experiment** *file*

JSON config for one experiment, written to `experiments/<name>/` or the config's `output_dir`. Repeat the flag to run several in one pass.

```bash
python scripts/score_ucs.py --experiment configs/closed-strict.json --experiment configs/closed-recall.json
```

**--output-dir** *dir*

Folder for experiment output instead of `experiments/<name>/`. One experiment writes into it directly, and several write one subfolder each, named after the config.

```bash
python scripts/score_ucs.py --experiment configs/default-open.json --experiment configs/open-recall.json --output-dir experiments
```

**--write-splits** *list*

Comma-separated splits to score, from `train`, `val`, and `test`, replacing the config's `splits`. Default is the config's list, which is `test` unless the config sets it.

```bash
python scripts/score_ucs.py --experiment configs/closed-strict.json --write-splits val,test
```

**--keywords** *list*

Scores one keyword list, written like the `Keywords` column in [Data](data.md), and prints the decision and the top candidates. Nothing is written.

```bash
python scripts/score_ucs.py --keywords "Meow,Cat,Animal"
```

**--category** *name*

Existing Category for a `--keywords` probe, used only to break a tie. Default is empty.

```bash
python scripts/score_ucs.py --keywords "Meow,Cat,Animal" --category ANIMALS
```

**--top** *n*

Number of candidates to print or write, at least 1. Default is 8, or 10 with `--candidates`.

```bash
python scripts/score_ucs.py --keywords "Meow,Cat,Animal" --top 5
```

**--candidates**

Adds `cand_count` and `cand_<n>_*` columns for each row's top subcategories, or prints them for a probe. An experiment is then written to `experiments/<name>-candidates/`, and a config's `output_dir` gets the same suffix.

```bash
python scripts/score_ucs.py --experiment configs/open-weighted-min075.json --candidates
```

**--evidence**

With `--candidates`, adds `cand_<n>_evidence`, the tags that produced each candidate's points.

```bash
python scripts/score_ucs.py --experiment configs/open-weighted-min075.json --candidates --evidence
```

## Files

`references/ucs-v8.2.1.xlsx` — UCS subcategories and synonyms.

`references/audioset_ontology.json` — ontology depths.

`configs/default.json` — default config, and the base every other config inherits from.

`audio/` — label files and FSD50K metadata, unless `--no-audio`.

`manifests/slice/` — default `--manifest-dir`.

`experiments/<name>/` — experiment output, or `experiments/<name>-candidates/` with `--candidates`.

## Exit status

0 on success.

2 when neither a manifest nor `--keywords` is given, after printing the help. Argument errors from argparse, such as a non-integer `--top`, also exit 2.

1 when the program stops with a message on stderr. The CLI's own messages are:

- `--top must be at least 1`
- `--evidence applies to --candidates`
- `--write-splits applies to --experiment`
- `--output-dir applies to --experiment`
- `pass an experiment or a manifest to score, not both`
- `use --config or --experiment, not both`
- `pass -o for the candidates CSV`, printed after the report
- `<manifest> has no Keywords column. Drop --no-audio so labels are read from the audio folder.`
- `<n> split rows have no label file under <audio>`
- `refusing to write <dir> inside <manifest-dir>; slice tags there stay as labeled`
- `<name> and <name> would both write <dir>`
- `unknown split <name>; expected train, val, test`
- `UCS list not found`, `AudioSet ontology not found`, `audio folder not found`, `config not found`, `experiment config not found`, or `slice manifest not found`, followed by the path

An invalid config file also exits 1, usually with a message that names the file. A missing `manifest` ends in a Python traceback with status 1.

## See also

[Scoring](scoring.md), [Configs](configs.md), [Data](data.md), [make_split_manifest](make_split_manifest.md), [make_envsound_foleyset](make_envsound_foleyset.md)

The tests run with `python -m unittest discover -s scripts/tests`.
