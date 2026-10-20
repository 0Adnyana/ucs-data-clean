# make_test_envsound_no_audioset

## Name

`make_test_envsound_no_audioset` — build the AudioSet ablation manifests

## Synopsis

```
python scripts/make_test_envsound_no_audioset.py [--original dir] [--foley dir] [--out dir]
```

## Description

Reads the original EnvSound split and the scored `envsound-foleyset` manifests, and writes four folders of `envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv`. The test file is the same in every folder: the original test split with `source` `AudioSet` removed. EnvSound `Category` and `SubCategory` are copied from the original split. FoleySet `Category` and `SubCategory` are copied from the scored manifests. Row counts for the last build are in `manifests/test-envsound-no-audioset/README.md`.

`1-original` keeps the original train and val. `2-no-audioset` drops AudioSet from train and val. `3-audioset-same-size` samples train and val from the original split so each `Category`/`SubCategory` has the same count as `2-no-audioset`; AudioSet clips in a shared pair stay eligible, and pairs that exist only on AudioSet are left out. `4-no-audioset-foleyset` appends the FoleySet train split to train and the FoleySet val split to val. The FoleySet test split is not written.

A relative path is joined to the repo root, not the working directory, and an absolute path is used as given.

## Options

**--original** *dir*

Original EnvSound split. Default is `manifests/original-envsound`.

**--foley** *dir*

Scored envsound-foleyset manifests. Default is `scoring/experiments/min075-envsound-foleyset`.

**--out** *dir*

Output directory, created if needed. Default is `manifests/test-envsound-no-audioset`. Existing split files in the four folders are overwritten.

## Files

`manifests/original-envsound/envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` — original clips and labels.

`scoring/experiments/min075-envsound-foleyset/` — FoleySet UCS labels.

`manifests/test-envsound-no-audioset/` — output.

## Exit status

0 on success.

2 on an argument error from argparse, such as an unknown option.

1 when the program stops with a message on stderr. The messages are:

- `manifest not found: <path>`
- `<path> is missing columns: <columns>`
- `original split missing: <split>`
- `no-audioset pair <pair> is not in the original split`
- `same-size split has <n> rows, expected <n>`
- `shared test still contains AudioSet`
- `<folder> test is not the shared test`
- `<folder> leaks into the test set: <path>`
- `<folder> repeats a clip in train and val`
- `FoleySet test clip is already in the shared test: <path>`

## See also

[Data](../data.md), [make_envsound_foleyset](make_envsound_foleyset.md)
