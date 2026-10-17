# make_master_manifest

## Name

`make_master_manifest` — build manifests/master.csv from the dataset metadata in audio/

## Synopsis

```
python scripts/make_master_manifest.py [--fill-ucs [map]]
```

## Description

Reads the AudioSet, ESC-50, FSD50K, and FoleySet label files under `audio/` and writes one row per clip to `manifests/master.csv`, replacing the file on each run. An ESC-50 clip whose Freesound id is already an FSD50K clip is left out, and so is a FoleySet clip whose id is already in either set. A clip whose wav is missing is still listed, with `exists` set to `False`. Without `--fill-ucs`, `Category` and `SubCategory` are empty on every row.

The script prints one summary line with row counts per source, the omitted overlaps, and the missing wavs. It does not change `audio/` or any other manifest.

`audio/` and `manifests/master.csv` are fixed under the repo root. A relative `--fill-ucs` path is joined to the repo root, not the working directory, and an absolute path is used as given.

## Options

**--fill-ucs** [*map*]

Fills `Category` and `SubCategory` from a label map CSV with `source`, `label`, `role`, `category`, and `subcategory` columns, and adds the assigned, category-only, blank, and unmapped counts to the summary. Bare, it reads `references/mapping/label_map_llm.csv`.

```bash
python scripts/make_master_manifest.py --fill-ucs
python scripts/make_master_manifest.py --fill-ucs references/mapping/label_map_base.csv
```

## Files

`audio/AudioSet/audios/balanced_train_segments.csv` and `eval_segments.csv` — AudioSet labels.

`audio/ESC-50/meta/esc50.csv` — ESC-50 labels and Freesound ids.

`audio/FSD50K/FSD50K.ground_truth/dev.csv` and `eval.csv` — FSD50K labels.

`audio/FoleySet/metadata/foleyset_metadata.csv` — FoleySet labels and Freesound ids.

`references/mapping/label_map_llm.csv` — default `--fill-ucs` map.

`manifests/master.csv` — output.

## Exit status

0 on success.

2 on an argument error from argparse, such as an unknown option.

1 when the program stops with a message on stderr. The messages are:

- `dataset file not found: <path>`
- `label map not found: <path>`
- `<map> is missing columns: <columns>`
- `<map> repeats <source> label '<label>' with a different UCS pair`

## See also

[Data](data.md), [Scoring](scoring.md), [make_label_map_base](make_label_map_base.md), [make_split_manifest](make_split_manifest.md)
