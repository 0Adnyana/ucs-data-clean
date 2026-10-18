# make_label_map_base

## Name

`make_label_map_base` — build a label map of the unique keywords in audio/, assigning each label a role

## Synopsis

```
python mapping/make_label_map_base.py [--prior map] [--output csv]
```

## Description

Reads the dataset label files under `audio/`, keeping the clips `make_master_manifest` keeps, and overwrites the output with one row per unique `source` and label pair, leaving `audio/` and the prior map unchanged. `category` and `subcategory` are copied from the prior map when it lists the pair and left empty otherwise; the prior map's `role` is ignored. Role is computed: a FoleySet `category` value is `group`, other FoleySet and all ESC-50 labels are `primary`, and an AudioSet or FSD50K label is `context` when it is `Music`, `Speech`, or found only under a style, mood, setting, noise, or recording branch of `references/audioset_hierarchy.json`, `parent` when the class has children, and `primary` otherwise, with exceptions listed in the module docstring. `audio/` and the ontology are fixed under the repo root, and a relative `--prior` or `--output` path is joined to the repo root, not the working directory.

## Options

**--prior** *map*

Label map CSV with `source`, `label`, `role`, `category`, and `subcategory` columns to copy categories from. Default is `mapping/label_map_llm.csv`.

```bash
python mapping/make_label_map_base.py --prior mapping/label_map_manual.csv
```

**--output** *csv*

Where to write the base map, creating parent folders as needed. Default is `mapping/label_map_base.csv`.

```bash
python mapping/make_label_map_base.py --output mapping/label_map_base.csv
```

## Files

`audio/AudioSet/audios/balanced_train_segments.csv` and `eval_segments.csv` — AudioSet labels.

`audio/ESC-50/meta/esc50.csv` — ESC-50 labels.

`audio/FSD50K/FSD50K.ground_truth/dev.csv` and `eval.csv` — FSD50K labels.

`audio/FoleySet/metadata/foleyset_metadata.csv` — FoleySet labels and the `category` values that become `group`.

`references/audioset_hierarchy.json` — AudioSet ontology used for AudioSet and FSD50K roles.

`mapping/label_map_llm.csv` — default `--prior` map.

`mapping/label_map_base.csv` — default output.

## Exit status

0 on success.

2 on an argument error from argparse, such as an unknown option.

1 when the program stops with a message on stderr. The messages are:

- `dataset file not found: <path>`
- `label map not found: <path>`
- `<map> is missing columns: <columns>`
- `<map> repeats <source> label '<label>' with a different UCS pair`
- `ontology hierarchy not found: <path>`
- `audioset_hierarchy.json must be a list of ontology nodes`

## See also

[Data](../data.md), [Scoring](../scoring.md), [make_master_manifest](make_master_manifest.md)
