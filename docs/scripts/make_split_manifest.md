# make_split_manifest

## Name

`make_split_manifest` — split a manifest into train, val, and test at 70/15/15

## Synopsis

```
python scripts/make_split_manifest.py [--master csv] [--out dir] [--check]
```

## Description

Reads a manifest with `Category`, `SubCategory`, `source`, and `path` columns and writes every row to exactly one of `envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` in the output directory, with the input's columns. Rows are split by UCS pair, so each pair lands near 70/15/15; all blank rows form one group, and so do the category-only rows of each category. The same input always gives the same three files. The master manifest is left unchanged, and so is any other file in the output directory, including an earlier `envsound_test_check.csv` when `--check` is not given.

The script prints one line with the output directory and the row count of each split. A relative `--master` or `--out` path is joined to the repo root, not the working directory, and an absolute path is used as given.

## Options

**--master** *csv*

Manifest to split. Default is `manifests/master.csv`.

```bash
python scripts/make_split_manifest.py --master manifests/master.csv
```

**--out** *dir*

Directory for the split CSVs, created if needed, with existing split files in it overwritten. Default is `manifests/split`.

```bash
python scripts/make_split_manifest.py --out manifests/new-split
```

**--check**

Also writes `envsound_test_check.csv` with up to 2 test rows from each group, preferring different sources, and `Category` and `SubCategory` empty on that copy only. Each group with fewer than 2 test rows is then printed with its test count.

```bash
python scripts/make_split_manifest.py --out manifests/new-split --check
```

## Files

`manifests/master.csv` — default `--master`.

`manifests/split/envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` — default output.

`manifests/split/envsound_test_check.csv` — listening copy, with `--check`.

## Exit status

0 on success.

2 on an argument error from argparse, such as an unknown option.

1 when the program stops with a message on stderr. The messages are:

- `manifest not found: <path>`
- `manifest missing columns: <columns>`

## See also

[Data](../data.md), [make_master_manifest](make_master_manifest.md), [score_ucs](score_ucs.md)
